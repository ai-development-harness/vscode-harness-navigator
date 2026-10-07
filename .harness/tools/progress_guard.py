#!/usr/bin/env python3
"""Bounded deterministic progress signal for long-running STEP executions.

This module is a guard, not a scheduler and not a second lifecycle machine.
It samples canonical repository facts, stores only compact fingerprints/metrics,
and classifies repeated states independently of model/chat history.

Review/FIX repair policy remains owned by repair_cycle.py / #153. Callers may
record those samples for diagnostics while suppressing generic stop decisions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from completion_gate import acceptance_criteria, deterministic_precheck
from document_contract import content_hash, stable_hash
from execution_groups import implementation_plan_step_count, normalize_execution_groups
from planning_contract import (
    plan_content_hash,
    planning_context_basis,
    read_task,
    step_completion_proof,
)
from review_contract import latest_review, repository_activity_fingerprint
from review_findings import (
    SUPPORTED_FINDING_CONTRACT_VERSIONS,
    FindingContractError,
    parse_machine_findings,
)
from verification import verification_freshness


PROGRESS_SCHEMA_VERSION = 1
PROGRESS_TELEMETRY_VERSION = 1
MAX_PROGRESS_SAMPLES = 8
STAGNATION_RESUME_LIMIT = 2
DRIFT_LIMIT = 2
SEMANTIC_STEP_OPERATIONS = {"PLAN", "IMPLEMENT", "REVIEW", "FIX"}

_VERIFICATION_RANK = {
    None: 0,
    "UNKNOWN": 0,
    "MISSING": 0,
    "BLOCKED": 0,
    "FAIL": 1,
    "MANUAL_REQUIRED": 2,
    "PASS": 3,
}
_STEP_STATUS_RANK = {
    None: 0,
    "planned": 0,
    "blocked": 0,
    "in_progress": 1,
    "completed": 3,
    "cancelled": 3,
    "deferred": 3,
}


class ProgressGuardError(ValueError):
    """Canonical progress state cannot be sampled safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _completion_findings(review: dict[str, Any] | None) -> list[str]:
    """Return stable completion-gap identities from validated latest review."""
    if not isinstance(review, dict):
        return []
    document = review.get("document")
    if not isinstance(document, dict):
        return []
    section = document.get("sections", {}).get("Completion convergence")
    if not isinstance(section, str) or not section.strip():
        return []
    text = section.strip()
    fence = chr(96) * 3
    start = fence + "json\n"
    end = "\n" + fence
    if not (text.startswith(start) and text.endswith(end)):
        return []
    raw = text[len(start) : -len(end)]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings, list):
        return []
    identities: list[str] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        identities.append(
            stable_hash(
                {
                    "kind": item.get("kind"),
                    "criterion": item.get("criterion"),
                    "route": item.get("route"),
                }
            )
        )
    return sorted(identities)


def _review_findings(review: dict[str, Any] | None) -> tuple[list[str], str | None]:
    """Prefer structured finding fingerprints; prose-only history gets one stable hash."""
    if not isinstance(review, dict):
        return [], None
    document = review.get("document")
    if not isinstance(document, dict):
        return [], None
    meta = document.get("frontmatter")
    if not isinstance(meta, dict):
        return [], None

    finding_contract = meta.get("finding_contract")
    if finding_contract in SUPPORTED_FINDING_CONTRACT_VERSIONS:
        try:
            findings = parse_machine_findings(
                document,
                expected_version=int(finding_contract),
            )
        except FindingContractError as exc:
            raise ProgressGuardError(str(exc)) from exc
        return (
            sorted(str(item["fingerprint"]) for item in findings),
            f"v{finding_contract}",
        )

    section = document.get("sections", {}).get("Findings")
    if isinstance(section, str) and section.strip() and section.strip() != "No material findings.":
        return [content_hash(section)], "legacy"
    return [], "legacy"


