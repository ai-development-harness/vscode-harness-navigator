#!/usr/bin/env python3
"""Synthetic regressions for role-specific Context Contracts."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

from context_contracts import (
    ContextContractError,
    build_context_contract,
    validate_expansion,
)


MANIFEST = """sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  principles: docs/principles
protocol:
  taskDirectory: planning/tasks
"""

STEP = """---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: P1
depends_on:
  - STEP-000
requirements:
  - REQ-001
adrs:
  - ADR-001
architecture_refs:
  - docs/architecture.md#api
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

# STEP-001 — Test

## Goal

Goal.

## Context

Context.

## Scope

- work

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

- manual: check

## Deliverables

- code

## Implementation plan

Plan.

## Evidence

Evidence.

## Blocker / Failure reason

—
"""

DEP = STEP.replace("STEP-001", "STEP-000").replace(
    "depends_on:\n  - STEP-000", "depends_on: []"
).replace(
    "requirements:\n  - REQ-001", "requirements: []"
).replace(
    "adrs:\n  - ADR-001", "adrs: []"
).replace(
    "architecture_refs:\n  - docs/architecture.md#api", "architecture_refs: []"
)

REQ = """---
schema: 1
id: REQ-001
priority: high
source: brief
steps:
  - STEP-001
adrs:
  - ADR-001
---

# REQ-001 — R

## Requirement

Behavior.

## Rationale

Reason.

## Acceptance

- observable
"""

UNRELATED_REQ = REQ.replace("REQ-001", "REQ-999").replace(
    "  - STEP-001", "[]"
).replace(
    "  - ADR-001", "[]"
)

ADR = """---
schema: 1
id: ADR-001
status: accepted
date: 2026-01-01
deciders: []
supersedes: []
superseded_by: []
requirements:
  - REQ-001
steps:
  - STEP-001
---

# ADR-001 — A

## Context

C.

## Problem

P.

## Decision

D.

## Alternatives considered

A.

## Consequences

C.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

None.
"""

UNRELATED_ADR = ADR.replace("ADR-001", "ADR-999").replace(
    "  - REQ-001", "[]"
).replace(
    "  - STEP-001", "[]"
)

OQ = """---
schema: 1
id: OQ-001
status: open
affects:
  - STEP-001
created_at: 2026-01-01T00:00:00Z
resolved_at: null
---

# OQ-001 — Question

## Context

Context.

## Decision needed

Choose behavior.
"""

PRN = """---
schema: 1
id: PRN-001
status: active
severity: blocking
scope: project
superseded_by: null
requirements: []
adrs: []
---

# PRN-001 — Compatibility

## Rule

Public contracts preserve compatibility.

## Rationale

Consumers upgrade independently.

## Applies to

Public contracts.

## Exceptions / approved deviation

Explicit reviewed deviation only.
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    git(root, "config", "user.email", "context@example.invalid")
    git(root, "config", "user.name", "Context Contract Test")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")


def required_paths(contract: dict[str, object]) -> set[str]:
    return {
        str(item["path"])
        for item in contract["required"]  # type: ignore[index]
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        for directory in (
            "docs/requirements",
            "docs/adr",
            "docs/open-questions",
            "docs/principles",
            "planning/tasks",
            "src",
        ):
            (root / directory).mkdir(parents=True, exist_ok=True)

        write(root, "planning/tasks/STEP-001.md", STEP)
        write(root, "planning/tasks/STEP-000.md", DEP)
        write(root, "docs/requirements/REQ-001-r.md", REQ)
        write(root, "docs/requirements/REQ-999-unrelated.md", UNRELATED_REQ)
        write(root, "docs/adr/ADR-001-a.md", ADR)
        write(root, "docs/adr/ADR-999-unrelated.md", UNRELATED_ADR)
        write(root, "docs/open-questions/OQ-001-gap.md", OQ)
        write(root, "docs/principles/PRN-001-compat.md", PRN)
        write(root, "docs/architecture.md", "# Architecture\n\n## API\n\nContract.\n")
        write(root, "docs/unrelated.md", "noise\n")
        write(root, "src/extra.ts", "export {}\n")
        write(root, ".harness/tools/secret.py", "internal\n")
        init_repo(root)

        planner = build_context_contract(root, "STEP-001", "planner")
        implementer = build_context_contract(root, "STEP-001", "implementer")
        reviewer = build_context_contract(root, "STEP-001", "reviewer")

        assert planner["role"] == "planner"
        assert implementer["role"] == "implementer"
        assert reviewer["role"] == "reviewer"
        assert planner != reviewer
        assert planner["runtimeNeutral"] is True
        assert planner["repositoryRevision"] == reviewer["repositoryRevision"]
        assert planner["metrics"]["fullRepositoryPreload"] is False
        assert reviewer["metrics"]["fullRepositoryPreload"] is False
        assert planner["metrics"]["manifestChars"] > 0

        # Runtime neutrality is structural: resolver has no provider input.
        # Codex/Claude adapters therefore receive byte-equivalent semantic
        # selection for the same role/STEP/revision.
        codex_selection = json.dumps(planner["required"], sort_keys=True)
        claude_selection = json.dumps(
            build_context_contract(root, "STEP-001", "planner")["required"],
            sort_keys=True,
        )
        assert codex_selection == claude_selection

        planner_paths = required_paths(planner)
        reviewer_paths = required_paths(reviewer)
        for unrelated in (
            "docs/unrelated.md",
            "docs/requirements/REQ-999-unrelated.md",
            "docs/adr/ADR-999-unrelated.md",
        ):
            assert unrelated not in planner_paths
            assert unrelated not in reviewer_paths

        planner_step = next(
            item for item in planner["required"] if item["artifact"] == "STEP-001"
        )
        reviewer_step = next(
            item for item in reviewer["required"] if item["artifact"] == "STEP-001"
        )
        assert "Context" in planner_step["sections"]
        assert "Evidence" not in planner_step["sections"]
        assert "Evidence" in reviewer_step["sections"]

        oq_item = next(
            item for item in planner["required"] if item["artifact"] == "OQ-001"
        )
        assert "Decision needed" in oq_item["sections"]
        assert "Resolution" not in oq_item["sections"]

        assert any(
            item["artifact"] == "PRN-001" for item in planner["required"]
        )
        assert not any(
            item["artifact"] == "PRN-001" for item in implementer["required"]
        )

        expanded = validate_expansion(
            root,
            "src/extra.ts",
            "integration implementation detail required",
        )
        assert expanded["status"] == "PASS"

        for path, reason in (
            (".harness/tools/secret.py", "inspect implementation"),
            ("src/extra.ts", ""),
        ):
            try:
                validate_expansion(root, path, reason)
            except ContextContractError:
                pass
            else:
                raise AssertionError("invalid expansion must fail closed")

        # Missing required canonical link must BLOCK resolver; no full-repo
        # fallback and no silent omission is allowed.
        (root / "docs/requirements/REQ-001-r.md").unlink()
        try:
            build_context_contract(root, "STEP-001", "planner")
        except ContextContractError:
            pass
        else:
            raise AssertionError("missing linked REQ must fail closed")

    print("context-contract self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
