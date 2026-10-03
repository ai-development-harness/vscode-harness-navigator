#!/usr/bin/env python3
"""Deterministic impact propagation for planning-contract evolution.

The authoritative freshness decision remains planning_context_basis. This module
only explains that result with component fingerprints from the same schema-v4
planning snapshot and projects affected STEP surface. It never rewrites
downstream artifacts and never promotes code to source of truth.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from document_contract import parse_document
from harness_config import task_directory
from planning_contract import (
    adr_ids,
    architecture_refs,
    canonical_adr_path,
    dependency_ids,
    planning_context_basis,
    planning_context_components,
    read_task,
    relevant_open_questions,
    requirement_ids,
)

SCHEMA_VERSION = 1
_CHANGED_ID_RE = re.compile(r"^(?:REQ|ADR|STEP|OQ|PRN)-\d{3,}$")


class ImpactAnalysisError(ValueError):
    """Impact surface cannot be derived safely from canonical artifacts."""


def _decode_components(values: Any, *, allow_empty: bool) -> dict[str, str]:
    if values is None and allow_empty:
        return {}
    if not isinstance(values, list):
        raise ImpactAnalysisError("plan.context_components must be a string array")
    if not values and allow_empty:
        return {}

    result: dict[str, str] = {}
    for index, item in enumerate(values):
        if not isinstance(item, str) or "=" not in item:
            raise ImpactAnalysisError(
                f"plan.context_components[{index}] must be COMPONENT=sha256"
            )
        key, digest = item.rsplit("=", 1)
        if not key or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ImpactAnalysisError(
                f"plan.context_components[{index}] has invalid fingerprint"
            )
        if key in result:
            raise ImpactAnalysisError(
                f"duplicate plan.context_components key: {key}"
            )
        result[key] = digest
    return result


def compare_component_sets(
    stored: list[str],
    current: list[str],
) -> list[dict[str, str]]:
    before = _decode_components(stored, allow_empty=False)
    after = _decode_components(current, allow_empty=False)
    changes: list[dict[str, str]] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append({"component": key, "change": "added"})
        elif key not in after:
            changes.append({"component": key, "change": "removed"})
        elif before[key] != after[key]:
            changes.append({"component": key, "change": "changed"})
    return changes


def plan_staleness(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    plan = task["frontmatter"].get("plan")
    if not isinstance(plan, dict):
        return {
            "status": "invalid",
            "causes": [{"component": f"STEP@{step_id}", "change": "invalid-plan"}],
            "action": f"STEP PLAN {step_id}",
        }
    if plan.get("status") != "ready":
        return {
            "status": "not_ready",
            "causes": [],
            "action": f"STEP PLAN {step_id}",
        }

    stored_basis = plan.get("context_basis")
    current_basis = planning_context_basis(root, step_id)
    if stored_basis == current_basis:
        return {"status": "fresh", "causes": [], "action": None}

    stored_components = plan.get("context_components")
    # Compatibility: Ready plans created before this capability still fail-safe
    # on the authoritative basis mismatch, but cannot claim a component cause
    # that was never durably recorded.
    if stored_components in (None, []):
        causes = [{"component": "PLANNING_CONTEXT", "change": "changed"}]
    else:
        if not isinstance(stored_components, list):
            raise ImpactAnalysisError(
                f"{step_id}: plan.context_components must be a string array"
            )
        causes = compare_component_sets(
            stored_components,
            planning_context_components(root, step_id),
        )
        if not causes:
            causes = [{"component": "PLANNING_CONTEXT", "change": "changed"}]

    return {
        "status": "stale",
        "causes": causes,
        "action": f"STEP PLAN {step_id}",
        "storedBasis": stored_basis,
        "currentBasis": current_basis,
    }


def _changed_component_key(value: str) -> str:
    if value.startswith("ARCH@") and len(value) > len("ARCH@"):
        return value
    if _CHANGED_ID_RE.fullmatch(value):
        prefix = value.split("-", 1)[0]
        return f"{prefix}@{value}"
    raise ImpactAnalysisError(
        f"unsupported changed artifact {value!r}; expected REQ/ADR/STEP/OQ/PRN ID or ARCH@ref"
    )


def _linked_component_keys(root: Path, step_id: str) -> set[str]:
    """Return known current component identities without duplicating hashes."""
    task = read_task(root, step_id)
    keys = {f"STEP@{step_id}"}
    keys.update(f"REQ@{item}" for item in requirement_ids(task))
    keys.update(f"ADR@{item}" for item in adr_ids(task))
    keys.update(f"STEP@{item}" for item in dependency_ids(task))
    keys.update(f"ARCH@{item}" for item in architecture_refs(task))
    keys.update(
        f"OQ@{item['id']}"
        for item in relevant_open_questions(root, task)
        if isinstance(item.get("id"), str)
    )

    plan = task["frontmatter"].get("plan")
    if isinstance(plan, dict):
        stored = _decode_components(
            plan.get("context_components"),
            allow_empty=True,
        )
        keys.update(stored)
    try:
        current = _decode_components(
            planning_context_components(root, step_id),
            allow_empty=True,
        )
    except (OSError, ValueError):
        current = {}
    keys.update(current)
    return keys


def _replacement_reasons(
    root: Path,
    task: dict[str, Any],
    changed_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    for linked_id in adr_ids(task):
        path = canonical_adr_path(root, linked_id)
        document = parse_document(path)
        superseded_by = document["frontmatter"].get("superseded_by")
        values = superseded_by if isinstance(superseded_by, list) else []
        for replacement in values:
            if isinstance(replacement, str) and replacement in changed_ids:
                reasons.append(
                    f"linked architecture decision {linked_id} superseded by: {replacement}"
                )
    return reasons


def _reason_for_component(key: str) -> str:
    kind, _, value = key.partition("@")
    labels = {
        "REQ": "linked requirement changed",
        "ADR": "linked architecture decision changed",
        "STEP": "STEP/dependency contract changed",
        "OQ": "relevant open question changed",
        "PRN": "project principle changed",
        "ARCH": "architecture reference changed",
    }
    return f"{labels.get(kind, 'planning component changed')}: {value}"


def affected_steps(root: Path, changed: list[str]) -> dict[str, Any]:
    if not isinstance(changed, list) or not changed:
        raise ImpactAnalysisError("changed artifacts must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in changed):
        raise ImpactAnalysisError("changed artifacts must be non-empty strings")

    normalized = sorted(set(item.strip() for item in changed))
    changed_keys = {_changed_component_key(item): item for item in normalized}
    changed_ids = set(normalized)
    affected: list[dict[str, Any]] = []

    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        step_id = path.stem
        task = read_task(root, step_id)
        linked = _linked_component_keys(root, step_id)
        reasons = [
            _reason_for_component(key)
            for key in sorted(changed_keys)
            if key in linked
        ]
        reasons.extend(_replacement_reasons(root, task, changed_ids))
        reasons = sorted(set(reasons))
        if not reasons:
            continue

        freshness = plan_staleness(root, step_id)
        affected.append(
            {
                "step": step_id,
                "reasons": reasons,
                "plan": freshness["status"],
                "causes": freshness.get("causes", []),
                "action": freshness.get("action"),
            }
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "changed": normalized,
        "affected": affected,
    }


__all__ = [
    "ImpactAnalysisError",
    "affected_steps",
    "compare_component_sets",
    "plan_staleness",
]
