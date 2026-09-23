#!/usr/bin/env python3
"""Детерминированные planning contracts, fingerprints и lifecycle gates.

Модуль проверяет всё, что можно доказать без LLM: schema, refs, dependency graph,
completion proofs, OQ blockers, architecture refs, planning fingerprints и
durable semantic review links.

Semantic непротиворечивость плана остаётся за независимым planning-review, но
static gate не позволяет вызвать этот review на заведомо повреждённом contract.

Ключевые safety invariants:
- completion не выводится только из mutable status;
- Ready требует fresh context_basis + content_hash + matching PASS review;
- dependency contract и open OQ входят в PLAN; completion proof проверяется непосредственно перед IMPLEMENT;
- stale/invalid refs не заменяются предположениями;
- legacy active docs допускаются только явным migration compatibility flow.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

from harness_config import (
    ConfigError,
    adr_directory,
    architecture_path,
    init_review_directory,
    max_fix_review_cycles,
    open_questions_directory,
    planning_review_directory,
    project_overview_path,
    requirements_directory,
    review_directory,
    task_directory,
)
from document_contract import (
    ADR_ID_RE,
    ADR_STATUSES,
    DocumentError,
    OQ_ID_RE,
    OQ_STATUSES,
    PLAN_STATUSES,
    PRIORITIES,
    REQ_ID_RE,
    STEP_ID_RE,
    STEP_STATUSES,
    STEP_TYPES,
    content_hash,
    exact_h1,
    has_unresolved_placeholder,
    markdown_headings,
    normalize_text,
    parse_document,
    require_nonempty_sections,
    require_schema,
    stable_hash,
    string_list,
    validate_report_timestamp_identity,
)


RISK_FLAGS = {
    "none",
    "security-sensitive",
    "data-migration",
    "destructive",
    "public-api",
    "architecture",
    "concurrency",
    "external-integration",
    "performance-critical",
    "release-critical",
}
CONTRACT_SECTIONS = (
    "Goal",
    "Context",
    "Scope",
    "Mutation policy",
    "Out of scope",
    "Acceptance criteria",
    "Verification",
    "Deliverables",
)
REQUIRED_TASK_SECTIONS = CONTRACT_SECTIONS + (
    "Implementation plan",
    "Evidence",
    "Blocker / Failure reason",
)

REQ_SECTIONS = ("Requirement", "Rationale", "Acceptance")
ADR_SECTIONS = (
    "Context",
    "Problem",
    "Decision",
    "Alternatives considered",
    "Consequences",
    "Security implications",
    "Data / migration implications",
    "Compatibility / operational implications",
)


def task_path(root: Path, step_id: str) -> Path:
    if STEP_ID_RE.fullmatch(step_id) is None:
        raise ValueError(f"invalid STEP id: {step_id}")
    path = task_directory(root) / f"{step_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"task file not found: {path.relative_to(root)}")
    return path


def read_task(root: Path, step_id: str) -> dict[str, Any]:
    document = parse_document(task_path(root, step_id))
    # compatibility alias нужен execution_status до полного удаления старого parser API.
    document["metadata"] = document["frontmatter"]
    return document


def _list(meta: dict[str, Any], key: str) -> list[str]:
    value = meta.get(key)
    return value if isinstance(value, list) and all(isinstance(x, str) for x in value) else []


def dependency_ids(task: dict[str, Any]) -> list[str]:
    return _list(task["frontmatter"], "depends_on")


def requirement_ids(task: dict[str, Any]) -> list[str]:
    return _list(task["frontmatter"], "requirements")


def adr_ids(task: dict[str, Any]) -> list[str]:
    return _list(task["frontmatter"], "adrs")


def architecture_refs(task: dict[str, Any]) -> list[str]:
    return _list(task["frontmatter"], "architecture_refs")


def canonical_requirement_path(root: Path, req_id: str) -> Path:
    if REQ_ID_RE.fullmatch(req_id) is None:
        raise ValueError(f"invalid REQ id: {req_id}")
    matches = sorted(requirements_directory(root).glob(f"{req_id}-*.md"))
    matches = [path for path in matches if path.name != "TEMPLATE.md"]
    if len(matches) != 1:
        raise ValueError(f"{req_id}: expected exactly one canonical REQ file, found {len(matches)}")
    return matches[0]


def canonical_adr_path(root: Path, adr_id: str) -> Path:
    if ADR_ID_RE.fullmatch(adr_id) is None:
        raise ValueError(f"invalid ADR id: {adr_id}")
    matches = sorted(adr_directory(root).glob(f"{adr_id}-*.md"))
    matches += [
        path for path in sorted(adr_directory(root).glob(f"{adr_id}.md"))
        if path not in matches
    ]
    matches = [path for path in matches if path.name != "TEMPLATE.md"]
    if len(matches) != 1:
        raise ValueError(f"{adr_id}: expected exactly one canonical ADR file, found {len(matches)}")
    return matches[0]


def canonical_oq_path(root: Path, oq_id: str) -> Path:
    if OQ_ID_RE.fullmatch(oq_id) is None:
        raise ValueError(f"invalid OQ id: {oq_id}")
    matches = sorted(open_questions_directory(root).glob(f"{oq_id}-*.md"))
    matches = [path for path in matches if path.name != "TEMPLATE.md"]
    if len(matches) != 1:
        raise ValueError(f"{oq_id}: expected exactly one canonical OQ file, found {len(matches)}")
    return matches[0]


def _semantic_sections(document: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    """Вернуть только sections, изменение которых меняет implementation intent."""
    return {name: document["sections"].get(name, "") for name in names}


def requirement_contract_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    """Semantic REQ snapshot без lifecycle/traceability metadata.

    priority/source и обратные steps/adrs полезны для управления/навигации, но
    сами по себе не меняют implementation contract уже связанного STEP.
    """
    meta = document["frontmatter"]
    return {
        "frontmatter": {
            "schema": meta.get("schema"),
            "id": meta.get("id"),
        },
        "sections": _semantic_sections(document, REQ_SECTIONS),
    }


def adr_contract_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    """Semantic ADR snapshot без provenance/reverse traceability metadata."""
    meta = document["frontmatter"]
    return {
        "frontmatter": {
            key: meta.get(key)
            for key in ("schema", "id", "status", "supersedes", "superseded_by")
        },
        "sections": _semantic_sections(document, ADR_SECTIONS),
    }


def task_contract_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    """Semantic STEP contract без scheduling/lifecycle metadata."""
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    machine = {
        key: meta.get(key)
        for key in (
            "schema", "id", "type", "depends_on",
            "requirements", "adrs", "architecture_refs", "risk_flags",
        )
    }
    return {
        "frontmatter": machine,
        "sections": _semantic_sections(task, CONTRACT_SECTIONS),
    }

def _heading_slug(title: str) -> str:
    value = title.strip().lower()
    value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
    return re.sub(r"[\s-]+", "-", value).strip("-")


def _architecture_ref_snapshot(root: Path, ref: str) -> dict[str, str]:
    path_part, marker, fragment = ref.partition("#")
    if not path_part:
        raise ValueError(f"architecture ref has empty path: {ref}")
    candidate = (root / path_part).resolve()
    base = root.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"architecture ref escapes repository: {ref}") from exc
    if not candidate.is_file():
        raise ValueError(f"architecture ref file not found: {ref}")
    text = candidate.read_text(encoding="utf-8")
    if not marker:
        selected = normalize_text(text)
    else:
        if not fragment:
            raise ValueError(f"architecture ref has empty anchor: {ref}")
        lines = text.replace("\r\n", "\n").split("\n")
        headings = markdown_headings(text)
        start: int | None = None
        level = 0
        for index, heading_level, title in headings:
            if _heading_slug(title) == fragment:
                start = index
                level = heading_level
                break
        if start is None:
            raise ValueError(f"architecture anchor not found: {ref}")
        end = len(lines)
        for index, heading_level, _title in headings:
            if index > start and heading_level <= level:
                end = index
                break
        selected = normalize_text("\n".join(lines[start:end]))
    return {"ref": ref, "content": selected}


def _parse_canonical_document(path: Path, expected_id: str) -> dict[str, Any]:
    document = parse_document(path)
    meta = document["frontmatter"]
    if meta.get("schema") != 1 or meta.get("id") != expected_id:
        raise ValueError(f"{expected_id}: invalid schema/id in {path}")
    return document


def open_questions(root: Path) -> list[dict[str, Any]]:
    directory = open_questions_directory(root)
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("OQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        document = parse_document(path)
        meta = document["frontmatter"]
        result.append({
            "path": path,
            "id": meta.get("id"),
            "status": meta.get("status"),
            "affects": meta.get("affects", []),
            "document": document,
        })
    return result


def relevant_open_questions(root: Path, task: dict[str, Any]) -> list[dict[str, Any]]:
    relevant = {
        task["frontmatter"].get("id"),
        *requirement_ids(task),
        *adr_ids(task),
    }
    return [
        item for item in open_questions(root)
        if isinstance(item.get("affects"), list)
        and relevant.intersection(set(item["affects"]))
    ]


def _evidence_present(task: dict[str, Any]) -> bool:
    value = task["sections"].get("Evidence", "").strip()
    return bool(value and value not in {"—", "-"} and not has_unresolved_placeholder(value))


# ---------------------------------------------------------------------------
# Completion proof.
# Статус STEP сам по себе недостаточен. Proof зависит от type и может включать
# Evidence, immutable PASS review или accepted ADR. Proof используется lifecycle/
# projection/IMPLEMENT gates, но schema-v4 planning basis его не fingerprint-ит.
# ---------------------------------------------------------------------------
def step_completion_proof(
    root: Path,
    step_id: str,
    *,
    extra_legacy_review_pins: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Вернуть type-specific proof prerequisite completion.

    Это structural proof. review_contract.py дополнительно доказывает корректность
    самого immutable report и reviewed revision.
    """
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    step_type = meta.get("type")
    complete = meta.get("status") == "completed"
    reasons: list[str] = []
    if not complete:
        reasons.append("status is not completed")

    evidence = _evidence_present(task)
    if step_type in {"research"}:
        if not evidence:
            reasons.append("research step has no durable Evidence")
        if not task["sections"].get("Deliverables", "").strip():
            reasons.append("research step has no Deliverables")
    elif step_type == "adr":
        if not evidence:
            reasons.append("ADR step has no durable Evidence")
        for adr_id in adr_ids(task):
            try:
                adr = _parse_canonical_document(canonical_adr_path(root, adr_id), adr_id)
            except (DocumentError, ValueError, OSError) as exc:
                reasons.append(str(exc))
                continue
            if adr["frontmatter"].get("status") != "accepted":
                reasons.append(f"{adr_id} is not accepted")
    elif step_type in {"audit", "review"}:
        if not evidence:
            reasons.append(f"{step_type} step has no durable Evidence")
    else:
        # Completion dependency proof выводится из durable review history, а не
        # только из mutable STEP metadata. Это позволяет schema migration
        # сохранить доказательство старого completed STEP через hash-pinned
        # immutable legacy report, не переписывая историю задним числом.
        from review_contract import latest_trusted_review

        trusted = latest_trusted_review(
            root,
            step_id,
            extra_legacy_pins=extra_legacy_review_pins,
        )
        review_snapshot: dict[str, Any] | None = None
        if trusted is None:
            reasons.append("trusted PASS review is missing")
        elif trusted.get("verdict") != "PASS":
            reasons.append("latest trusted review verdict is not PASS")
        else:
            review_path = trusted["path"].relative_to(root).as_posix()
            review_snapshot = {
                "path": review_path,
                "verdict": trusted["verdict"],
                "legacy": bool(trusted.get("legacy")),
                "content_hash": trusted.get("content_hash")
                or content_hash(trusted["path"].read_text(encoding="utf-8")),
            }
        if not evidence:
            reasons.append("step has no durable Evidence")

    snapshot = {
        "step_id": step_id,
        "type": step_type,
        "status": meta.get("status"),
        "review": review_snapshot if step_type not in {"research", "adr", "audit", "review"} else None,
        "evidence_hash": content_hash(task["sections"].get("Evidence", "")),
        "reasons": reasons,
    }
    return {
        "complete": not reasons,
        "reasons": reasons,
        "snapshot": snapshot,
        "proof_hash": stable_hash(snapshot),
    }


