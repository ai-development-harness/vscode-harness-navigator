#!/usr/bin/env python3
"""Универсальное crash-safe состояние выполнения Harness-команд.

Validation note
---------------
Модуль в целом не является standalone validator, но `validate_status()` —
обязательная schema boundary local execution state. И чтение, и запись проходят
через неё, поэтому повреждённый JSON/state не трактуется как "истории нет".



Модуль хранит bounded operational state canonical invocations в одном локальном
файле .harness/local/execution/execution-status.json. Он не является audit log:
full records остаются только для active/recoverable executions, STEP recovery
proof хранится отдельно, а terminal history ограничена compact tombstones.
Canonical project artifacts не заменяются local state.

Модель намеренно простая:
- каждый явный ввод пользователя создаёт независимую root execution;
- single command после completion останавливается;
- explicit chain продолжает только свою исходную sequence через CTS;
- STEP RUN использует orchestration mode и существующие STEP child commands;
- current.status=running после обрыва означает resume той же команды.

CTS остаётся единственным источником разрешённых переходов. Этот модуль отвечает
не на вопрос «можно ли перейти?», а на вопрос «что реально запускалось и успело
ли завершиться?».
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
from typing import Any
from uuid import uuid4

from command_transitions import (
    load_transition_table,
    parse_canonical_command,
    validate_command_text,
)
from document_contract import render_document
from harness_config import ConfigError, get, load_git_policy, update_lock_path
from planning_contract import (
    implementation_prerequisite_failures,
    latest_matching_planning_review,
    max_fix_review_cycles,
    plan_content_hash,
    planning_context_basis,
    read_task as read_planning_task,
    step_completion_proof,
    task_contract_snapshot,
    task_path as configured_task_path,
)
from review_contract import latest_review as latest_valid_review

# Фиксированный project-level operational state. Один файл намеренно покрывает
# STEP, Git, Harness update и остальные namespaces.
STATUS_PATH = ".harness/local/execution/execution-status.json"
LOCK_PATH = ".harness/local/execution/execution-status.lock"
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_LOCK_LOCAL = threading.local()
# mode описывает форму уже существующего пользовательского ввода и НЕ является
# новой командой/профилем. Пользователь никогда не выбирает mode вручную.
STATUS_SCHEMA_VERSION = 2
LEGACY_STATUS_SCHEMA_VERSION = 1
RECENT_TERMINAL_LIMIT = 100
MAX_DETAILS_BYTES = 16 * 1024

EXECUTION_MODES = {"single", "chain", "orchestration"}
EXECUTION_STATUSES = {"running", "complete", "blocked"}
ACTIVE_EXECUTION_STATUSES = {"running", "blocked"}
TERMINAL_EXECUTION_STATUSES = {"complete", "blocked"}
COMMAND_STATUSES = {"running", "complete", "blocked"}
RESULTS = {"SUCCESS", "PASS", "FAIL", "BLOCKED"}

CONTRACT_METADATA = ("Type", "Depends on")
CONTRACT_SECTIONS = (
    "Requirements",
    "ADR",
    "Risk flags",
    "Goal",
    "Context",
    "Scope",
    "Mutation policy",
    "Out of scope",
    "Acceptance criteria",
    "Verification",
    "Deliverables",
)
REVIEW_VERDICTS = {"PASS", "FAIL", "BLOCKED", "NOT REVIEWED"}



# Вернуть UTC timestamp в стабильном ISO-формате. Local timezone намеренно не хранится, чтобы сравнение records не зависело от окружения.
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")



# Вернуть единственный фиксированный путь execution-status.json. Per-STEP state files в этой модели не используются.
def status_path(root: Path) -> Path:
    return root / STATUS_PATH



# Создать bounded schema v2 для проекта, где execution-status ещё ни разу не записывался.
def empty_status() -> dict[str, Any]:
    return {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "executions": [],
        "stepRecovery": {},
        "recentTerminals": [],
        "nextOrdinal": 1,
    }


def _process_lock(key: str) -> threading.RLock:
    """Вернуть process-local reentrant lock для одного project state path."""
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


@contextmanager
def execution_state_lock(root: Path):
    """Сериализовать execution-state transaction между threads/processes.

    OS advisory lock живёт на отдельном local-only файле и освобождается ядром
    при завершении процесса. Reentrant слой нужен потому, что public mutation
    helpers вызывают друг друга и resolver recovery может записать state внутри
    уже открытой transaction.
    """
    lock_path = root / LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve())
    process_lock = _process_lock(key)

    with process_lock:
        held = getattr(_LOCK_LOCAL, "held", None)
        if held is None:
            held = {}
            _LOCK_LOCAL.held = held
        depth = int(held.get(key, 0))
        if depth > 0:
            held[key] = depth + 1
            try:
                yield
            finally:
                held[key] -= 1
            return

        fh = lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if fh.seek(0, os.SEEK_END) == 0:
                    fh.write(b"\0")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            held[key] = 1
            try:
                yield
            finally:
                held.pop(key, None)
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def execution_state_mutation(func):
    """Обернуть public read-modify-write operation общей transaction lock."""
    @wraps(func)
    def wrapped(root: Path, *args: Any, **kwargs: Any):
        with execution_state_lock(root):
            return func(root, *args, **kwargs)

    return wrapped



# ---------------------------------------------------------------------------
# Execution Status schema + deterministic local migration.
#
# schema v2 хранит только full active/recoverable records. Completed/superseded
# invocations превращаются в bounded terminal tombstones, а STEP baseline живёт
# отдельно в stepRecovery. Это не audit log: canonical project artifacts
# остаются source of truth.
# ---------------------------------------------------------------------------
def _validate_baseline(value: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]
    step_id = value.get("stepId")
    git_head = value.get("gitHead")
    captured_at = value.get("capturedAt")
    source_execution_id = value.get("sourceExecutionId")
    if not isinstance(step_id, str) or re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        errors.append(f"{prefix}.stepId must be STEP-NNN")
    if (
        not isinstance(git_head, str)
        or re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", git_head) is None
    ):
        errors.append(f"{prefix}.gitHead must be a 40/64-hex Git OID")
    if not isinstance(captured_at, str) or not captured_at.strip():
        errors.append(f"{prefix}.capturedAt must be non-empty")
    if not isinstance(source_execution_id, str) or not source_execution_id:
        errors.append(f"{prefix}.sourceExecutionId must be non-empty")
    return errors


def _details_size_bytes(value: dict[str, Any]) -> int:
    """Размер durable details в точном compact UTF-8 JSON transport."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(encoded)


def _details_errors(
    value: Any,
    *,
    prefix: str,
    enforce_budget: bool,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]
    if enforce_budget:
        try:
            size = _details_size_bytes(value)
        except (TypeError, ValueError) as exc:
            return [f"{prefix} must be JSON-serializable: {exc}"]
        if size > MAX_DETAILS_BYTES:
            return [
                f"{prefix} exceeds {MAX_DETAILS_BYTES} UTF-8 JSON bytes: {size}"
            ]
    return []


def _require_details_budget(value: dict[str, Any] | None) -> None:
    """Reject oversized durable handoff metadata before execution mutation."""
    errors = _details_errors(
        value,
        prefix="current.details",
        enforce_budget=True,
    )
    if errors:
        raise ValueError("; ".join(errors))


