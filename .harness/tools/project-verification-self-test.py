#!/usr/bin/env python3
"""Synthetic regression suite for Project Verification Driver (#218)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from verification import run_step_verification, verification_freshness

from project_verification import (
    DRIVER_SKILL_PATH,
    FEATURE_MAP_PATH,
    ProjectVerificationError,
    qualify_driver,
    source_basis,
    validate_feature_map,
    validate_product_observations,
)


MANIFEST = """execution:
  verificationCommandTimeoutSeconds: 300
sources:
  requirements: docs/requirements
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""

REQ = """---
schema: 1
id: REQ-001
priority: medium
source: self-test
steps:
  - STEP-001
adrs: []
---

# REQ-001 — Product verification

## Requirement

The user can inspect status.

## Rationale

Real-product proof is required.

## Acceptance

- User sees the current status through the primary interface.
"""

STEP = """---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: P1
depends_on: []
requirements:
  - REQ-001
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

Verify product behavior.

## Context

Fixture.

## Scope

- status surface

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

- User sees the current status through the primary interface.

## Verification

- product: FEATURE-STATUS

## Deliverables

- fixture

## Implementation plan

1. Verify.

## Evidence

—

## Blocker / Failure reason

—
"""

DRIVER = """---
name: verify-product
description: Drive the fixture CLI exactly as a user does.
---

# verify-product

## Launch

Build the fixture with the repository command and start each CLI invocation separately.

## Doctor

Run the read-only version/status probe before driving the feature.

## Drive

Invoke the public CLI entry point described by the feature map.

## Evidence

Capture command, stdout, stderr and exit code under .harness/local/product-verification/.

## Cleanup

Remove only scratch state created by this verification run; keep evidence files.
"""


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def feature_map(root: Path, *, criterion: str | None = None) -> dict:
    basis = source_basis(root, ["src/status.py"])
    return {
        "schemaVersion": 1,
        "driver": {
            "skillPath": DRIVER_SKILL_PATH,
            "primarySurface": "cli",
            "additionalSurfaces": ["api"],
            "qualification": None,
        },
        "features": [
            {
                "id": "FEATURE-STATUS",
                "title": "Inspect status",
                "surface": "cli",
                "requirements": ["REQ-001"],
                "acceptance": [
                    {
                        "artifact": "REQ-001",
                        "criterion": criterion
                        or "User sees the current status through the primary interface.",
                    },
                    {
                        "artifact": "STEP-001",
                        "criterion": "User sees the current status through the primary interface.",
                    },
                ],
                "sourcePaths": ["src/status.py"],
                "sourceBasis": basis,
                "entryPoints": ["Run app status from the public CLI."],
                "drive": ["Invoke the status command through the public binary."],
                "observe": ["Exit 0 and stdout contains the current status."],
            }
        ],
    }


def expect_blocked(callable_, fragment: str) -> None:
    try:
        callable_()
    except ProjectVerificationError as exc:
        assert fragment in str(exc), str(exc)
        return
    raise AssertionError(f"expected ProjectVerificationError containing {fragment!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="project-verification-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        write(root, "docs/requirements/REQ-001-status.md", REQ)
        write(root, "planning/tasks/STEP-001.md", STEP)
        write(root, "src/status.py", 'STATUS = "ok"\n')
        write(root, DRIVER_SKILL_PATH, DRIVER)
        fmap = feature_map(root)
        write(root, FEATURE_MAP_PATH, json.dumps(fmap, ensure_ascii=False, indent=2) + "\n")
        write(root, ".gitignore", ".harness/local/\n")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "verify@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Verification Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

        unqualified = validate_feature_map(root, require_qualified=False)
        assert unqualified["status"] == "BLOCKED", unqualified
        assert unqualified["driver"]["qualificationState"] == "UNQUALIFIED"

        expect_blocked(
            lambda: validate_feature_map(root, require_qualified=True),
            "not qualified",
        )

        proof_path = ".harness/local/product-verification/qualification.txt"
        write(root, proof_path, "status command returned ok\n")
        qualified = qualify_driver(
            root,
            {
                "featureId": "FEATURE-STATUS",
                "observed": "Public CLI returned status=ok.",
                "evidencePaths": [proof_path],
            },
        )
        assert qualified["status"] == "PASS", qualified
        current = validate_feature_map(root)
        assert current["status"] == "PASS", current
        assert current["driver"]["primarySurface"] == "cli"
        assert current["features"][0]["surface"] == "cli"

        # STEP Verification treats product proof as an explicit semantic boundary.
        pending_run = run_step_verification(
            root,
            "STEP-001",
            write_evidence=False,
        )
        assert pending_run["status"] == "MANUAL_REQUIRED", pending_run
        assert pending_run["productPending"] == ["FEATURE-STATUS"], pending_run

        # No supplied proof means semantic handoff, not an invented PASS.
        observed, pending = validate_product_observations(
            root,
            ["FEATURE-STATUS"],
            None,
        )
        assert observed == []
        assert pending == ["FEATURE-STATUS"]

        live_proof = ".harness/local/product-verification/status.txt"
        write(root, live_proof, "command=app status\nstdout=status=ok\nexit=0\n")
        observed, pending = validate_product_observations(
            root,
            ["FEATURE-STATUS"],
            [
                {
                    "featureId": "FEATURE-STATUS",
                    "status": "PASS",
                    "observed": "app status exited 0 and printed status=ok.",
                    "evidencePaths": [live_proof],
                }
            ],
        )
        assert pending == []
        assert observed[0]["status"] == "PASS"
        assert observed[0]["evidence"][0]["sha256"].startswith("sha256:")

        verified = run_step_verification(
            root,
            "STEP-001",
            product_results=[
                {
                    "featureId": "FEATURE-STATUS",
                    "status": "PASS",
                    "observed": "app status exited 0 and printed status=ok.",
                    "evidencePaths": [live_proof],
                }
            ],
        )
        assert verified["status"] == "PASS", verified
        freshness = verification_freshness(root, "STEP-001")
        assert freshness["status"] == "PASS" and freshness["fresh"] is True, freshness

        write(root, "outside-proof.txt", "not local proof\n")
        expect_blocked(
            lambda: validate_product_observations(
                root,
                ["FEATURE-STATUS"],
                [
                    {
                        "featureId": "FEATURE-STATUS",
                        "status": "PASS",
                        "observed": "fake",
                        "evidencePaths": ["outside-proof.txt"],
                    }
                ],
            ),
            "must stay under .harness/local/product-verification",
        )

        # Product source drift invalidates the map before another proof is accepted.
        write(root, "src/status.py", 'STATUS = "changed"\n')
        expect_blocked(
            lambda: validate_feature_map(root),
            "feature map is stale",
        )

        # Restore source, then changing the driver invalidates its qualification.
        write(root, "src/status.py", 'STATUS = "ok"\n')
        write(root, DRIVER_SKILL_PATH, DRIVER + "\nDriver changed.\n")
        expect_blocked(
            lambda: validate_feature_map(root),
            "not qualified",
        )
        write(root, DRIVER_SKILL_PATH, DRIVER)
        assert validate_feature_map(root)["status"] == "PASS"

        # Exact REQ/STEP acceptance references are validated, not merely named.
        bad = feature_map(root, criterion="Invented acceptance criterion.")
        write(root, FEATURE_MAP_PATH, json.dumps(bad, ensure_ascii=False, indent=2) + "\n")
        expect_blocked(
            lambda: validate_feature_map(root, require_qualified=False),
            "is not an exact bullet",
        )

    print("project-verification self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