def planning_context_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    """Собрать semantic planning context schema v4.

    Snapshot намеренно отделён от lifecycle/traceability state: reverse links,
    priority/phase и факт completion dependency не должны требовать повторного
    semantic review уже корректного Implementation plan.
    """
    task = read_task(root, step_id)

    requirements: dict[str, Any] = {}
    for req_id in requirement_ids(task):
        path = canonical_requirement_path(root, req_id)
        document = _parse_canonical_document(path, req_id)
        requirements[req_id] = requirement_contract_snapshot(document)

    adrs: dict[str, Any] = {}
    for adr_id in adr_ids(task):
        path = canonical_adr_path(root, adr_id)
        document = _parse_canonical_document(path, adr_id)
        adrs[adr_id] = adr_contract_snapshot(document)

    dependencies: dict[str, Any] = {}
    for dependency_id in dependency_ids(task):
        dependencies[dependency_id] = {
            "contract": task_contract_snapshot(root, dependency_id),
        }

    architecture = [
        _architecture_ref_snapshot(root, ref)
        for ref in architecture_refs(task)
    ]

    oqs: dict[str, Any] = {}
    for item in relevant_open_questions(root, task):
        oqs[str(item["id"])] = {
            "status": item["status"],
            "affects": item["affects"],
            "hash": content_hash(item["document"]["text"]),
        }

    return {
        "schema": 4,
        "step": task_contract_snapshot(root, step_id),
        "requirements": requirements,
        "adrs": adrs,
        "dependencies": dependencies,
        "architecture_refs": architecture,
        "open_questions": oqs,
    }

