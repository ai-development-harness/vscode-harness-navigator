#!/usr/bin/env python3
"""Synthetic regressions for Semantic Blast Radius."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from review_contract import repository_revision
from semantic_blast_radius import (
    BlastRadiusError,
    blast_radius_preflight,
    validate_blast_radius_payload,
)
from verification import run_step_verification


MANIFEST = """sources:
  openQuestions: docs/open-questions
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
execution:
  verificationCommandTimeoutSeconds: 30
"""

STEP = """---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: high
phase: P1
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - public-api
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — High impact

## Goal

Change public behavior.

## Context

Synthetic blast-radius fixture.

## Scope

- API behavior.

## Mutation policy

### Allowed

- src.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- unrelated.

## Acceptance criteria

- API remains compatible.

## Verification

- command: `python3 verify.py`
- manual: Confirm semantic condition

## Deliverables

- implementation.

## Implementation plan

TBD.

## Evidence

—

## Blocker / Failure reason

—
"""

DEPENDENT = STEP.replace("STEP-001", "STEP-002").replace(
    "depends_on: []",
    "depends_on:\n  - STEP-001",
).replace(
    "risk_flags:\n  - public-api",
    "risk_flags:\n  - none",
).replace(
    "Change public behavior.",
    "Consume public behavior.",
)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")


def init_repo(root: Path) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "blast@example.invalid")
    git(root, "config", "user.name", "Blast Radius Test")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")


def context(root: Path) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "repositoryRevision": repository_revision(root),
        "required": [
            {
                "artifact": "STEP-001",
                "path": "planning/tasks/STEP-001.md",
                "sections": ["Goal", "Scope", "Verification"],
            }
        ],
        "metrics": {
            "artifactCount": 1,
            "sectionCount": 3,
            "manifestChars": 120,
            "fullRepositoryPreload": False,
        },
    }


def grounding(root: Path) -> dict[str, object]:
    revision = repository_revision(root)
    claim = {
        "claim": "STEP owns the public API behavior.",
        "evidence": ["planning/tasks/STEP-001.md"],
    }
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "scope": "simple",
        "target": "public API behavior",
        "repositoryRevision": revision,
        "flow": [claim],
        "ownership": [claim],
        "boundaries": [claim],
        "interfaces": [claim],
        "invariants": [],
        "gotchas": [],
        "unknowns": [],
        "evidencePaths": ["planning/tasks/STEP-001.md"],
        "expansions": [],
    }


def plan_payload(root: Path) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "INCONCLUSIVE",
        "phase": "plan",
        "scope": "simple",
        "stepId": "STEP-001",
        "repositoryRevision": repository_revision(root),
        "hypotheses": [
            {
                "id": "H-001",
                "risk": "Dependent consumer may rely on existing API behavior.",
                "affectedBehavior": "STEP-002 remains compatible with STEP-001.",
                "critical": True,
                "evidencePaths": ["planning/tasks/STEP-001.md"],
                "proof": {
                    "status": "planned",
                    "kind": "verification-command",
                    "command": "python3 verify.py",
                },
            }
        ],
        "provenObservations": [
            {
                "claim": "The changed contract is public API behavior.",
                "evidencePaths": ["planning/tasks/STEP-001.md"],
            }
        ],
        "testSurfaces": [
            {
                "behavior": "Existing consumer remains compatible.",
                "verification": "python3 verify.py",
            }
        ],
        "expansions": [],
    }


def review_payload(root: Path) -> dict[str, object]:
    value = plan_payload(root)
    value["status"] = "PASS"
    value["phase"] = "review"
    value["repositoryRevision"] = repository_revision(root)
    hypotheses = value["hypotheses"]
    assert isinstance(hypotheses, list)
    hypotheses[0]["proof"] = {
        "status": "proven",
        "kind": "verification-command",
        "command": "python3 verify.py",
    }
    return value


def expect_blocked(root: Path, ctx: dict, grd: dict, payload: dict, phase: str) -> None:
    try:
        validate_blast_radius_payload(
            root,
            "STEP-001",
            phase,
            ctx,
            grd,
            payload,
        )
    except BlastRadiusError:
        return
    raise AssertionError("blast-radius payload must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="blast-radius-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        write(root, "planning/tasks/STEP-001.md", STEP)
        write(root, "planning/tasks/STEP-002.md", DEPENDENT)
        write(root, "verify.py", "raise SystemExit(0)\n")
        init_repo(root)

        preflight = blast_radius_preflight(root, "STEP-001", "plan")
        assert preflight["required"] is True, preflight
        assert preflight["riskFlags"] == ["public-api"], preflight
        assert [item["step"] for item in preflight["explicitImpact"]["affected"]] == [
            "STEP-002"
        ], preflight

        low_risk = blast_radius_preflight(root, "STEP-002", "plan")
        assert low_risk["required"] is False, low_risk

        ctx = context(root)
        grd = grounding(root)
        planned = validate_blast_radius_payload(
            root,
            "STEP-001",
            "plan",
            ctx,
            grd,
            plan_payload(root),
        )
        assert planned["status"] == "INCONCLUSIVE", planned
        assert planned["deterministic"]["required"] is True
        assert planned["contextBudget"]["totalExpansionFiles"] == 0

        false_pass = plan_payload(root)
        false_pass["status"] = "PASS"
        expect_blocked(root, ctx, grd, false_pass, "plan")

        # Review PASS requires executable evidence generated by the canonical
        # Verification runner for the current subject revision.
        review_before_evidence = review_payload(root)
        expect_blocked(root, ctx, grd, review_before_evidence, "review")

        result = run_step_verification(root, "STEP-001")
        assert result["status"] == "MANUAL_REQUIRED", result
        assert result["commands"][0]["status"] == "PASS", result
        assert result["manualPending"] == ["Confirm semantic condition"], result

        ctx_after = context(root)
        grd_after = grounding(root)
        reviewed = validate_blast_radius_payload(
            root,
            "STEP-001",
            "review",
            ctx_after,
            grd_after,
            review_payload(root),
        )
        assert reviewed["status"] == "PASS", reviewed
        assert reviewed["deterministic"]["verification"]["freshness"]["fresh"] is False
        proof_evidence = reviewed["deterministic"]["criticalProofEvidence"]
        assert proof_evidence[0]["status"] == "PASS", proof_evidence
        assert proof_evidence[0]["fresh"] is True, proof_evidence

        wrong_command = review_payload(root)
        wrong_command["hypotheses"][0]["proof"]["command"] = "python3 other.py"
        expect_blocked(root, ctx_after, grd_after, wrong_command, "review")

        # Any product/config mutation makes generated Verification evidence
        # stale, so the same semantic self-report can no longer produce PASS.
        write(root, "src/change.py", "value = 1\n")
        stale_ctx = context(root)
        stale_grd = grounding(root)
        stale_payload = review_payload(root)
        expect_blocked(root, stale_ctx, stale_grd, stale_payload, "review")

    print("semantic-blast-radius self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
