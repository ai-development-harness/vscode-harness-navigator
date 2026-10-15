#!/usr/bin/env python3
"""Focused regression: an obsolete IMPLEMENT must not replay completed work."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from execution_status import _completed_step_recovery


def command(value: str) -> dict:
    pieces = value.split()
    return {
        "domain": pieces[0],
        "operation": pieces[1],
        "target": pieces[2] if len(pieces) == 3 else None,
    }


def execution(root_command: str, *, mode: str = "chain") -> dict:
    sequence = root_command.split(" > ")
    return {
        "rootCommand": root_command,
        "mode": mode,
        "sequence": sequence,
        "current": {
            "command": "STEP IMPLEMENT STEP-033",
            "status": "running",
        },
    }


def evaluate(*, completed: bool, evidence: bool, review: bool, competing: bool = False,
             report_content_hash: str | None = "sha256:identical-product",
             legacy_revision_current: bool = False,
             sequence: str = "STEP PLAN STEP-033 > STEP IMPLEMENT STEP-033 > STEP REVIEW STEP-033") -> dict | None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with (
            patch("execution_status.normalize_single_command", side_effect=lambda _root, value: command(value)),
            patch("execution_status.read_planning_task", return_value={
                "frontmatter": {"status": "completed" if completed else "in_progress"},
            }),
            patch("execution_status.step_completion_proof", return_value={
                "complete": evidence, "reasons": [] if evidence else ["invalid evidence"],
                "proof_hash": "sha256:valid",
            }),
            patch("execution_status.latest_review", side_effect=lambda _root, _step, *,
                  require_current_revision=False: (
                    None if require_current_revision and not legacy_revision_current
                    else ({
                        "path": "planning/reviews/STEP-033/REVIEW-pass.md",
                        "verdict": "PASS", "completionResult": "PASS",
                        "reviewedContentHash": report_content_hash,
                    } if review else {"path": "bad", "verdict": "FAIL", "completionResult": "FAIL"})
                  )),
            patch("execution_status.load_status", return_value={
                "executions": ([{"executionId": "other", "status": "running",
                    "current": {"command": "STEP REVIEW STEP-033", "status": "running"}}]
                    if competing else []),
            }),
            patch("verification.verification_freshness", return_value={
                "status": "PASS" if evidence else "STALE",
                "fresh": evidence, "reasonCode": None if evidence else "VERIFICATION_SUBJECT_STALE",
                "subjectContentHash": "sha256:identical-product",
            }),
        ):
            return _completed_step_recovery(root, execution(sequence))


def main() -> int:
    assert evaluate(completed=False, evidence=False, review=False) is None
    result = evaluate(completed=True, evidence=True, review=True)
    assert result is not None and result["kind"] == "reconciled", result
    assert result["stepId"] == "STEP-033", result

    # Старый Git HEAD не является основанием отвергнуть совпадающие bytes.
    # Но последний independent REVIEW тоже должен быть привязан к тем же bytes.
    report_stale = evaluate(
        completed=True, evidence=True, review=True,
        report_content_hash="sha256:older-product",
    )
    assert report_stale is not None and report_stale["kind"] == "blocked", report_stale
    legacy_missing = evaluate(
        completed=True, evidence=True, review=True, report_content_hash=None,
    )
    assert legacy_missing is not None and legacy_missing["kind"] == "blocked", legacy_missing
    legacy_exact = evaluate(
        completed=True, evidence=True, review=True, report_content_hash=None,
        legacy_revision_current=True,
    )
    assert legacy_exact is not None and legacy_exact["kind"] == "reconciled", legacy_exact

    for evidence, review in ((False, True), (True, False), (False, False)):
        result = evaluate(completed=True, evidence=evidence, review=review)
        assert result is not None and result["kind"] == "blocked", result
        assert result["blocker"]["reasonCode"] == "COMPLETED_STEP_RECOVERY_CONFLICT"

    conflict = evaluate(completed=True, evidence=True, review=True, competing=True)
    assert conflict is not None and conflict["kind"] == "blocked", conflict
    assert conflict["blocker"]["details"]["competingExecutions"] == ["other"]

    # A completed STEP never proves unrelated Git publication or another STEP.
    for sequence in (
        "STEP IMPLEMENT STEP-033 > GIT PUSH",
        "STEP IMPLEMENT STEP-033 > STEP REVIEW STEP-034",
    ):
        result = evaluate(completed=True, evidence=True, review=True, sequence=sequence)
        assert result is not None and result["kind"] == "blocked", result

    print("completed-step-recovery-self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