def planning_context_basis(root: Path, step_id: str) -> str:
    """Hash exact planning context, от которого зависит корректность плана."""
    return stable_hash(planning_context_snapshot(root, step_id))


def plan_content_hash(root: Path, step_id: str) -> str:
    task = read_task(root, step_id)
    return content_hash(task["sections"].get("Implementation plan", ""))


def implementation_prerequisite_failures(root: Path, step_id: str) -> list[str]:
    """Детерминированно доказать prerequisites непосредственно перед IMPLEMENT.

    PLAN может быть Ready до завершения dependency. Здесь, на executable
    boundary, completion proof уже обязателен. Helper не запускает LLM и
    возвращает точные причины, пригодные для execution runtime precondition.
    """
    failures: list[str] = []
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    plan = meta.get("plan")

    if not isinstance(plan, dict) or plan.get("status") != "ready":
        failures.append("plan-is-not-ready")
    else:
        try:
            current_basis = planning_context_basis(root, step_id)
        except (DocumentError, ConfigError, OSError, ValueError) as exc:
            failures.append(f"context-basis-unavailable:{exc}")
            current_basis = None
        current_content = plan_content_hash(root, step_id)
        stored_basis = plan.get("context_basis")
        stored_content = plan.get("content_hash")

        if current_basis is not None and stored_basis != current_basis:
            failures.append("plan-context-basis-is-stale")
        if stored_content != current_content:
            failures.append("plan-content-hash-is-stale")
        if _valid_sha256(stored_basis) and _valid_sha256(stored_content):
            matched = _latest_planning_review_for(
                root, step_id, stored_basis, stored_content
            )
            if matched is None:
                failures.append("matching-planning-review-pass-is-missing")
            else:
                report = matched["path"].relative_to(root).as_posix()
                if plan.get("reviewed_report") != report:
                    failures.append("reviewed-report-does-not-match-pass")
        else:
            failures.append("plan-fingerprints-are-invalid")

    if str(meta.get("phase")).upper() == "TBD":
        failures.append("phase-is-tbd")

    for adr_id in adr_ids(task):
        try:
            adr = _parse_canonical_document(canonical_adr_path(root, adr_id), adr_id)
        except (DocumentError, OSError, ValueError) as exc:
            failures.append(f"adr-unavailable:{adr_id}:{exc}")
            continue
        if adr["frontmatter"].get("status") != "accepted":
            failures.append(f"adr-not-accepted:{adr_id}")

    for item in relevant_open_questions(root, task):
        if item.get("status") == "open":
            failures.append(f"open-question:{item.get('id')}")

    for dep_id in dependency_ids(task):
        try:
            proof = step_completion_proof(root, dep_id)
        except (DocumentError, ConfigError, OSError, ValueError) as exc:
            failures.append(f"dependency-unprovable:{dep_id}:{exc}")
            continue
        if not proof["complete"]:
            failures.append(
                f"dependency-incomplete:{dep_id}:" + "; ".join(proof["reasons"])
            )

    return failures


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:].lower())
    )


