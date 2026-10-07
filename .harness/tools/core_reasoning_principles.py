#!/usr/bin/env python3
"""Deterministic selector for Harness-owned Core Reasoning Principles.

Core Reasoning Principles (CRP) describe *how* an agent should reason. They are
not project engineering policy and therefore must never be mixed with project
PRN-NNN artifacts.

The model must not receive the whole CRP catalog on every semantic phase.
This module scans/validates the Harness-owned leaf catalog deterministically,
derives applicability from existing STEP/Context facts, and returns only the
small set of leaf paths that the runtime should load.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from document_contract import (
    DocumentError,
    parse_document,
    require_nonempty_sections,
    require_schema,
)


SCHEMA_VERSION = 1
NAMESPACE = "CRP"
MIN_CATALOG_SIZE = 6
MAX_CATALOG_SIZE = 10
MAX_LEAF_CHARS = 4_000

ROLES = {"planner", "implementer", "reviewer"}

# Trigger names are protocol-level deterministic selectors. They are deliberately
# coarse: if applicability cannot be derived reliably from current STEP facts,
# it should stay out of the automatic Context Contract instead of being guessed.
TRIGGERS = {
    "context-heavy",
    "review-phase",
    "multi-unit",
    "concurrency-risk",
    "bugfix",
    "hardening",
    "refactor",
    "architecture-risk",
}

REQUIRED_SECTIONS = (
    "Trigger / applicability",
    "Rationale",
    "Actionable pattern",
)
ID_RE = re.compile(r"CRP-\d{3}")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class CoreReasoningPrincipleError(ValueError):
    """Catalog/selection cannot be trusted; caller must fail closed."""


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise CoreReasoningPrincipleError(
            f"Core Principle path escapes repository: {path}"
        ) from exc


def _string_list(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise CoreReasoningPrincipleError(
            f"{label} must be a non-empty-string list"
        )
    result = [item.strip() for item in value]
    if not result:
        raise CoreReasoningPrincipleError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise CoreReasoningPrincipleError(f"{label} must not contain duplicates")
    return result


def catalog_directory(root: Path) -> Path:
    return (
        root
        / ".agents"
        / "skills"
        / "core-reasoning-principles"
        / "leaves"
    )


def _load_leaf(root: Path, path: Path) -> dict[str, Any]:
    """Parse one short CRP leaf and validate the machine-readable envelope."""
    if path.is_symlink():
        raise CoreReasoningPrincipleError(
            f"{_rel(root, path)}: Core Principle leaf must not be a symlink"
        )
    try:
        document = parse_document(path)
    except (DocumentError, OSError, UnicodeError) as exc:
        raise CoreReasoningPrincipleError(
            f"{_rel(root, path)}: cannot parse Core Principle: {exc}"
        ) from exc

    errors = require_schema(document)
    errors.extend(require_nonempty_sections(document, REQUIRED_SECTIONS))
    meta = document["frontmatter"]
    allowed_meta = {
        "schema",
        "namespace",
        "id",
        "slug",
        "status",
        "roles",
        "triggers",
    }
    unexpected_meta = sorted(set(meta) - allowed_meta)
    if unexpected_meta:
        errors.append(
            "unsupported frontmatter keys: " + ", ".join(unexpected_meta)
        )

    if meta.get("namespace") != NAMESPACE:
        errors.append(f"frontmatter namespace must be {NAMESPACE}")

    principle_id = meta.get("id")
    if not isinstance(principle_id, str) or ID_RE.fullmatch(principle_id) is None:
        errors.append("frontmatter id must match CRP-NNN")

    slug = meta.get("slug")
    if not isinstance(slug, str) or SLUG_RE.fullmatch(slug) is None:
        errors.append("frontmatter slug must be lowercase kebab-case")

    if meta.get("status") != "active":
        errors.append("frontmatter status must be active")

    try:
        roles = _string_list(meta.get("roles"), label="frontmatter roles")
        triggers = _string_list(meta.get("triggers"), label="frontmatter triggers")
    except CoreReasoningPrincipleError as exc:
        errors.append(str(exc))
        roles = []
        triggers = []

    unknown_roles = sorted(set(roles) - ROLES)
    if unknown_roles:
        errors.append("unknown roles: " + ", ".join(unknown_roles))
    unknown_triggers = sorted(set(triggers) - TRIGGERS)
    if unknown_triggers:
        errors.append("unknown triggers: " + ", ".join(unknown_triggers))

    if isinstance(principle_id, str) and isinstance(slug, str):
        expected_name = f"{principle_id}-{slug}.md"
        if path.name != expected_name:
            errors.append(f"filename must be {expected_name}")
        if re.fullmatch(
            rf"# {re.escape(principle_id)} — .+",
            str(document.get("h1") or ""),
        ) is None:
            errors.append(f"H1 must start with '# {principle_id} — '")

    chars = len(document["text"])
    if chars > MAX_LEAF_CHARS:
        errors.append(
            f"leaf is too large for progressive disclosure: "
            f"{chars}>{MAX_LEAF_CHARS} chars"
        )

    if errors:
        raise CoreReasoningPrincipleError(
            f"{_rel(root, path)}: " + "; ".join(errors)
        )

    assert isinstance(principle_id, str)
    assert isinstance(slug, str)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "namespace": NAMESPACE,
        "id": principle_id,
        "slug": slug,
        "path": _rel(root, path),
        "roles": roles,
        "triggers": triggers,
        "chars": chars,
    }


def load_core_reasoning_principles(root: Path) -> list[dict[str, Any]]:
    """Load the Harness-owned catalog without exposing it to semantic context."""
    directory = catalog_directory(root)
    if not directory.is_dir():
        raise CoreReasoningPrincipleError(
            "Core Reasoning Principles catalog directory is missing"
        )

    markdown_files = [
        path
        for path in sorted(directory.glob("*.md"))
        if path.is_file()
    ]
    unexpected = [
        _rel(root, path)
        for path in markdown_files
        if re.fullmatch(r"CRP-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*\.md", path.name)
        is None
    ]
    if unexpected:
        raise CoreReasoningPrincipleError(
            "unexpected Core Principle leaf files: " + ", ".join(unexpected)
        )

    leaves = [_load_leaf(root, path) for path in markdown_files]
    if not MIN_CATALOG_SIZE <= len(leaves) <= MAX_CATALOG_SIZE:
        raise CoreReasoningPrincipleError(
            "Core Reasoning Principles first-iteration catalog must contain "
            f"{MIN_CATALOG_SIZE}-{MAX_CATALOG_SIZE} leaves; found {len(leaves)}"
        )

    ids = [str(item["id"]) for item in leaves]
    slugs = [str(item["slug"]) for item in leaves]
    if len(ids) != len(set(ids)):
        raise CoreReasoningPrincipleError("Core Principle ids must be unique")
    if len(slugs) != len(set(slugs)):
        raise CoreReasoningPrincipleError("Core Principle slugs must be unique")

    return sorted(leaves, key=lambda item: str(item["id"]))


def applicability_signals(
    task: dict[str, Any],
    *,
    role: str,
    artifact_count: int,
    section_count: int,
) -> set[str]:
    """Derive only signals that are already deterministic STEP/context facts."""
    if role not in ROLES:
        raise CoreReasoningPrincipleError(
            f"role must be one of {sorted(ROLES)}"
        )
    if artifact_count < 0 or section_count < 0:
        raise CoreReasoningPrincipleError(
            "artifact_count/section_count must be non-negative"
        )

    meta = task.get("frontmatter")
    if not isinstance(meta, dict):
        raise CoreReasoningPrincipleError("task frontmatter must be an object")

    step_type = meta.get("type")
    raw_flags = meta.get("risk_flags")
    raw_dependencies = meta.get("depends_on")
    plan = meta.get("plan")

    if (
        not isinstance(raw_flags, list)
        or not raw_flags
        or any(not isinstance(item, str) or not item for item in raw_flags)
    ):
        raise CoreReasoningPrincipleError(
            "task risk_flags must be a non-empty string list"
        )
    if (
        not isinstance(raw_dependencies, list)
        or any(not isinstance(item, str) or not item for item in raw_dependencies)
    ):
        raise CoreReasoningPrincipleError(
            "task depends_on must be a string list"
        )
    if not isinstance(plan, dict):
        raise CoreReasoningPrincipleError("task plan must be an object")

    flags = set(raw_flags)
    dependencies = list(raw_dependencies)

    groups = plan.get("execution_groups")
    if groups is None:
        execution_group_count = 0
    elif isinstance(groups, dict):
        execution_group_count = len(groups)
    else:
        raise CoreReasoningPrincipleError(
            "task plan.execution_groups must be an object when present"
        )

    signals: set[str] = set()

    # Context-heavy is based on the already-resolved section-level contract,
    # not on token/model heuristics. Thresholds are conservative and stable.
    if artifact_count >= 6 or section_count >= 20:
        signals.add("context-heavy")

    if role == "reviewer":
        signals.add("review-phase")

    # Multi-unit is intentionally structural: declared groups, multiple direct
    # dependencies, migration/release risk. We do not keyword-match prose.
    if (
        execution_group_count >= 2
        or len(dependencies) >= 2
        or bool(flags & {"data-migration", "release-critical"})
    ):
        signals.add("multi-unit")

    if "concurrency" in flags:
        signals.add("concurrency-risk")
    if "architecture" in flags:
        signals.add("architecture-risk")
    if step_type == "bugfix":
        signals.add("bugfix")
    if step_type == "hardening":
        signals.add("hardening")
    if step_type == "refactor":
        signals.add("refactor")

    return signals


def select_core_reasoning_principles(
    root: Path,
    task: dict[str, Any],
    *,
    role: str,
    artifact_count: int,
    section_count: int,
) -> list[dict[str, Any]]:
    """Return only applicable leaves; never return the whole catalog by default."""
    catalog = load_core_reasoning_principles(root)
    signals = applicability_signals(
        task,
        role=role,
        artifact_count=artifact_count,
        section_count=section_count,
    )

    selected: list[dict[str, Any]] = []
    for leaf in catalog:
        if role not in leaf["roles"]:
            continue
        matched = sorted(set(leaf["triggers"]) & signals)
        if not matched:
            continue
        selected.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "namespace": NAMESPACE,
                "id": leaf["id"],
                "slug": leaf["slug"],
                "path": leaf["path"],
                "triggeredBy": matched,
                "chars": leaf["chars"],
            }
        )

    return selected


__all__ = [
    "CoreReasoningPrincipleError",
    "NAMESPACE",
    "ROLES",
    "TRIGGERS",
    "applicability_signals",
    "load_core_reasoning_principles",
    "select_core_reasoning_principles",
]
