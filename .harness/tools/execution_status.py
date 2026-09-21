#!/usr/bin/env python3
"""Универсальное crash-safe состояние выполнения Harness-команд.

Validation note
---------------
Модуль в целом не является standalone validator, но `validate_status()` —
обязательная schema boundary local execution state. И чтение, и запись проходят
через неё, поэтому повреждённый JSON/state не трактуется как "истории нет".



Модуль хранит operational history всех canonical invocations в одном локальном
файле .harness/local/execution/execution-status.json. Он не является audit log
и не заменяет canonical project artifacts.

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

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
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
    latest_matching_planning_review,
    max_fix_review_cycles,
    plan_content_hash,
    planning_context_basis,
    read_task as read_planning_task,
    task_contract_snapshot,
    task_path as configured_task_path,
)
from review_contract import latest_review as latest_valid_review

# Фиксированный project-level operational state. Один файл намеренно покрывает
# STEP, Git, Harness update и остальные namespaces.
STATUS_PATH = ".harness/local/execution/execution-status.json"
# mode описывает форму уже существующего пользовательского ввода и НЕ является
# новой командой/профилем. Пользователь никогда не выбирает mode вручную.
EXECUTION_MODES = {"single", "chain", "orchestration"}
EXECUTION_STATUSES = {"running", "complete", "blocked"}
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



# Создать пустую schema v1 для проекта, где execution-status ещё ни разу не записывался.
def empty_status() -> dict[str, Any]:
    return {"schemaVersion": 1, "executions": []}



# Прочитать local state и сразу проверить schema. Повреждённый JSON/state не должен тихо трактоваться как отсутствие истории.
def load_status(root: Path) -> dict[str, Any]:
    path = status_path(root)
    if not path.is_file():
        return empty_status()
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    errors = validate_status(value)
    if errors:
        raise ValueError("; ".join(errors))
    return value



# ---------------------------------------------------------------------------
# Execution Status schema validator.
# Проверяет только форму operational state; допустимость command transitions
# остаётся за CTS. Такое разделение не превращает local recovery state во второй
# source of truth protocol semantics.
# ---------------------------------------------------------------------------
def validate_status(value: dict[str, Any]) -> list[str]:
    """Проверить schemaVersion, records, IDs, modes/status/results и attempts."""
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("execution-status: schemaVersion must be 1")
    # Несколько records нужны принципиально: отдельный GIT CHECK не должен
    # уничтожать interrupted STEP RUN, и наоборот.
    executions = value.get("executions")
    if not isinstance(executions, list):
        return errors + ["execution-status: executions must be an array"]

    ids: set[str] = set()
    for index, execution in enumerate(executions):
        prefix = f"execution-status.executions[{index}]"
        if not isinstance(execution, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        execution_id = execution.get("executionId")
        if not isinstance(execution_id, str) or not execution_id:
            errors.append(f"{prefix}: executionId must be non-empty")
        elif execution_id in ids:
            errors.append(f"{prefix}: duplicate executionId {execution_id}")
        else:
            ids.add(execution_id)

        if execution.get("mode") not in EXECUTION_MODES:
            errors.append(f"{prefix}: invalid mode")
        if execution.get("status") not in EXECUTION_STATUSES:
            errors.append(f"{prefix}: invalid status")
        if not isinstance(execution.get("rootCommand"), str) or not execution.get("rootCommand"):
            errors.append(f"{prefix}: rootCommand must be non-empty")

        sequence = execution.get("sequence")
        if not isinstance(sequence, list) or any(
            not isinstance(item, str) or not item for item in sequence
        ):
            errors.append(f"{prefix}: sequence must be a non-empty string array")

        current = execution.get("current")
        if not isinstance(current, dict):
            errors.append(f"{prefix}: current must be an object")
            continue
        if not isinstance(current.get("command"), str) or not current.get("command"):
            errors.append(f"{prefix}: current.command must be non-empty")
        if current.get("status") not in COMMAND_STATUSES:
            errors.append(f"{prefix}: invalid current.status")
        result = current.get("result")
        if result is not None and result not in RESULTS:
            errors.append(f"{prefix}: invalid current.result")
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
    return errors



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
# load_status(). Нельзя сохранить структуру, которую следующий процесс не сможет
# корректно восстановить.
def save_status(root: Path, value: dict[str, Any]) -> None:
    errors = validate_status(value)
    if errors:
        raise ValueError("; ".join(errors))
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
    candidates = status.get("executions", [])
    for item in reversed(candidates):
        if execution_id is not None and item.get("executionId") != execution_id:
            continue
        if root_command is not None and item.get("rootCommand") != root_command:
            continue
        if statuses is not None and item.get("status") not in statuses:
            continue
        return item
    return None



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



# Собрать минимальный context, нужный только для crash recovery конкретных commands; не превращать его в копию project state.
def _command_context(root: Path, command: str) -> dict[str, Any]:
    parsed = normalize_single_command(root, command)
    context: dict[str, Any] = {}

    if parsed.get("domain") == "STEP" and parsed.get("target"):
        step_id = parsed["target"]
        if parsed.get("operation") in {"PLAN", "IMPLEMENT", "REVIEW", "FIX"}:
            try:
                context["planBasisAtStart"] = contract_basis(root, step_id)
            except (OSError, ValueError, FileNotFoundError):
                pass
        if parsed.get("operation") == "REVIEW":
            review = latest_review(root, step_id)
            context["reviewReportBefore"] = review["path"] if review else None

    # Для COMMIT сравнение HEAD защищает от создания второго commit, если Git
    # mutation успела завершиться, а local complete-checkpoint — нет.
    if parsed.get("domain") == "GIT" and parsed.get("operation") == "COMMIT":
        context["gitHeadBefore"] = _git_head(root)

    return context



# Зарегистрировать новый root invocation либо resume уже running invocation с тем же normalized rootCommand.
def start_execution(root: Path, raw_command: str) -> dict[str, Any]:
    normalized = _normalize_root(root, raw_command)
    status = load_status(root)

    # Повтор той же root command после session interruption должен resume
    # существующий record, а не создавать параллельный duplicate.
    existing = _latest_execution(
        status,
        root_command=normalized["rootCommand"],
        statuses={"running"},
    )
    if existing is not None:
        current = existing["current"]
        if current.get("status") == "running":
            current["attempt"] = int(current.get("attempt", 1)) + 1
            current["startedAt"] = utc_now()
            existing["updatedAt"] = utc_now()
            save_status(root, status)
        return existing

    now = utc_now()
    first_command = normalized["sequence"][0]
    execution = {
        "executionId": "exec-" + uuid4().hex,
        "mode": normalized["mode"],
        "requestedCommand": raw_command.strip(),
        "rootCommand": normalized["rootCommand"],
        "sequence": normalized["sequence"],
        "currentIndex": 0 if normalized["mode"] in {"single", "chain"} else None,
        "status": "running",
        "current": {
            "command": first_command if normalized["mode"] != "orchestration" else normalized["rootCommand"],
            "status": "running",
            "result": None,
            "attempt": 1,
            "startedAt": now,
            "completedAt": None,
            "context": _command_context(
                root,
                first_command if normalized["mode"] != "orchestration" else normalized["rootCommand"],
            ),
        },
        "notExecuted": [],
        "fixReviewCycles": 0,
        "startedAt": now,
        "completedAt": None,
        "updatedAt": now,
    }
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

    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running", "blocked"},
    )
    if execution is None:
        raise ValueError(f"active execution not found for {normalized_root}")

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
def begin_command(
    root: Path,
    root_command: str,
    command: str,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running"},
    )
    if execution is None:
        execution = start_execution(root, root_command)
        status = load_status(root)
        execution = _latest_execution(
            status,
            root_command=normalized_root,
            statuses={"running"},
        )
        assert execution is not None

    current = execution["current"]
    if current.get("command") == normalized_command and current.get("status") == "running":
        current["attempt"] = int(current.get("attempt", 1)) + 1
        current["startedAt"] = utc_now()
        current["context"] = _command_context(root, normalized_command)
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

    preconditions = [] if allow_first_orchestration_child else list(
        resolved.get("runtimePreconditions") or []
    )
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
        # CTS не имеет права добавить в неё «логичный» лишний segment.
        sequence = execution["sequence"]
        index = sequence.index(normalized_command)
        execution["currentIndex"] = index

    # FIX -> REVIEW завершает один repair cycle. Счётчик хранится в root
    # execution и переживает session restart, поэтому budget нельзя обойти
    # перезапуском reasoning-модели.
    previous_parsed = normalize_single_command(root, current["command"])
    next_parsed = normalize_single_command(root, normalized_command)
    if (
        execution["mode"] == "orchestration"
        and previous_parsed.get("domain") == "STEP"
        and previous_parsed.get("operation") == "FIX"
        and current.get("status") == "complete"
        and current.get("result") == "SUCCESS"
        and next_parsed.get("operation") == "REVIEW"
    ):
        execution["fixReviewCycles"] = int(execution.get("fixReviewCycles", 0)) + 1

    execution["current"] = {
        "command": normalized_command,
        "status": "running",
        "result": None,
        "attempt": 1,
        "startedAt": utc_now(),
        "completedAt": None,
        "context": _command_context(root, normalized_command),
    }
    execution["updatedAt"] = utc_now()
    save_status(root, status)
    return execution



# Явно остановить root execution как blocked. Blocked state сохраняется между sessions и не продолжается автоматически.
def block_execution(
    root: Path,
    root_command: str,
    *,
    command: str | None = None,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running"},
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
    # reviewReportBefore. Это экономит повторный дорогой review после crash.
    if parsed.get("domain") == "STEP" and parsed.get("operation") == "REVIEW":
        target = parsed.get("target")
        baseline = current.get("context", {}).get("reviewReportBefore")
        if target:
            review = latest_review(root, target, require_current_revision=True)
            if review is not None and review.get("path") != baseline:
                verdict = review.get("verdict")
                if verdict in {"PASS", "FAIL", "BLOCKED"}:
                    return verdict

    if parsed.get("domain") == "GIT" and parsed.get("operation") == "COMMIT":
        before = current.get("context", {}).get("gitHeadBefore")
        now = _git_head(root)
        if before and now and before != now:
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
            if (
                parsed.get("domain") == "STEP"
                and parsed.get("operation") == "REVIEW"
                and result == "FAIL"
                and candidates[0].get("to") == "FIX"
            ):
                cycles = int(execution.get("fixReviewCycles", 0))
                limit = max_fix_review_cycles(root)
                if cycles >= limit:
                    return {
                        "status": "BLOCKED",
                        "executionId": execution["executionId"],
                        "rootCommand": execution["rootCommand"],
                        "command": None,
                        "reasonCode": "FIX_REVIEW_LIMIT_REACHED",
                        "fixReviewCycles": cycles,
                        "maxFixReviewCycles": limit,
                    }

            next_command = _build_next_from_edge(root, current["command"], candidates[0])
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



# Найти последнюю relevant execution для конкретного root command и разрешить её текущее состояние.
def resolve_root(root: Path, root_command: str) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running", "blocked"},
    )
    if execution is None:
        completed = _latest_execution(
            status,
            root_command=normalized_root,
            statuses={"complete"},
        )
        if completed is not None:
            return resolve_execution(root, completed)
        return {
            "status": "NOT_FOUND",
            "rootCommand": normalized_root,
            "command": None,
            "reasonCode": "EXECUTION_NOT_FOUND",
        }
    return resolve_execution(root, execution)



# Вернуть все running/blocked executions проекта. Это позволяет новой session увидеть несколько независимых незавершённых работ.
def unresolved_executions(root: Path) -> list[dict[str, Any]]:
    status = load_status(root)
    values: list[dict[str, Any]] = []
    for execution in status.get("executions", []):
        if execution.get("status") in {"running", "blocked"}:
            resolved = resolve_execution(root, execution)
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
    normalized = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    executions = status.get("executions", [])

    if latest_only:
        latest_completed = next(
            (
                execution
                for execution in reversed(executions)
                if execution.get("status") == "complete"
            ),
            None,
        )
        if latest_completed is None:
            return None
        current = latest_completed.get("current", {})
        if (
            current.get("command") == normalized
            and current.get("status") == "complete"
            and (result is None or current.get("result") == result)
        ):
            return latest_completed
        return None

    for execution in reversed(executions):
        current = execution.get("current", {})
        if (
            current.get("command") == normalized
            and current.get("status") == "complete"
            and (result is None or current.get("result") == result)
        ):
            return execution
    return None