def _validate_iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_semantic_review_sections(
    document: dict[str, Any],
    *,
    verdict: Any,
) -> list[str]:
    errors: list[str] = []
    for section in ("Scope checked", "Findings", "Verdict rationale"):
        value = document["sections"].get(section)
        if value is None:
            errors.append(f"missing section '## {section}'")
        elif not value.strip():
            errors.append(f"empty section '## {section}'")

    count = document["frontmatter"].get("finding_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        errors.append("finding_count must be a non-negative integer")
    elif verdict == "pass" and count != 0:
        errors.append("PASS semantic review requires finding_count=0")
    elif verdict == "blocked" and count < 1:
        errors.append("BLOCKED semantic review requires finding_count>=1")
    return errors


# ---------------------------------------------------------------------------
# Durable planning-review validator.
# Report доказывает semantic review exact pair context_basis + plan_content_hash.
# Старый PASS не переносится на изменившийся contract или изменённый plan text.
# ---------------------------------------------------------------------------
def validate_planning_review_report(
    root: Path,
    path: Path,
    *,
    expected_step_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable planning review must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]
    errors.extend(require_schema(document, kind="planning_review"))

    step_id = meta.get("step_id")
    if not isinstance(step_id, str) or STEP_ID_RE.fullmatch(step_id) is None:
        errors.append("step_id must be STEP-NNN")
    elif expected_step_id is not None and step_id != expected_step_id:
        errors.append(f"step_id must match review directory {expected_step_id}")

    verdict = meta.get("verdict")
    if verdict not in {"pass", "blocked"}:
        errors.append("verdict must be pass|blocked")
    if meta.get("reviewer_role") != "reviewer":
        errors.append("reviewer_role must be reviewer (independent from planner)")
    if not _valid_sha256(meta.get("context_basis")):
        errors.append("context_basis must be sha256")
    if not _valid_sha256(meta.get("plan_content_hash")):
        errors.append("plan_content_hash must be sha256")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="PLAN-REVIEW-",
            created_at=meta.get("created_at"),
        )
    )
    errors.extend(_validate_semantic_review_sections(document, verdict=verdict))
    return errors


