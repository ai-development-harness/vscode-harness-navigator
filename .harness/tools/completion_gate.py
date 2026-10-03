#!/usr/bin/env python3
"""Completion / Convergence Gate for STEP closure."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Callable

from document_contract import atomic_write_text, render_document
from planning_contract import (
    implementation_prerequisite_failures,
    read_task,
    step_completion_proof,
    task_path,
)
from projection_contract import ProjectionDerivationError, write_projections
from verification import verification_freshness

ASSERTION_KEYS = (
    "requirementObligations",
    "plannedScope",
    "specializedObligations",
)
FINDING_KINDS = {
    "missing_acceptance_coverage",
    "missing_requirement_obligation",
    "missing_planned_scope",
    "missing_specialized_obligation",
    "contract_gap",
    "evidence_gap",
}


class CompletionGateError(ValueError):
    """Completion payload violates deterministic/semantic transport contract."""


def acceptance_criteria(root: Path, step_id: str) -> list[str]:
    task = read_task(root, step_id)
    text = task["sections"].get("Acceptance criteria", "")
    result: list[str] = []
    for raw in text.splitlines():
        match = re.match(r"^\s*[-*]\s+(.+?)\s*$", raw)
        if match:
            value = match.group(1).strip()
            if value:
                result.append(value)
    return result


def deterministic_precheck(
    root: Path,
    step_id: str,
    *,
    freshness_provider: Callable[[Path, str], dict[str, Any]] = verification_freshness,
    prerequisite_provider: Callable[[Path, str], list[str]] = implementation_prerequisite_failures,
) -> dict[str, Any]:
    criteria = acceptance_criteria(root, step_id)
    freshness = freshness_provider(root, step_id)
    findings: list[dict[str, str]] = []
    if not criteria:
        findings.append({
            "code": "ACCEPTANCE_MISSING",
            "kind": "contract",
            "message": "STEP has no machine-discoverable Acceptance criteria",
        })
    if freshness.get("status") != "PASS" or freshness.get("fresh") is not True:
        findings.append({
            "code": str(freshness.get("reasonCode") or "VERIFICATION_NOT_PASS"),
            "kind": "evidence",
            "message": "Generated Verification evidence is missing, stale or not PASS.",
        })
    for reason in prerequisite_provider(root, step_id):
        findings.append({
            "code": "CURRENT_CONTRACT_NOT_EXECUTABLE",
            "kind": "contract",
            "message": reason,
        })
    return {
        "schemaVersion": 1,
        "status": "PASS" if not findings else "BLOCKED",
        "stepId": step_id,
        "acceptanceCriteria": criteria,
        "verificationFreshness": freshness,
        "findings": findings,
    }


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CompletionGateError(f"{label} must be a non-empty string")
    return value.strip()


def _assertion(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompletionGateError(f"{label} must be an object")
    unexpected = sorted(set(value) - {"status", "evidence"})
    if unexpected:
        raise CompletionGateError(f"{label} has unsupported keys: {', '.join(unexpected)}")
    status = value.get("status")
    if status not in {"covered", "missing", "not_applicable"}:
        raise CompletionGateError(f"{label}.status must be covered|missing|not_applicable")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        raise CompletionGateError(f"{label}.evidence must be string array")
    if status in {"covered", "not_applicable"} and not evidence:
        raise CompletionGateError(f"{label} {status} requires evidence/rationale")
    return {"status": status, "evidence": [item.strip() for item in evidence]}


def normalize_semantic_completion(payload: Any, criteria: list[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CompletionGateError("completion must be an object")
    unexpected = sorted(
        set(payload) - {"disposition", "coverage", "assertions", "findings", "rationale"}
    )
    if unexpected:
        raise CompletionGateError("completion has unsupported keys: " + ", ".join(unexpected))

    disposition = payload.get("disposition")
    if disposition not in {"pass", "fix", "blocked"}:
        raise CompletionGateError("completion.disposition must be pass|fix|blocked")

    coverage = payload.get("coverage")
    if not isinstance(coverage, list):
        raise CompletionGateError("completion.coverage must be an array")
    normalized_coverage: list[dict[str, Any]] = []
    observed: set[str] = set()
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            raise CompletionGateError(f"coverage[{index}] must be an object")
        if set(item) - {"criterion", "status", "evidence"}:
            raise CompletionGateError(f"coverage[{index}] has unsupported keys")
        criterion = _text(item.get("criterion"), f"coverage[{index}].criterion")
        if criterion not in criteria:
            raise CompletionGateError(
                f"coverage[{index}] references out-of-scope criterion"
            )
        if criterion in observed:
            raise CompletionGateError(f"duplicate coverage criterion: {criterion}")
        observed.add(criterion)
        status = item.get("status")
        if status not in {"covered", "missing"}:
            raise CompletionGateError(
                f"coverage[{index}].status must be covered|missing"
            )
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or any(
            not isinstance(value, str) or not value.strip() for value in evidence
        ):
            raise CompletionGateError(
                f"coverage[{index}].evidence must be string array"
            )
        if status == "covered" and not evidence:
            raise CompletionGateError(
                f"covered criterion requires evidence: {criterion}"
            )
        normalized_coverage.append({
            "criterion": criterion,
            "status": status,
            "evidence": [value.strip() for value in evidence],
        })

    missing_criteria = [item for item in criteria if item not in observed]
    missing_coverage = [
        item["criterion"]
        for item in normalized_coverage
        if item["status"] == "missing"
    ]

    assertions_value = payload.get("assertions")
    if not isinstance(assertions_value, dict):
        raise CompletionGateError("completion.assertions must be an object")
    if set(assertions_value) != set(ASSERTION_KEYS):
        raise CompletionGateError(
            "completion.assertions must contain exactly: " + ", ".join(ASSERTION_KEYS)
        )
    assertions = {
        key: _assertion(assertions_value[key], f"completion.assertions.{key}")
        for key in ASSERTION_KEYS
    }

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise CompletionGateError("completion.findings must be an array")
    route = "FIX" if disposition == "fix" else "BLOCKED" if disposition == "blocked" else None
    findings: list[dict[str, Any]] = []
    for index, value in enumerate(raw_findings, 1):
        if not isinstance(value, dict):
            raise CompletionGateError(f"completion.findings[{index - 1}] must be an object")
        unexpected_finding = sorted(set(value) - {"kind", "criterion", "message"})
        if unexpected_finding:
            raise CompletionGateError(
                f"completion.findings[{index - 1}] has unsupported keys"
            )
        kind = value.get("kind")
        if kind not in FINDING_KINDS:
            raise CompletionGateError(
                f"completion.findings[{index - 1}].kind is invalid"
            )
        criterion = value.get("criterion")
        if criterion is not None:
            if not isinstance(criterion, str) or criterion not in criteria:
                raise CompletionGateError(
                    f"completion.findings[{index - 1}].criterion must reference Acceptance"
                )
        if kind == "missing_acceptance_coverage" and criterion is None:
            raise CompletionGateError(
                "missing_acceptance_coverage finding requires criterion"
            )
        findings.append({
            "id": f"COMP-{index:03d}",
            "kind": kind,
            "criterion": criterion,
            "route": route,
            "message": _text(value.get("message"), f"completion.findings[{index - 1}].message"),
        })

    rationale = _text(payload.get("rationale"), "completion.rationale")
    assertion_missing = [
        key for key, value in assertions.items() if value["status"] == "missing"
    ]
    material_gap = bool(
        missing_criteria or missing_coverage or assertion_missing or findings
    )
    contract_findings = [
        item for item in findings if item["kind"] == "contract_gap"
    ]
    missing_without_finding = [
        criterion
        for criterion in missing_coverage
        if not any(item.get("criterion") == criterion for item in findings)
    ]

    if disposition == "pass":
        if material_gap:
            raise CompletionGateError(
                "completion PASS requires complete coverage/assertions and no findings"
            )
        if any(value["status"] == "missing" for value in assertions.values()):
            raise CompletionGateError("completion PASS cannot contain missing assertion")
    elif not material_gap:
        raise CompletionGateError(
            f"completion {disposition.upper()} requires a material gap"
        )
    else:
        if not findings:
            raise CompletionGateError(
                f"completion {disposition.upper()} requires structured findings"
            )
        if missing_without_finding:
            raise CompletionGateError(
                "missing Acceptance coverage requires a matching structured finding: "
                + ", ".join(missing_without_finding)
            )
        if disposition == "fix" and contract_findings:
            raise CompletionGateError(
                "completion FIX cannot contain contract_gap; contract gaps must BLOCK"
            )
        if disposition == "blocked" and not contract_findings:
            raise CompletionGateError(
                "completion BLOCKED requires a contract_gap finding"
            )

    return {
        "disposition": disposition,
        "coverage": normalized_coverage,
        "assertions": assertions,
        "missingCriteria": missing_criteria,
        "missingAssertions": assertion_missing,
        "findings": findings,
        "rationale": rationale,
    }


def evaluate_completion(root: Path, step_id: str, payload: Any | None) -> dict[str, Any]:
    precheck = deterministic_precheck(root, step_id)
    if precheck["status"] != "PASS":
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "completionResult": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "COMPLETION_PRECHECK_BLOCKED",
            "precheck": precheck,
            "findings": [
                {
                    "id": f"COMP-{index:03d}",
                    "kind": "evidence_gap" if item["kind"] == "evidence" else "contract_gap",
                    "criterion": None,
                    "route": "BLOCKED",
                    "message": item["message"],
                }
                for index, item in enumerate(precheck["findings"], 1)
            ],
        }
    if payload is None:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "completionResult": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "COMPLETION_PAYLOAD_MISSING",
            "precheck": precheck,
            "findings": [{
                "id": "COMP-001",
                "kind": "contract_gap",
                "criterion": None,
                "route": "BLOCKED",
                "message": "Semantic completion payload was not supplied.",
            }],
        }

    semantic = normalize_semantic_completion(payload, precheck["acceptanceCriteria"])
    disposition = semantic["disposition"]
    if disposition == "pass":
        status, result, reason = "PASS", "PASS", None
    elif disposition == "fix":
        status, result, reason = "INCOMPLETE", "FAIL", "COMPLETION_IN_SCOPE_WORK_MISSING"
    else:
        status, result, reason = "BLOCKED", "BLOCKED", "COMPLETION_CONTRACT_BLOCKED"
    return {
        "schemaVersion": 1,
        "status": status,
        "completionResult": result,
        "stepId": step_id,
        "reasonCode": reason,
        "precheck": precheck,
        "semantic": semantic,
        "findings": semantic["findings"],
    }


def finalize_step_completion(root: Path, step_id: str) -> dict[str, Any]:
    """Idempotently close STEP after durable REVIEW+completion PASS."""
    path = task_path(root, step_id)
    original = path.read_text(encoding="utf-8")
    task = read_task(root, step_id)
    previous_status = task["frontmatter"].get("status")
    changed_status = previous_status != "completed"
    if changed_status:
        meta = deepcopy(task["frontmatter"])
        meta["status"] = "completed"
        atomic_write_text(path, render_document(meta, task["body"]))

    try:
        proof = step_completion_proof(root, step_id)
    except (OSError, ValueError) as exc:
        if changed_status:
            atomic_write_text(path, original)
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROOF_ERROR",
            "message": str(exc),
        }

    if not proof["complete"]:
        if changed_status:
            atomic_write_text(path, original)
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROOF_INCOMPLETE",
            "proof": proof,
        }

    try:
        projections = write_projections(root)
    except (ProjectionDerivationError, OSError, ValueError) as exc:
        if changed_status:
            atomic_write_text(path, original)
            try:
                write_projections(root)
            except (ProjectionDerivationError, OSError, ValueError):
                pass
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROJECTION_FAILED",
            "message": str(exc),
            "proof": proof,
        }

    return {
        "completed": True,
        "previousStatus": previous_status,
        "proof": proof,
        "projections": projections,
    }
