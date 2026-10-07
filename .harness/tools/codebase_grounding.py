#!/usr/bin/env python3
"""Deterministic contract validator for semantic Codebase Grounding payloads.

Semantic reconstruction (flow/ownership/boundaries) выполняет модель.
Этот модуль проверяет только вычислимые свойства: schema, exact revision,
explicit context expansions, bounded context budget и provenance evidence paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from context_contracts import ContextContractError, validate_expansion


SCHEMA_VERSION = 1
SCOPE_LIMITS: dict[str, dict[str, int]] = {
    "simple": {"maxExpansionFiles": 6, "maxExpansionChars": 60_000},
    "complex": {"maxExpansionFiles": 16, "maxExpansionChars": 160_000},
}
REQUIRED_LIST_FIELDS = (
    "flow",
    "ownership",
    "boundaries",
    "interfaces",
    "invariants",
    "gotchas",
    "unknowns",
)


class GroundingContractError(ValueError):
    """Grounding payload нельзя безопасно использовать downstream."""


def _non_empty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GroundingContractError(f"{label} must be a non-empty string")
    return value.strip()


def _list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise GroundingContractError(f"{label} must be a list")
    return value


def _revision(value: object, *, label: str) -> dict[str, str | None]:
    """Normalize canonical repositoryRevision without reducing it to a string."""
    if not isinstance(value, dict):
        raise GroundingContractError(f"{label} must be an object")
    unexpected = sorted(set(value) - {"git_head", "worktree_hash"})
    if unexpected:
        raise GroundingContractError(
            f"{label} has unsupported keys: " + ", ".join(unexpected)
        )
    result: dict[str, str | None] = {}
    for key in ("git_head", "worktree_hash"):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise GroundingContractError(
                f"{label}.{key} must be null or a non-empty string"
            )
        result[key] = item.strip() if isinstance(item, str) else None
    return result


def _required_context_paths(context_contract: dict[str, Any]) -> set[str]:
    required = _list(context_contract.get("required"), label="context.required")
    result: set[str] = set()
    for index, item in enumerate(required):
        if not isinstance(item, dict):
            raise GroundingContractError(
                f"context.required[{index}] must be an object"
            )
        result.add(
            _non_empty_string(
                item.get("path"),
                label=f"context.required[{index}].path",
            )
        )
    return result


def _normalize_claim_entries(
    value: object,
    *,
    field: str,
    allowed_evidence: set[str],
) -> list[dict[str, Any]]:
    """Проверить semantic claim envelope, не оценивая истинность самого claim."""
    items = _list(value, label=field)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise GroundingContractError(f"{field}[{index}] must be an object")
        claim = _non_empty_string(
            item.get("claim"),
            label=f"{field}[{index}].claim",
        )
        raw_evidence = _list(
            item.get("evidence"),
            label=f"{field}[{index}].evidence",
        )
        evidence: list[str] = []
        for evidence_index, raw_path in enumerate(raw_evidence):
            evidence_path = _non_empty_string(
                raw_path,
                label=f"{field}[{index}].evidence[{evidence_index}]",
            )
            if evidence_path not in allowed_evidence:
                raise GroundingContractError(
                    f"{field}[{index}] evidence was not available to grounding: "
                    f"{evidence_path}"
                )
            if evidence_path not in evidence:
                evidence.append(evidence_path)
        if not evidence:
            raise GroundingContractError(
                f"{field}[{index}].evidence must be non-empty"
            )
        result.append({"claim": claim, "evidence": evidence})
    return result


def validate_grounding_payload(
    root: Path,
    context_contract: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize one grounding payload without semantic judgement."""
    if context_contract.get("status") != "PASS":
        raise GroundingContractError("context contract status must be PASS")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise GroundingContractError(
            f"schemaVersion must be {SCHEMA_VERSION}"
        )
    if payload.get("status") not in {"PASS", "BLOCKED"}:
        raise GroundingContractError("status must be PASS or BLOCKED")

    scope = _non_empty_string(payload.get("scope"), label="scope")
    if scope not in SCOPE_LIMITS:
        raise GroundingContractError(
            f"scope must be one of {sorted(SCOPE_LIMITS)}"
        )
    target = _non_empty_string(payload.get("target"), label="target")
    revision = _revision(
        payload.get("repositoryRevision"),
        label="repositoryRevision",
    )
    expected_revision = _revision(
        context_contract.get("repositoryRevision"),
        label="context.repositoryRevision",
    )
    if revision != expected_revision:
        raise GroundingContractError(
            "repositoryRevision does not match Context Contract"
        )

    metrics = context_contract.get("metrics")
    if not isinstance(metrics, dict):
        raise GroundingContractError("context.metrics must be an object")
    if metrics.get("fullRepositoryPreload") is not False:
        raise GroundingContractError(
            "Context Contract must declare fullRepositoryPreload=false"
        )
    for key in ("artifactCount", "sectionCount", "manifestChars"):
        value = metrics.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise GroundingContractError(
                f"context.metrics.{key} must be a non-negative integer"
            )

    raw_sections: dict[str, list[Any]] = {}
    for field in REQUIRED_LIST_FIELDS:
        raw_sections[field] = _list(payload.get(field), label=field)

    expansions = _list(payload.get("expansions"), label="expansions")
    limits = SCOPE_LIMITS[scope]
    if len(expansions) > limits["maxExpansionFiles"]:
        raise GroundingContractError(
            f"{scope} grounding allows at most "
            f"{limits['maxExpansionFiles']} expansion files"
        )

    expansion_paths: set[str] = set()
    normalized_expansions: list[dict[str, Any]] = []
    expanded_chars = 0
    for index, item in enumerate(expansions):
        if not isinstance(item, dict):
            raise GroundingContractError(
                f"expansions[{index}] must be an object"
            )
        path = _non_empty_string(
            item.get("path"),
            label=f"expansions[{index}].path",
        )
        reason = _non_empty_string(
            item.get("reason"),
            label=f"expansions[{index}].reason",
        )
        if path in expansion_paths:
            raise GroundingContractError(f"duplicate expansion path: {path}")
        try:
            validated = validate_expansion(root, path, reason)
        except ContextContractError as exc:
            raise GroundingContractError(str(exc)) from exc
        resolved = (root / validated["path"]).resolve()
        try:
            chars = len(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise GroundingContractError(
                f"cannot measure expansion {validated['path']}: {exc}"
            ) from exc
        expanded_chars += chars
        expansion_paths.add(validated["path"])
        normalized_expansions.append(
            {
                "path": validated["path"],
                "reason": validated["reason"],
                "chars": chars,
            }
        )

    if expanded_chars > limits["maxExpansionChars"]:
        raise GroundingContractError(
            f"{scope} grounding expansion budget exceeded: "
            f"{expanded_chars}>{limits['maxExpansionChars']} chars"
        )

    evidence_paths = _list(payload.get("evidencePaths"), label="evidencePaths")
    normalized_evidence: list[str] = []
    allowed_evidence = _required_context_paths(context_contract) | expansion_paths
    for index, raw_path in enumerate(evidence_paths):
        path = _non_empty_string(
            raw_path,
            label=f"evidencePaths[{index}]",
        )
        if path not in allowed_evidence:
            raise GroundingContractError(
                f"evidence path was not available to grounding: {path}"
            )
        if path not in normalized_evidence:
            normalized_evidence.append(path)
    if payload.get("status") == "PASS" and not normalized_evidence:
        raise GroundingContractError("evidencePaths must be non-empty for PASS")

    normalized_sections: dict[str, list[dict[str, Any]]] = {}
    claim_evidence: set[str] = set()
    for field in REQUIRED_LIST_FIELDS:
        normalized = _normalize_claim_entries(
            raw_sections[field],
            field=field,
            allowed_evidence=allowed_evidence,
        )
        normalized_sections[field] = normalized
        for item in normalized:
            claim_evidence.update(item["evidence"])
    if payload.get("status") == "PASS":
        for field in ("flow", "ownership", "boundaries"):
            if not normalized_sections[field]:
                raise GroundingContractError(
                    f"{field} must be non-empty for PASS"
                )
    missing_from_index = sorted(claim_evidence - set(normalized_evidence))
    if missing_from_index:
        raise GroundingContractError(
            "claim evidence must also be listed in evidencePaths: "
            + ", ".join(missing_from_index)
        )

    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": payload["status"],
        "scope": scope,
        "target": target,
        "repositoryRevision": revision,
        **normalized_sections,
        "evidencePaths": normalized_evidence,
        "expansions": normalized_expansions,
        "contextBudget": {
            "baseMetrics": {
                "artifactCount": metrics["artifactCount"],
                "sectionCount": metrics["sectionCount"],
                "manifestChars": metrics["manifestChars"],
                "fullRepositoryPreload": False,
            },
            "expansionFiles": len(normalized_expansions),
            "expansionChars": expanded_chars,
            "maxExpansionFiles": limits["maxExpansionFiles"],
            "maxExpansionChars": limits["maxExpansionChars"],
        },
    }
    return result