def planning_review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    directory = planning_review_directory(root) / step_id
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("PLAN-REVIEW-*.md")):
        if validate_planning_review_report(root, path, expected_step_id=step_id):
            continue
        document = parse_document(path)
        result.append({"path": path, "document": document})
    return result


def _latest_planning_review_for(
    root: Path,
    step_id: str,
    basis: str,
    plan_hash: str,
) -> dict[str, Any] | None:
    for item in reversed(planning_review_reports(root, step_id)):
        meta = item["document"]["frontmatter"]
        if (
            meta.get("context_basis") == basis
            and meta.get("plan_content_hash") == plan_hash
        ):
            return item if meta.get("verdict") == "pass" else None
    return None


def latest_matching_planning_review(root: Path, step_id: str) -> dict[str, Any] | None:
    return _latest_planning_review_for(
        root,
        step_id,
        planning_context_basis(root, step_id),
        plan_content_hash(root, step_id),
    )


# ---------------------------------------------------------------------------
# Durable PROJECT INIT semantic-review validator.
# Stage-specific basis связывает PASS requirements/roadmap review с точным
# candidate project state.
# ---------------------------------------------------------------------------
def validate_init_review_report(
    root: Path,
    path: Path,
    *,
    expected_stage: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable INIT review must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]
    errors.extend(require_schema(document, kind="init_review"))

    stage = meta.get("stage")
    if stage not in {"requirements", "roadmap"}:
        errors.append("stage must be requirements|roadmap")
    elif expected_stage is not None and stage != expected_stage:
        errors.append(f"stage must be {expected_stage}")

    verdict = meta.get("verdict")
    if verdict not in {"pass", "blocked"}:
        errors.append("verdict must be pass|blocked")
    if meta.get("reviewer_role") != "reviewer":
        errors.append("reviewer_role must be reviewer (independent from initializer)")
    if not _valid_sha256(meta.get("basis")):
        errors.append("basis must be sha256")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="INIT-REVIEW-",
            created_at=meta.get("created_at"),
        )
    )
    errors.extend(_validate_semantic_review_sections(document, verdict=verdict))
    return errors


def _validate_semantic_review_reports(root: Path, errors: list[str]) -> None:
    planning_root = planning_review_directory(root)
    if planning_root.is_dir():
        for path in sorted(planning_root.glob("STEP-*/PLAN-REVIEW-*.md")):
            expected = path.parent.name
            for issue in validate_planning_review_report(
                root,
                path,
                expected_step_id=expected,
            ):
                errors.append(
                    f"planning-review: {path.relative_to(root)}: {issue}"
                )

    init_root = init_review_directory(root)
    if init_root.is_dir():
        for path in sorted(init_root.glob("INIT-REVIEW-*.md")):
            for issue in validate_init_review_report(root, path):
                errors.append(f"init-review: {path.relative_to(root)}: {issue}")


