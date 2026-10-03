#!/usr/bin/env python3
"""Synthetic policy tests adaptive FIX↔REVIEW stopping."""
from __future__ import annotations

import sys

from repair_cycle import compare_snapshots


def finding(fp: str, severity: str) -> dict[str, str]:
    return {"fingerprint": fp, "severity": severity}


def snap(
    *findings: dict[str, str],
    revision: str,
    basis: str = "basis-a",
    verification: str = "verify-a",
    verification_status: str | None = "PASS",
) -> dict[str, object]:
    return {
        "report": revision + ".md",
        "contractBasis": basis,
        "verificationBasis": verification,
        "verificationStatus": verification_status,
        "reviewedRevision": {"git_head": revision, "worktree_hash": None},
        "findings": list(findings),
    }


def main() -> int:
    # Progress: one finding disappears and severity falls.
    progress = compare_snapshots(
        snap(finding("a", "high"), finding("b", "medium"), revision="1" * 40),
        snap(finding("b", "medium"), revision="2" * 40),
        cycle=1,
    )
    assert progress["stopDecision"] == "continue", progress
    assert progress["resolved"] == 1
    assert progress["verificationChanged"] is False

    verification_delta = compare_snapshots(
        snap(finding("a", "high"), revision="1" * 40, verification="verify-a"),
        snap(finding("b", "medium"), revision="2" * 40, verification="verify-b"),
        cycle=1,
    )
    assert verification_delta["verificationChanged"] is True, verification_delta

    # Verification status regression has priority over otherwise positive finding delta.
    verification_regression = compare_snapshots(
        snap(
            finding("a", "high"),
            revision="1" * 40,
            verification="verify-a",
            verification_status="PASS",
        ),
        snap(
            finding("b", "medium"),
            revision="2" * 40,
            verification="verify-b",
            verification_status="FAIL",
        ),
        cycle=1,
    )
    assert verification_regression["reasonCode"] == "REGRESSION", verification_regression
    assert verification_regression["verificationRegressed"] is True

    # Historical reports without persisted status remain comparable fail-safe.
    legacy_verification = compare_snapshots(
        snap(
            finding("a", "high"),
            revision="1" * 40,
            verification_status=None,
        ),
        snap(
            finding("b", "medium"),
            revision="2" * 40,
            verification="verify-b",
            verification_status="PASS",
        ),
        cycle=1,
    )
    assert legacy_verification["verificationRegressed"] is None, legacy_verification
    assert legacy_verification["stopDecision"] == "continue", legacy_verification

    # Same findings after a real revision change: repeated repair.
    repeated = compare_snapshots(
        snap(finding("a", "high"), revision="1" * 40),
        snap(finding("a", "high"), revision="2" * 40),
        cycle=1,
    )
    assert repeated["reasonCode"] == "REPEATED_FINDINGS", repeated

    # No revision and no resolved finding: no progress.
    no_progress = compare_snapshots(
        snap(finding("a", "medium"), revision="1" * 40),
        snap(finding("a", "medium"), revision="1" * 40),
        cycle=1,
    )
    assert no_progress["reasonCode"] == "NO_PROGRESS", no_progress

    # New higher-severity defect under unchanged contract: regression.
    regression = compare_snapshots(
        snap(finding("a", "medium"), revision="1" * 40),
        snap(
            finding("a", "medium"),
            finding("c", "critical"),
            revision="2" * 40,
        ),
        cycle=1,
    )
    assert regression["reasonCode"] == "REGRESSION", regression

    # Scope/contract change suppresses automatic regression classification.
    scope_change = compare_snapshots(
        snap(finding("a", "medium"), revision="1" * 40, basis="basis-a"),
        snap(
            finding("a", "medium"),
            finding("c", "critical"),
            revision="2" * 40,
            basis="basis-b",
        ),
        cycle=1,
    )
    assert scope_change["stopDecision"] == "continue", scope_change
    assert scope_change["scopeComparable"] is False

    print("repair-cycle-self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
