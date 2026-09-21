#!/usr/bin/env python3
"""Cross-document deterministic integrity aggregator active project state.

Этот модуль отвечает за связи **между** canonical artifacts. Низкоуровневую
schema каждого STEP/report/template проверяют специализированные contract modules,
а project_integrity собирает их и добавляет reverse traceability, lifecycle и
configured-artifact invariants.

Прямого CLI нет: основной caller — validate.py и PROJECT INIT finalization.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from document_contract import (
    ADR_ID_RE,
    ADR_STATUSES,
    DocumentError,
    PRIORITIES,
    REQ_ID_RE,
    STEP_ID_RE,
    exact_h1,
    parse_document,
    require_nonempty_sections,
    require_schema,
    string_list,
)
from harness_config import (
    ConfigError,
    adr_directory,
    architecture_path,
    get,
    load_manifest,
    load_update_policy,
    project_overview_path,
    requirements_directory,
    skill_registry_path,
    task_directory,
    update_lock_path,
    update_report_directory,
    open_questions_directory,
)
from planning_contract import (
    adr_ids,
    dependency_ids,
    open_questions,
    read_task,
    requirement_ids,
    validate_planning_contracts,
)
from projection_contract import validate_projections
from report_contract import validate_all_operational_reports
from review_contract import validate_all_review_reports
from template_contract import validate_project_templates


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


def _valid_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _canonical_requirements(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(requirements_directory(root).glob("REQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            document = parse_document(path)
        except DocumentError:
            continue
        req_id = document["frontmatter"].get("id")
        if isinstance(req_id, str):
            result[req_id] = document
    return result


def _canonical_adrs(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(adr_directory(root).glob("ADR-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            document = parse_document(path)
        except DocumentError:
            continue
        adr_id = document["frontmatter"].get("id")
        if isinstance(adr_id, str):
            result[adr_id] = document
    return result


# ---------------------------------------------------------------------------
# REQ integrity.
# Проверяет unique ID/file/H1/schema/sections и двусторонние REQ <-> STEP/ADR
# links. Отсутствующая reverse link считается drift, даже если forward ref есть.
# ---------------------------------------------------------------------------
def validate_requirements(root: Path) -> list[str]:
    errors: list[str] = []
    req_paths: dict[str, list[Path]] = {}
    for path in sorted(requirements_directory(root).glob("REQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            document = parse_document(path)
        except DocumentError as exc:
            errors.append(f"requirements: {path.relative_to(root)}: {exc}")
            continue
        req_id = document["frontmatter"].get("id")
        if isinstance(req_id, str):
            req_paths.setdefault(req_id, []).append(path)
    for req_id, paths in sorted(req_paths.items()):
        if len(paths) > 1:
            rendered = ", ".join(path.relative_to(root).as_posix() for path in paths)
            errors.append(f"requirements: duplicate canonical id {req_id}: {rendered}")

    reqs = _canonical_requirements(root)
    adrs = _canonical_adrs(root)
    tasks: dict[str, dict[str, Any]] = {}
    for path in task_directory(root).glob("STEP-*.md"):
        try:
            tasks[path.stem] = read_task(root, path.stem)
        except Exception:
            pass

    for req_id, doc in sorted(reqs.items()):
        prefix = f"requirements: {doc['path'].relative_to(root)}"
        for issue in require_schema(doc):
            errors.append(f"{prefix}: {issue}")
        if REQ_ID_RE.fullmatch(req_id) is None:
            errors.append(f"{prefix}: invalid id")
            continue
        if not doc["path"].name.startswith(req_id + "-"):
            errors.append(f"{prefix}: filename/id mismatch")
        if not exact_h1(doc, req_id):
            errors.append(f"{prefix}: invalid H1")
        meta = doc["frontmatter"]
        if meta.get("priority") not in PRIORITIES:
            errors.append(f"{prefix}: invalid priority")
        if not isinstance(meta.get("source"), str) or not meta.get("source"):
            errors.append(f"{prefix}: source must be non-empty")
        for key, pattern in (("steps", STEP_ID_RE), ("adrs", ADR_ID_RE)):
            values, issues = string_list(meta.get(key), key)
            errors.extend(f"{prefix}: {issue}" for issue in issues)
            for value in values:
                if pattern.fullmatch(value) is None:
                    errors.append(f"{prefix}: invalid {key} reference {value}")
        errors.extend(f"{prefix}: {issue}" for issue in require_nonempty_sections(doc, REQ_SECTIONS))

        for adr_id in meta.get("adrs", []) if isinstance(meta.get("adrs"), list) else []:
            adr = adrs.get(adr_id)
            if adr is None:
                errors.append(f"{prefix}: referenced ADR does not exist: {adr_id}")
            else:
                reverse = adr["frontmatter"].get("requirements", [])
                if not isinstance(reverse, list) or req_id not in reverse:
                    errors.append(f"{prefix}: reverse ADR traceability mismatch with {adr_id}")

        for step_id in meta.get("steps", []) if isinstance(meta.get("steps"), list) else []:
            task = tasks.get(step_id)
            if task is None:
                errors.append(f"{prefix}: referenced STEP does not exist: {step_id}")
            elif req_id not in requirement_ids(task):
                errors.append(f"{prefix}: reverse traceability mismatch with {step_id}")

    for step_id, task in tasks.items():
        for req_id in requirement_ids(task):
            req = reqs.get(req_id)
            if req is None:
                continue
            steps = req["frontmatter"].get("steps", [])
            if not isinstance(steps, list) or step_id not in steps:
                errors.append(
                    f"requirements: {step_id} links {req_id}, but canonical REQ does not link back"
                )
    return errors


# ---------------------------------------------------------------------------
# ADR integrity.
# Помимо schema/refs проверяет reciprocal supersession graph и запрещает cycles,
# потому что cyclic decision history не имеет deterministic current meaning.
# ---------------------------------------------------------------------------
def validate_adrs(root: Path) -> list[str]:
    errors: list[str] = []
    adr_paths: dict[str, list[Path]] = {}
    for path in sorted(adr_directory(root).glob("ADR-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            document = parse_document(path)
        except DocumentError as exc:
            errors.append(f"adr: {path.relative_to(root)}: {exc}")
            continue
        adr_id = document["frontmatter"].get("id")
        if isinstance(adr_id, str):
            adr_paths.setdefault(adr_id, []).append(path)
    for adr_id, paths in sorted(adr_paths.items()):
        if len(paths) > 1:
            rendered = ", ".join(path.relative_to(root).as_posix() for path in paths)
            errors.append(f"adr: duplicate canonical id {adr_id}: {rendered}")

    adrs = _canonical_adrs(root)
    reqs = _canonical_requirements(root)
    tasks: dict[str, dict[str, Any]] = {}
    for path in task_directory(root).glob("STEP-*.md"):
        if STEP_ID_RE.fullmatch(path.stem) is None:
            continue
        try:
            tasks[path.stem] = read_task(root, path.stem)
        except (DocumentError, ConfigError, OSError, ValueError):
            # Planning validation already owns this parse error. Cross-document
            # ADR checks must continue and report the rest of repository state.
            continue

    for adr_id, doc in sorted(adrs.items()):
        prefix = f"adr: {doc['path'].relative_to(root)}"
        for issue in require_schema(doc):
            errors.append(f"{prefix}: {issue}")
        if ADR_ID_RE.fullmatch(adr_id) is None:
            errors.append(f"{prefix}: invalid id")
        if not doc["path"].name.startswith(adr_id + "-") and doc["path"].stem != adr_id:
            errors.append(f"{prefix}: filename/id mismatch")
        if not exact_h1(doc, adr_id):
            errors.append(f"{prefix}: invalid H1")
        meta = doc["frontmatter"]
        if meta.get("status") not in ADR_STATUSES:
            errors.append(f"{prefix}: invalid status")
        if meta.get("date") is not None and not isinstance(meta.get("date"), str):
            errors.append(f"{prefix}: date must be null or string")
        for key, pattern in (
            ("deciders", re.compile(r".+")),
            ("supersedes", ADR_ID_RE),
            ("superseded_by", ADR_ID_RE),
            ("requirements", REQ_ID_RE),
            ("steps", STEP_ID_RE),
        ):
            values, issues = string_list(meta.get(key), key)
            errors.extend(f"{prefix}: {issue}" for issue in issues)
            for value in values:
                if pattern.fullmatch(value) is None:
                    errors.append(f"{prefix}: invalid {key} reference {value}")
        errors.extend(f"{prefix}: {issue}" for issue in require_nonempty_sections(doc, ADR_SECTIONS))

        for req_id in meta.get("requirements", []) if isinstance(meta.get("requirements"), list) else []:
            req = reqs.get(req_id)
            if req is None:
                errors.append(f"{prefix}: referenced REQ does not exist: {req_id}")
            else:
                reverse = req["frontmatter"].get("adrs", [])
                if not isinstance(reverse, list) or adr_id not in reverse:
                    errors.append(f"{prefix}: reverse REQ traceability mismatch with {req_id}")

        supersedes = meta.get("supersedes", []) if isinstance(meta.get("supersedes"), list) else []
        superseded_by = meta.get("superseded_by", []) if isinstance(meta.get("superseded_by"), list) else []
        if adr_id in supersedes or adr_id in superseded_by:
            errors.append(f"{prefix}: ADR cannot supersede/reference itself")
        if meta.get("status") == "superseded" and not superseded_by:
            errors.append(f"{prefix}: superseded ADR requires superseded_by")
        if superseded_by and meta.get("status") != "superseded":
            errors.append(f"{prefix}: ADR with superseded_by must have status=superseded")
        for target_id in supersedes:
            target = adrs.get(target_id)
            if target is None:
                errors.append(f"{prefix}: superseded ADR does not exist: {target_id}")
                continue
            reverse = target["frontmatter"].get("superseded_by", [])
            if not isinstance(reverse, list) or adr_id not in reverse:
                errors.append(f"{prefix}: supersedes relation is not reciprocal with {target_id}")
        for target_id in superseded_by:
            target = adrs.get(target_id)
            if target is None:
                errors.append(f"{prefix}: superseding ADR does not exist: {target_id}")
                continue
            reverse = target["frontmatter"].get("supersedes", [])
            if not isinstance(reverse, list) or adr_id not in reverse:
                errors.append(f"{prefix}: superseded_by relation is not reciprocal with {target_id}")

        for step_id in meta.get("steps", []) if isinstance(meta.get("steps"), list) else []:
            task = tasks.get(step_id)
            if task is None:
                errors.append(f"{prefix}: referenced STEP does not exist: {step_id}")
            elif adr_id not in adr_ids(task):
                errors.append(f"{prefix}: reverse traceability mismatch with {step_id}")

    # Supersession graph должен быть ацикличным: cycle делает current decision
    # неоднозначным и ломает deterministic resolution Accepted ADR.
    graph: dict[str, list[str]] = {}
    for node_id, node in adrs.items():
        values = node["frontmatter"].get("supersedes", [])
        graph[node_id] = [item for item in values if isinstance(item, str) and item in adrs] if isinstance(values, list) else []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str, trail: list[str]) -> None:
        if node_id in visiting:
            cycle_start = trail.index(node_id) if node_id in trail else 0
            cycle = trail[cycle_start:] + [node_id]
            errors.append("adr: supersession cycle: " + " -> ".join(cycle))
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for target_id in graph.get(node_id, []):
            visit(target_id, trail + [node_id])
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(graph):
        visit(node_id, [])

    for step_id, task in tasks.items():
        for adr_id in adr_ids(task):
            adr = adrs.get(adr_id)
            if adr is None:
                continue
            steps = adr["frontmatter"].get("steps", [])
            if not isinstance(steps, list) or step_id not in steps:
                errors.append(
                    f"adr: {step_id} links {adr_id}, but canonical ADR does not link back"
                )
    return errors



def validate_configured_artifacts(root: Path) -> list[str]:
    """Проверить обязательные artifacts именно по manifest-configured paths.

    Defaults не используются как второй source of truth: relocated/configured
    path обязан существовать там, где его объявляет manifest.
    """
    errors: list[str] = []
    checks = [
        (requirements_directory(root) / "TEMPLATE.md", "requirements template"),
        (requirements_directory(root) / "SPEC.md", "requirements SPEC projection"),
        (requirements_directory(root) / "STATUS.md", "requirements STATUS projection"),
        (adr_directory(root) / "TEMPLATE.md", "ADR template"),
        (task_directory(root) / "TEMPLATE.md", "STEP template"),
        (open_questions_directory(root) / "TEMPLATE.md", "Open Question template"),
        (skill_registry_path(root), "skill registry"),
        (update_report_directory(root) / "README.md", "Harness update report README"),
    ]
    for path, label in checks:
        if not path.is_file():
            errors.append(f"configured artifact missing ({label}): {path.relative_to(root)}")
    return errors

# Update lock связывает current manifest release с source repository/ref/commit.
# Это repository-level identity check, но не remote tag verification updater-а.
def validate_update_lock(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_manifest(root)
        policy = load_update_policy(root)
        path = update_lock_path(root)
    except ConfigError as exc:
        return [f"update-lock: {exc}"]
    if not path.is_file():
        return [f"update-lock: missing {path.relative_to(root)}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"update-lock: invalid JSON: {exc}"]

    if data.get("schemaVersion") != 1:
        errors.append("update-lock: schemaVersion must be 1")
    if data.get("harnessVersion") != str(get(manifest, "harness.version")):
        errors.append("update-lock: harnessVersion differs from manifest")
    release = get(manifest, "harness.release")
    if data.get("release") != release:
        errors.append("update-lock: release differs from manifest")
    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("update-lock: source must be an object")
        return errors
    expected_repo = get(policy, "source.repository")
    if source.get("repository") != expected_repo:
        errors.append("update-lock: source.repository differs from update policy")
    tag_pattern = get(policy, "source.tag_pattern")
    ref = source.get("ref")
    if not isinstance(tag_pattern, str) or not isinstance(ref, str):
        errors.append("update-lock: source.ref/tag_pattern missing")
    else:
        try:
            valid = re.fullmatch(tag_pattern, ref) is not None
        except re.error as exc:
            errors.append(f"update-lock: invalid source.tag_pattern: {exc}")
            valid = False
        if not valid:
            errors.append("update-lock: source.ref does not match tag_pattern")
        if release and ref != f"v{release}":
            errors.append("update-lock: source.ref must equal v<manifest release>")
    pinned_commit = source.get("commit")
    if pinned_commit is not None and (
        not isinstance(pinned_commit, str)
        or re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", pinned_commit) is None
    ):
        errors.append("update-lock: source.commit must be a 40/64-hex Git OID when present")
    return errors


# Initialized-project invariants применяются только после commit point INIT:
# имя/timestamp/project overview/canonical REQ+STEP и отсутствие PROJECT blockers.
def validate_initialized_project(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_manifest(root)
    except ConfigError as exc:
        return [f"project: {exc}"]
    initialized = get(manifest, "project.initialized")
    if not isinstance(initialized, bool):
        return ["project.initialized must be boolean"]
    if not initialized:
        return errors

    name = get(manifest, "project.name")
    initialized_at = get(manifest, "project.initializedAt")
    if not isinstance(name, str) or not name.strip():
        errors.append("project: initialized project requires non-empty project.name")
    if not _valid_iso(initialized_at):
        errors.append("project: initialized project requires ISO-8601 initializedAt")
    overview = project_overview_path(root)
    if not overview.is_file():
        errors.append(f"project: initialized project missing {overview.relative_to(root)}")

    reqs = _canonical_requirements(root)
    if not reqs:
        errors.append("project: initialized project requires canonical REQ")
    if any(path.name == "REQ-001-template.md" for path in requirements_directory(root).glob("REQ-*.md")):
        errors.append("project: initialized project still contains template REQ")
    steps = list(task_directory(root).glob("STEP-*.md"))
    if not steps:
        errors.append("project: initialized project requires at least one canonical STEP")

    for item in open_questions(root):
        if item.get("status") == "open" and "PROJECT" in set(item.get("affects") or []):
            errors.append(f"project: INIT blocked by project-level Open Question {item.get('id')}")
    return errors


# ---------------------------------------------------------------------------
# Главный project aggregator. allow_legacy — строго migration-only compatibility
# window; обычный commit/CI проходит полный набор current-schema validators.
# ---------------------------------------------------------------------------
def validate_project_integrity(
    root: Path,
    *,
    warnings: list[str] | None = None,
    allow_legacy: bool = False,
    ci_mode: bool = False,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_planning_contracts(root, warnings=warnings, allow_legacy=allow_legacy))
    if not allow_legacy:
        errors.extend(validate_requirements(root))
        errors.extend(validate_adrs(root))
        errors.extend(validate_all_review_reports(root, ci_mode=ci_mode))
        errors.extend(validate_all_operational_reports(root))
        errors.extend(validate_projections(root))
        errors.extend(validate_project_templates(root))
        errors.extend(validate_initialized_project(root))
    try:
        errors.extend(validate_configured_artifacts(root))
    except ConfigError as exc:
        errors.append(f"configured artifacts: {exc}")
    errors.extend(validate_update_lock(root))
    return errors