# ---------------------------------------------------------------------------
# STEP validator.
# Проверяет schema/sections/refs/risk/mutation policy и отдельно усиливает
# требования для plan.status=ready.
# ---------------------------------------------------------------------------
def _validate_task(root: Path, step_id: str, task: dict[str, Any], errors: list[str], warnings: list[str] | None) -> None:
    prefix = f"planning: {step_id}"
    for issue in require_schema(task):
        errors.append(f"{prefix}: {issue}")
    meta = task["frontmatter"]
    if meta.get("id") != step_id:
        errors.append(f"{prefix}: frontmatter id must match filename")
    if not exact_h1(task, step_id):
        errors.append(f"{prefix}: H1 must be '# {step_id} — <title>'")
    if meta.get("status") not in STEP_STATUSES:
        errors.append(f"{prefix}: invalid status")
    if meta.get("type") not in STEP_TYPES:
        errors.append(f"{prefix}: invalid type")
    if meta.get("priority") not in PRIORITIES:
        errors.append(f"{prefix}: invalid priority")
    if not isinstance(meta.get("phase"), str) or not meta.get("phase"):
        errors.append(f"{prefix}: phase must be a non-empty string")

    list_specs = {
        "depends_on": STEP_ID_RE,
        "requirements": REQ_ID_RE,
        "adrs": ADR_ID_RE,
    }
    for key, pattern in list_specs.items():
        values, issues = string_list(meta.get(key), key)
        errors.extend(f"{prefix}: {issue}" for issue in issues)
        for value in values:
            if pattern.fullmatch(value) is None:
                errors.append(f"{prefix}: invalid {key} reference {value}")

    refs, issues = string_list(meta.get("architecture_refs"), "architecture_refs")
    errors.extend(f"{prefix}: {issue}" for issue in issues)
    risks, issues = string_list(meta.get("risk_flags"), "risk_flags")
    errors.extend(f"{prefix}: {issue}" for issue in issues)
    if not risks:
        errors.append(f"{prefix}: risk_flags must not be empty")
    for flag in risks:
        if flag not in RISK_FLAGS:
            errors.append(f"{prefix}: unknown risk flag {flag}")
    if "none" in risks and len(risks) > 1:
        errors.append(f"{prefix}: risk flag 'none' is mutually exclusive")

    for section in REQUIRED_TASK_SECTIONS:
        if section not in task["sections"]:
            errors.append(f"{prefix}: missing section '## {section}'")
    for duplicate in task["duplicate_sections"]:
        errors.append(f"{prefix}: duplicate section '## {duplicate}'")

    mutation = task["sections"].get("Mutation policy", "")
    for heading in ("Allowed", "Conditional", "Forbidden"):
        if len(re.findall(rf"(?m)^### {heading}\s*$", mutation)) != 1:
            errors.append(f"{prefix}: Mutation policy requires exactly one '### {heading}'")

    for dep_id in dependency_ids(task):
        if dep_id == step_id:
            errors.append(f"{prefix}: depends on itself")
        elif not (task_directory(root) / f"{dep_id}.md").is_file():
            errors.append(f"{prefix}: dependency not found: {dep_id}")
    for req_id in requirement_ids(task):
        try:
            canonical_requirement_path(root, req_id)
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")
    for adr_id in adr_ids(task):
        try:
            adr = _parse_canonical_document(canonical_adr_path(root, adr_id), adr_id)
            if meta.get("plan", {}).get("status") == "ready" and adr["frontmatter"].get("status") != "accepted":
                errors.append(f"{prefix}: ready plan references non-accepted {adr_id}")
        except (DocumentError, ValueError, OSError) as exc:
            errors.append(f"{prefix}: {exc}")
    for ref in refs:
        try:
            _architecture_ref_snapshot(root, ref)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{prefix}: {exc}")

    plan = meta.get("plan")
    if not isinstance(plan, dict):
        errors.append(f"{prefix}: plan must be a mapping")
        return
    if plan.get("status") not in PLAN_STATUSES:
        errors.append(f"{prefix}: invalid plan.status")
        return
    revision = plan.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        errors.append(f"{prefix}: plan.revision must be a non-negative integer")

    if plan.get("status") == "ready":
        for issue in require_nonempty_sections(task, CONTRACT_SECTIONS + ("Implementation plan",)):
            errors.append(f"{prefix}: {issue}")
        for section in CONTRACT_SECTIONS + ("Implementation plan",):
            if has_unresolved_placeholder(task["sections"].get(section, "")):
                errors.append(f"{prefix}: unresolved placeholder in '## {section}'")
        if str(meta.get("phase")).upper() == "TBD":
            errors.append(f"{prefix}: ready plan has phase=TBD")
        for item in relevant_open_questions(root, task):
            if item.get("status") == "open":
                errors.append(f"{prefix}: ready plan is blocked by {item.get('id')}")

        expected_basis = None
        try:
            expected_basis = planning_context_basis(root, step_id)
        except (DocumentError, ConfigError, OSError, ValueError) as exc:
            errors.append(f"{prefix}: cannot compute context basis: {exc}")
        expected_content = plan_content_hash(root, step_id)
        stored_basis = plan.get("context_basis")
        stored_content = plan.get("content_hash")
        if expected_basis is not None and stored_basis != expected_basis:
            message = f"{prefix}: ready plan context_basis is stale"
            if warnings is None:
                errors.append(message)
            else:
                warnings.append(message)
        if stored_content != expected_content:
            errors.append(f"{prefix}: ready plan content_hash is stale")
        if not isinstance(plan.get("reviewed_report"), str) or not plan.get("reviewed_report"):
            errors.append(f"{prefix}: ready plan missing reviewed_report")
        if not _validate_iso_timestamp(plan.get("planned_at")):
            errors.append(f"{prefix}: ready plan planned_at must be ISO-8601")
        proof_basis = stored_basis if _valid_sha256(stored_basis) else None
        proof_content = stored_content if _valid_sha256(stored_content) else None
        if proof_basis is None:
            errors.append(f"{prefix}: ready plan context_basis must be sha256")
        if proof_content is None:
            errors.append(f"{prefix}: ready plan content_hash must be sha256")
        if proof_basis is not None and proof_content is not None:
            try:
                matched = _latest_planning_review_for(
                    root,
                    step_id,
                    proof_basis,
                    proof_content,
                )
            except (DocumentError, ConfigError, OSError, ValueError):
                matched = None
            if matched is None:
                errors.append(
                    f"{prefix}: ready plan has no PASS planning-review for stored basis/content"
                )
            else:
                actual = matched["path"].relative_to(root).as_posix()
                if plan.get("reviewed_report") != actual:
                    errors.append(
                        f"{prefix}: plan.reviewed_report does not point to matching PASS report"
                    )

    # completed — это не самостоятельное доказательство выполнения. Canonical
    # lifecycle разрешён только вместе с type-specific durable completion proof:
    # Evidence, accepted ADR и/или trusted PASS review в зависимости от STEP type.
    if meta.get("status") == "completed":
        try:
            proof = step_completion_proof(root, step_id)
        except (DocumentError, ConfigError, OSError, ValueError) as exc:
            errors.append(f"{prefix}: cannot prove completed lifecycle: {exc}")
        else:
            for reason in proof["reasons"]:
                errors.append(
                    f"{prefix}: completed STEP completion proof failed: {reason}"
                )


