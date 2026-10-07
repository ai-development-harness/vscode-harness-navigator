#!/usr/bin/env python3
"""Synthetic regressions for Recurring Correction → Structural Enforcement."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from review_findings import normalize_findings, render_machine_findings
from structural_enforcement import (
    StructuralEnforcementError,
    build_preflight,
    validate_proposal,
)


MANIFEST = """protocol:
  reviewDirectory: planning/reviews
"""

STEP = """---
schema: 1
id: STEP-001
status: planned
type: bugfix
priority: medium
phase: P1
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
---

# STEP-001 — Fixture

## Goal

Fixture.

## Context

Fixture.

## Scope

- fixture

## Mutation policy

### Allowed

- src

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- unrelated

## Acceptance criteria

- works

## Verification

- manual: fixture

## Deliverables

- fixture

## Implementation plan

1. Fixture.

## Evidence

—

## Blocker / Failure reason

—
"""


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr}"
        )
    return proc.stdout.strip()


def init_repo(root: Path) -> None:
    write(root, ".harness/manifest.yaml", MANIFEST)
    write(root, "planning/tasks/STEP-001.md", STEP)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "enforcement@example.invalid")
    git(root, "config", "user.name", "Enforcement Test")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")


def finding() -> dict[str, object]:
    return {
        "title": "Direct mutable state write bypasses owner",
        "severity": "high",
        "category": "implementation",
        "location": {"path": "src/state.py", "line": 10},
        "scenario": {
            "given": "state has a single owner",
            "when": "caller writes storage directly",
            "then": "the supported owner API must be used",
        },
        "expected": "Caller uses StateStore.update().",
        "observed": "Caller writes state.json directly.",
        "impact": "Concurrent writers can corrupt state.",
        "repair": {
            "direction": "Route writes through StateStore.",
            "admissibleAlternatives": [],
        },
        "constraints": ["Keep one canonical owner."],
        "evidence": ["src/state.py:10 direct state.json write reproduced in fixture"],
        "evidenceBasis": {
            "kind": "reproduced",
            "source": "Synthetic direct-write regression fixture.",
            "preconditions": [],
            "verification": {
                "method": "Inspect the fixture call path and execute the owner-bypass reproducer.",
                "result": "Caller writes state.json directly instead of using StateStore.update().",
                "outcome": "confirmed",
            },
        },
    }


def review(
    root: Path,
    *,
    name: str,
    revision: str,
    include_finding: bool = True,
    finding_contract: int = 3,
) -> None:
    findings = normalize_findings([finding()]) if include_finding else []
    machine = render_machine_findings(findings)
    body = f"""---
schema: 1
kind: step_review
finding_contract: {finding_contract}
step_id: STEP-001
verdict: fail
reviewer_role: reviewer
created_at: 2026-10-06T10:00:00Z
reviewed_revision:
  git_head: {revision}
  worktree_hash: null
---

# STEP REVIEW STEP-001 — fixture

## Findings

fixture

## Machine-readable findings