def _execution_groups(task: dict[str, Any]) -> list[dict[str, Any]]:
    meta = task["frontmatter"]
    plan = meta.get("plan")
    groups_value = plan.get("execution_groups") if isinstance(plan, dict) else None
    if groups_value in (None, [], {}):
        return []
    body = task["sections"].get("Implementation plan", "")
    return normalize_execution_groups(
        groups_value,
        implementation_plan_step_count(body),
    )


def _execution_groups_hash(groups: list[dict[str, Any]]) -> str | None:
    return stable_hash(groups) if groups else None


def _activity_scope(
    groups: list[dict[str, Any]],
    operation: str,
) -> set[str] | None:
    # PLAN/REVIEW are semantic/read-only phases: unrelated worktree movement
    # must never reset their stagnation counter.
    if operation in {"PLAN", "REVIEW"}:
        return set()
    # executionGroups provide the only strict machine-readable mutation
    # surface today. Without groups retain conservative whole-repository
    # fallback instead of guessing paths from prose Mutation policy.
    if not groups:
        return None
    return {
        str(path)
        for group in groups
        for path in group.get("mutationPaths", [])
        if isinstance(path, str) and path
    }


def _verification_state(
    root: Path,
    step_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        value = verification_freshness(root, step_id)
    except (OSError, UnicodeError, ValueError) as exc:
        value = {
            "status": "UNKNOWN",
            "fresh": False,
            "reasonCode": "VERIFICATION_UNAVAILABLE",
            "errorHash": content_hash(str(exc)),
        }
    summary = {
        "status": value.get("status"),
        "fresh": value.get("fresh"),
        "reasonCode": value.get("reasonCode"),
    }
    if "errorHash" in value:
        summary["errorHash"] = value["errorHash"]
    return summary, value


def _precheck_summary(
    root: Path,
    step_id: str,
    verification_value: dict[str, Any],
) -> dict[str, Any]:
    try:
        value = deterministic_precheck(
            root,
            step_id,
            freshness_provider=lambda _root, _step: verification_value,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "status": "BLOCKED",
            "findingKeys": [stable_hash({"unavailable": str(exc)})],
        }
    findings = value.get("findings")
    keys: list[str] = []
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict):
                keys.append(
                    stable_hash(
                        {
                            "code": item.get("code"),
                            "kind": item.get("kind"),
                            "message": item.get("message"),
                        }
                    )
                )
    return {
        "status": value.get("status"),
        "findingKeys": sorted(keys),
    }


