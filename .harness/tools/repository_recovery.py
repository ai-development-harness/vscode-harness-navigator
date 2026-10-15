#!/usr/bin/env python3
"""Read-only поиск возможной незавершённой STEP-работы в другом Git-клоне.

Repository facts не заменяют локальный execution checkpoint: отсутствие
executionId, Intent Basis и side-effect proof всегда запрещает auto-resume.
Модуль только объясняет, что видно из опубликованных project artifacts.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from harness_config import get, load_manifest, task_directory
from document_contract import STEP_STATUSES, STEP_TYPES, exact_h1, require_schema
from planning_contract import (
    REQUIRED_TASK_SECTIONS,
    latest_matching_planning_review,
    plan_content_hash,
    planning_context_basis,
    read_task,
)


STEP_ID_RE = re.compile(r"STEP-\d{3,}\Z")


class RepositoryRecoveryError(ValueError):
    """Не удалось безопасно построить read-only кандидат восстановления."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _git(root: Path, *args: str, required: bool = True) -> bytes | None:
    """Прочитать Git-факт без fetch, checkout или другой mutation команды."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryRecoveryError("GIT_UNAVAILABLE", str(exc)) from exc
    if result.returncode != 0:
        if not required:
            return None
        raise RepositoryRecoveryError(
            "GIT_UNAVAILABLE",
            f"cannot read Git fact: {' '.join(args)}",
        )
    return result.stdout.strip()


def _git_facts(root: Path) -> dict[str, Any]:
    """Проверить, что мы читаем Git worktree именно выбранного Harness root."""
    top = _git(root, "rev-parse", "--show-toplevel")
    assert top is not None
    if Path(top.decode("utf-8", errors="surrogateescape")).resolve() != root:
        raise RepositoryRecoveryError(
            "GIT_ROOT_MISMATCH", "Harness root must be the Git worktree root",
        )
    head = _git(root, "rev-parse", "--verify", "HEAD")
    assert head is not None
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", required=False)
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    assert status is not None
    return {
        "head": head.decode("ascii"),
        "branch": branch.decode("utf-8", errors="surrogateescape") if branch else None,
        "dirty": bool(status),
    }


def _candidate(root: Path, step_id: str) -> dict[str, Any] | None:
    """Извлечь только факты STEP. Не выдавать потенциальную команду за RESUME."""
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    if meta.get("id") != step_id:
        raise RepositoryRecoveryError(
            "STEP_ID_MISMATCH", f"{step_id}: document ID differs from filename",
        )

    # Parser подтверждает синтаксис, но не обязательные schema/sections.
    # Не называем повреждённый STEP "просто не in_progress": ошибка в
    # проектных данных должна оставаться видимой, даже для полного scan.
    invalid = require_schema(task)
    if not exact_h1(task, step_id):
        invalid.append("invalid STEP H1")
    if meta.get("status") not in STEP_STATUSES:
        invalid.append("invalid STEP status")
    if meta.get("type") not in STEP_TYPES:
        invalid.append("invalid STEP type")
    for title in REQUIRED_TASK_SECTIONS:
        if title not in task["sections"]:
            invalid.append(f"missing required section: {title}")
    if invalid:
        raise RepositoryRecoveryError(
            "STEP_CONTRACT_INVALID", f"{step_id}: " + "; ".join(invalid),
        )
    if meta.get("status") != "in_progress":
        return None

    # Даже у ещё не Ready STEP обязательны разрешимые REQ/ADR/STEP/OQ
    # links. Для этого используется тот же canonical planning snapshot,
    # что и для полноценного STEP PLAN, а не альтернативный resolver.
    try:
        current_context = planning_context_basis(root, step_id)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RepositoryRecoveryError(
            "STEP_REFERENCES_UNPROVEN", f"{step_id}: {exc}",
        ) from exc

    plan = meta.get("plan")
    plan_status = plan.get("status") if isinstance(plan, dict) else None
    if plan_status != "ready":
        freshness, reason = "not_ready", "PLAN_NOT_READY"
    else:
        try:
            context_ok = plan.get("context_basis") == current_context
            content_ok = plan.get("content_hash") == plan_content_hash(root, step_id)
            if not context_ok or not content_ok:
                freshness, reason = "stale", "PLAN_BASIS_STALE"
            else:
                # Совпавшие hashes ещё не доказывают обязательный независимый
                # planning-review. Проверяем его через canonical resolver, а
                # не придумываем ещё одну схему доверия для Portable Resume.
                review = latest_matching_planning_review(root, step_id)
                expected_report = plan.get("reviewed_report")
                report_path = (
                    review["path"].relative_to(root).as_posix()
                    if review is not None else None
                )
                if report_path is None or report_path != expected_report:
                    freshness, reason = "unprovable", "PLAN_REVIEW_PROOF_MISSING"
                else:
                    freshness, reason = "fresh", "LOCAL_EXECUTION_PROOF_MISSING"
        except (OSError, ValueError, KeyError, TypeError):
            freshness, reason = "unprovable", "PLAN_PROOF_UNAVAILABLE"

    # Даже fresh Ready plan не подтверждает выполненный IMPLEMENT, наличие
    # Verification proof и точку продолжения одной конкретной invocation.
    return {
        "stepId": step_id,
        "lifecycleStatus": "in_progress",
        "planStatus": plan_status,
        "planFreshness": freshness,
        "reasonCode": reason,
        "safeToResume": False,
        "nextCommand": None,
        "requires": [
            "inspect published STEP and implementation",
            "verify current canonical contracts and prerequisites",
            "repeat Verification where local proof is unavailable",
            "resolve safe STEP phase through normal Harness gates",
        ],
    }


def repository_recovery_preview(root: Path, step_id: str | None = None) -> dict[str, Any]:
    """Вернуть кандидатов по tracked project state, ничего не импортируя.

    Результат PASS подтверждает только успешную диагностику, НЕ право
    выполнить команду. Этот API не читает .harness/local и не меняет
    execution-status.json, checkpoint marker, reviews или Git refs.
    """
    root = root.resolve()
    try:
        if step_id is not None and STEP_ID_RE.fullmatch(step_id) is None:
            raise RepositoryRecoveryError(
                "INVALID_STEP_ID", "expected canonical STEP-NNN identifier",
            )
        manifest = load_manifest(root)
        if get(manifest, "project.initialized", False) is not True:
            raise RepositoryRecoveryError(
                "PROJECT_NOT_INITIALIZED", "PROJECT INIT has not completed",
            )
        git = _git_facts(root)
        directory = task_directory(root)
        if not directory.is_dir() or directory.is_symlink():
            raise RepositoryRecoveryError(
                "TASK_DIRECTORY_UNAVAILABLE", "configured task directory is missing or unsafe",
            )

        paths = [directory / f"{step_id}.md"] if step_id else sorted(directory.glob("STEP-*.md"))
        candidates: list[dict[str, Any]] = []
        for path in paths:
            if not path.is_file() or path.is_symlink():
                raise RepositoryRecoveryError(
                    "STEP_DOCUMENT_UNAVAILABLE",
                    f"canonical STEP file is missing or unsafe: {path.name}",
                )
            if STEP_ID_RE.fullmatch(path.stem) is None:
                raise RepositoryRecoveryError(
                    "INVALID_STEP_ID", f"invalid canonical STEP filename: {path.name}",
                )
            if not path.resolve().is_relative_to(root):
                raise RepositoryRecoveryError(
                    "STEP_DOCUMENT_UNSAFE", f"STEP path leaves repository: {path.name}",
                )
            # Чистый git status не доказывает, что ignored файл попал в
            # опубликованный commit. Кандидат Portable Resume должен
            # существовать именно в Git index, а не только на диске.
            rel = path.relative_to(root).as_posix()
            if _git(root, "ls-files", "--error-unmatch", "--", rel, required=False) is None:
                raise RepositoryRecoveryError(
                    "STEP_NOT_TRACKED", f"canonical STEP is not tracked by Git: {rel}",
                )
            candidate = _candidate(root, path.stem)
            if candidate is not None:
                candidates.append(candidate)

        if git["branch"] is None:
            status, reason = "BLOCKED", "DETACHED_HEAD"
        elif git["dirty"]:
            status, reason = "BLOCKED", "WORKTREE_DIRTY"
        else:
            status = "PASS"
            reason = (
                "NO_IN_PROGRESS_STEP" if not candidates
                else "MULTIPLE_RECOVERY_CANDIDATES" if len(candidates) > 1
                else "RECOVERY_CANDIDATE_REQUIRES_INSPECTION"
            )
        return {
            "schemaVersion": 1,
            "status": status,
            "reasonCode": reason,
            "mode": "read-only",
            "source": "git-and-canonical-project-artifacts",
            "git": git,
            "candidates": candidates,
            "candidateCount": len(candidates),
            "safeToResume": False,
            "nextCommand": None,
            "localExecutionImported": False,
            "externalSideEffectsExecuted": False,
        }
    except RepositoryRecoveryError as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": exc.code,
            "message": str(exc),
            "mode": "read-only",
            "safeToResume": False,
            "nextCommand": None,
        }
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": "REPOSITORY_RECOVERY_UNPROVEN",
            "message": str(exc),
            "mode": "read-only",
            "safeToResume": False,
            "nextCommand": None,
        }


__all__ = ["RepositoryRecoveryError", "repository_recovery_preview"]
