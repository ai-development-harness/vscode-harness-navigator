#!/usr/bin/env python3
"""Deterministic boundary for semantic Blast Radius.

The model proposes implicit behavioral risks. This module owns only facts that
can be recomputed: STEP risk flags, explicit dependency impact, repository
revision, Context Contract/grounding provenance, context budget and executable
Verification evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codebase_grounding import (
    GroundingContractError,
    SCOPE_LIMITS,
    validate_grounding_payload,
)
from context_contracts import ContextContractError, validate_expansion
from impact_analysis import affected_steps
from planning_contract import read_task
from review_contract import repository_revision
from verification import (
    parse_verification,
    verification_command_evidence,
    verification_freshness,
)


SCHEMA_VERSION = 1
PHASES = {"plan", "review"}
STATUSES = {"PASS", "INCONCLUSIVE", "BLOCKED"}
PROOF_STATUSES = {"proven", "disproven", "planned", "unavailable"}
PROOF_KINDS = {"verification-command", "inspection", "none"}


class BlastRadiusError(ValueError):
    """Semantic blast-radius result cannot be trusted downstream."""


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlastRadiusError(f"{label} must be a non-empty string")
    return value.strip()


def _list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BlastRadiusError(f"{label} must be a list")
    return value


def _context_paths(context_contract: dict[str, Any]) -> set[str]:
    required = _list(context_contract.get("required"), label="context.required")
    result: set[str] = set()
    for index, item in enumerate(required):
        if not isinstance(item, dict):
            raise BlastRadiusError(f"context.required[{index}] must be an object")
        result.add(
            _text(item.get("path"), label=f"context.required[{index}].path")
        )
    return result


def _revision(value: object, *, label: str) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise BlastRadiusError(f"{label} must be an object")
    unexpected = sorted(set(value) - {"git_head", "worktree_hash"})
    if unexpected:
        raise BlastRadiusError(
            f"{label} has unsupported keys: " + ", ".join(unexpected)
        )
    result: dict[str, str | None] = {}
    for key in ("git_head", "worktree_hash"):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise BlastRadiusError(
                f"{label}.{key} must be null or a non-empty string"
            )
        result[key] = item.strip() if isinstance(item, str) else None
    return result


def blast_radius_preflight(root: Path, step_id: str, phase: str) -> dict[str, Any]:
    """Return deterministic trigger/facts without semantic inference."""
    if phase not in PHASES:
        raise BlastRadiusError(f"phase must be one of {sorted(PHASES)}")
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    raw_flags = meta.get("risk_flags")
    if not isinstance(raw_flags, list) or not all(
        isinstance(item, str) and item for item in raw_flags
    ):
        raise BlastRadiusError("STEP risk_flags must be a non-empty string list")
    flags = sorted(set(raw_flags))
    material = [item for item in flags if item != "none"]
    required = bool(material)

    impact = affected_steps(root, [step_id])
    explicit = [
        item for item in impact["affected"]
        if item.get("step") != step_id
    ]
    entries = parse_verification(root, step_id)
    verification: dict[str, Any] = {
        "commands": [
            item["value"] for item in entries if item["kind"] == "command"
        ],
        "freshness": verification_freshness(root, step_id),
    }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "phase": phase,
        "stepId": step_id,
        "required": required,
        "requiredReasons": [f"risk flag: {item}" for item in material],
        "riskFlags": flags,
        "repositoryRevision": repository_revision(root),
        "explicitImpact": {
            "changed": impact["changed"],
            "affected": explicit,
        },
        "verification": verification,
    }


def _validate_evidence_paths(
    value: object,
    *,
    label: str,
    allowed: set[str],
) -> list[str]:
    raw = _list(value, label=label)
    result: list[str] = []
    for index, item in enumerate(raw):
        path = _text(item, label=f"{label}[{index}]")
        if path not in allowed:
            raise BlastRadiusError(
                f"{label}[{index}] was not available to blast-radius: {path}"
            )
        if path not in result:
            result.append(path)
    if not result:
        raise BlastRadiusError(f"{label} must be non-empty")
    return result


def validate_blast_radius_payload(
    root: Path,
    step_id: str,
    phase: str,
    context_contract: dict[str, Any],
    grounding_payload: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate semantic hypotheses against fresh deterministic facts."""
    preflight = blast_radius_preflight(root, step_id, phase)

    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise BlastRadiusError(f"schemaVersion must be {SCHEMA_VERSION}")
    status = payload.get("status")
    if status not in STATUSES:
        raise BlastRadiusError(f"status must be one of {sorted(STATUSES)}")
    if payload.get("phase") != phase:
        raise BlastRadiusError("payload phase does not match requested phase")
    if payload.get("stepId") != step_id:
        raise BlastRadiusError("payload stepId does not match requested STEP")

    revision = _revision(payload.get("repositoryRevision"), label="repositoryRevision")
    context_revision = _revision(
        context_contract.get("repositoryRevision"),
        label="context.repositoryRevision",
    )
    current_revision = _revision(
        preflight["repositoryRevision"],
        label="current.repositoryRevision",
    )
    if revision != context_revision or revision != current_revision:
        raise BlastRadiusError(
            "repositoryRevision must match Context Contract and current repository"
        )

    try:
        grounding = validate_grounding_payload(
            root,
            context_contract,
            grounding_payload,
        )
    except GroundingContractError as exc:
        raise BlastRadiusError(f"invalid grounding: {exc}") from exc
    if grounding["status"] != "PASS":
        raise BlastRadiusError("grounding status must be PASS")
    scope = payload.get("scope")
    if scope != grounding["scope"] or scope not in SCOPE_LIMITS:
        raise BlastRadiusError("scope must match validated grounding scope")

    limits = SCOPE_LIMITS[scope]
    expansions = _list(payload.get("expansions"), label="expansions")
    base_context_paths = _context_paths(context_contract)
    grounding_expansions = {
        item["path"] for item in grounding.get("expansions", [])
    }
    normalized_expansions: list[dict[str, Any]] = []
    extra_paths: set[str] = set()
    extra_chars = 0
    for index, item in enumerate(expansions):
        if not isinstance(item, dict):
            raise BlastRadiusError(f"expansions[{index}] must be an object")
        path = _text(item.get("path"), label=f"expansions[{index}].path")
        reason = _text(item.get("reason"), label=f"expansions[{index}].reason")
        if (
            path in base_context_paths
            or path in grounding_expansions
            or path in extra_paths
        ):
            raise BlastRadiusError(f"duplicate/redundant expansion path: {path}")
        try:
            validated = validate_expansion(root, path, reason)
        except ContextContractError as exc:
            raise BlastRadiusError(str(exc)) from exc
        candidate = (root / validated["path"]).resolve()
        try:
            chars = len(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise BlastRadiusError(
                f"cannot measure expansion {validated['path']}: {exc}"
            ) from exc
        extra_paths.add(validated["path"])
        extra_chars += chars
        normalized_expansions.append(
            {
                "path": validated["path"],
                "reason": validated["reason"],
                "chars": chars,
            }
        )

    base_budget = grounding["contextBudget"]
    total_files = base_budget["expansionFiles"] + len(normalized_expansions)
    total_chars = base_budget["expansionChars"] + extra_chars
    if total_files > limits["maxExpansionFiles"]:
        raise BlastRadiusError(
            f"{scope} combined expansion file budget exceeded: "
            f"{total_files}>{limits['maxExpansionFiles']}"
        )
    if total_chars > limits["maxExpansionChars"]:
        raise BlastRadiusError(
            f"{scope} combined expansion char budget exceeded: "
            f"{total_chars}>{limits['maxExpansionChars']}"
        )

    allowed = (
        base_context_paths
        | set(grounding["evidencePaths"])
        | grounding_expansions
        | extra_paths
    )
    hypotheses_raw = _list(payload.get("hypotheses"), label="hypotheses")
    hypotheses: list[dict[str, Any]] = []
    critical_count = 0
    seen_ids: set[str] = set()
    verification_commands = set(
        (preflight.get("verification") or {}).get("commands") or []
    )

    for index, item in enumerate(hypotheses_raw, start=1):
        if not isinstance(item, dict):
            raise BlastRadiusError(f"hypotheses[{index}] must be an object")
        expected_id = f"H-{index:03d}"
        hypothesis_id = item.get("id")
        if hypothesis_id != expected_id or hypothesis_id in seen_ids:
            raise BlastRadiusError(
                f"hypotheses[{index}].id must be {expected_id}"
            )
        seen_ids.add(hypothesis_id)
        risk = _text(item.get("risk"), label=f"hypotheses[{index}].risk")
        behavior = _text(
            item.get("affectedBehavior"),
            label=f"hypotheses[{index}].affectedBehavior",
        )
        critical = item.get("critical")
        if not isinstance(critical, bool):
            raise BlastRadiusError(
                f"hypotheses[{index}].critical must be boolean"
            )
        if critical:
            critical_count += 1
        evidence = _validate_evidence_paths(
            item.get("evidencePaths"),
            label=f"hypotheses[{index}].evidencePaths",
            allowed=allowed,
        )
        proof = item.get("proof")
        if not isinstance(proof, dict):
            raise BlastRadiusError(f"hypotheses[{index}].proof must be an object")
        proof_status = proof.get("status")
        proof_kind = proof.get("kind")
        if proof_status not in PROOF_STATUSES:
            raise BlastRadiusError(
                f"hypotheses[{index}].proof.status must be one of "
                f"{sorted(PROOF_STATUSES)}"
            )
        if proof_kind not in PROOF_KINDS:
            raise BlastRadiusError(
                f"hypotheses[{index}].proof.kind must be one of "
                f"{sorted(PROOF_KINDS)}"
            )
        command = proof.get("command")
        if command is not None:
            command = _text(
                command,
                label=f"hypotheses[{index}].proof.command",
            )
        if proof_kind == "verification-command":
            if command is None:
                raise BlastRadiusError(
                    f"hypotheses[{index}] verification proof requires command"
                )
            if phase == "review" and command not in verification_commands:
                raise BlastRadiusError(
                    f"hypotheses[{index}] proof command is not in STEP Verification"
                )
        elif command is not None:
            raise BlastRadiusError(
                f"hypotheses[{index}] non-command proof cannot carry command"
            )
        hypotheses.append(
            {
                "id": hypothesis_id,
                "risk": risk,
                "affectedBehavior": behavior,
                "critical": critical,
                "evidencePaths": evidence,
                "proof": {
                    "status": proof_status,
                    "kind": proof_kind,
                    **({"command": command} if command is not None else {}),
                },
            }
        )

    if preflight["required"]:
        if not hypotheses:
            raise BlastRadiusError("required analysis must contain hypotheses")
        if critical_count < 1 or critical_count > 2:
            raise BlastRadiusError(
                "required analysis must contain 1-2 critical hypotheses"
            )

    observations: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(payload.get("provenObservations"), label="provenObservations"),
        start=1,
    ):
        if not isinstance(item, dict):
            raise BlastRadiusError(
                f"provenObservations[{index}] must be an object"
            )
        observations.append(
            {
                "claim": _text(
                    item.get("claim"),
                    label=f"provenObservations[{index}].claim",
                ),
                "evidencePaths": _validate_evidence_paths(
                    item.get("evidencePaths"),
                    label=f"provenObservations[{index}].evidencePaths",
                    allowed=allowed,
                ),
            }
        )

    surfaces: list[dict[str, str]] = []
    for index, item in enumerate(
        _list(payload.get("testSurfaces"), label="testSurfaces"),
        start=1,
    ):
        if not isinstance(item, dict):
            raise BlastRadiusError(f"testSurfaces[{index}] must be an object")
        surfaces.append(
            {
                "behavior": _text(
                    item.get("behavior"),
                    label=f"testSurfaces[{index}].behavior",
                ),
                "verification": _text(
                    item.get("verification"),
                    label=f"testSurfaces[{index}].verification",
                ),
            }
        )

    critical = [item for item in hypotheses if item["critical"]]
    critical_proof_evidence: list[dict[str, Any]] = []
    if status == "PASS" and preflight["required"]:
        for item in critical:
            proof = item["proof"]
            if (
                proof["status"] != "proven"
                or proof["kind"] != "verification-command"
            ):
                raise BlastRadiusError(
                    "PASS requires proven verification-command proof for "
                    f"{item['id']}"
                )
            if proof["command"] not in verification_commands:
                raise BlastRadiusError(
                    f"{item['id']} proof command is not in STEP Verification"
                )
            command_evidence = verification_command_evidence(
                root,
                step_id,
                proof["command"],
            )
            if (
                command_evidence.get("fresh") is not True
                or command_evidence.get("status") != "PASS"
            ):
                raise BlastRadiusError(
                    "PASS requires fresh PASS evidence for exact proof command "
                    f"{proof['command']!r}"
                )
            critical_proof_evidence.append(
                {
                    "hypothesisId": item["id"],
                    **command_evidence,
                }
            )

    if status == "INCONCLUSIVE" and preflight["required"]:
        unresolved = [
            item for item in critical
            if item["proof"]["status"] != "proven"
        ]
        if not unresolved:
            raise BlastRadiusError(
                "INCONCLUSIVE requires at least one unresolved critical proof"
            )
        if phase == "plan" and not surfaces:
            raise BlastRadiusError(
                "plan INCONCLUSIVE must expose at least one testSurface"
            )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "phase": phase,
        "scope": scope,
        "stepId": step_id,
        "repositoryRevision": revision,
        "deterministic": {
            "required": preflight["required"],
            "requiredReasons": preflight["requiredReasons"],
            "riskFlags": preflight["riskFlags"],
            "explicitImpact": preflight["explicitImpact"],
            "verification": preflight["verification"],
            "criticalProofEvidence": critical_proof_evidence,
        },
        "hypotheses": hypotheses,
        "provenObservations": observations,
        "testSurfaces": surfaces,
        "expansions": normalized_expansions,
        "contextBudget": {
            "groundingExpansionFiles": base_budget["expansionFiles"],
            "groundingExpansionChars": base_budget["expansionChars"],
            "blastExpansionFiles": len(normalized_expansions),
            "blastExpansionChars": extra_chars,
            "totalExpansionFiles": total_files,
            "totalExpansionChars": total_chars,
            "maxExpansionFiles": limits["maxExpansionFiles"],
            "maxExpansionChars": limits["maxExpansionChars"],
        },
    }


__all__ = [
    "BlastRadiusError",
    "blast_radius_preflight",
    "validate_blast_radius_payload",
]