# Open Question validator: ID/status/affects targets и обязательные sections.
# PROJECT и конкретные STEP/REQ/ADR — единственные допустимые blocker targets.
def _validate_open_questions(root: Path, errors: list[str]) -> None:
    known_steps = {
        path.stem for path in task_directory(root).glob("STEP-*.md")
        if STEP_ID_RE.fullmatch(path.stem)
    }
    known_reqs = {
        match.group(1)
        for path in requirements_directory(root).glob("REQ-*.md")
        if (match := re.match(r"(REQ-\d{3,})-", path.name))
    }
    known_adrs = {
        match.group(1)
        for path in adr_directory(root).glob("ADR-*.md")
        if (match := re.match(r"(ADR-\d{3,})(?:-|\.md)", path.name))
    }
    seen: set[str] = set()
    for item in open_questions(root):
        path = item["path"]
        document = item["document"]
        meta = document["frontmatter"]
        oq_id = meta.get("id")
        prefix = f"planning: {path.relative_to(root)}"
        for issue in require_schema(document):
            errors.append(f"{prefix}: {issue}")
        if not isinstance(oq_id, str) or OQ_ID_RE.fullmatch(oq_id) is None:
            errors.append(f"{prefix}: invalid OQ id")
            continue
        if oq_id in seen:
            errors.append(f"planning: duplicate Open Question ID: {oq_id}")
        seen.add(oq_id)
        if not path.name.startswith(oq_id + "-"):
            errors.append(f"{prefix}: filename/id mismatch")
        if not exact_h1(document, oq_id):
            errors.append(f"{prefix}: invalid H1")
        if meta.get("status") not in OQ_STATUSES:
            errors.append(f"{prefix}: invalid status")
        affects, issues = string_list(meta.get("affects"), "affects")
        errors.extend(f"{prefix}: {issue}" for issue in issues)
        if not affects:
            errors.append(f"{prefix}: affects must not be empty")
        for target in affects:
            if target == "PROJECT":
                continue
            if STEP_ID_RE.fullmatch(target):
                exists = target in known_steps
            elif REQ_ID_RE.fullmatch(target):
                exists = target in known_reqs
            elif ADR_ID_RE.fullmatch(target):
                exists = target in known_adrs
            else:
                errors.append(f"{prefix}: invalid affects target {target}")
                continue
            if not exists:
                errors.append(f"{prefix}: affects target does not exist: {target}")
        errors.extend(
            f"{prefix}: {issue}"
            for issue in require_nonempty_sections(document, ("Context", "Decision needed"))
        )