```json
{machine}
```
"""
    write(root, f"planning/reviews/STEP-001/{name}", body)


def proposal(
    class_key: str,
    evidence_ids: list[str],
    *,
    kind: str = "validator-lint",
) -> dict[str, object]:
    rejected_map = {
        "architecture-ownership": [],
        "schema-type": [
            {
                "kind": "architecture-ownership",
                "reason": "Ownership is already correct; the defect is an invalid call shape.",
            }
        ],
        "validator-lint": [
            {
                "kind": "architecture-ownership",
                "reason": "Ownership is already correct and does not need redesign.",
            },
            {
                "kind": "schema-type",
                "reason": "The language boundary cannot make this file-path write unrepresentable.",
            },
        ],
        "regression-test": [
            {
                "kind": "architecture-ownership",
                "reason": "No architecture change is needed.",
            },
            {
                "kind": "schema-type",
                "reason": "Type system cannot express the cross-file rule.",
            },
            {
                "kind": "validator-lint",
                "reason": "No reliable static predicate exists.",
            },
        ],
        "durable-instruction": [
            {
                "kind": "architecture-ownership",
                "reason": "No ownership change is applicable.",
            },
            {
                "kind": "schema-type",
                "reason": "Judgement cannot be represented as a type.",
            },
            {
                "kind": "validator-lint",
                "reason": "Judgement has no reliable deterministic predicate.",
            },
            {
                "kind": "regression-test",
                "reason": "The decision concerns trade-off reasoning rather than behavior.",
            },
        ],
    }
    mechanism: dict[str, object] = {
        "kind": kind,
        "rationale": "Prevent the same class before review instead of adding more prose.",
        "higherLevelsRejected": rejected_map[kind],
    }
    if kind == "architecture-ownership":
        mechanism["decisionRoute"] = "architecture-change"

    proof = None
    if kind != "durable-instruction":
        proof = {
            "fixture": "tests/regressions/direct-state-write.txt",
            "command": ["python3", "tools/check-state-ownership.py"],
            "oldMistakeExpectedFailure": "The old direct-write fixture must fail with actionable ownership guidance.",
            "correctedStateExpectedPass": "The corrected owner-mediated example must pass.",
        }

    return {
        "schemaVersion": 1,
        "status": "PASS",
        "classKey": class_key,
        "recurringErrorClass": "Direct writes bypass the canonical state owner.",
        "mechanism": mechanism,
        "candidateScope": ["src", "tests/regressions"],
        "proof": proof,
        "evidenceIds": evidence_ids,
        "gaps": [],
    }


def expect_rejected(callable_) -> None:
    try:
        callable_()
    except StructuralEnforcementError:
        return
    raise AssertionError("invalid structural enforcement input must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="structural-enforcement-") as tmp:
        root = Path(tmp)
        init_repo(root)

        fp = normalize_findings([finding()])[0]["fingerprint"]

        # Same finding on one revision reported twice counts as one factual
        # occurrence. A new reviewed revision makes it recurring.
        review(root, name="REVIEW-20261006T100000Z.md", revision="a" * 40)
        review(root, name="REVIEW-20261006T100100Z.md", revision="a" * 40)

        one = build_preflight(root, step_id="STEP-001")
        classes = one["classes"]
        assert len(classes) == 1, classes
        current = classes[0]
        assert current["reviewFingerprints"] == [fp]
        assert current["occurrenceCount"] == 1, current
        assert current["recurring"] is False

        one_events = [
            item["evidenceId"]
            for item in one["evidence"]
            if item["classKey"] == current["classKey"]
        ]
        single_payload = proposal(current["classKey"], [one_events[0]])
        expect_rejected(
            lambda: validate_proposal(root, one, single_payload)
        )

        explicit = validate_proposal(
            root,
            one,
            single_payload,
            explicit_single=True,
        )
        assert explicit["class"]["explicitSingleOverride"] is True

        review(root, name="REVIEW-20261006T100200Z.md", revision="b" * 40)
        recurring = build_preflight(root, step_id="STEP-001")
        current = recurring["classes"][0]
        assert current["occurrenceCount"] == 2, current
        assert current["recurring"] is True

        # Reference one evidence item from each distinct occurrence.
        by_occurrence: dict[str, str] = {}
        for event in recurring["evidence"]:
            if event["classKey"] == current["classKey"]:
                by_occurrence.setdefault(
                    str(event["occurrenceId"]),
                    str(event["evidenceId"]),
                )
        payload = proposal(
            current["classKey"],
            list(by_occurrence.values()),
        )
        validated = validate_proposal(root, recurring, payload)
        assert validated["status"] == "PASS"
        assert validated["regressionFixtureRequired"] is True
        assert validated["automaticMutationAllowed"] is False

        # Implemented deterministic rule cannot claim completion without the
        # actual regression fixture in the repository.
        expect_rejected(
            lambda: validate_proposal(
                root,
                recurring,
                payload,
                require_existing_fixture=True,
            )
        )
        write(
            root,
            "tests/regressions/direct-state-write.txt",
            "direct write reproducer\n",
        )
        implemented = validate_proposal(
            root,
            recurring,
            payload,
            require_existing_fixture=True,
        )
        assert implemented["implementedFixtureVerified"] is True

        # Strongest feasible mechanism must justify every stronger level.
        broken_ladder = json.loads(json.dumps(payload))
        broken_ladder["mechanism"]["higherLevelsRejected"] = []
        expect_rejected(
            lambda: validate_proposal(root, recurring, broken_ladder)
        )

        # Architecture proposal requires an explicit architecture route and still
        # never grants mutation authority.
        arch = proposal(
            current["classKey"],
            list(by_occurrence.values()),
            kind="architecture-ownership",
        )
        arch_result = validate_proposal(root, recurring, arch)
        assert arch_result["architectureDecisionRequired"] is True
        assert arch_result["automaticMutationAllowed"] is False
        bad_arch = json.loads(json.dumps(arch))
        bad_arch["mechanism"].pop("decisionRoute")
        expect_rejected(
            lambda: validate_proposal(root, recurring, bad_arch)
        )

        # Durable instruction is last-resort judgement and must not fake a
        # deterministic regression proof.
        instruction = proposal(
            current["classKey"],
            list(by_occurrence.values()),
            kind="durable-instruction",
        )
        instruction_result = validate_proposal(root, recurring, instruction)
        assert instruction_result["regressionFixtureRequired"] is False

        # Structured validator failures can form their own recurring class.
        supplied = {
            "schemaVersion": 1,
            "events": [
                {
                    "sourceKind": "validator_failure",
                    "classKey": "validation:missing-owner-check",
                    "occurrenceId": "ci:100",
                    "category": "validation",
                    "evidenceRef": "ci/run/100",
                    "observedAt": "2026-10-06T10:00:00Z",
                    "signal": "owner check failed",
                },
                {
                    "sourceKind": "validator_failure",
                    "classKey": "validation:missing-owner-check",
                    "occurrenceId": "ci:101",
                    "category": "validation",
                    "evidenceRef": "ci/run/101",
                    "observedAt": "2026-10-06T11:00:00Z",
                    "signal": "owner check failed",
                },
                {
                    "sourceKind": "repair_stop",
                    "classKey": "validation:missing-owner-check",
                    "occurrenceId": "repair:101",
                    "category": "validation",
                    "evidenceRef": ".harness/local/execution/execution-status.json",
                    "observedAt": "2026-10-06T11:05:00Z",
                    "signal": "REPEATED_FINDINGS",
                },
            ],
        }
        supplemental = build_preflight(
            root,
            step_id="STEP-001",
            supplied_evidence=supplied,
        )
        validation_class = next(
            item
            for item in supplemental["classes"]
            if item["classKey"] == "validation:missing-owner-check"
        )
        assert validation_class["occurrenceCount"] == 2, validation_class
        assert validation_class["sourceCounts"]["repair_stop"] == 1

        # Chat/transcript is not in the closed source-kind registry.
        bad_source = json.loads(json.dumps(supplied))
        bad_source["events"][0]["sourceKind"] = "transcript"
        expect_rejected(
            lambda: build_preflight(
                root,
                step_id="STEP-001",
                supplied_evidence=bad_source,
            )
        )

        # Legacy reviews are not semantically reconstructed from prose.
        review(
            root,
            name="REVIEW-20261006T100300Z.md",
            revision="c" * 40,
            finding_contract=1,
        )
        legacy = build_preflight(root, step_id="STEP-001")
        assert legacy["metrics"]["skippedLegacyReviews"] == 1

    print("structural-enforcement self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
