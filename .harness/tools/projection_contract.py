#!/usr/bin/env python3
"""Детерминированный renderer/validator tracked project projections.

Canonical REQ/STEP/OQ являются source of truth. Projection-файлы — только
отслеживаемое представление для навигации и обзора.

Validator не сравнивает "смысл" или отдельные поля: expected content полностью
рендерится заново и должен byte-for-byte совпасть с tracked copy.

Fail-closed: malformed canonical artifact, недоказуемый completion proof или
ошибка relevant OQ derivation превращаются в ProjectionDerivationError, а не в
частичную правдоподобную projection.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from document_contract import atomic_write_text, DocumentError, parse_document
from harness_config import (
    open_questions_index_path,
    requirements_directory,
    roadmap_path,
    status_path,
    task_directory,
)
from planning_contract import (
    dependency_ids,
    open_questions,
    read_task,
    relevant_open_questions,
    step_completion_proof,
)


class ProjectionDerivationError(RuntimeError):
    """Canonical state нельзя безопасно превратить в projection.

    Это не обычный DRIFT. Пока derivation недоказуем, writer/validator не имеют
    права генерировать частичный snapshot.
    """


def _title(document: dict[str, Any]) -> str:
    h1 = document["h1"]
    return h1.split(" — ", 1)[1].strip() if " — " in h1 else h1.lstrip("# ").strip()


def _fmt_refs(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return "—"
    return ", ".join(str(item) for item in values)


# ---------------------------------------------------------------------------
# Canonical readers.
# Любой parse/id mismatch прерывает derivation целиком: projection не должна
# скрывать повреждённый canonical document.
# ---------------------------------------------------------------------------
def canonical_requirements(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    directory = requirements_directory(root)
    for path in sorted(directory.glob("REQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            document = parse_document(path)
        except DocumentError as exc:
            raise ProjectionDerivationError(
                f"cannot parse canonical requirement {path.relative_to(root)}: {exc}"
            ) from exc
        meta = document["frontmatter"]
        req_id = meta.get("id")
        if not isinstance(req_id, str) or not path.name.startswith(req_id + "-"):
            raise ProjectionDerivationError(
                f"invalid canonical requirement identity: {path.relative_to(root)}"
            )
        result.append({"path": path, "document": document})
    return result


def canonical_steps(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        try:
            document = parse_document(path)
        except DocumentError as exc:
            raise ProjectionDerivationError(
                f"cannot parse canonical STEP {path.relative_to(root)}: {exc}"
            ) from exc
        meta = document["frontmatter"]
        if meta.get("id") != path.stem:
            raise ProjectionDerivationError(
                f"invalid canonical STEP identity: {path.relative_to(root)}"
            )
        result.append({"path": path, "document": document})
    return result


def render_requirements_spec(root: Path) -> str:
    lines = [
        "# Requirements Specification",
        "",
        "> Tracked deterministic projection/index. Canonical REQ находятся в отдельных versioned REQ-NNN-*.md; этот файл не является источником истины.",
        "",
        "| REQ | Название | Приоритет | Источник |",
        "|---|---|---|---|",
    ]
    for item in canonical_requirements(root):
        doc = item["document"]
        meta = doc["frontmatter"]
        lines.append(
            f"| [{meta['id']}]({item['path'].name}) | {_title(doc)} | {meta.get('priority', '—')} | {meta.get('source', '—')} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Derived lifecycle state REQ.
# Статус не хранится в REQ: он вычисляется из linked STEP + completion proofs.
# ---------------------------------------------------------------------------
def _requirement_status(
    root: Path,
    req: dict[str, Any],
    *,
    extra_legacy_review_pins: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    meta = req["document"]["frontmatter"]
    steps = meta.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return "planned", "—", "—"
    completed = 0
    deferred = 0
    cancelled = 0
    evidence: list[str] = []
    valid_steps: list[str] = []
    req_id = str(meta.get("id", "<unknown REQ>"))
    for step_id in steps:
        if not isinstance(step_id, str):
            raise ProjectionDerivationError(
                f"{req_id}: non-string STEP reference in canonical requirement"
            )
        try:
            task = read_task(root, step_id)
            proof = step_completion_proof(
                root,
                step_id,
                extra_legacy_review_pins=extra_legacy_review_pins,
            )
        except Exception as exc:
            raise ProjectionDerivationError(
                f"{req_id}: cannot derive state from {step_id}: {exc}"
            ) from exc
        valid_steps.append(step_id)
        status = task["frontmatter"].get("status")
        if status == "deferred":
            deferred += 1
        elif status == "cancelled":
            cancelled += 1
        if proof["complete"]:
            completed += 1
            evidence.append(proof["proof_hash"])
    total = len(valid_steps)
    if total and completed == total:
        status = "completed"
    elif completed:
        status = "partial"
    elif total and deferred == total:
        status = "deferred"
    elif total and cancelled == total:
        status = "cancelled"
    else:
        status = "planned"
    return status, _fmt_refs(valid_steps), _fmt_refs(evidence)


def render_requirements_status(
    root: Path,
    *,
    extra_legacy_review_pins: dict[str, str] | None = None,
) -> str:
    lines = [
        "# Requirements Status",
        "",
        "> Tracked deterministic projection lifecycle state. Статус выводится из canonical REQ + STEP completion proofs.",
        "",
        "| REQ | Название | Статус | Реализующие STEP | Evidence |",
        "|---|---|---|---|---|",
    ]
    for item in canonical_requirements(root):
        doc = item["document"]
        req_id = doc["frontmatter"]["id"]
        status, steps, evidence = _requirement_status(
            root,
            item,
            extra_legacy_review_pins=extra_legacy_review_pins,
        )
        lines.append(
            f"| [{req_id}]({item['path'].name}) | {_title(doc)} | {status} | {steps} | {evidence} |"
        )
    return "\n".join(lines) + "\n"


def render_roadmap(root: Path) -> str:
    lines = [
        "# Project Roadmap",
        "",
        "> Tracked deterministic projection. Полный contract каждого STEP находится в configured protocol.taskDirectory.",
        "",
        "| STEP | Название | Type | Priority | Status | Depends on | REQ |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in canonical_steps(root):
        doc = item["document"]
        meta = doc["frontmatter"]
        lines.append(
            "| {id} | {title} | {type} | {priority} | {status} | {deps} | {reqs} |".format(
                id=meta["id"],
                title=_title(doc),
                type=meta.get("type", "—"),
                priority=meta.get("priority", "—"),
                status=meta.get("status", "—"),
                deps=_fmt_refs(meta.get("depends_on")),
                reqs=_fmt_refs(meta.get("requirements")),
            )
        )
    return "\n".join(lines) + "\n"


def _is_unblocked_planned_step(root: Path, task: dict[str, Any]) -> bool:
    """Проверить, можно ли показывать planned STEP как следующий unblocked work.

    Missing/invalid dependency proof или OQ derivation error не трактуются как
    "просто заблокировано": они поднимают ProjectionDerivationError.
    """
    """Planned STEP пригоден для NEXT только без hard blockers."""
    meta = task["frontmatter"]
    if meta.get("status") != "planned":
        return False
    step_id = str(meta.get("id", "<unknown STEP>"))
    for dependency in dependency_ids(task):
        try:
            proof = step_completion_proof(root, dependency)
        except Exception as exc:
            raise ProjectionDerivationError(
                f"{step_id}: cannot derive dependency proof for {dependency}: {exc}"
            ) from exc
        if not proof["complete"]:
            return False
    try:
        questions = relevant_open_questions(root, task)
    except Exception as exc:
        raise ProjectionDerivationError(
            f"{step_id}: cannot derive relevant Open Questions: {exc}"
        ) from exc
    if any(item.get("status") == "open" for item in questions):
        return False
    return True


def render_project_status(root: Path) -> str:
    steps = canonical_steps(root)
    groups: dict[str, list[str]] = {}
    for item in steps:
        meta = item["document"]["frontmatter"]
        groups.setdefault(str(meta.get("status")), []).append(str(meta.get("id")))

    counts = Counter(str(item["document"]["frontmatter"].get("status")) for item in steps)
    lines = [
        "# Project Status",
        "",
        "> Tracked deterministic projection canonical STEP state.",
        "",
        "## Summary",
        "",
        f"- total: {len(steps)}",
    ]
    for status_name in sorted(counts):
        lines.append(f"- {status_name}: {counts[status_name]}")

    def section(title: str, statuses: tuple[str, ...]) -> None:
        lines.extend(["", f"## {title}", ""])
        values: list[str] = []
        for state in statuses:
            values.extend(groups.get(state, []))
        lines.append(", ".join(values) if values else "—")

    section("In progress", ("in_progress",))
    section("Blocked", ("blocked",))

    lines.extend(["", "## Next unblocked work", ""])
    unblocked = [
        str(item["document"]["frontmatter"].get("id"))
        for item in steps
        if _is_unblocked_planned_step(root, item["document"])
    ]
    lines.append(", ".join(unblocked) if unblocked else "—")

    section("Recent completed", ("completed",))
    return "\n".join(lines) + "\n"


def render_open_questions_index(root: Path) -> str:
    lines = [
        "# Open Questions",
        "",
        "> Tracked deterministic projection/index. Canonical OQ находятся в configured sources.openQuestions.",
        "",
        "| OQ | Статус | Вопрос | Affects |",
        "|---|---|---|---|",
    ]
    for item in open_questions(root):
        doc = item["document"]
        meta = doc["frontmatter"]
        oq_id = str(meta.get("id"))
        path = item["path"]
        try:
            rel = path.relative_to(open_questions_index_path(root).parent).as_posix()
        except ValueError:
            rel = path.relative_to(root).as_posix()
        lines.append(
            f"| [{oq_id}]({rel}) | {meta.get('status', '—')} | {_title(doc)} | {_fmt_refs(meta.get('affects'))} |"
        )
    lines.extend([
        "",
        "## Blocking semantics",
        "",
        "status: open блокирует STEP по explicit affects; PROJECT используется как project-level blocker для INIT.",
    ])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Единственная карта output path -> expected content.
# И --check, и mutation mode используют именно её, чтобы не иметь двух renderer
# implementations с разной semantics.
# ---------------------------------------------------------------------------
def projection_targets(
    root: Path,
    *,
    extra_legacy_review_pins: dict[str, str] | None = None,
) -> dict[Path, str]:
    requirements = requirements_directory(root)
    return {
        requirements / "SPEC.md": render_requirements_spec(root),
        requirements / "STATUS.md": render_requirements_status(
            root,
            extra_legacy_review_pins=extra_legacy_review_pins,
        ),
        roadmap_path(root): render_roadmap(root),
        status_path(root): render_project_status(root),
        open_questions_index_path(root): render_open_questions_index(root),
    }


def validate_projections(root: Path) -> list[str]:
    """Сравнить все tracked projections с deterministic expected content.

    Возвращает обычный DRIFT как errors list; derivation failure сворачивается
    в отдельную диагностическую ошибку, чтобы caller не принял partial state.
    """
    errors: list[str] = []
    try:
        targets = projection_targets(root)
    except Exception as exc:
        return [f"projection derivation failed: {exc}"]
    for path, expected in targets.items():
        if not path.is_file():
            errors.append(f"projection missing: {path.relative_to(root)}")
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"projection is not UTF-8: {path.relative_to(root)}")
            continue
        if actual != expected:
            errors.append(f"projection drift: {path.relative_to(root)}")
    return errors


def write_projections(
    root: Path,
    *,
    extra_legacy_review_pins: dict[str, str] | None = None,
) -> list[str]:
    changed: list[str] = []
    for path, expected in projection_targets(
        root,
        extra_legacy_review_pins=extra_legacy_review_pins,
    ).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual != expected:
            atomic_write_text(path, expected)
            changed.append(path.relative_to(root).as_posix())
    return changed