# ---------------------------------------------------------------------------
# Главный planning aggregator.
# Сканирует STEP files, проверяет каждый contract, затем dependency cycles, OQ
# и semantic review history. allow_legacy используется только migration flow.
# ---------------------------------------------------------------------------
def validate_planning_contracts(
    root: Path,
    *,
    warnings: list[str] | None = None,
    allow_legacy: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        directory = task_directory(root)
    except ConfigError as exc:
        return [f"planning: {exc}"]
    if not directory.is_dir():
        return errors

    tasks: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("STEP-*.md")):
        if STEP_ID_RE.fullmatch(path.stem) is None:
            errors.append(f"planning: invalid STEP filename: {path.relative_to(root)}")
            continue
        try:
            task = parse_document(path)
        except DocumentError as exc:
            if allow_legacy and "legacy document" in str(exc):
                if warnings is not None:
                    warnings.append(f"planning: legacy active STEP pending PROJECT RECONCILE: {path.relative_to(root)}")
                continue
            errors.append(f"planning: {path.relative_to(root)}: {exc}")
            continue
        tasks[path.stem] = task
        _validate_task(root, path.stem, task, errors, warnings)

    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(step_id: str, chain: list[str]) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            start = chain.index(step_id) if step_id in chain else 0
            errors.append("planning: dependency cycle: " + " -> ".join(chain[start:] + [step_id]))
            return
        visiting.add(step_id)
        chain.append(step_id)
        for dep_id in dependency_ids(tasks[step_id]):
            if dep_id in tasks:
                visit(dep_id, chain)
        chain.pop()
        visiting.remove(step_id)
        visited.add(step_id)
    for step_id in sorted(tasks):
        visit(step_id, [])

    try:
        _validate_open_questions(root, errors)
    except (DocumentError, ConfigError, OSError, ValueError) as exc:
        errors.append(f"planning: open questions validation failed: {exc}")
    try:
        _validate_semantic_review_reports(root, errors)
    except (DocumentError, ConfigError, OSError, ValueError) as exc:
        errors.append(f"planning: semantic review validation failed: {exc}")
    return errors


def init_review_basis(root: Path, stage: str) -> str:
    """Fingerprint всех candidate contracts, которые semantic INIT review доказал."""
    if stage not in {"requirements", "roadmap"}:
        raise ValueError("init review stage must be requirements or roadmap")

    payload: dict[str, Any] = {
        "schema": 2,
        "stage": stage,
        "project_overview": None,
        "requirements": {},
        "adrs": {},
        "open_questions": {},
        "architecture": None,
    }

    overview = project_overview_path(root)
    if overview.is_file():
        payload["project_overview"] = content_hash(overview.read_text(encoding="utf-8"))

    req_dir = requirements_directory(root)
    for path in sorted(req_dir.glob("REQ-*.md")):
        if path.name in {"TEMPLATE.md", "REQ-001-template.md"}:
            continue
        payload["requirements"][path.name] = content_hash(path.read_text(encoding="utf-8"))

    for path in sorted(adr_directory(root).glob("ADR-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        payload["adrs"][path.name] = content_hash(path.read_text(encoding="utf-8"))

    for item in open_questions(root):
        payload["open_questions"][str(item["id"])] = content_hash(item["document"]["text"])

    arch = architecture_path(root)
    if arch.is_file():
        payload["architecture"] = content_hash(arch.read_text(encoding="utf-8"))

    if stage == "roadmap":
        payload["steps"] = {
            path.name: content_hash(path.read_text(encoding="utf-8"))
            for path in sorted(task_directory(root).glob("STEP-*.md"))
        }

    return stable_hash(payload)


def latest_matching_init_review(root: Path, stage: str) -> Path | None:
    directory = init_review_directory(root)
    if not directory.is_dir():
        return None
    basis = init_review_basis(root, stage)
    for path in reversed(sorted(directory.glob("INIT-REVIEW-*.md"))):
        if validate_init_review_report(root, path):
            continue
        document = parse_document(path)
        meta = document["frontmatter"]
        if meta.get("stage") == stage and meta.get("basis") == basis:
            return path if meta.get("verdict") == "pass" else None
    return None


__all__ = [
    "architecture_path",
    "canonical_adr_path",
    "canonical_requirement_path",
    "dependency_ids",
    "init_review_basis",
    "latest_matching_init_review",
    "latest_matching_planning_review",
    "max_fix_review_cycles",
    "plan_content_hash",
    "planning_context_basis",
    "read_task",
    "requirements_directory",
    "review_directory",
    "step_completion_proof",
    "task_contract_snapshot",
    "task_directory",
    "task_path",
    "validate_init_review_report",
    "validate_planning_contracts",
    "validate_planning_review_report",
]
