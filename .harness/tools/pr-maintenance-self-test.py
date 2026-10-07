#!/usr/bin/env python3
"""Synthetic contract tests for PR maintenance semantic workflows (#226)."""
from __future__ import annotations

from copy import deepcopy

from pr_maintenance import PRMaintenanceError, _basis, validate_semantic


def fixture() -> dict:
    value = {
        "schemaVersion": 1,
        "capturedAt": "2026-10-07T00:00:00Z",
        "provider": {"name": "github", "host": "github.com", "repository": "owner/repo"},
        "pr": {
            "number": 42,
            "url": "https://github.com/owner/repo/pull/42",
            "state": "OPEN",
            "headRefName": "feature/x",
            "headRefOid": "abc",
            "baseRefName": "main",
            "isDraft": False,
            "title": "feat: x",
            "mergedAt": None,
        },
        "checks": [
            {"factId": "check:101", "providerId": 101, "kind": "check-run", "name": "unit", "status": "COMPLETED", "conclusion": "FAILURE", "url": "https://example/check/101"},
            {"factId": "check:102", "providerId": 102, "kind": "check-run", "name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS", "url": "https://example/check/102"},
            {"factId": "check:103", "providerId": 103, "kind": "check-run", "name": "integration", "status": "COMPLETED", "conclusion": "FAILURE", "url": "https://example/check/103"},
        ],
        "comments": [
            {"factId": "comment:201", "providerId": 201, "url": "https://example/comment/201", "author": "reviewer", "body": "Handle empty input.", "createdAt": "2026-10-07T00:00:00Z", "updatedAt": "2026-10-07T00:00:00Z"}
        ],
        "reviews": [
            {"factId": "review:301", "providerId": 301, "url": "https://example/review/301", "author": "reviewer", "state": "CHANGES_REQUESTED", "body": "Please add regression coverage.", "submittedAt": "2026-10-07T00:00:00Z"}
        ],
        "files": [
            {"path": "src/a.ts", "status": "modified", "additions": 4, "deletions": 1, "changes": 5},
            {"path": "generated/api.ts", "status": "modified", "additions": 100, "deletions": 100, "changes": 200},
        ],
    }
    value["snapshotBasis"] = _basis(value)
    return value


def expect_blocked(callable_, fragment: str) -> None:
    try:
        callable_()
    except PRMaintenanceError as exc:
        assert fragment in str(exc), str(exc)
        return
    raise AssertionError(f"expected blocker containing {fragment!r}")


def base_payload(snapshot: dict, mode: str) -> dict:
    return {
        "schemaVersion": 1,
        "mode": mode,
        "snapshotBasis": snapshot["snapshotBasis"],
        "refreshCount": 0,
        "items": [],
        "reviewerGuidance": None,
        "nextAction": "none",
        "rationale": "No mutation is implied by this semantic result.",
    }


def main() -> int:
    snapshot = fixture()

    ci = base_payload(snapshot, "ci-triage")
    ci["items"] = [{
        "factId": "check:101",
        "disposition": "fix",
        "summary": "Unit test fails on empty input.",
        "action": "Inspect the first failing assertion and prepare a focused code fix.",
    }]
    ci["nextAction"] = "fix"
    result = validate_semantic(snapshot, ci)
    assert result["status"] == "PASS"
    assert result["items"][0]["providerId"] == 101
    assert result["autoMergeAllowed"] is False
    assert result["historyRewriteAllowed"] is False

    successful = deepcopy(ci)
    successful["items"][0]["factId"] = "check:102"
    expect_blocked(lambda: validate_semantic(snapshot, successful), "successful check")

    two_roots = deepcopy(ci)
    two_roots["items"].append({
        "factId": "check:103",
        "disposition": "fix",
        "summary": "Integration check also failed.",
        "action": "Fix it too.",
    })
    expect_blocked(lambda: validate_semantic(snapshot, two_roots), "at most one first actionable")

    feedback = base_payload(snapshot, "feedback")
    feedback["items"] = [
        {"factId": "comment:201", "disposition": "fix", "summary": "Empty input behavior is incomplete.", "action": "Add guarded handling and regression coverage."},
        {"factId": "review:301", "disposition": "clarify", "summary": "Reviewer asks for additional regression coverage.", "action": "Confirm which observed regression path needs coverage."},
    ]
    feedback["nextAction"] = "fix"
    result = validate_semantic(snapshot, feedback)
    assert [item["providerId"] for item in result["items"]] == [201, 301]

    duplicate = deepcopy(feedback)
    duplicate["items"][1]["factId"] = "comment:201"
    expect_blocked(lambda: validate_semantic(snapshot, duplicate), "duplicate semantic fact reference")

    reviewability = base_payload(snapshot, "reviewability")
    reviewability["reviewerGuidance"] = {
        "summary": "Core behavior is in src/a.ts; generated API diff is mechanical.",
        "risks": ["Empty-input behavior changed."],
        "verification": ["unit check must pass"],
        "generatedOrMechanicalPaths": ["generated/api.ts"],
    }
    result = validate_semantic(snapshot, reviewability)
    assert result["reviewerGuidance"]["generatedOrMechanicalPaths"] == ["generated/api.ts"]

    bad_path = deepcopy(reviewability)
    bad_path["reviewerGuidance"]["generatedOrMechanicalPaths"] = ["not-in-diff.ts"]
    expect_blocked(lambda: validate_semantic(snapshot, bad_path), "outside PR diff")

    stale = deepcopy(feedback)
    stale["snapshotBasis"] = "sha256:stale"
    expect_blocked(lambda: validate_semantic(snapshot, stale), "PR_SNAPSHOT_STALE")

    babysit = base_payload(snapshot, "babysit")
    babysit["refreshCount"] = 4
    expect_blocked(lambda: validate_semantic(snapshot, babysit), "refreshCount must be 0..3")

    first = validate_semantic(snapshot, feedback)
    second = validate_semantic(snapshot, feedback)
    assert first == second

    print("pr maintenance self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