def capture_progress(
    root: Path,
    step_id: str,
    command: str,
    operation: str,
) -> dict[str, Any]:
    """Capture bounded canonical progress state without transcript/model state."""
    if operation not in SEMANTIC_STEP_OPERATIONS:
        raise ProgressGuardError(f"unsupported semantic STEP operation: {operation}")

    task = read_task(root, step_id)
    meta = task["frontmatter"]
    plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
    groups = _execution_groups(task)
    activity_scope = _activity_scope(groups, operation)

    proof = step_completion_proof(root, step_id)
    review = latest_review(root, step_id)
    review_fingerprints, review_contract = _review_findings(review)
    completion_fingerprints = _completion_findings(review)
    verification, verification_value = _verification_state(root, step_id)
    precheck = _precheck_summary(root, step_id, verification_value)
    criteria = acceptance_criteria(root, step_id)
    context_basis = planning_context_basis(root, step_id)
    content_hash_value = plan_content_hash(root, step_id)

    material = {
        "stepStatus": meta.get("status"),
        "contextBasis": context_basis,
        "planContentHash": content_hash_value,
        "planRevision": plan.get("revision"),
        "executionGroupsHash": _execution_groups_hash(groups),
        "acceptanceHash": stable_hash(criteria),
        "evidenceHash": proof["snapshot"].get("evidence_hash"),
        "completionComplete": bool(proof.get("complete")),
        "completionProofHash": proof.get("proof_hash"),
        "completionReasons": sorted(str(item) for item in proof.get("reasons", [])),
        "verification": verification,
        "completionPrecheck": precheck,
        "reviewVerdict": review.get("verdict") if isinstance(review, dict) else None,
        "reviewCompletionResult": (
            review.get("completionResult") if isinstance(review, dict) else None
        ),
        "reviewFindingContract": review_contract,
        "reviewFindings": review_fingerprints,
        "completionFindings": completion_fingerprints,
    }
    activity_revision = repository_activity_fingerprint(
        root,
        included_paths=activity_scope,
    )
    activity = {
        "repositoryActivity": activity_revision,
        "scope": (
            sorted(activity_scope)
            if isinstance(activity_scope, set)
            else None
        ),
    }
    metrics = {
        "stepStatus": material["stepStatus"],
        "completionComplete": material["completionComplete"],
        "completionReasonCount": len(material["completionReasons"]),
        "completionPrecheckFindingCount": len(precheck["findingKeys"]),
        "reviewFindingCount": len(review_fingerprints),
        "completionFindingCount": len(completion_fingerprints),
        "verificationStatus": verification.get("status"),
        "evidenceHash": material["evidenceHash"],
        "executionGroupsHash": material["executionGroupsHash"],
    }
    material_fingerprint = stable_hash(material)
    activity_fingerprint = stable_hash(activity)
    return {
        "schemaVersion": PROGRESS_SCHEMA_VERSION,
        "stepId": step_id,
        "command": command,
        "operation": operation,
        "materialFingerprint": material_fingerprint,
        "activityFingerprint": activity_fingerprint,
        "fingerprint": stable_hash(
            {
                "material": material_fingerprint,
                "activity": activity_fingerprint,
            }
        ),
        "metrics": metrics,
        "capturedAt": _utc_now(),
    }


def _changed_metrics(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[str], list[str]]:
    left = before.get("metrics") if isinstance(before.get("metrics"), dict) else {}
    right = after.get("metrics") if isinstance(after.get("metrics"), dict) else {}
    names = sorted(set(left) | set(right))
    changed = [name for name in names if left.get(name) != right.get(name)]
    unchanged = [name for name in names if left.get(name) == right.get(name)]
    if before.get("activityFingerprint") != after.get("activityFingerprint"):
        changed.append("repositoryActivity")
    else:
        unchanged.append("repositoryActivity")
    return changed, unchanged


