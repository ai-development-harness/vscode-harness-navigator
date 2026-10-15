#!/usr/bin/env python3
"""Versioned Git-backed Handoff для STEP без переноса local execution state.

Handoff — только переносимое указание на Git/STEP/PLAN факты. Его PASS не
означает разрешение HARNESS RESUME и не подменяет current runtime/CTS guards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import atomic_write_text
from harness_config import task_directory
from planning_contract import plan_content_hash, planning_context_basis, read_task
from repository_recovery import repository_recovery_preview


SCHEMA_VERSION = 1
KIND = "portable-step-handoff"
STEP_ID_RE = re.compile(r"STEP-\d{3,}\Z")
GIT_OID_RE = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
SHA256_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")


class PortableHandoffError(ValueError):
    """Fail-closed ошибка portable handoff boundary."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _git(root: Path, *args: str, timeout: int = 15) -> bytes:
    """Запустить только заранее выбранную read-only команду Git."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PortableHandoffError("GIT_UNAVAILABLE", str(exc)) from exc
    if result.returncode:
        raise PortableHandoffError(
            "GIT_PROOF_UNAVAILABLE", f"cannot prove Git fact: {' '.join(args[:2])}",
        )
    return result.stdout.strip()


def _step_index_oid(root: Path, step_id: str) -> str:
    """Получить exact Git index object STEP без зависимости от CRLF checkout."""
    task = task_directory(root) / f"{step_id}.md"
    if not task.is_file() or task.is_symlink():
        raise PortableHandoffError("STEP_UNSAFE", "STEP file is missing or a symlink")
    rel = task.relative_to(root).as_posix()
    rows = _git(root, "ls-files", "--stage", "-z", "--", rel).split(b"\0")
    records = [row for row in rows if row]
    if len(records) != 1:
        raise PortableHandoffError("STEP_NOT_TRACKED", "STEP must have one Git index entry")
    meta, sep, path = records[0].partition(b"\t")
    parts = meta.split()
    if (
        sep != b"\t" or path.decode("utf-8", errors="surrogateescape") != rel
        or len(parts) != 3 or parts[0] not in {b"100644", b"100755"}
        or parts[2] != b"0"
    ):
        raise PortableHandoffError("STEP_INDEX_INVALID", "STEP index entry is not a regular stage-0 file")
    oid = parts[1].decode("ascii")
    if GIT_OID_RE.fullmatch(oid) is None:
        raise PortableHandoffError("STEP_INDEX_INVALID", "invalid Git object id")
    return oid


def _handoff_path(root: Path, step_id: str, *, create: bool) -> Path:
    """Хранить handoff рядом с manifest-defined taskDirectory, без второго registry."""
    if STEP_ID_RE.fullmatch(step_id) is None:
        raise PortableHandoffError("INVALID_STEP_ID", "expected STEP-NNN")
    directory = task_directory(root)
    if directory.is_symlink() or not directory.is_dir():
        raise PortableHandoffError("TASK_DIRECTORY_UNSAFE", "task directory unavailable")
    handoffs = directory.parent / "handoffs"
    if handoffs.is_symlink():
        raise PortableHandoffError("HANDOFF_PATH_UNSAFE", "handoff directory is a symlink")
    if not handoffs.resolve().is_relative_to(root):
        raise PortableHandoffError("HANDOFF_PATH_UNSAFE", "handoff path escapes repository")
    if create:
        handoffs.mkdir(parents=True, exist_ok=True)
    path = handoffs / f"{step_id}.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PortableHandoffError("HANDOFF_PATH_UNSAFE", "handoff path must be a regular file")
    return path


def _canonical_facts(root: Path, step_id: str) -> dict[str, str]:
    """Единственные разрешённые semantic facts — существующие Harness fingerprints."""
    task = read_task(root, step_id)
    plan = task["frontmatter"].get("plan")
    if not isinstance(plan, dict):
        raise PortableHandoffError("PLAN_INVALID", "STEP plan is not a mapping")
    status = task["frontmatter"].get("status")
    if status != "in_progress":
        raise PortableHandoffError(
            "STEP_NOT_IN_PROGRESS", "only in_progress STEP can publish handoff",
        )
    try:
        return {
            "stepStatus": status,
            "planStatus": str(plan.get("status")),
            "planningContextBasis": planning_context_basis(root, step_id),
            "planContentHash": plan_content_hash(root, step_id),
        }
    except (OSError, ValueError) as exc:
        raise PortableHandoffError("CONTRACT_UNPROVEN", str(exc)) from exc


def _validate_payload(value: Any, step_id: str) -> dict[str, Any]:
    """Strict allowlist: запрещены provider/session/secret/user-auth поля."""
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "kind", "stepId", "source", "facts",
    }:
        raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", "unknown/missing top-level fields")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != SCHEMA_VERSION or value["kind"] != KIND:
        raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", "unsupported schema or kind")
    if value["stepId"] != step_id:
        raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", "STEP identity mismatch")
    source, facts = value["source"], value["facts"]
    if (
        not isinstance(source, dict)
        or set(source) != {"gitHeadBeforeHandoff", "branch", "taskIndexObject"}
        or not isinstance(facts, dict)
        or set(facts) != {"stepStatus", "planStatus", "planningContextBasis", "planContentHash"}
    ):
        raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", "source/facts allowlist mismatch")
    if not (
        isinstance(source["gitHeadBeforeHandoff"], str)
        and GIT_OID_RE.fullmatch(source["gitHeadBeforeHandoff"])
        and isinstance(source["taskIndexObject"], str)
        and GIT_OID_RE.fullmatch(source["taskIndexObject"])
        and isinstance(source["branch"], str)
        and bool(source["branch"].strip())
        and not any(char in source["branch"] for char in ("\n", "\r", "\0"))
        and facts["stepStatus"] == "in_progress"
        and facts["planStatus"] in {"ready", "draft", "not_planned"}
        and isinstance(facts["planningContextBasis"], str)
        and SHA256_RE.fullmatch(facts["planningContextBasis"])
        and isinstance(facts["planContentHash"], str)
        and SHA256_RE.fullmatch(facts["planContentHash"])
    ):
        raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", "invalid typed portable handoff fields")
    return value


def _result_error(exc: PortableHandoffError) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "BLOCKED",
        "reasonCode": exc.code,
        "message": str(exc),
        "safeToResume": False,
        "nextCommand": None,
    }


def write_handoff(root: Path, step_id: str) -> dict[str, Any]:
    """Подготовить portable файл; НЕ делать git add, commit, push или execution import."""
    root = root.resolve()
    try:
        preview = repository_recovery_preview(root, step_id)
        if preview["status"] != "PASS" or preview.get("candidateCount") != 1:
            raise PortableHandoffError(
                "REPOSITORY_NOT_PUBLISHABLE",
                f"read-only STEP preflight blocked: {preview.get('reasonCode')}",
            )
        git = preview["git"]
        if git["dirty"] or git["branch"] is None:
            raise PortableHandoffError("REPOSITORY_NOT_PUBLISHABLE", "Git worktree must be clean")
        path = _handoff_path(root, step_id, create=False)
        current = path.read_bytes() if path.is_file() else None
        if current is not None:
            # Чужой/неизвестный файл нельзя затереть под видом renewal.
            try:
                _validate_payload(json.loads(current.decode("utf-8")), step_id)
            except (ValueError, UnicodeError) as exc:
                raise PortableHandoffError("HANDOFF_COLLISION", str(exc)) from exc

        record = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": KIND,
            "stepId": step_id,
            "source": {
                "gitHeadBeforeHandoff": git["head"],
                "branch": git["branch"],
                "taskIndexObject": _step_index_oid(root, step_id),
            },
            "facts": _canonical_facts(root, step_id),
        }
        _validate_payload(record, step_id)
        content = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = _handoff_path(root, step_id, create=True)
        if current is None:
            # O_EXCL: чужой файл, возникший после preflight, не overwrite.
            try:
                with path.open("x", encoding="utf-8", newline="\n") as fh:
                    fh.write(content)
                    fh.flush()
                    os.fsync(fh.fileno())
            except FileExistsError as exc:
                raise PortableHandoffError("HANDOFF_COLLISION", "handoff appeared concurrently") from exc
        else:
            atomic_write_text(path, content, expected_bytes=current)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "PASS",
            "reasonCode": "HANDOFF_WRITTEN_NOT_PUBLISHED",
            "path": path.relative_to(root).as_posix(),
            "sourceGitHead": git["head"],
            "safeToResume": False,
            "nextCommand": None,
            "gitActionsExecuted": False,
        }
    except PortableHandoffError as exc:
        return _result_error(exc)
    except (OSError, ValueError, UnicodeError) as exc:
        return _result_error(PortableHandoffError("HANDOFF_WRITE_BLOCKED", str(exc)))


def check_handoff(root: Path, step_id: str) -> dict[str, Any]:
    """Проверить опубликованный Git-handoff, но не импортировать его в Execution Status."""
    root = root.resolve()
    try:
        preview = repository_recovery_preview(root, step_id)
        if preview["status"] != "PASS" or preview.get("candidateCount") != 1:
            raise PortableHandoffError(
                "REPOSITORY_STATE_INVALID",
                f"repository diagnostic blocked: {preview.get('reasonCode')}",
            )
        git = preview["git"]
        path = _handoff_path(root, step_id, create=False)
        if not path.is_file():
            raise PortableHandoffError("HANDOFF_NOT_FOUND", "no portable handoff for STEP")
        rel = path.relative_to(root).as_posix()
        # Index alone недостаточен: staged/unpublished handoff ещё не part of HEAD.
        in_head = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{rel}"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=15,
        )
        if in_head.returncode:
            raise PortableHandoffError("HANDOFF_NOT_PUBLISHED", "handoff is not committed")
        try:
            record = _validate_payload(json.loads(path.read_text(encoding="utf-8")), step_id)
        except (ValueError, UnicodeError) as exc:
            raise PortableHandoffError("HANDOFF_SCHEMA_INVALID", str(exc)) from exc
        source = record["source"]
        if git["branch"] != source["branch"]:
            raise PortableHandoffError("HANDOFF_BRANCH_CHANGED", "published handoff belongs to another branch")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source["gitHeadBeforeHandoff"], "HEAD"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=15,
        )
        if ancestor.returncode:
            raise PortableHandoffError("HANDOFF_SOURCE_UNREACHABLE", "source HEAD is not an ancestor")
        if source["taskIndexObject"] != _step_index_oid(root, step_id):
            raise PortableHandoffError("HANDOFF_STEP_CHANGED", "task Git object changed")
        if record["facts"] != _canonical_facts(root, step_id):
            raise PortableHandoffError("HANDOFF_CONTRACT_STALE", "STEP/REQ/ADR/PLAN context changed")

        # Handoff не является distributed lease. Если с момента его публикации
        # появился ещё один commit (даже без изменения STEP/REQ/ADR), старый
        # снимок не должен разрешать работу поверх нового product code.
        # Поэтому HEAD обязан быть самим publication commit, а его единственным
        # parent — снимок Git перед writer. Никаких wall-clock/latest heuristics.
        parents = _git(root, "rev-list", "--parents", "-n", "1", "HEAD").decode("ascii").split()
        if (
            len(parents) != 2
            or parents[0] != git["head"]
            or parents[1] != source["gitHeadBeforeHandoff"]
        ):
            raise PortableHandoffError(
                "HANDOFF_OUTDATED",
                "HEAD is not the exact handoff publication commit; publish a new handoff",
            )

        # Writer работает только с clean repository. Publication commit также
        # не может незаметно захватить новые product changes в один Git commit
        # с handoff: тогда сохранённые до commit semantic facts были бы stale.
        changed = [
            name.decode("utf-8", errors="surrogateescape")
            for name in _git(root, "diff-tree", "--no-commit-id", "--name-only",
                             "-r", "-z", "HEAD").split(b"\0")
            if name
        ]
        if changed != [rel]:
            raise PortableHandoffError(
                "HANDOFF_PUBLICATION_MIXED",
                "publication commit must change only this handoff file",
            )

        # Git status может не заметить изменения в файлах с assume-unchanged.
        # Сравниваем реальный payload с blob текущего HEAD: подмена локального
        # JSON не должна проходить из-за флагов Git index.
        published = _git(root, "show", f"HEAD:{rel}")
        if json.loads(published) != record:
            raise PortableHandoffError(
                "HANDOFF_WORKTREE_MISMATCH",
                "handoff working-tree content differs from published Git object",
            )
        # Если настроена upstream tracking branch, локальная revision
        # обязана совпадать с ПОСЛЕДНИМ ИЗВЕСТНЫМ tracking ref. При гонке двух
        # publishers после explicit fetch появится divergence и BLOCKED.
        # Здесь намеренно нет fetch/ls-remote: скрытых сетевых действий нет.
        upstream = subprocess.run(
            ["git", "rev-parse", "--verify", "@{upstream}"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )
        if upstream.returncode == 0 and upstream.stdout.strip().decode("ascii") != git["head"]:
            raise PortableHandoffError(
                "HANDOFF_UPSTREAM_DIVERGED",
                "tracked upstream differs from local HEAD; reconcile Git before resume",
            )
        if _git(root, "rev-parse", "--verify", "HEAD").decode("ascii") != git["head"]:
            raise PortableHandoffError("HANDOFF_HEAD_CHANGED", "HEAD moved during validation")

        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "PASS",
            "reasonCode": "HANDOFF_PROVEN_NOT_EXECUTION",
            "stepId": step_id,
            "path": rel,
            "sourceGitHead": source["gitHeadBeforeHandoff"],
            "publicationHead": git["head"],
            "safeToResume": False,
            "nextCommand": None,
            "localExecutionImported": False,
        }
    except PortableHandoffError as exc:
        return _result_error(exc)
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired) as exc:
        return _result_error(PortableHandoffError("HANDOFF_CHECK_BLOCKED", str(exc)))


__all__ = ["PortableHandoffError", "write_handoff", "check_handoff"]