def _validate_execution_record(
    execution: Any,
    *,
    prefix: str,
    allowed_statuses: set[str],
    require_ordinal: bool,
    require_nonempty_sequence: bool = True,
    enforce_details_budget: bool = True,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(execution, dict):
        return [f"{prefix}: must be an object"]

    execution_id = execution.get("executionId")
    if not isinstance(execution_id, str) or not execution_id:
        errors.append(f"{prefix}: executionId must be non-empty")
    if require_ordinal:
        ordinal = execution.get("ordinal")
        if (
            not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
        ):
            errors.append(f"{prefix}: ordinal must be >= 1")
    if execution.get("mode") not in EXECUTION_MODES:
        errors.append(f"{prefix}: invalid mode")
    if execution.get("status") not in allowed_statuses:
        errors.append(f"{prefix}: invalid status")
    if not isinstance(execution.get("rootCommand"), str) or not execution.get("rootCommand"):
        errors.append(f"{prefix}: rootCommand must be non-empty")

    sequence = execution.get("sequence")
    if (
        not isinstance(sequence, list)
        or (require_nonempty_sequence and not sequence)
        or any(not isinstance(item, str) or not item for item in sequence)
    ):
        errors.append(
            f"{prefix}: sequence must be "
            + ("a non-empty string array" if require_nonempty_sequence else "a string array")
        )

    current = execution.get("current")
    if not isinstance(current, dict):
        errors.append(f"{prefix}: current must be an object")
        return errors
    if not isinstance(current.get("command"), str) or not current.get("command"):
        errors.append(f"{prefix}: current.command must be non-empty")
    if current.get("status") not in COMMAND_STATUSES:
        errors.append(f"{prefix}: invalid current.status")
    result = current.get("result")
    if result is not None and result not in RESULTS:
        errors.append(f"{prefix}: invalid current.result")
    errors.extend(
        _details_errors(
            current.get("details"),
            prefix=f"{prefix}: current.details",
            enforce_budget=enforce_details_budget,
        )
    )
    attempt = current.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append(f"{prefix}: current.attempt must be >= 1")

    fix_review_cycles = execution.get("fixReviewCycles", 0)
    if (
        not isinstance(fix_review_cycles, int)
        or isinstance(fix_review_cycles, bool)
        or fix_review_cycles < 0
    ):
        errors.append(f"{prefix}: fixReviewCycles must be a non-negative integer")

    baseline = execution.get("implementationBaseline")
    if baseline is not None:
        errors.extend(_validate_baseline(baseline, f"{prefix}.implementationBaseline"))
    return errors


def _validate_terminal_record(value: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{prefix}: must be an object"]
    if not isinstance(value.get("executionId"), str) or not value.get("executionId"):
        errors.append(f"{prefix}: executionId must be non-empty")
    ordinal = value.get("ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        errors.append(f"{prefix}: ordinal must be >= 1")
    if value.get("status") not in TERMINAL_EXECUTION_STATUSES:
        errors.append(f"{prefix}: invalid status")
    if value.get("mode") not in EXECUTION_MODES:
        errors.append(f"{prefix}: invalid mode")
    if not isinstance(value.get("rootCommand"), str) or not value.get("rootCommand"):
        errors.append(f"{prefix}: rootCommand must be non-empty")
    current = value.get("current")
    if not isinstance(current, dict):
        errors.append(f"{prefix}: current must be an object")
    else:
        if not isinstance(current.get("command"), str) or not current.get("command"):
            errors.append(f"{prefix}: current.command must be non-empty")
        if current.get("status") not in COMMAND_STATUSES:
            errors.append(f"{prefix}: invalid current.status")
        result = current.get("result")
        if result is not None and result not in RESULTS:
            errors.append(f"{prefix}: invalid current.result")
        errors.extend(
            _details_errors(
                current.get("details"),
                prefix=f"{prefix}: current.details",
                enforce_budget=True,
            )
        )
    return errors


def _validate_v1_status(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schemaVersion") != LEGACY_STATUS_SCHEMA_VERSION:
        errors.append("execution-status: schemaVersion must be 1")
    executions = value.get("executions")
    if not isinstance(executions, list):
        return errors + ["execution-status: executions must be an array"]
    ids: set[str] = set()
    for index, execution in enumerate(executions):
        prefix = f"execution-status.executions[{index}]"
        errors.extend(
            _validate_execution_record(
                execution,
                prefix=prefix,
                allowed_statuses=EXECUTION_STATUSES,
                require_ordinal=False,
                require_nonempty_sequence=False,
                enforce_details_budget=False,
            )
        )
        if isinstance(execution, dict):
            execution_id = execution.get("executionId")
            if isinstance(execution_id, str) and execution_id:
                if execution_id in ids:
                    errors.append(f"{prefix}: duplicate executionId {execution_id}")
                ids.add(execution_id)
    return errors


def _validate_v2_status(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schemaVersion") != STATUS_SCHEMA_VERSION:
        errors.append(f"execution-status: schemaVersion must be {STATUS_SCHEMA_VERSION}")

    executions = value.get("executions")
    terminals = value.get("recentTerminals")
    recovery = value.get("stepRecovery")
    next_ordinal = value.get("nextOrdinal")
    if not isinstance(executions, list):
        errors.append("execution-status: executions must be an array")
        executions = []
    if not isinstance(terminals, list):
        errors.append("execution-status: recentTerminals must be an array")
        terminals = []
    if isinstance(terminals, list) and len(terminals) > RECENT_TERMINAL_LIMIT:
        errors.append(
            f"execution-status: recentTerminals exceeds hard limit {RECENT_TERMINAL_LIMIT}"
        )
    if not isinstance(recovery, dict):
        errors.append("execution-status: stepRecovery must be an object")
        recovery = {}
    if (
        not isinstance(next_ordinal, int)
        or isinstance(next_ordinal, bool)
        or next_ordinal < 1
    ):
        errors.append("execution-status: nextOrdinal must be >= 1")

    ids: set[str] = set()
    ordinals: set[int] = set()
    max_ordinal = 0
    for index, execution in enumerate(executions):
        prefix = f"execution-status.executions[{index}]"
        errors.extend(
            _validate_execution_record(
                execution,
                prefix=prefix,
                allowed_statuses=ACTIVE_EXECUTION_STATUSES,
                require_ordinal=True,
            )
        )
        if isinstance(execution, dict):
            execution_id = execution.get("executionId")
            ordinal = execution.get("ordinal")
            if isinstance(execution_id, str) and execution_id:
                if execution_id in ids:
                    errors.append(f"{prefix}: duplicate executionId {execution_id}")
                ids.add(execution_id)
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                if ordinal in ordinals:
                    errors.append(f"{prefix}: duplicate ordinal {ordinal}")
                ordinals.add(ordinal)
                max_ordinal = max(max_ordinal, ordinal)

    for index, terminal in enumerate(terminals):
        prefix = f"execution-status.recentTerminals[{index}]"
        errors.extend(_validate_terminal_record(terminal, prefix))
        if isinstance(terminal, dict):
            execution_id = terminal.get("executionId")
            ordinal = terminal.get("ordinal")
            if isinstance(execution_id, str) and execution_id:
                if execution_id in ids:
                    errors.append(f"{prefix}: duplicate executionId {execution_id}")
                ids.add(execution_id)
            if isinstance(ordinal, int) and not isinstance(ordinal, bool):
                if ordinal in ordinals:
                    errors.append(f"{prefix}: duplicate ordinal {ordinal}")
                ordinals.add(ordinal)
                max_ordinal = max(max_ordinal, ordinal)

    for step_id, item in recovery.items():
        prefix = f"execution-status.stepRecovery.{step_id}"
        if not isinstance(step_id, str) or re.fullmatch(r"STEP-\d{3,}", step_id) is None:
            errors.append(f"{prefix}: key must be STEP-NNN")
            continue
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        baseline = item.get("implementationBaseline")
        errors.extend(_validate_baseline(baseline, f"{prefix}.implementationBaseline"))
        if isinstance(baseline, dict) and baseline.get("stepId") != step_id:
            errors.append(
                f"{prefix}.implementationBaseline.stepId must match recovery key {step_id}"
            )
        updated_at = item.get("updatedAt")
        if updated_at is not None and (
            not isinstance(updated_at, str) or not updated_at.strip()
        ):
            errors.append(f"{prefix}.updatedAt must be null or non-empty")

    if isinstance(next_ordinal, int) and not isinstance(next_ordinal, bool):
        if next_ordinal <= max_ordinal:
            errors.append(
                "execution-status: nextOrdinal must be greater than all stored ordinals"
            )
    return errors


def validate_status(value: dict[str, Any]) -> list[str]:
    """Validate both legacy v1 input and bounded current v2 state."""
    if not isinstance(value, dict):
        return ["execution-status: root must be an object"]
    version = value.get("schemaVersion")
    if version == LEGACY_STATUS_SCHEMA_VERSION:
        return _validate_v1_status(value)
    if version == STATUS_SCHEMA_VERSION:
        return _validate_v2_status(value)
    return [f"execution-status: unsupported schemaVersion {version!r}"]


def _terminal_from_execution(execution: dict[str, Any]) -> dict[str, Any]:
    """Сжать terminal execution, сохранив bounded durable handoff metadata."""
    current = execution.get("current")
    current_value = current if isinstance(current, dict) else {}
    terminal_current: dict[str, Any] = {
        "command": current_value.get("command"),
        "status": current_value.get("status"),
        "result": current_value.get("result"),
        "completedAt": current_value.get("completedAt"),
    }
    details = current_value.get("details")
    if isinstance(details, dict):
        # details — command-specific durable handoff metadata (например
        # resolved UPDATE target/route). Полная execution history удаляется,
        # но recent tombstone обязан сохранить этот bounded handoff contract.
        terminal_current["details"] = deepcopy(details)

    return {
        "executionId": execution["executionId"],
        "ordinal": execution["ordinal"],
        "rootCommand": execution["rootCommand"],
        "mode": execution["mode"],
        "status": execution["status"],
        "current": terminal_current,
        "completedAt": execution.get("completedAt"),
        "updatedAt": execution.get("updatedAt"),
    }


def _migrate_status_v1(value: dict[str, Any]) -> dict[str, Any]:
    """Lossless-enough v1 -> bounded v2 migration before atomic replacement."""
    executions_v1 = value.get("executions", [])
    copied: list[dict[str, Any]] = []
    latest_by_root: dict[str, int] = {}
    step_recovery: dict[str, dict[str, Any]] = {}

    for ordinal, original in enumerate(executions_v1, start=1):
        execution = deepcopy(original)
        execution["ordinal"] = ordinal
        copied.append(execution)
        root_command = execution.get("rootCommand")
        if isinstance(root_command, str):
            latest_by_root[root_command] = ordinal
        baseline = execution.get("implementationBaseline")
        if isinstance(baseline, dict):
            step_id = baseline.get("stepId")
            if isinstance(step_id, str):
                step_recovery[step_id] = {
                    "implementationBaseline": deepcopy(baseline),
                    "updatedAt": execution.get("updatedAt") or baseline.get("capturedAt"),
                }

    active: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    for execution in copied:
        status = execution.get("status")
        root_command = execution.get("rootCommand")
        ordinal = int(execution["ordinal"])
        if status == "running":
            active.append(execution)
        elif (
            status == "blocked"
            and latest_by_root.get(root_command) == ordinal
        ):
            active.append(execution)
        else:
            terminals.append(_terminal_from_execution(execution))

    terminals.sort(key=lambda item: int(item["ordinal"]))
    terminals = terminals[-RECENT_TERMINAL_LIMIT:]
    return {
        "schemaVersion": STATUS_SCHEMA_VERSION,
        "executions": active,
        "stepRecovery": step_recovery,
        "recentTerminals": terminals,
        "nextOrdinal": len(copied) + 1,
    }


# Прочитать local state, fail-closed validate и при необходимости атомарно
# мигрировать legacy v1. PROJECT RECONCILE здесь намеренно не участвует.
def load_status(root: Path) -> dict[str, Any]:
    path = status_path(root)
    with execution_state_lock(root):
        if not path.is_file():
            return empty_status()
        try:
            with path.open("r", encoding="utf-8") as fh:
                value = json.load(fh)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"execution-status: cannot parse JSON: {exc}") from exc
        # Не-object root (array/string) — повреждённый state, а не AttributeError (#117).
        if not isinstance(value, dict):
            raise ValueError("execution-status: root must be a JSON object")

        if value.get("schemaVersion") == LEGACY_STATUS_SCHEMA_VERSION:
            errors = _validate_v1_status(value)
            if errors:
                raise ValueError("; ".join(errors))
            migrated = _migrate_status_v1(value)
            compacted = _compact_status(root, migrated)
            errors = _validate_v2_status(compacted)
            if errors:
                raise ValueError("; ".join(errors))
            _atomic_write_json(path, compacted)
            return compacted

        errors = _validate_v2_status(value)
        if errors:
            raise ValueError("; ".join(errors))
        return value



# Записать JSON crash-safe способом через temporary file, fsync и atomic os.replace. Это защищает от половины файла при process/session crash.
def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)



# Любая запись local execution state проходит через тот же validator, что и
# load_status(). Public read-modify-write операции дополнительно держат
# execution_state_lock() на всю transaction; atomic replace один не защищает от
# lost update между двумя параллельными sessions.
def _step_recovery_needed(
    root: Path,
    status: dict[str, Any],
    step_id: str,
) -> bool:
    """Fail-safe доказать, нужен ли baseline конкретного STEP.

    Active IMPLEMENT/REVIEW/FIX удерживает recovery даже до первой mutation,
    когда canonical STEP ещё может быть planned. Без active execution canonical
    in_progress удерживает baseline между отдельными invocations. Ошибка чтения
    task не является основанием удалять recovery proof.
    """
    for execution in status.get("executions", []):
        baseline = execution.get("implementationBaseline")
        if isinstance(baseline, dict) and baseline.get("stepId") == step_id:
            return True

    try:
        task = read_planning_task(root, step_id)
    except (OSError, ValueError, FileNotFoundError, ConfigError):
        return True
    # Удаляем recovery только при доказанном terminal lifecycle. planned/blocked
    # сами по себе не доказывают, что ранее начатая implementation lifecycle
    # безопасно забыта; fresh IMPLEMENT всё равно перезапишет baseline до mutation.
    return task["frontmatter"].get("status") not in {
        "completed",
        "cancelled",
        "deferred",
    }


def _compact_status(root: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Свести v2 к bounded operational state без потери active recovery."""
    status = deepcopy(value)
    if status.get("schemaVersion") != STATUS_SCHEMA_VERSION:
        return status

    executions = [
        item for item in status.get("executions", [])
        if isinstance(item, dict)
    ]
    terminals = [
        item for item in status.get("recentTerminals", [])
        if isinstance(item, dict)
    ]

    latest_by_root: dict[str, int] = {}
    for item in [*executions, *terminals]:
        root_command = item.get("rootCommand")
        ordinal = item.get("ordinal")
        if (
            isinstance(root_command, str)
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
        ):
            latest_by_root[root_command] = max(
                latest_by_root.get(root_command, 0),
                ordinal,
            )

    terminal_by_id: dict[str, dict[str, Any]] = {
        str(item.get("executionId")): item
        for item in terminals
        if isinstance(item.get("executionId"), str)
    }
    active: list[dict[str, Any]] = []
    for execution in executions:
        execution_id = execution.get("executionId")
        root_command = execution.get("rootCommand")
        ordinal = execution.get("ordinal")
        execution_status = execution.get("status")
        superseded_blocked = (
            execution_status == "blocked"
            and isinstance(root_command, str)
            and isinstance(ordinal, int)
            and latest_by_root.get(root_command, ordinal) > ordinal
        )
        if execution_status == "complete" or superseded_blocked:
            if isinstance(execution_id, str):
                terminal_by_id[execution_id] = _terminal_from_execution(execution)
            continue
        active.append(execution)

    active.sort(key=lambda item: int(item.get("ordinal", 0)))
    compact_terminals = sorted(
        terminal_by_id.values(),
        key=lambda item: int(item.get("ordinal", 0)),
    )[-RECENT_TERMINAL_LIMIT:]

    status["executions"] = active
    status["recentTerminals"] = compact_terminals

    recovery = status.get("stepRecovery")
    if not isinstance(recovery, dict):
        recovery = {}
    retained_recovery: dict[str, Any] = {}
    for step_id, item in recovery.items():
        if (
            isinstance(step_id, str)
            and isinstance(item, dict)
            and _step_recovery_needed(root, status, step_id)
        ):
            retained_recovery[step_id] = item
    status["stepRecovery"] = retained_recovery

    max_ordinal = max(
        [
            int(item.get("ordinal", 0))
            for item in [*active, *compact_terminals]
            if isinstance(item.get("ordinal"), int)
            and not isinstance(item.get("ordinal"), bool)
        ]
        or [0]
    )
    current_next = status.get("nextOrdinal")
    if (
        not isinstance(current_next, int)
        or isinstance(current_next, bool)
        or current_next <= max_ordinal
    ):
        status["nextOrdinal"] = max_ordinal + 1
    return status


def save_status(root: Path, value: dict[str, Any]) -> None:
    """Compact + validate + atomic write current local execution state."""
    compacted = _compact_status(root, value)
    errors = _validate_v2_status(compacted)
    if errors:
        raise ValueError("; ".join(errors))
    value.clear()
    value.update(compacted)
    _atomic_write_json(status_path(root), value)



# Пропустить пользовательский root command через CTS parser и автоматически определить internal mode: single, chain или STEP RUN orchestration.
def _normalize_root(root: Path, raw: str) -> dict[str, Any]:
    table = load_transition_table(root)
    result = validate_command_text(raw, table)
    if not result.get("valid"):
        raise ValueError(
            f"{result.get('code')}: {result.get('message', 'invalid command')}"
        )
    normalized = result["normalized"]
    root_command = " > ".join(normalized)
    first = parse_canonical_command(normalized[0], table)
    if not first.get("valid"):
        raise ValueError("normalized root command failed canonical parser")

    # mode выводится только из синтаксически уже валидного root command.
    # Никакого execution profile/config для этого не существует.
    if len(normalized) > 1:
        mode = "chain"
    elif first.get("domain") == "STEP" and first.get("operation") == "RUN":
        mode = "orchestration"
    else:
        mode = "single"

    return {
        "mode": mode,
        "rootCommand": root_command,
        "sequence": normalized,
        "first": first,
    }



# Нормализовать одну canonical command без chain. Используется там, где current/child command уже должна быть одиночной.
def normalize_single_command(root: Path, raw: str) -> dict[str, Any]:
    table = load_transition_table(root)
    parsed = parse_canonical_command(raw, table)
    if not parsed.get("valid"):
        raise ValueError(
            f"{parsed.get('code')}: {parsed.get('message', 'invalid command')}"
        )
    return parsed



# Найти последнюю подходящую execution по ID/root/status. Поиск идёт с конца, потому что файл хранит records в порядке появления.
def _latest_execution(
    status: dict[str, Any],
    *,
    root_command: str | None = None,
    execution_id: str | None = None,
    statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    """Найти latest full active execution по monotonic ordinal."""
    candidates: list[dict[str, Any]] = []
    for item in status.get("executions", []):
        if execution_id is not None and item.get("executionId") != execution_id:
            continue
        if root_command is not None and item.get("rootCommand") != root_command:
            continue
        if statuses is not None and item.get("status") not in statuses:
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item.get("ordinal", 0)))


def _latest_invocation(
    status: dict[str, Any],
    *,
    root_command: str | None = None,
    execution_id: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Найти latest invocation среди active records и terminal tombstones."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    for item in status.get("executions", []):
        if execution_id is not None and item.get("executionId") != execution_id:
            continue
        if root_command is not None and item.get("rootCommand") != root_command:
            continue
        candidates.append(("active", item))
    for item in status.get("recentTerminals", []):
        if execution_id is not None and item.get("executionId") != execution_id:
            continue
        if root_command is not None and item.get("rootCommand") != root_command:
            continue
        candidates.append(("terminal", item))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: int(pair[1].get("ordinal", 0)))


def _resolve_terminal(terminal: dict[str, Any]) -> dict[str, Any]:
    status = terminal.get("status")
    return {
        "status": "DONE" if status == "complete" else "BLOCKED",
        "executionId": terminal.get("executionId"),
        "rootCommand": terminal.get("rootCommand"),
        "command": None,
        "reasonCode": (
            "EXECUTION_COMPLETE"
            if status == "complete"
            else "EXECUTION_BLOCKED"
        ),
    }



# Безопасно прочитать текущий Git HEAD для narrow durable proof GIT COMMIT. Ошибка Git здесь не должна ломать execution tracking.
def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def git_commit_completion_proven(
    root: Path,
    execution: dict[str, Any],
) -> bool:
    """Prove that the current canonical COMMIT advanced repository HEAD."""

    current = execution.get("current")
    if not isinstance(current, dict) or current.get("status") != "running":
        return False
    try:
        parsed = normalize_single_command(root, str(current.get("command") or ""))
    except ValueError:
        return False
    if parsed.get("domain") != "GIT" or parsed.get("operation") != "COMMIT":
        return False

    context = current.get("context")
    before = context.get("gitHeadBefore") if isinstance(context, dict) else None
    now = _git_head(root)
    # before=None is valid for the first commit in an unborn repository. A
    # non-empty current HEAD still proves that the COMMIT created durable state.
    return now is not None and now != before



# Durable implementation baseline не зависит от terminal execution history:
# REVIEW/FIX восстанавливают proof из bounded stepRecovery.
def _remember_step_recovery(
    status: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    step_id = baseline.get("stepId")
    if not isinstance(step_id, str):
        return
    recovery = status.setdefault("stepRecovery", {})
    recovery[step_id] = {
        "implementationBaseline": deepcopy(baseline),
        "updatedAt": utc_now(),
    }


def _latest_implementation_baseline(
    status: dict[str, Any],
    step_id: str,
) -> dict[str, Any] | None:
    """Вернуть STEP baseline независимо от bounded terminal history."""
    recovery = status.get("stepRecovery")
    if isinstance(recovery, dict):
        item = recovery.get(step_id)
        if isinstance(item, dict):
            baseline = item.get("implementationBaseline")
            if (
                isinstance(baseline, dict)
                and baseline.get("stepId") == step_id
            ):
                return dict(baseline)

    # Defensive compatibility для in-memory active record до первого save.
    for item in reversed(status.get("executions", [])):
        baseline = item.get("implementationBaseline")
        if isinstance(baseline, dict) and baseline.get("stepId") == step_id:
            return dict(baseline)
    return None



def _baseline_for_new_command(
    root: Path,
    status: dict[str, Any],
    execution: dict[str, Any],
    command: str,
) -> dict[str, Any] | None:
    """Attach/reuse baseline when entering IMPLEMENT/REVIEW/FIX.

    IMPLEMENT captures HEAD before semantic product mutation. If the STEP is
    already in_progress, an existing baseline is the start of the same
    implementation lifecycle and must not be silently moved forward by a new
    independent IMPLEMENT invocation. REVIEW/FIX only inherit an existing proof;
    they never invent one for historical executions.
    """
    parsed = normalize_single_command(root, command)
    if parsed.get("domain") != "STEP" or not parsed.get("target"):
        return None
    operation = parsed.get("operation")
    if operation not in {"IMPLEMENT", "REVIEW", "FIX"}:
        return None

    step_id = str(parsed["target"])
    current = execution.get("implementationBaseline")
    if isinstance(current, dict) and current.get("stepId") == step_id:
        _remember_step_recovery(status, current)
        return current

    historical = _latest_implementation_baseline(status, step_id)
    try:
        task_status = read_task(root, step_id)["frontmatter"].get("status")
    except (OSError, ValueError, FileNotFoundError):
        task_status = None

    if operation in {"REVIEW", "FIX"}:
        # Historical baseline относится к текущей implementation lifecycle
        # только пока canonical STEP действительно in_progress. Planned/new
        # lifecycle не должна случайно унаследовать proof завершённой работы.
        if task_status == "in_progress" and historical is not None:
            execution["implementationBaseline"] = historical
            _remember_step_recovery(status, historical)
            return historical
        return None

    # IMPLEMENT: reuse the original lifecycle baseline once product mutation has
    # moved STEP to in_progress. Planned STEP means product mutation has not yet
    # been established, so a fresh capture is safe and exact.
    if task_status == "in_progress" and historical is not None:
        execution["implementationBaseline"] = historical
        _remember_step_recovery(status, historical)
        return historical

    git_head = _git_head(root)
    if git_head is None:
        return None
    baseline = {
        "stepId": step_id,
        "gitHead": git_head,
        "capturedAt": utc_now(),
        "sourceExecutionId": execution["executionId"],
    }
    execution["implementationBaseline"] = baseline
    _remember_step_recovery(status, baseline)
    return baseline


# Собрать минимальный context, нужный только для crash recovery конкретных commands; не превращать его в копию project state.
def _command_context(
    root: Path,
    command: str,
    implementation_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = normalize_single_command(root, command)
    context: dict[str, Any] = {}

    if parsed.get("domain") == "STEP" and parsed.get("target"):
        step_id = parsed["target"]
        if parsed.get("operation") in {"PLAN", "IMPLEMENT", "REVIEW", "FIX"}:
            try:
                context["planBasisAtStart"] = contract_basis(root, step_id)
            except (OSError, ValueError, FileNotFoundError):
                pass
        if (
            isinstance(implementation_baseline, dict)
            and implementation_baseline.get("stepId") == step_id
        ):
            context["implementationBaseline"] = dict(implementation_baseline)
        if parsed.get("operation") == "REVIEW":
            review = latest_review(root, step_id)
            context["reviewReportBefore"] = review["path"] if review else None

    # Для COMMIT сравнение HEAD защищает от создания второго commit, если Git
    # mutation успела завершиться, а local complete-checkpoint — нет.
    if parsed.get("domain") == "GIT" and parsed.get("operation") == "COMMIT":
        context["gitHeadBefore"] = _git_head(root)

    return context



# Зарегистрировать новый root invocation либо resume уже running invocation с тем же normalized rootCommand.
@execution_state_mutation
def start_execution(root: Path, raw_command: str) -> dict[str, Any]:
    normalized = _normalize_root(root, raw_command)

    # Первый executable segment не имеет incoming CTS edge, поэтому его
    # command-specific preconditions проверяются отдельно до создания local
    # execution record. Это делает direct STEP IMPLEMENT таким же fail-closed,
    # как PLAN -> IMPLEMENT внутри chain/RUN.
    if normalized["mode"] != "orchestration":
        failures = _command_dispatch_precondition_failures(
            root,
            normalized["sequence"][0],
        )
        if failures:
            raise ValueError("command precondition failed: " + "; ".join(failures))

    status = load_status(root)

    # Повтор той же root command после session interruption должен resume
    # существующий record, а не создавать параллельный duplicate.
    latest = _latest_invocation(
        status,
        root_command=normalized["rootCommand"],
    )
    if latest is not None:
        invocation_kind, existing = latest
        if (
            invocation_kind == "active"
            and existing.get("status") == "running"
        ):
            current = existing["current"]
            if current.get("status") == "running":
                current["attempt"] = int(current.get("attempt", 1)) + 1
                current["startedAt"] = utc_now()
                existing["updatedAt"] = utc_now()
                save_status(root, status)
            return existing

    now = utc_now()
    ordinal = int(status.get("nextOrdinal", 1))
    status["nextOrdinal"] = ordinal + 1
    first_command = normalized["sequence"][0]
    current_command = (
        first_command
        if normalized["mode"] != "orchestration"
        else normalized["rootCommand"]
    )
    execution = {
        "executionId": "exec-" + uuid4().hex,
        "ordinal": ordinal,
        "mode": normalized["mode"],
        "requestedCommand": raw_command.strip(),
        "rootCommand": normalized["rootCommand"],
        "sequence": normalized["sequence"],
        "currentIndex": 0 if normalized["mode"] in {"single", "chain"} else None,
        "status": "running",
        "current": {
            "command": current_command,
            "status": "running",
            "result": None,
            "attempt": 1,
            "startedAt": now,
            "completedAt": None,
            "context": {},
        },
        "notExecuted": [],
        "fixReviewCycles": 0,
        "startedAt": now,
        "completedAt": None,
        "updatedAt": now,
    }
    baseline = _baseline_for_new_command(
        root,
        status,
        execution,
        current_command,
    )
    execution["current"]["context"] = _command_context(
        root,
        current_command,
        baseline,
    )
    status["executions"].append(execution)
    save_status(root, status)
    return execution



# Найти конкретный CTS edge между двумя уже нормализованными commands. Cross-domain переход здесь всегда отсутствует.
def _edge_for(
    root: Path,
    from_command: str,
    to_command: str,
) -> dict[str, Any] | None:
    table = load_transition_table(root)
    left = parse_canonical_command(from_command, table)
    right = parse_canonical_command(to_command, table)
    if not left.get("valid") or not right.get("valid"):
        return None
    if left.get("domain") != right.get("domain"):
        return None
    domain = table["domains"][left["domain"]]
    for edge in domain.get("transitions", []):
        if edge.get("from") == left.get("operation") and edge.get("to") == right.get("operation"):
            return edge
    return None



# Выполнить read-only Git probe для runtime preconditions. Сетевые операции здесь
# намеренно не выполняются: command skill позже делает полный fetch/preflight.
def _git_probe(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return proc.returncode, proc.stdout.strip()


# Разрешить remote-tracking ref текущей ветки строго через configured
# git-policy.push.remote. Upstream другой remote не подменяет repository policy.
def _published_ref(root: Path) -> tuple[str | None, str | None]:
    code, branch = _git_probe(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if code != 0 or not branch:
        return None, "detached-or-missing-branch"

    try:
        policy = load_git_policy(root)
    except ConfigError as exc:
        return None, f"git-policy-unreadable:{exc}"
    remote = get(policy, "push.remote")
    if not isinstance(remote, str) or not remote.strip():
        return None, "git-policy-push-remote-missing"

    code, _ = _git_probe(root, "remote", "get-url", remote)
    if code != 0:
        return None, f"configured-remote-missing:{remote}"
    return f"{remote}/{branch}", None


# Проверить narrow deterministic Git readiness. Это не заменяет полный GIT PUSH /
# GIT PR preflight: здесь только fail-closed proof для CTS shortcut edge.
def _git_runtime_precondition(root: Path, name: str) -> str | None:
    remote_ref, error = _published_ref(root)
    if error is not None:
        return error
    assert remote_ref is not None

    code, _ = _git_probe(root, "rev-parse", "--verify", remote_ref)
    remote_exists = code == 0

    if name == "git-push-ready":
        # Новый remote branch допустим: сам GIT PUSH ещё проверит policy и
        # установит upstream. Existing branch обязан быть ancestor локального HEAD,
        # иначе direct CHECK -> PUSH мог бы скрыть remote-ahead/divergence.
        if not remote_exists:
            return None
        code, _ = _git_probe(root, "merge-base", "--is-ancestor", remote_ref, "HEAD")
        return None if code == 0 else "remote-branch-is-not-ancestor-of-head"

    if name == "git-pr-ready":
        if not remote_exists:
            return "remote-branch-is-not-published"
        code, local_head = _git_probe(root, "rev-parse", "HEAD")
        remote_code, remote_head = _git_probe(root, "rev-parse", remote_ref)
        if code != 0 or remote_code != 0 or not local_head or local_head != remote_head:
            return "published-branch-does-not-match-head"
        return None

    return f"unsupported-git-precondition:{name}"


# CHECK -> APPLY доверяет только durable details exact предыдущего CHECK и
# текущему lock. Любая отсутствующая/несовпадающая metadata заставляет сделать
# fresh CHECK отдельной командой вместо молчаливого APPLY.
def _update_runtime_precondition(
    root: Path,
    current: dict[str, Any],
    next_command: str,
) -> str | None:
    details = current.get("details")
    if not isinstance(details, dict):
        return "update-check-details-missing"
    target = details.get("resolvedTarget")
    route = details.get("route")
    lock_ref = details.get("lockRef")
    if (
        not isinstance(target, str)
        or not target
        or not isinstance(lock_ref, str)
        or not lock_ref
        or not isinstance(route, list)
        or not route
        or any(not isinstance(item, str) or not item for item in route)
    ):
        return "update-check-details-invalid"
    if route[0] != lock_ref or route[-1] != target:
        return "update-check-route-does-not-match-details"

    try:
        lock = json.loads(update_lock_path(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "update-lock-unreadable"
    source = lock.get("source")
    if not isinstance(source, dict) or source.get("ref") != lock_ref:
        return "update-lock-ref-changed"

    parsed = normalize_single_command(root, next_command)
    explicit_target = parsed.get("target")
    if explicit_target is not None and explicit_target != target:
        return "update-target-changed"
    return None


# Выполнить runtimePreconditions CTS edge непосредственно перед dispatch. Возврат
# списка причин делает неизвестный/недоказанный precondition fail-closed.
def _command_dispatch_precondition_failures(
    root: Path,
    command: str,
) -> list[str]:
    """Проверить prerequisites команды, у которой нет incoming CTS edge."""
    parsed = normalize_single_command(root, command)
    if (
        parsed.get("domain") == "STEP"
        and parsed.get("operation") == "IMPLEMENT"
        and parsed.get("target")
    ):
        return [
            f"step-implement-ready: {issue}"
            for issue in implementation_prerequisite_failures(
                root,
                str(parsed["target"]),
            )
        ]
    return []


def _runtime_precondition_failures(
    root: Path,
    execution: dict[str, Any],
    next_command: str,
    preconditions: list[str],
) -> list[str]:
    failures: list[str] = []
    current = execution["current"]
    for name in preconditions:
        if name in {"git-push-ready", "git-pr-ready"}:
            issue = _git_runtime_precondition(root, name)
        elif name == "matching-update-target-and-route":
            issue = _update_runtime_precondition(root, current, next_command)
        elif name == "step-implement-ready":
            command_failures = _command_dispatch_precondition_failures(
                root,
                next_command,
            )
            failures.extend(command_failures)
            continue
        else:
            issue = f"unknown-runtime-precondition:{name}"
        if issue is not None:
            failures.append(f"{name}: {issue}")
    return failures



# Построить canonical next command по CTS edge, сохранив STEP/release target текущей execution.
def _build_next_from_edge(
    root: Path,
    current_command: str,
    edge: dict[str, Any],
) -> str:
    table = load_transition_table(root)
    parsed = parse_canonical_command(current_command, table)
    domain_name = parsed["domain"]
    spec = table["domains"][domain_name]["commands"][edge["to"]]
    canonical = spec["canonical"]

    if spec.get("target") == "step":
        target = parsed.get("target")
        if not target:
            raise ValueError("STEP transition lost target")
        canonical = canonical.replace("STEP-NNN", target)
    elif spec.get("target") == "release-optional":
        target = parsed.get("target")
        if target:
            canonical = f"{canonical} TO {target}"
    return canonical.rstrip(":")



# Закрыть root execution как complete/blocked и записать timestamps. Функция не решает, можно ли было туда перейти.
def _mark_root_complete(execution: dict[str, Any], *, blocked: bool = False) -> None:
    execution["status"] = "blocked" if blocked else "complete"
    execution["completedAt"] = utc_now()
    execution["updatedAt"] = utc_now()



# Зафиксировать result текущей command и обновить состояние root execution согласно её mode.
@execution_state_mutation
def complete_command(
    root: Path,
    root_command: str,
    command: str,
    result: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {sorted(RESULTS)}")
    _require_details_budget(details)

    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    # Completion относится к самой новой invocation этого root command.
    # Иначе старый blocked execution может затенить более новый successful
    # execution после его завершения и исказить повторный complete.
    latest = _latest_invocation(
        status,
        root_command=normalized_root,
    )
    if latest is None:
        raise ValueError(f"execution not found for {normalized_root}")
    invocation_kind, execution = latest
    if invocation_kind == "terminal":
        if execution.get("status") == "complete":
            raise ValueError(f"execution is already complete for {normalized_root}")
        raise ValueError(f"execution is blocked for {normalized_root}")
    if execution.get("status") == "blocked":
        raise ValueError(f"execution is blocked for {normalized_root}")
    if execution.get("status") != "running":
        raise ValueError(
            f"execution has unsupported status {execution.get('status')!r} for {normalized_root}"
        )

    current = execution["current"]
    if current.get("command") != normalized_command:
        raise ValueError(
            f"current command is {current.get('command')}, not {normalized_command}"
        )
    if current.get("status") != "running":
        raise ValueError("current command is not running")

    current["status"] = "blocked" if result == "BLOCKED" else "complete"
    current["result"] = result
    current["completedAt"] = utc_now()
    if details is not None:
        current["details"] = details
    execution["updatedAt"] = utc_now()

    # BLOCKED всегда терминален для автоматического продолжения root execution.
    # Уже выполненные side effects при этом не откатываются.
    if result == "BLOCKED":
        _mark_root_complete(execution, blocked=True)
        save_status(root, status)
        return execution

    mode = execution["mode"]
    # Single invocation завершается здесь даже если CTS знает потенциальный edge.
    # Пользователь не просил chain/orchestration — скрыто продолжать нельзя.
    if mode == "single":
        _mark_root_complete(execution)
    elif mode == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            _mark_root_complete(execution)
        else:
            next_command = sequence[index + 1]
            edge = _edge_for(root, current["command"], next_command)
            if edge is None or result not in edge.get("onPreviousResult", []):
                execution["notExecuted"] = sequence[index + 1 :]
                _mark_root_complete(execution)
    elif mode == "orchestration":
        if current["command"] == execution["rootCommand"]:
            _mark_root_complete(execution)

    save_status(root, status)
    return execution



# Проверить допустимость первой child command STEP RUN. Это bootstrap orchestration до появления первого CTS child edge.
def _orchestration_first_child_allowed(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> bool:
    table = load_transition_table(root)
    root_parsed = parse_canonical_command(execution["rootCommand"], table)
    child = parse_canonical_command(command, table)
    if not root_parsed.get("valid") or not child.get("valid"):
        return False
    if root_parsed.get("domain") != "STEP" or root_parsed.get("operation") != "RUN":
        return False
    if child.get("domain") != "STEP":
        return False
    if child.get("target") != root_parsed.get("target"):
        return False
    return child.get("operation") in {"PLAN", "IMPLEMENT", "REVIEW", "FIX", "AUDIT"}



# Перевести chain/orchestration execution на следующую child command. Ожидаемая команда сверяется с resolver, чтобы не перескочить phase.
@execution_state_mutation
def begin_command(
    root: Path,
    root_command: str,
    command: str,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    latest = _latest_invocation(
        status,
        root_command=normalized_root,
    )
    execution = (
        latest[1]
        if latest is not None
        and latest[0] == "active"
        and latest[1].get("status") == "running"
        else None
    )
    if execution is None:
        execution = start_execution(root, root_command)
        status = load_status(root)
        latest = _latest_invocation(
            status,
            root_command=normalized_root,
        )
        assert latest is not None and latest[0] == "active"
        execution = latest[1]

    current = execution["current"]
    if current.get("command") == normalized_command and current.get("status") == "running":
        current["attempt"] = int(current.get("attempt", 1)) + 1
        current["startedAt"] = utc_now()
        baseline = execution.get("implementationBaseline")
        current["context"] = _command_context(
            root,
            normalized_command,
            baseline if isinstance(baseline, dict) else None,
        )
        execution["updatedAt"] = utc_now()
        save_status(root, status)
        return execution

    if execution["mode"] == "single":
        raise ValueError("single execution cannot switch to another command")

    # Для child transition доверяем resolver, а не caller. Это не даёт вручную
    # перескочить, например, с IMPLEMENT сразу в FIX внутри того же root RUN.
    resolved = resolve_execution(root, execution, mutate=False)
    expected = resolved.get("command")

    allow_first_orchestration_child = (
        execution["mode"] == "orchestration"
        and current.get("command") == execution["rootCommand"]
        and current.get("status") == "running"
        and _orchestration_first_child_allowed(root, execution, normalized_command)
    )

    if not allow_first_orchestration_child and expected != normalized_command:
        raise ValueError(
            f"resolver expects {expected!r}, cannot begin {normalized_command!r}"
        )

    if allow_first_orchestration_child:
        failures = _command_dispatch_precondition_failures(
            root,
            normalized_command,
        )
    else:
        preconditions = list(resolved.get("runtimePreconditions") or [])
        failures = _runtime_precondition_failures(
            root,
            execution,
            normalized_command,
            preconditions,
        )
    if failures:
        # Предыдущая child command уже завершилась фактическим result. Не
        # перезаписываем её: blocker относится к переходу/корневой execution.
        execution["blockedBy"] = {
            "reasonCode": "RUNTIME_PRECONDITION_FAILED",
            "command": normalized_command,
            "failures": failures,
        }
        if execution["mode"] == "chain":
            index = int(execution.get("currentIndex", 0))
            execution["notExecuted"] = execution["sequence"][index + 1 :]
        _mark_root_complete(execution, blocked=True)
        save_status(root, status)
        raise ValueError("runtime precondition failed: " + "; ".join(failures))

    if execution["mode"] == "chain":
        # Chain продолжает только sequence, которую пользователь ввёл изначально.
        # CTS не имеет права добавить в неё «логичный» лишний segment. Позиция
        # всегда продвигается на следующий segment: команда может повторяться
        # (REVIEW > FIX > REVIEW), и поиск первого вхождения зациклил бы chain (#116).
        sequence = execution["sequence"]
        index = int(execution.get("currentIndex", 0)) + 1
        if index >= len(sequence) or sequence[index] != normalized_command:
            raise ValueError(
                f"chain expects segment {index}, cannot begin {normalized_command!r}"
            )
        execution["currentIndex"] = index

    # FIX -> REVIEW завершает один repair cycle. Счётчик хранится в root
    # execution и переживает session restart, поэтому budget нельзя обойти
    # перезапуском reasoning-модели.
    previous_parsed = normalize_single_command(root, current["command"])
    next_parsed = normalize_single_command(root, normalized_command)
    if (
        execution["mode"] in {"orchestration", "chain"}
        and previous_parsed.get("domain") == "STEP"
        and previous_parsed.get("operation") == "FIX"
        and current.get("status") == "complete"
        and current.get("result") == "SUCCESS"
        and next_parsed.get("operation") == "REVIEW"
    ):
        execution["fixReviewCycles"] = int(execution.get("fixReviewCycles", 0)) + 1

    baseline = _baseline_for_new_command(
        root,
        status,
        execution,
        normalized_command,
    )
    execution["current"] = {
        "command": normalized_command,
        "status": "running",
        "result": None,
        "attempt": 1,
        "startedAt": utc_now(),
        "completedAt": None,
        "context": _command_context(root, normalized_command, baseline),
    }
    execution["updatedAt"] = utc_now()
    save_status(root, status)
    return execution



def running_command_for(root: Path, root_command: str) -> str | None:
    """Вернуть текущую running команду active execution root или None."""
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    latest = _latest_invocation(load_status(root), root_command=normalized_root)
    if latest is None or latest[0] != "active":
        return None
    execution = latest[1]
    current = execution.get("current")
    if execution.get("status") != "running" or not isinstance(current, dict):
        return None
    if current.get("status") != "running":
        return None
    command = current.get("command")
    return command if isinstance(command, str) else None


def _fix_review_limit(
    root: Path,
    execution: dict[str, Any],
    current_command: str,
    next_command: str,
    result: str,
) -> dict[str, Any] | None:
    """BLOCKED, если REVIEW FAIL открыл бы FIX сверх execution.maxFixReviewCycles."""
    current_parsed = normalize_single_command(root, current_command)
    next_parsed = normalize_single_command(root, next_command)
    if not (
        current_parsed.get("domain") == "STEP"
        and current_parsed.get("operation") == "REVIEW"
        and result == "FAIL"
        and next_parsed.get("operation") == "FIX"
    ):
        return None
    cycles = int(execution.get("fixReviewCycles", 0))
    limit = max_fix_review_cycles(root)
    if cycles < limit:
        return None
    return {
        "status": "BLOCKED",
        "executionId": execution["executionId"],
        "rootCommand": execution["rootCommand"],
        "command": None,
        "reasonCode": "FIX_REVIEW_LIMIT_REACHED",
        "fixReviewCycles": cycles,
        "maxFixReviewCycles": limit,
    }


# Явно остановить root execution как blocked. Blocked state сохраняется между sessions и не продолжается автоматически.
@execution_state_mutation
def block_execution(
    root: Path,
    root_command: str,
    *,
    command: str | None = None,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    latest = _latest_invocation(
        status,
        root_command=normalized_root,
    )
    execution = (
        latest[1]
        if latest is not None
        and latest[0] == "active"
        and latest[1].get("status") == "running"
        else None
    )
    if execution is None:
        raise ValueError(f"active execution not found for {normalized_root}")
    current = execution["current"]
    if command is not None:
        normalized_command = normalize_single_command(root, command)["normalized"]
        if current.get("command") != normalized_command:
            raise ValueError("block command does not match current command")
    # Если blocker возник после уже завершённой child command (например,
    # REVIEW=FAIL после исчерпания FIX budget), не уничтожаем factual verdict.
    # Для running command BLOCKED остаётся result самой команды.
    if current.get("status") == "running":
        current["status"] = "blocked"
        current["result"] = "BLOCKED"
        current["completedAt"] = utc_now()
    elif current.get("status") != "complete":
        raise ValueError("current command must be running or complete to block root execution")
    _mark_root_complete(execution, blocked=True)
    save_status(root, status)
    return execution



# Разрешить STEP id через manifest-driven config layer.
def task_path(root: Path, step_id: str) -> Path:
    return configured_task_path(root, step_id)


# Использовать единый versioned STEP parser; отдельной Markdown-семантики в
# execution layer больше нет.
def read_task(root: Path, step_id: str) -> dict[str, Any]:
    return read_planning_task(root, step_id)


def contract_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    return task_contract_snapshot(root, step_id)


def contract_basis(root: Path, step_id: str) -> str:
    return planning_context_basis(root, step_id)


def plan_info(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    plan = task["frontmatter"].get("plan")
    if not isinstance(plan, dict):
        return {
            "status": None,
            "storedBasis": None,
            "currentBasis": None,
            "storedContentHash": None,
            "currentContentHash": None,
            "ready": False,
        }
    current_basis = contract_basis(root, step_id)
    current_content = plan_content_hash(root, step_id)
    matched = latest_matching_planning_review(root, step_id)
    report_path = (
        matched["path"].relative_to(root).as_posix()
        if matched is not None
        else None
    )
    return {
        "status": plan.get("status"),
        "storedBasis": plan.get("context_basis"),
        "currentBasis": current_basis,
        "storedContentHash": plan.get("content_hash"),
        "currentContentHash": current_content,
        "reviewedReport": plan.get("reviewed_report"),
        "ready": (
            plan.get("status") == "ready"
            and plan.get("context_basis") == current_basis
            and plan.get("content_hash") == current_content
            and report_path is not None
            and plan.get("reviewed_report") == report_path
        ),
    }


# Ready разрешён только после durable PASS planning-review для точных context
# basis + plan content hash. Так direct stamp-plan нельзя использовать для
# обхода semantic consistency gate.
def stamp_plan(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    plan_body = task["sections"].get("Implementation plan", "").strip()
    if not plan_body:
        raise ValueError("Implementation plan must be non-empty before stamp-plan")
    review = latest_matching_planning_review(root, step_id)
    if review is None:
        raise ValueError(
            "no PASS planning-review matches current context basis and plan content"
        )

    meta = task["frontmatter"]
    current_plan = meta.get("plan")
    if not isinstance(current_plan, dict):
        raise ValueError("task frontmatter.plan must be a mapping")
    revision = current_plan.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("task plan.revision must be a non-negative integer")

    basis = planning_context_basis(root, step_id)
    content = plan_content_hash(root, step_id)
    report_path = review["path"].relative_to(root).as_posix()
    meta["plan"] = {
        "status": "ready",
        "revision": revision + 1,
        "context_basis": basis,
        "content_hash": content,
        "reviewed_report": report_path,
        "planned_at": utc_now(),
    }
    updated = render_document(meta, task["body"])
    fd, tmp_name = tempfile.mkstemp(
        prefix=task["path"].name + ".",
        suffix=".tmp",
        dir=str(task["path"].parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(updated)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, task["path"])
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return {
        "stepId": step_id,
        "planStatus": "ready",
        "planRevision": revision + 1,
        "planBasis": basis,
        "planContentHash": content,
        "planningReview": report_path,
    }


# Execution recovery принимает только schema-valid review report. Для REVIEW
# дополнительно требуется совпадение точной git/worktree revision.
def review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    from review_contract import review_reports as valid_reports

    values: list[dict[str, Any]] = []
    for item in valid_reports(root, step_id):
        values.append({
            "path": item["path"].relative_to(root).as_posix(),
            "verdict": item["verdict"],
        })
    return values


def latest_review(root: Path, step_id: str, *, require_current_revision: bool = False) -> dict[str, Any] | None:
    item = latest_valid_review(
        root,
        step_id,
        require_current_revision=require_current_revision,
    )
    if item is None:
        return None
    return {
        "path": item["path"].relative_to(root).as_posix(),
        "verdict": item["verdict"],
    }


# Попробовать доказать completion running command по durable artifacts и тем самым закрыть crash-window между фактом и local checkpoint.
def _durable_recovery_result(
    root: Path,
    execution: dict[str, Any],
) -> str | None:
    current = execution["current"]
    if current.get("status") != "running":
        return None
    parsed = normalize_single_command(root, current["command"])

    # PLAN — редкий случай, где durable artifact сильнее stale local "running":
    # Ready + совпадающий Plan basis доказывают завершение planning.
    if parsed.get("domain") == "STEP" and parsed.get("operation") == "PLAN":
        target = parsed.get("target")
        if target:
            try:
                if plan_info(root, target)["ready"]:
                    return "SUCCESS"
            except (OSError, ValueError, FileNotFoundError):
                return None

    # REVIEW можно восстановить по новому immutable report, появившемуся после
    # reviewReportBefore. FAIL/BLOCKED не меняют STEP lifecycle и потому требуют
    # exact current revision. PASS writer после валидного report может выполнить
    # единственную post-review mutation status->completed; тогда exact revision
    # закономерно меняется, а recovery использует более сильный combined proof:
    # новый PASS report + completed STEP + type-specific completion proof.
    if parsed.get("domain") == "STEP" and parsed.get("operation") == "REVIEW":
        target = parsed.get("target")
        baseline = current.get("context", {}).get("reviewReportBefore")
        if target:
            review = latest_review(root, target, require_current_revision=True)
            if review is not None and review.get("path") != baseline:
                verdict = review.get("verdict")
                if verdict in {"PASS", "FAIL", "BLOCKED"}:
                    return verdict

            latest = latest_review(root, target, require_current_revision=False)
            if (
                latest is not None
                and latest.get("path") != baseline
                and latest.get("verdict") == "PASS"
            ):
                try:
                    task = read_planning_task(root, target)
                    proof = step_completion_proof(root, target)
                except (OSError, ValueError, FileNotFoundError):
                    return None
                if (
                    task["frontmatter"].get("status") == "completed"
                    and proof.get("complete") is True
                ):
                    return "PASS"

    if (
        parsed.get("domain") == "GIT"
        and parsed.get("operation") == "COMMIT"
        and git_commit_completion_proven(root, execution)
    ):
        return "SUCCESS"

    return None



# Применить доказанный durable result к local state так, как будто completion checkpoint успел записаться до crash.
def _apply_recovered_completion(
    root: Path,
    status: dict[str, Any],
    execution: dict[str, Any],
    result: str,
) -> None:
    current = execution["current"]
    current["status"] = "blocked" if result == "BLOCKED" else "complete"
    current["result"] = result
    current["completedAt"] = utc_now()
    current["recoveredFromDurableState"] = True
    execution["updatedAt"] = utc_now()

    if result == "BLOCKED":
        _mark_root_complete(execution, blocked=True)
    elif execution["mode"] == "single":
        _mark_root_complete(execution)
    elif execution["mode"] == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            _mark_root_complete(execution)
        else:
            edge = _edge_for(root, current["command"], sequence[index + 1])
            if edge is None or result not in edge.get("onPreviousResult", []):
                execution["notExecuted"] = sequence[index + 1 :]
                _mark_root_complete(execution)
    elif execution["mode"] == "orchestration" and current["command"] == execution["rootCommand"]:
        _mark_root_complete(execution)
    save_status(root, status)



# Главный deterministic resolver одной root execution: RESUME running command либо NEXT/DONE/BLOCKED по mode и CTS.
@execution_state_mutation
def resolve_execution(
    root: Path,
    execution: dict[str, Any],
    *,
    mutate: bool = True,
) -> dict[str, Any]:
    if execution.get("status") == "complete":
        return {
            "status": "DONE",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "EXECUTION_COMPLETE",
        }
    if execution.get("status") == "blocked":
        return {
            "status": "BLOCKED",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "EXECUTION_BLOCKED",
        }

    current = execution["current"]
    if current.get("status") == "running":
        # Базовое правило: running => RESUME той же command. Только узкий набор
        # доказуемых durable facts имеет право автоматически закрыть crash-window.
        recovered = _durable_recovery_result(root, execution)
        if recovered is not None and mutate:
            status = load_status(root)
            stored = _latest_execution(
                status,
                execution_id=execution["executionId"],
            )
            if stored is not None:
                _apply_recovered_completion(root, status, stored, recovered)
                return resolve_execution(root, stored, mutate=False)
        return {
            "status": "RESUME",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": current["command"],
            "reasonCode": "COMMAND_INTERRUPTED",
            "attempt": current.get("attempt", 1),
        }

    if current.get("status") == "blocked":
        return {
            "status": "BLOCKED",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "COMMAND_BLOCKED",
        }

    result = current.get("result")
    if execution["mode"] == "single":
        return {
            "status": "DONE",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "SINGLE_COMMAND_COMPLETE",
        }

    if execution["mode"] == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            return {
                "status": "DONE",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "CHAIN_COMPLETE",
            }
        next_command = sequence[index + 1]
        edge = _edge_for(root, current["command"], next_command)
        if edge is None or result not in edge.get("onPreviousResult", []):
            return {
                "status": "DONE",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "CHAIN_CONDITION_NOT_MET",
                "notExecuted": sequence[index + 1 :],
            }
        # Ручная chain подчиняется тому же FIX↔REVIEW budget, что и STEP RUN.
        limited = _fix_review_limit(root, execution, current["command"], next_command, result)
        if limited is not None:
            return limited
        return {
            "status": "NEXT",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": next_command,
            "reasonCode": "CHAIN_NEXT_SEGMENT",
            "runtimePreconditions": edge.get("runtimePreconditions", []),
        }

    # STEP RUN — единственная текущая orchestration command. Если появится ещё
    # одна, её semantics нужно добавить явно; generic "умного" продолжения нет.
    # Переходы между дочерними командами используют тот же CTS, что и
    # вручную введённые STEP chains. Отдельной recovery-матрицы нет.
    if execution["mode"] == "orchestration":
        if current["command"] == execution["rootCommand"]:
            return {
                "status": "RESUME",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": execution["rootCommand"],
                "reasonCode": "ORCHESTRATION_ROOT_INTERRUPTED",
            }

        table = load_transition_table(root)
        parsed = parse_canonical_command(current["command"], table)
        domain = table["domains"].get(parsed.get("domain"), {})
        candidates = [
            edge
            for edge in domain.get("transitions", [])
            if edge.get("from") == parsed.get("operation")
            and result in edge.get("onPreviousResult", [])
        ]
        if len(candidates) == 1:
            # execution.maxFixReviewCycles — deterministic orchestration budget,
            # а не рекомендация агенту. После исчерпания лимита REVIEW FAIL не
            # может открыть ещё один FIX даже при повторной session.
            next_command = _build_next_from_edge(root, current["command"], candidates[0])
            limited = _fix_review_limit(root, execution, current["command"], next_command, result)
            if limited is not None:
                return limited
            return {
                "status": "NEXT",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": next_command,
                "reasonCode": "ORCHESTRATION_CTS_TRANSITION",
                "runtimePreconditions": candidates[0].get("runtimePreconditions", []),
            }
        if len(candidates) > 1:
            return {
                "status": "BLOCKED",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "AMBIGUOUS_CTS_TRANSITION",
            }
        return {
            "status": "RESUME",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": execution["rootCommand"],
            "reasonCode": "ORCHESTRATION_CONTINUE",
        }

    raise ValueError(f"unsupported execution mode: {execution['mode']}")



@execution_state_mutation
def implementation_baseline_for_step(
    root: Path,
    step_id: str,
) -> dict[str, Any] | None:
    """Вернуть baseline active STEP invocation, затем bounded stepRecovery.

    Active REVIEW без baseline имеет приоритет и явно подавляет stale recovery.
    Отдельные REVIEW/FIX получают baseline из stepRecovery, а не из бесконечной
    completed execution history.
    """
    status = load_status(root)
    for execution in reversed(status.get("executions", [])):
        current = execution.get("current")
        if (
            execution.get("status") != "running"
            or not isinstance(current, dict)
            or current.get("status") != "running"
        ):
            continue
        try:
            parsed = normalize_single_command(
                root,
                str(current.get("command") or ""),
            )
        except ValueError:
            continue
        if parsed.get("domain") != "STEP" or parsed.get("target") != step_id:
            continue

        # Exact active invocation имеет приоритет даже при отсутствии baseline:
        # это явное доказательство новой/legacy lifecycle, и старый historical
        # proof не должен просачиваться в writer через fallback scan.
        baseline = execution.get("implementationBaseline")
        if isinstance(baseline, dict) and baseline.get("stepId") == step_id:
            return dict(baseline)
        return None

    return _latest_implementation_baseline(status, step_id)


@execution_state_mutation
def stamp_review_expectation(
    root: Path,
    execution_id: str,
    step_id: str,
    repository_revision: dict[str, Any],
    gate_basis: str,
) -> dict[str, Any]:
    """Зафиксировать exact deterministic REVIEW context до semantic reasoning.

    Expectation хранится в active execution, а не приходит обратно от модели.
    Повторный handoff на неизменённом state идемпотентен; попытка заменить уже
    выданную reviewer revision/gate fail-closed.
    """
    if not isinstance(repository_revision, dict):
        raise ValueError("review repository revision must be an object")
    if (
        not isinstance(gate_basis, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", gate_basis) is None
    ):
        raise ValueError("review gate basis must be sha256")

    status = load_status(root)
    execution = _latest_execution(status, execution_id=execution_id)
    if execution is None:
        raise ValueError(f"execution not found: {execution_id}")
    if execution.get("status") != "running":
        raise ValueError("review expectation requires running execution")

    current = execution.get("current")
    if not isinstance(current, dict) or current.get("status") != "running":
        raise ValueError("review expectation requires running current command")
    parsed = normalize_single_command(root, str(current.get("command") or ""))
    if (
        parsed.get("domain") != "STEP"
        or parsed.get("operation") != "REVIEW"
        or parsed.get("target") != step_id
    ):
        raise ValueError("review expectation does not match current STEP REVIEW")

    expectation = {
        "stepId": step_id,
        "repositoryRevision": dict(repository_revision),
        "gateBasis": gate_basis,
    }
    context = current.get("context")
    if not isinstance(context, dict):
        context = {}
        current["context"] = context
    existing = context.get("reviewExpectation")
    if existing is not None and existing != expectation:
        raise ValueError(
            "review expectation already stamped for a different revision/gate"
        )
    context["reviewExpectation"] = expectation
    execution["updatedAt"] = utc_now()
    save_status(root, status)
    return dict(expectation)


@execution_state_mutation
@execution_state_mutation
def record_review_report(root: Path, step_id: str, record: dict[str, Any]) -> bool:
    """Связать созданный writer-ом report с active STEP REVIEW execution.

    Локальный след происхождения: какой execution создал report, с каким
    content hash и для какой revision. Возвращает False, если active REVIEW нет.
    """
    status = load_status(root)
    for execution in status.get("executions", []):
        current = execution.get("current")
        if execution.get("status") != "running" or not isinstance(current, dict):
            continue
        if current.get("status") != "running":
            continue
        try:
            parsed = normalize_single_command(root, str(current.get("command") or ""))
        except ValueError:
            continue
        if parsed.get("domain") != "STEP" or parsed.get("operation") != "REVIEW":
            continue
        if parsed.get("target") != step_id:
            continue
        context = current.get("context")
        if not isinstance(context, dict):
            context = {}
            current["context"] = context
        context["reviewReport"] = dict(record)
        execution["updatedAt"] = utc_now()
        save_status(root, status)
        return True
    return False


def review_expectation_for_step(
    root: Path,
    step_id: str,
) -> dict[str, Any] | None:
    """Вернуть expectation единственного active STEP REVIEW.

    Если active REVIEW существует, но dispatcher не успел/не смог зафиксировать
    expectation, writer не имеет права молча считать текущий state тем, что
    проверяла модель. Несколько concurrent REVIEW одного STEP также ambiguous.
    """
    status = load_status(root)
    matches: list[dict[str, Any]] = []
    for execution in status.get("executions", []):
        if execution.get("status") != "running":
            continue
        current = execution.get("current")
        if not isinstance(current, dict) or current.get("status") != "running":
            continue
        try:
            parsed = normalize_single_command(root, str(current.get("command") or ""))
        except ValueError:
            continue
        if (
            parsed.get("domain") != "STEP"
            or parsed.get("operation") != "REVIEW"
            or parsed.get("target") != step_id
        ):
            continue
        context = current.get("context")
        expectation = (
            context.get("reviewExpectation")
            if isinstance(context, dict)
            else None
        )
        if not isinstance(expectation, dict):
            raise ValueError(
                f"active STEP REVIEW {execution.get('executionId')} has no stamped expectation"
            )
        matches.append(expectation)

    if len(matches) > 1:
        raise ValueError(f"multiple active STEP REVIEW executions for {step_id}")
    return dict(matches[0]) if matches else None


# Найти самую новую invocation конкретного root command и разрешить именно её состояние.
# Статус старой записи не имеет приоритета над более новым запуском того же root:
# иначе historical blocked execution может затенить running/complete successor.
@execution_state_mutation
def resolve_root(root: Path, root_command: str) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    latest = _latest_invocation(
        status,
        root_command=normalized_root,
    )
    if latest is None:
        return {
            "status": "NOT_FOUND",
            "rootCommand": normalized_root,
            "command": None,
            "reasonCode": "EXECUTION_NOT_FOUND",
        }
    invocation_kind, execution = latest
    if invocation_kind == "terminal":
        return _resolve_terminal(execution)
    return resolve_execution(root, execution)



# Вернуть только актуальные unresolved executions: historical blocked record
# перестаёт быть actionable, как только существует более новая invocation того
# же rootCommand. mutate=False используется read-only HARNESS STATUS.
@execution_state_mutation
def unresolved_executions(
    root: Path,
    *,
    mutate: bool = True,
) -> list[dict[str, Any]]:
    status = load_status(root)
    executions = status.get("executions", [])

    latest_ordinal_by_root: dict[str, int] = {}
    for item in [*executions, *status.get("recentTerminals", [])]:
        root_command = item.get("rootCommand")
        ordinal = item.get("ordinal")
        if (
            isinstance(root_command, str)
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
        ):
            latest_ordinal_by_root[root_command] = max(
                latest_ordinal_by_root.get(root_command, 0),
                ordinal,
            )

    values: list[dict[str, Any]] = []
    for execution in executions:
        root_command = execution.get("rootCommand")
        ordinal = execution.get("ordinal")
        if latest_ordinal_by_root.get(root_command) != ordinal:
            continue
        if execution.get("status") in ACTIVE_EXECUTION_STATUSES:
            resolved = resolve_execution(root, execution, mutate=mutate)
            resolved["mode"] = execution["mode"]
            resolved["updatedAt"] = execution["updatedAt"]
            values.append(resolved)
    values.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
    return values



# Найти завершённую command для безопасного cross-session handoff; latest_only используется там, где старый PASS может протухнуть.
def find_completed(
    root: Path,
    command: str,
    *,
    result: str | None = None,
    latest_only: bool = False,
) -> dict[str, Any] | None:
    """Найти recent completed tombstone для cross-session handoff.

    История bounded: функция гарантирует только recent terminal window, а не
    бесконечный audit log. Canonical artifacts должны использоваться для
    долгоживущего proof.
    """
    normalized = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    completed = [
        item
        for item in status.get("recentTerminals", [])
        if item.get("status") == "complete"
    ]
    completed.sort(key=lambda item: int(item.get("ordinal", 0)))

    if latest_only:
        if not completed:
            return None
        latest = completed[-1]
        current = latest.get("current", {})
        if (
            current.get("command") == normalized
            and current.get("status") == "complete"
            and (result is None or current.get("result") == result)
        ):
            return latest
        return None

    for terminal in reversed(completed):
        current = terminal.get("current", {})
        if (
            current.get("command") == normalized
            and current.get("status") == "complete"
            and (result is None or current.get("result") == result)
        ):
            return terminal
    return None
