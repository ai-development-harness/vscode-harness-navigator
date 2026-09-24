#!/usr/bin/env python3
"""Идемпотентная migration active project documents в frontmatter schema=1.

Исторические immutable review/audit/update reports не переписываются. Миграция
касается active STEP/REQ/ADR/OQ и project-owned templates/projections.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from document_contract import (
    ADR_ID_RE,
    DocumentError,
    OQ_ID_RE,
    REQ_ID_RE,
    STEP_ID_RE,
    atomic_write_text,
    content_hash,
    create_durable_report,
    parse_document,
    render_document,
    split_frontmatter,
)
from harness_config import (
    adr_directory,
    audit_directory,
    open_questions_directory,
    open_questions_index_path,
    requirements_directory,
    task_directory,
)
from projection_contract import write_projections
from review_contract import current_legacy_review_snapshots, legacy_review_pins
from template_contract import (
    migrate_project_templates,
    project_template_migration_blockers,
    project_template_migration_pending,
)


STATUS_MAP = {
    "Запланировано": "planned",
    "В работе": "in_progress",
    "Заблокировано": "blocked",
    "Выполнено": "completed",
    "Отложено": "deferred",
    "Отменено": "cancelled",
    "Заменено": "cancelled",
}
PRIORITY_MAP = {
    "Критический": "critical",
    "Высокий": "high",
    "Средний": "medium",
    "Низкий": "low",
}
ADR_STATUS_MAP = {
    "Proposed": "proposed",
    "Accepted": "accepted",
    "Superseded": "superseded",
    "Rejected": "rejected",
}
RISK_FLAGS = {
    "none", "security-sensitive", "data-migration", "destructive", "public-api",
    "architecture", "concurrency", "external-integration",
    "performance-critical", "release-critical",
}


def _legacy_metadata(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\*\*([^*]+?):\*\*\s*(.*)$", text):
        result[match.group(1).strip()] = match.group(2).strip()
    return result


def _sections(text: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.replace("\r\n", "\n").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            result.setdefault(current, [])
            continue
        if current is not None:
            result[current].append(line)
    return {key: "\n".join(value).strip() for key, value in result.items()}


def _ids(value: str, pattern: re.Pattern[str]) -> list[str]:
    return sorted(set(pattern.findall(value)))


def _h1(text: str, pattern: re.Pattern[str]) -> tuple[str, str]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    match = re.fullmatch(rf"# ({pattern.pattern}) — (.+)", first)
    if not match:
        raise ValueError(f"cannot parse legacy H1: {first}")
    return match.group(1), match.group(2)


def _body_from_sections(title: str, sections: dict[str, str], names: list[str]) -> str:
    chunks = [title, ""]
    for name in names:
        if name not in sections:
            continue
        chunks.extend([f"## {name}", "", sections[name], ""])
    return "\n".join(chunks).strip()


def _clean_plan_section(value: str) -> str:
    lines = []
    for line in value.splitlines():
        if re.match(r"^\*\*(Plan status|Plan revision|Plan basis|Planned at):\*\*", line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or "Требуется повторный STEP PLAN после schema migration."


def migrate_legacy_step(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    step_id, title = _h1(text, STEP_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    old_plan = _legacy_metadata(sections.get("Implementation plan", ""))
    old_ready = old_plan.get("Plan status") == "Ready"
    risks = [
        flag for flag in RISK_FLAGS
        if re.search(rf"(?<![A-Za-z0-9-]){re.escape(flag)}(?![A-Za-z0-9-])", sections.get("Risk flags", ""))
    ] or ["none"]

    frontmatter: dict[str, Any] = {
        "schema": 1,
        "id": step_id,
        "status": STATUS_MAP.get(meta.get("Статус", ""), "planned"),
        "type": meta.get("Type", "IMPLEMENTATION").lower(),
        "priority": PRIORITY_MAP.get(meta.get("Приоритет", ""), "medium"),
        "phase": meta.get("Фаза") or "TBD",
        "depends_on": _ids(meta.get("Depends on", ""), STEP_ID_RE),
        "requirements": _ids(sections.get("Requirements", ""), REQ_ID_RE),
        "adrs": _ids(sections.get("ADR", ""), ADR_ID_RE),
        "architecture_refs": [],
        "risk_flags": risks,
        "plan": {
            # Старый Ready не имеет durable planning-review/content hash и не
            # переносится как доказанный Ready.
            "status": "draft" if old_ready else "not_planned",
            "revision": int(old_plan.get("Plan revision", "0")) if old_plan.get("Plan revision", "").isdigit() else 0,
            "context_basis": None,
            "content_hash": None,
            "reviewed_report": None,
            "planned_at": None,
        },
    }

    kept = [
        "Goal", "Context", "Scope", "Mutation policy", "Out of scope",
        "Acceptance criteria", "Verification", "Deliverables",
        "Implementation plan", "Evidence", "Blocker / Failure reason",
    ]
    if "Implementation plan" in sections:
        sections["Implementation plan"] = _clean_plan_section(sections["Implementation plan"])
    body = _body_from_sections(f"# {step_id} — {title}", sections, kept)
    atomic_write_text(path, render_document(frontmatter, body))
    return True


def migrate_legacy_requirement(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    req_id, title = _h1(text, REQ_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    trace = sections.get("Traceability", "")
    frontmatter = {
        "schema": 1,
        "id": req_id,
        "priority": PRIORITY_MAP.get(meta.get("Приоритет", ""), "medium"),
        "source": (meta.get("Источник") or "other").lower().replace(" ", "_"),
        "steps": _ids(trace, STEP_ID_RE),
        "adrs": _ids(trace, ADR_ID_RE),
    }
    body = _body_from_sections(
        f"# {req_id} — {title}",
        sections,
        ["Requirement", "Rationale", "Acceptance"],
    )
    atomic_write_text(path, render_document(frontmatter, body))
    return True


def migrate_monolithic_requirements(root: Path) -> list[str]:
    directory = requirements_directory(root)
    spec = directory / "SPEC.md"
    if not spec.is_file():
        return []
    text = spec.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^#{2,}\s+(REQ-\d{3,})\s+—\s+(.+)$", text))
    existing_ids: set[str] = set()
    for existing in directory.glob("REQ-*.md"):
        if existing.name == "TEMPLATE.md":
            continue
        match = re.match(r"(REQ-\d{3,})-", existing.name)
        if match:
            existing_ids.add(match.group(1))

    changed: list[str] = []
    for index, match in enumerate(matches):
        req_id, title = match.group(1), match.group(2).strip()
        if req_id in existing_ids:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[match.start():end]
        sub: dict[str, str] = {}
        for name in ("Requirement", "Rationale", "Acceptance", "Traceability"):
            heading = re.search(rf"(?m)^#{{2,6}}\s+{re.escape(name)}\s*$", chunk)
            if not heading:
                continue
            next_heading = re.search(r"(?m)^#{2,6}\s+", chunk[heading.end():])
            finish = heading.end() + next_heading.start() if next_heading else len(chunk)
            sub[name] = chunk[heading.end():finish].strip()
        frontmatter = {
            "schema": 1,
            "id": req_id,
            "priority": "medium",
            "source": "legacy",
            "steps": _ids(sub.get("Traceability", ""), STEP_ID_RE),
            "adrs": _ids(sub.get("Traceability", ""), ADR_ID_RE),
        }
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "requirement"
        path = directory / f"{req_id}-{slug}.md"
        body = _body_from_sections(
            f"# {req_id} — {title}",
            sub,
            ["Requirement", "Rationale", "Acceptance"],
        )
        atomic_write_text(path, render_document(frontmatter, body))
        changed.append(path.relative_to(root).as_posix())
    return changed


def migrate_legacy_adr(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    adr_id, title = _h1(text, ADR_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    trace = sections.get("Traceability", "")
    frontmatter = {
        "schema": 1,
        "id": adr_id,
        "status": ADR_STATUS_MAP.get(meta.get("Status", ""), "proposed"),
        "date": meta.get("Date") or None,
        "deciders": [item.strip() for item in meta.get("Deciders", "").split(",") if item.strip() and item.strip() != "TBD"],
        "supersedes": _ids(meta.get("Supersedes", ""), ADR_ID_RE),
        "superseded_by": _ids(meta.get("Superseded by", ""), ADR_ID_RE),
        "requirements": _ids(trace, REQ_ID_RE),
        "steps": _ids(trace, STEP_ID_RE),
    }
    body = _body_from_sections(
        f"# {adr_id} — {title}",
        sections,
        [
            "Context", "Problem", "Decision", "Alternatives considered",
            "Consequences", "Security implications", "Data / migration implications",
            "Compatibility / operational implications",
        ],
    )
    atomic_write_text(path, render_document(frontmatter, body))
    return True


def _legacy_oq_field(chunk: str, label: str) -> str:
    """Прочитать legacy OQ field целиком до следующего известного field header."""
    header = re.search(
        rf"(?mi)^(?:\*\*)?{re.escape(label)}:(?:\*\*)?[ \t]*(.*)$",
        chunk,
    )
    if not header:
        return ""
    first = header.group(1).strip()
    tail = chunk[header.end():]
    next_header = re.search(
        r"(?mi)^(?:\*\*)?(?:Status|Affects|Context|Decision needed|Resolution):(?:\*\*)?",
        tail,
    )
    extra = tail[: next_header.start() if next_header else len(tail)].strip()
    return "\n".join(part for part in (first, extra) if part).strip()


def migrate_monolithic_open_questions(root: Path) -> list[str]:
    index = open_questions_index_path(root)
    if not index.is_file():
        return []
    text = index.read_text(encoding="utf-8")
    if "| OQ |" in text:
        return []
    directory = open_questions_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    starts = list(re.finditer(r"(?m)^(?:#{1,6}\s+)?(OQ-\d{3,})\s+—\s+(.+)$", text))
    existing_ids = {
        match.group(1)
        for path in directory.glob("OQ-*.md")
        if (match := re.match(r"(OQ-\d{3,})-", path.name))
    }
    changed: list[str] = []
    for pos, match in enumerate(starts):
        oq_id, title = match.group(1), match.group(2).strip()
        if oq_id in existing_ids:
            continue
        end = starts[pos + 1].start() if pos + 1 < len(starts) else len(text)
        chunk = text[match.end():end]
        status_value = _legacy_oq_field(chunk, "Status").splitlines()[0] if _legacy_oq_field(chunk, "Status") else ""
        affects_value = _legacy_oq_field(chunk, "Affects")
        context = _legacy_oq_field(chunk, "Context")
        decision = _legacy_oq_field(chunk, "Decision needed")
        resolution = _legacy_oq_field(chunk, "Resolution")
        affects: list[str] = []
        if affects_value:
            affects.extend(_ids(affects_value, STEP_ID_RE))
            affects.extend(_ids(affects_value, REQ_ID_RE))
            affects.extend(_ids(affects_value, ADR_ID_RE))
            if "PROJECT" in affects_value:
                affects.append("PROJECT")
        frontmatter = {
            "schema": 1,
            "id": oq_id,
            "status": (status_value.lower() if status_value.upper() in {"OPEN", "RESOLVED", "DEFERRED"} else "open"),
            "affects": sorted(set(affects)) or ["PROJECT"],
            "created_at": None,
            "resolved_at": None,
        }
        body = (
            f"# {oq_id} — {title}\n\n"
            f"## Context\n\n{context or 'Legacy context not structured.'}\n\n"
            f"## Decision needed\n\n{decision or 'Требуется решение.'}\n\n"
            f"## Resolution\n\n{resolution}"
        )
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "question"
        path = directory / f"{oq_id}-{slug}.md"
        atomic_write_text(path, render_document(frontmatter, body))
        changed.append(path.as_posix())
    return changed


def _pending_legacy_review_pins(root: Path) -> dict[str, str]:
    """Новые legacy reviews для pinning; corruption уже pinned history блокирует migration."""
    try:
        recorded = legacy_review_pins(root)
    except ValueError as exc:
        raise ValueError(f"invalid recorded legacy review pins: {exc}") from exc
    current = current_legacy_review_snapshots(root)

    for rel, expected in recorded.items():
        path = root / rel
        if not path.is_file():
            raise ValueError(f"pinned legacy review is missing: {rel}")
        try:
            actual = content_hash(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read pinned legacy review {rel}: {exc}") from exc
        if actual != expected:
            raise ValueError(f"pinned legacy review changed after migration: {rel}")

    return {
        rel: digest
        for rel, digest in current.items()
        if rel not in recorded
    }


def _document_family_state(paths: list[Path]) -> str:
    """Вернуть current|legacy|mixed_or_invalid для набора active documents."""
    states: set[str] = set()
    for path in paths:
        try:
            frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, DocumentError):
            return "mixed_or_invalid"
        states.add("legacy" if frontmatter is None else "current")
    if len(states) > 1:
        return "mixed_or_invalid"
    return next(iter(states), "current")


def legacy_manual_bypass_allowed(root: Path) -> bool:
    """Разрешить post-update manual bypass только для цельного migratable state.

    Non-additive template conflicts никогда не попадают под migration warning:
    validator обязан оставить их hard blocker-ом до явного решения.
    """
    try:
        if project_template_migration_blockers(root):
            return False
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if not legacy_schema_pending(root):
        return False

    step_paths = sorted(task_directory(root).glob("STEP-*.md"))
    req_paths = sorted(
        path for path in requirements_directory(root).glob("REQ-*.md")
        if path.name != "TEMPLATE.md"
    )
    adr_paths = sorted(
        path for path in adr_directory(root).glob("ADR-*.md")
        if path.name != "TEMPLATE.md"
    )
    family_states = [
        _document_family_state(step_paths),
        _document_family_state(req_paths),
        _document_family_state(adr_paths),
    ]
    if "mixed_or_invalid" in family_states:
        return False

    # Legacy monolithic requirements безопасны для deferred migration только
    # пока ни один REQ из того же SPEC не материализован отдельно.
    spec = requirements_directory(root) / "SPEC.md"
    if spec.is_file():
        try:
            spec_ids = set(
                re.findall(
                    r"(?m)^#{2,}\s+(REQ-\d{3,})\b",
                    spec.read_text(encoding="utf-8"),
                )
            )
        except (OSError, UnicodeDecodeError):
            return False
        existing_ids = {
            match.group(1)
            for path in req_paths
            if (match := re.match(r"(REQ-\d{3,})-", path.name))
        }
        if spec_ids and existing_ids:
            return False

    # То же правило для старого монолитного OQ index: наличие уже созданных
    # OQ-NNN файлов означает partial migration, а не exact legacy layout.
    index = open_questions_index_path(root)
    if index.is_file():
        try:
            has_legacy_oq = re.search(
                r"(?m)^(?:#{1,6}\s+)?OQ-\d{3,}\s+—",
                index.read_text(encoding="utf-8"),
            ) is not None
        except (OSError, UnicodeDecodeError):
            return False
        if has_legacy_oq and any(open_questions_directory(root).glob("OQ-*.md")):
            return False

    # Если одна family уже current, а другая всё ещё legacy, repository также
    # частично мигрирован. Exact deferred state должен быть целостным.
    active_states = {state for state in family_states if state in {"current", "legacy"}}
    if "legacy" in active_states and "current" in active_states:
        return False
    return True


def legacy_schema_pending(root: Path) -> bool:
    paths: list[Path] = []
    paths.extend(task_directory(root).glob("STEP-*.md"))
    paths.extend(
        path for path in requirements_directory(root).glob("REQ-*.md")
        if path.name != "TEMPLATE.md"
    )
    paths.extend(
        path for path in adr_directory(root).glob("ADR-*.md")
        if path.name != "TEMPLATE.md"
    )
    for path in paths:
        try:
            if split_frontmatter(path.read_text(encoding="utf-8"))[0] is None:
                return True
        except (OSError, UnicodeDecodeError, DocumentError):
            return True
    spec = requirements_directory(root) / "SPEC.md"
    if spec.is_file():
        spec_ids = set(
            re.findall(r"(?m)^#{2,}\s+(REQ-\d{3,})\b", spec.read_text(encoding="utf-8"))
        )
        existing_ids = {
            match.group(1)
            for path in requirements_directory(root).glob("REQ-*.md")
            if path.name != "TEMPLATE.md"
            if (match := re.match(r"(REQ-\d{3,})-", path.name))
        }
        if spec_ids - existing_ids:
            return True
    index = open_questions_index_path(root)
    if index.is_file():
        data = index.read_text(encoding="utf-8")
        if re.search(r"(?m)^(?:#{1,6}\s+)?OQ-\d{3,}\s+—", data):
            return True
    try:
        if _pending_legacy_review_pins(root):
            return True
    except ValueError:
        return True
    try:
        if project_template_migration_pending(root):
            return True
    except (OSError, UnicodeDecodeError, ValueError):
        return True
    return False


def _filename_artifact_id(
    path: Path,
    pattern: re.Pattern[str],
) -> str | None:
    match = re.match(rf"^({pattern.pattern})(?:-|\.md$)", path.name)
    return match.group(1) if match else None


def _preflight_document_family(
    paths: list[Path],
    *,
    pattern: re.Pattern[str],
    label: str,
) -> list[str]:
    """Проверить migration identity/parse blockers без repository mutation."""
    blockers: list[str] = []
    seen_ids: dict[str, str] = {}
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _body = split_frontmatter(text)
        except (OSError, UnicodeDecodeError, DocumentError, ValueError) as exc:
            blockers.append(f"{path}: cannot parse {label}: {exc}")
            continue

        filename_id = _filename_artifact_id(path, pattern)
        if filename_id is None:
            blockers.append(f"{path}: filename does not contain canonical {label} id")
            continue

        if frontmatter is None:
            try:
                document_id, _title = _h1(text, pattern)
            except ValueError as exc:
                blockers.append(f"{path}: {exc}")
                continue
        else:
            # Current document migration не переписывает. Поэтому unsupported
            # current schema/identity — blocker, а не повод мутировать соседние
            # legacy artifacts до будущего validation failure.
            try:
                parsed = parse_document(path)
            except (OSError, UnicodeDecodeError, DocumentError, ValueError) as exc:
                blockers.append(f"{path}: cannot parse current {label}: {exc}")
                continue
            meta = parsed.get("frontmatter")
            document_id = meta.get("id") if isinstance(meta, dict) else None
            if not isinstance(meta, dict) or meta.get("schema") != 1:
                blockers.append(f"{path}: current {label} schema must be 1")
                continue
            if not isinstance(document_id, str):
                blockers.append(f"{path}: current {label} id must be a string")
                continue

        if document_id != filename_id:
            blockers.append(
                f"{path}: {label} id {document_id!r} does not match filename id {filename_id}"
            )
            continue
        previous = seen_ids.get(document_id)
        if previous is not None:
            blockers.append(
                f"{path}: duplicate {label} id {document_id} also used by {previous}"
            )
        else:
            seen_ids[document_id] = str(path)
    return blockers


def _preflight_monolithic_ids(
    path: Path,
    *,
    heading_pattern: re.Pattern[str],
    label: str,
) -> list[str]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: cannot read monolithic {label}: {exc}"]

    ids = heading_pattern.findall(text)
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in ids:
        document_id = item[0] if isinstance(item, tuple) else item
        if document_id in seen:
            duplicates.add(document_id)
        seen.add(document_id)
    return [
        f"{path}: duplicate monolithic {label} id {document_id}"
        for document_id in sorted(duplicates)
    ]


def migration_preflight(root: Path) -> dict[str, Any]:
    """Fail before first migration write when deterministic blocker is knowable."""
    blockers: list[str] = []

    # Immutable-history corruption и template hard conflicts уже имеют
    # read-only detectors. Вызываем их до любых active document migrations.
    try:
        pending_legacy_reviews = _pending_legacy_review_pins(root)
    except ValueError as exc:
        blockers.append(str(exc))
        pending_legacy_reviews = {}

    try:
        blockers.extend(project_template_migration_blockers(root))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        blockers.append(f"project template preflight failed: {exc}")

    step_paths = sorted(task_directory(root).glob("STEP-*.md"))
    req_paths = sorted(
        path
        for path in requirements_directory(root).glob("REQ-*.md")
        if path.name != "TEMPLATE.md"
    )
    adr_paths = sorted(
        path
        for path in adr_directory(root).glob("ADR-*.md")
        if path.name != "TEMPLATE.md"
    )
    blockers.extend(
        _preflight_document_family(
            step_paths,
            pattern=STEP_ID_RE,
            label="STEP",
        )
    )
    blockers.extend(
        _preflight_document_family(
            req_paths,
            pattern=REQ_ID_RE,
            label="REQ",
        )
    )
    blockers.extend(
        _preflight_document_family(
            adr_paths,
            pattern=ADR_ID_RE,
            label="ADR",
        )
    )

    blockers.extend(
        _preflight_monolithic_ids(
            requirements_directory(root) / "SPEC.md",
            heading_pattern=re.compile(r"(?m)^#{2,}\s+(REQ-\d{3,})\s+—\s+.+$"),
            label="REQ",
        )
    )
    blockers.extend(
        _preflight_monolithic_ids(
            open_questions_index_path(root),
            heading_pattern=re.compile(
                r"(?m)^(?:#{1,6}\s+)?(OQ-\d{3,})\s+—\s+.+$"
            ),
            label="OQ",
        )
    )

    if blockers:
        raise ValueError(
            "project migration preflight blocked: " + "; ".join(blockers)
        )
    return {"pendingLegacyReviews": pending_legacy_reviews}


def migrate_project(root: Path) -> dict[str, Any]:
    preflight = migration_preflight(root)
    pending_legacy_reviews = preflight["pendingLegacyReviews"]
    changed: list[str] = []
    changed.extend(migrate_monolithic_requirements(root))
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if migrate_legacy_step(path):
            changed.append(path.relative_to(root).as_posix())
    for path in sorted(requirements_directory(root).glob("REQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        if migrate_legacy_requirement(path):
            changed.append(path.relative_to(root).as_posix())
    for path in sorted(adr_directory(root).glob("ADR-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        if migrate_legacy_adr(path):
            changed.append(path.relative_to(root).as_posix())
    changed.extend(
        str(Path(item).relative_to(root)) if Path(item).is_absolute() else item
        for item in migrate_monolithic_open_questions(root)
    )

    # Project-owned templates не обновляются HARNESS UPDATE. RECONCILE
    # применяет только additive structural migration: missing keys/sections
    # добавляются из current protocol defaults, project values/prose сохраняются.
    # Non-additive conflicts остаются blocker и не перезаписываются.
    changed.extend(migrate_project_templates(root))
    # Pending legacy review pins участвуют в final projection calculation
    # в этом же migration run. После этого тот же exact pin set публикуется
    # в immutable migration report, поэтому второй RECONCILE — настоящий no-op.
    changed.extend(
        write_projections(
            root,
            extra_legacy_review_pins=pending_legacy_reviews,
        )
    )

    unique_changed = sorted(set(changed))
    if not unique_changed and not pending_legacy_reviews:
        return {
            "status": "NO_CHANGES",
            "changed": [],
            "report": None,
        }

    report_dir = audit_directory(root)

    def report_content(created_at: str) -> str:
        body = "# Project Schema Migration\n\n## Changed artifacts\n\n"
        body += "\n".join(f"- {item}" for item in unique_changed) if unique_changed else "- none"
        body += (
            "\n\n## Legacy immutable reviews\n\n"
            + (
                "\n".join(f"- pinned {rel}" for rel in sorted(pending_legacy_reviews))
                if pending_legacy_reviews
                else "- no new legacy review pins"
            )
        )
        body += "\n\n## Notes\n\nHistorical immutable reports were not rewritten."
        report_meta = {
            "schema": 1,
            "kind": "migration",
            "created_at": created_at,
            "result": "complete",
            "changed_count": len(unique_changed),
            "legacy_review_reports": [
                f"{digest} {rel}"
                for rel, digest in sorted(pending_legacy_reviews.items())
            ],
        }
        return render_document(report_meta, body)

    report, _created_at = create_durable_report(
        "MIGRATION-",
        directory=report_dir,
        content_factory=report_content,
    )
    return {
        "status": "MIGRATED",
        "changed": unique_changed,
        "report": report.relative_to(root).as_posix(),
    }