def compare_progress(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Classify factual delta; stop policy is applied by telemetry observers."""
    changed, unchanged = _changed_metrics(before, after)
    material_changed = before.get("materialFingerprint") != after.get("materialFingerprint")
    activity_changed = before.get("activityFingerprint") != after.get("activityFingerprint")

    left = before.get("metrics") if isinstance(before.get("metrics"), dict) else {}
    right = after.get("metrics") if isinstance(after.get("metrics"), dict) else {}
    improvements: list[str] = []
    regressions: list[str] = []

    if _STEP_STATUS_RANK.get(right.get("stepStatus"), 0) > _STEP_STATUS_RANK.get(left.get("stepStatus"), 0):
        improvements.append("stepStatus")
    if right.get("completionComplete") is True and left.get("completionComplete") is not True:
        improvements.append("completionComplete")
    if (
        isinstance(left.get("completionReasonCount"), int)
        and isinstance(right.get("completionReasonCount"), int)
        and right["completionReasonCount"] < left["completionReasonCount"]
    ):
        improvements.append("completionReasons")
    if (
        isinstance(left.get("completionPrecheckFindingCount"), int)
        and isinstance(right.get("completionPrecheckFindingCount"), int)
        and right["completionPrecheckFindingCount"] < left["completionPrecheckFindingCount"]
    ):
        improvements.append("completionPrecheck")
    if _VERIFICATION_RANK.get(right.get("verificationStatus"), 0) > _VERIFICATION_RANK.get(left.get("verificationStatus"), 0):
        improvements.append("verification")
    # Evidence text/hash change is material but directionless. It becomes
    # progress only through an independently improving verification/completion
    # fact; otherwise it must not mask regressions.

    if _STEP_STATUS_RANK.get(right.get("stepStatus"), 0) < _STEP_STATUS_RANK.get(left.get("stepStatus"), 0):
        regressions.append("stepStatus")
    if left.get("completionComplete") is True and right.get("completionComplete") is not True:
        regressions.append("completionComplete")
    if (
        isinstance(left.get("completionReasonCount"), int)
        and isinstance(right.get("completionReasonCount"), int)
        and right["completionReasonCount"] > left["completionReasonCount"]
    ):
        regressions.append("completionReasons")
    if (
        isinstance(left.get("completionPrecheckFindingCount"), int)
        and isinstance(right.get("completionPrecheckFindingCount"), int)
        and right["completionPrecheckFindingCount"] > left["completionPrecheckFindingCount"]
    ):
        regressions.append("completionPrecheck")
    left_verification = left.get("verificationStatus")
    right_verification = right.get("verificationStatus")
    if (
        left_verification in _VERIFICATION_RANK
        and right_verification in _VERIFICATION_RANK
        and _VERIFICATION_RANK[right_verification] < _VERIFICATION_RANK[left_verification]
    ):
        regressions.append("verification")

    left_review_findings = int(left.get("reviewFindingCount") or 0)
    right_review_findings = int(right.get("reviewFindingCount") or 0)
    if right_review_findings < left_review_findings:
        improvements.append("reviewFindings")
    elif right_review_findings > left_review_findings:
        regressions.append("reviewFindings")

    left_completion_findings = int(left.get("completionFindingCount") or 0)
    right_completion_findings = int(right.get("completionFindingCount") or 0)
    if right_completion_findings < left_completion_findings:
        improvements.append("completionFindings")
    elif right_completion_findings > left_completion_findings:
        regressions.append("completionFindings")

    if not material_changed and not activity_changed:
        classification = "NO_CHANGE"
    elif not material_changed and activity_changed:
        classification = "ACTIVITY_ONLY"
    elif regressions and not improvements:
        classification = "WORSENED"
    else:
        classification = "PROGRESS"

    return {
        "classification": classification,
        "materialChanged": material_changed,
        "activityChanged": activity_changed,
        "changed": sorted(set(changed)),
        "unchanged": sorted(set(unchanged)),
        "improvements": sorted(set(improvements)),
        "regressions": sorted(set(regressions)),
    }


def new_telemetry(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": PROGRESS_TELEMETRY_VERSION,
        "samples": [deepcopy(sample)],
        "unchangedResumes": 0,
        "driftStreak": 0,
        "lastDelta": None,
        "stopDecision": "continue",
    }


def _samples(value: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    samples = value.get("samples")
    if not isinstance(samples, list):
        return []
    return [item for item in samples if isinstance(item, dict)]


def _append_sample(telemetry: dict[str, Any], sample: dict[str, Any]) -> None:
    samples = _samples(telemetry)
    samples.append(deepcopy(sample))
    telemetry["samples"] = samples[-MAX_PROGRESS_SAMPLES:]


def _cycle_blocker(
    telemetry: dict[str, Any],
    sample: dict[str, Any],
) -> dict[str, Any] | None:
    samples = _samples(telemetry)
    if len(samples) < 2:
        return None
    for index in range(len(samples) - 2, -1, -1):
        prior = samples[index]
        # Normal phase transitions may legitimately observe the same project
        # state (for example IMPLEMENT -> REVIEW immediately after completion).
        # A cycle requires returning to the same semantic node after other work.
        if (
            prior.get("command") != sample.get("command")
            or prior.get("fingerprint") != sample.get("fingerprint")
        ):
            continue
        between = samples[index + 1 :]
        operations = {
            str(item.get("operation") or "")
            for item in [prior, *between, sample]
        }
        if operations and operations <= {"FIX", "REVIEW"}:
            return None
        if not between:
            continue
        return {
            "reasonCode": "EXECUTION_CYCLE",
            "message": "execution returned to an equivalent authoritative progress state",
            "stepId": sample.get("stepId"),
            "command": sample.get("command"),
            "cycleFromSample": index,
            "cycleLength": len(samples) - index,
            "operations": sorted(operations),
            "remediation": f"STEP PLAN {sample.get('stepId')}",
        }
    return None


def observe_transition(
    telemetry: dict[str, Any] | None,
    sample: dict[str, Any],
    *,
    suppress_stop: bool = False,
) -> dict[str, Any]:
    """Record a new semantic node and detect exact bounded cycles."""
    current = deepcopy(telemetry) if isinstance(telemetry, dict) else new_telemetry(sample)
    if not isinstance(telemetry, dict):
        return {"telemetry": current, "blocker": None, "delta": None}

    blocker = None if suppress_stop else _cycle_blocker(current, sample)
    before = _samples(current)[-1] if _samples(current) else None
    delta = compare_progress(before, sample) if isinstance(before, dict) else None
    _append_sample(current, sample)
    current["unchangedResumes"] = 0
    current["driftStreak"] = 0
    current["lastDelta"] = delta
    current["stopDecision"] = blocker["reasonCode"] if blocker else "continue"
    return {"telemetry": current, "blocker": blocker, "delta": delta}


def observe_resume(
    telemetry: dict[str, Any] | None,
    sample: dict[str, Any],
    *,
    suppress_stop: bool = False,
) -> dict[str, Any]:
    """Compare one actual resume attempt with the last observed canonical state."""
    current = deepcopy(telemetry) if isinstance(telemetry, dict) else new_telemetry(sample)
    samples = _samples(current)
    if not samples:
        _append_sample(current, sample)
        return {"telemetry": current, "blocker": None, "delta": None}

    before = samples[-1]
    delta = compare_progress(before, sample)
    blocker: dict[str, Any] | None = None

    if delta["classification"] == "NO_CHANGE":
        current["unchangedResumes"] = int(current.get("unchangedResumes", 0)) + 1
        current["driftStreak"] = 0
        if (
            not suppress_stop
            and current["unchangedResumes"] >= STAGNATION_RESUME_LIMIT
        ):
            blocker = {
                "reasonCode": "EXECUTION_STAGNATION",
                "message": "repeated semantic resume made no material or repository progress",
                "stepId": sample.get("stepId"),
                "command": sample.get("command"),
                "unchangedAttempts": current["unchangedResumes"],
                "changed": delta["changed"],
                "unchanged": delta["unchanged"],
                "remediation": f"STEP PLAN {sample.get('stepId')}",
            }
    elif delta["classification"] == "WORSENED":
        current["unchangedResumes"] = 0
        current["driftStreak"] = int(current.get("driftStreak", 0)) + 1
        if not suppress_stop and current["driftStreak"] >= DRIFT_LIMIT:
            blocker = {
                "reasonCode": "EXECUTION_DRIFT",
                "message": "canonical completion/progress facts worsened across repeated semantic resumes",
                "stepId": sample.get("stepId"),
                "command": sample.get("command"),
                "driftStreak": current["driftStreak"],
                "changed": delta["changed"],
                "improvements": delta["improvements"],
                "regressions": delta["regressions"],
                "remediation": f"STEP PLAN {sample.get('stepId')}",
            }
    else:
        current["unchangedResumes"] = 0
        current["driftStreak"] = 0

    _append_sample(current, sample)
    current["lastDelta"] = delta
    current["stopDecision"] = blocker["reasonCode"] if blocker else "continue"
    return {"telemetry": current, "blocker": blocker, "delta": delta}


__all__ = [
    "DRIFT_LIMIT",
    "MAX_PROGRESS_SAMPLES",
    "PROGRESS_SCHEMA_VERSION",
    "PROGRESS_TELEMETRY_VERSION",
    "ProgressGuardError",
    "STAGNATION_RESUME_LIMIT",
    "capture_progress",
    "compare_progress",
    "new_telemetry",
    "observe_resume",
    "observe_transition",
]
