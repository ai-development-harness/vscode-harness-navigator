#!/usr/bin/env python3
"""Contract regressions Completion / Convergence Gate."""
from __future__ import annotations
from pathlib import Path
import tempfile

from completion_gate import (
    CompletionGateError,
    deterministic_precheck,
    normalize_semantic_completion,
)

CRITERIA = ["User can save the record.", "Failed save preserves input."]


def assertions(*, planned: str = "covered", specialized: str = "not_applicable"):
    return {
        "requirementObligations": {
            "status": "covered",
            "evidence": ["REQ acceptance mapped to STEP criteria."],
        },
        "plannedScope": {
            "status": planned,
            "evidence": ["Ready plan actions inspected."],
        },
        "specializedObligations": {
            "status": specialized,
            "evidence": ["No additional specialized obligation is applicable."],
        },
    }


def main() -> int:
    complete = normalize_semantic_completion({
        "disposition": "pass",
        "coverage": [
            {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
            {"criterion": CRITERIA[1], "status": "covered", "evidence": ["test_failed_save PASS"]},
        ],
        "assertions": assertions(),
        "findings": [],
        "rationale": "All in-scope obligations are proven.",
    }, CRITERIA)
    assert complete["disposition"] == "pass"

    fix = normalize_semantic_completion({
        "disposition": "fix",
        "coverage": [
            {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
            {"criterion": CRITERIA[1], "status": "missing", "evidence": []},
        ],
        "assertions": assertions(),
        "findings": [{
            "kind": "missing_acceptance_coverage",
            "criterion": CRITERIA[1],
            "message": "Error path is not implemented.",
        }],
        "rationale": "Missing behavior is inside approved STEP scope.",
    }, CRITERIA)
    assert fix["findings"][0]["id"] == "COMP-001"
    assert fix["findings"][0]["route"] == "FIX"

    blocked = normalize_semantic_completion({
        "disposition": "blocked",
        "coverage": [
            {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
            {"criterion": CRITERIA[1], "status": "missing", "evidence": []},
        ],
        "assertions": assertions(planned="missing"),
        "findings": [{
            "kind": "contract_gap",
            "criterion": CRITERIA[1],
            "message": "Acceptance requires a missing architecture decision.",
        }],
        "rationale": "Current contract cannot be completed inside scope.",
    }, CRITERIA)
    assert blocked["findings"][0]["route"] == "BLOCKED"

    try:
        normalize_semantic_completion({
            "disposition": "fix",
            "coverage": [
                {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
                {"criterion": CRITERIA[1], "status": "missing", "evidence": []},
            ],
            "assertions": assertions(),
            "findings": [{
                "kind": "contract_gap",
                "criterion": CRITERIA[1],
                "message": "Architecture decision is missing.",
            }],
            "rationale": "invalid route",
        }, CRITERIA)
    except CompletionGateError as exc:
        assert "contract gaps must BLOCK" in str(exc)
    else:
        raise AssertionError("contract gap was accepted into FIX route")

    try:
        normalize_semantic_completion({
            "disposition": "fix",
            "coverage": [
                {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
                {"criterion": CRITERIA[1], "status": "missing", "evidence": []},
            ],
            "assertions": assertions(),
            "findings": [],
            "rationale": "missing structured finding",
        }, CRITERIA)
    except CompletionGateError as exc:
        assert "structured findings" in str(exc)
    else:
        raise AssertionError("completion gap without structured finding was accepted")

    try:
        normalize_semantic_completion({
            "disposition": "blocked",
            "coverage": [
                {"criterion": CRITERIA[0], "status": "covered", "evidence": ["test_save PASS"]},
                {"criterion": CRITERIA[1], "status": "missing", "evidence": []},
            ],
            "assertions": assertions(),
            "findings": [{
                "kind": "evidence_gap",
                "criterion": CRITERIA[1],
                "message": "Only implementation evidence is missing.",
            }],
            "rationale": "invalid blocker",
        }, CRITERIA)
    except CompletionGateError as exc:
        assert "requires a contract_gap" in str(exc)
    else:
        raise AssertionError("evidence-only semantic gap was accepted as BLOCKED")

    try:
        normalize_semantic_completion({
            "disposition": "pass",
            "coverage": [{
                "criterion": "Out of scope obligation",
                "status": "covered",
                "evidence": ["x"],
            }],
            "assertions": assertions(),
            "findings": [],
            "rationale": "invalid",
        }, CRITERIA)
    except CompletionGateError as exc:
        assert "out-of-scope" in str(exc)
    else:
        raise AssertionError("out-of-scope completion obligation was accepted")

    # Deterministic stale-evidence fixture: same real Acceptance parser, injected
    # factual provider; real verification_freshness is covered by verification-self-test.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".harness").mkdir()
        (root / ".harness/manifest.yaml").write_text(
            "protocol:\n  taskDirectory: planning/tasks\n",
            encoding="utf-8",
        )
        task = root / "planning/tasks/STEP-001.md"
        task.parent.mkdir(parents=True)
        task.write_text("""---
schema: 1
id: STEP-001
status: in_progress
type: implementation
priority: medium
phase: P1
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---
# STEP-001 — Fixture
## Goal
G.
## Context
C.
## Scope
- s
## Mutation policy
### Allowed
- x
### Conditional
- none
### Forbidden
- y
## Out of scope
- z
## Acceptance criteria
- User can save the record.
## Verification
- manual: check
## Deliverables
- x
## Implementation plan
- x
## Evidence
—
## Blocker / Failure reason
—
""", encoding="utf-8")
        stale = deterministic_precheck(
            root,
            "STEP-001",
            freshness_provider=lambda _root, _step: {
                "status": "PASS",
                "fresh": False,
                "reasonCode": "VERIFICATION_SUBJECT_STALE",
            },
            prerequisite_provider=lambda _root, _step: [],
        )
        assert stale["status"] == "BLOCKED"
        assert stale["findings"][0]["code"] == "VERIFICATION_SUBJECT_STALE"

        dependency_blocked = deterministic_precheck(
            root,
            "STEP-001",
            freshness_provider=lambda _root, _step: {
                "status": "PASS",
                "fresh": True,
                "reasonCode": None,
            },
            prerequisite_provider=lambda _root, _step: [
                "dependency-incomplete:STEP-000:completion proof missing"
            ],
        )
        assert dependency_blocked["status"] == "BLOCKED", dependency_blocked
        assert (
            dependency_blocked["findings"][0]["message"]
            == "dependency-incomplete:STEP-000:completion proof missing"
        ), dependency_blocked

    print("completion-gate self-test: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
