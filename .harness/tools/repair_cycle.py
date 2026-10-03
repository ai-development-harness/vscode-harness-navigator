#!/usr/bin/env python3
"""Deterministic comparison of consecutive Review Contract v2 reports.

Module does not own CTS transitions or execution persistence. It converts two
immutable REVIEW artifacts into bounded repair-cycle telemetry and a conservative
continue/stop recommendation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from document_contract import parse_document
from review_findings import FINDING_CONTRACT_VERSION, parse_machine_findings

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
VERIFICATION_RANK = {"BLOCKED": 0, "FAIL": 1, "MANUAL_REQUIRED": 2, "PASS": 3}
STOP_REASONS = {"NO_PROGRESS", "REPEATED_FINDINGS", "REGRESSION"}


class RepairCycleError(ValueError):
    """Review pair cannot be compared deterministically."""


def _snapshot(root: Path, report: str, *, expected_step_id: str) -> dict[str, Any]:
    path = (root / report).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise RepairCycleError("review report escapes repository") from exc
    if not path.is_file() or path.is_symlink():
        raise RepairCycleError(f"review report is not a regular file: {report}")
    document = parse_document(path)
    meta = document["frontmatter"]
    if meta.get("kind") != "step_review":
        raise RepairCycleError(f"{report}: kind must be step_review")
    if meta.get("step_id") != expected_step_id:
        raise RepairCycleError(f"{report}: step_id mismatch")
    if meta.get("finding_contract") != FINDING_CONTRACT_VERSION:
        raise RepairCycleError(f"{report}: Review Contract v2 is required")
    findings = parse_machine_findings(document)
    return {
        "report": report,
        "verdict": meta.get("verdict"),
        "contractBasis": meta.get("contract_basis"),
        "verificationBasis": meta.get("verification_basis"),
        "verificationStatus": meta.get("verification_status"),
        "reviewedRevision": meta.get("reviewed_revision"),
        "findings": findings,
    }


def _highest(findings: list[dict[str, Any]]) -> str | None:
    if not findings:
        return None
    return max(findings, key=lambda item: SEVERITY_RANK[str(item["severity"])])["severity"]


def _rank(value: str | None) -> int:
    return SEVERITY_RANK.get(str(value), 0)


def compare_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    cycle: int,
) -> dict[str, Any]:
    """Return bounded telemetry and conservative deterministic stop decision."""
    if cycle < 1:
        raise RepairCycleError("adaptive comparison requires cycle >= 1")

    before_findings = list(before.get("findings") or [])
    after_findings = list(after.get("findings") or [])
    before_by_fp = {str(item["fingerprint"]): item for item in before_findings}
    after_by_fp = {str(item["fingerprint"]): item for item in after_findings}

    before_fps = set(before_by_fp)
    after_fps = set(after_by_fp)
    resolved = sorted(before_fps - after_fps)
    persisted = sorted(before_fps & after_fps)
    introduced = sorted(after_fps - before_fps)

    highest_before = _highest(before_findings)
    highest_after = _highest(after_findings)
    contract_before = before.get("contractBasis")
    contract_after = after.get("contractBasis")
    scope_comparable = (
        isinstance(contract_before, str)
        and bool(contract_before)
        and contract_before == contract_after
    )
    revision_changed = before.get("reviewedRevision") != after.get("reviewedRevision")
    verification_before = before.get("verificationBasis")
    verification_after = after.get("verificationBasis")
    verification_changed = (
        verification_before != verification_after
        if isinstance(verification_before, str) and isinstance(verification_after, str)
        else None
    )
    verification_status_before = before.get("verificationStatus")
    verification_status_after = after.get("verificationStatus")
    verification_regressed = (
        VERIFICATION_RANK[verification_status_after]
        < VERIFICATION_RANK[verification_status_before]
        if verification_status_before in VERIFICATION_RANK
        and verification_status_after in VERIFICATION_RANK
        else None
    )

    stop: str | None = None
    message = "repair cycle made deterministic progress or scope is not comparable"

    # Scope change is an explicit guardrail: new findings after REQ/ADR/STEP
    # contract drift are not classified as a regression of the repair itself.
    if scope_comparable:
        if verification_regressed is True:
            stop = "REGRESSION"
            message = (
                "deterministic verification status became worse while contract scope stayed unchanged"
            )
        elif before_fps == after_fps:
            if revision_changed:
                stop = "REPEATED_FINDINGS"
                message = "FIX changed repository revision, but the same material findings remain"
            else:
                stop = "NO_PROGRESS"
                message = "FIX produced no repository revision delta and did not resolve findings"
        elif introduced and _rank(highest_after) > _rank(highest_before):
            stop = "REGRESSION"
            message = "FIX introduced a higher-severity finding while contract scope stayed unchanged"
        elif not resolved and _rank(highest_after) >= _rank(highest_before):
            stop = "NO_PROGRESS"
            message = "FIX resolved no findings and did not reduce highest material severity"

    return {
        "cycle": cycle,
        "beforeReport": before.get("report"),
        "afterReport": after.get("report"),
        "findingsBefore": len(before_findings),
        "findingsAfter": len(after_findings),
        "resolved": len(resolved),
        "persisted": len(persisted),
        "introduced": len(introduced),
        "highestSeverityBefore": highest_before,
        "highestSeverityAfter": highest_after,
        "repositoryRevisionChanged": revision_changed,
        "contractBasisChanged": contract_before != contract_after,
        "scopeComparable": scope_comparable,
        "verificationChanged": verification_changed,
        "verificationStatusBefore": verification_status_before,
        "verificationStatusAfter": verification_status_after,
        "verificationRegressed": verification_regressed,
        "stopDecision": stop or "continue",
        "reasonCode": stop,
        "message": message,
    }


def compare_review_reports(
    root: Path,
    step_id: str,
    before_report: str,
    after_report: str,
    *,
    cycle: int,
) -> dict[str, Any]:
    before = _snapshot(root, before_report, expected_step_id=step_id)
    after = _snapshot(root, after_report, expected_step_id=step_id)
    return compare_snapshots(before, after, cycle=cycle)


__all__ = [
    "RepairCycleError",
    "SEVERITY_RANK",
    "STOP_REASONS",
    "compare_review_reports",
    "compare_snapshots",
]
