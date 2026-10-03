#!/usr/bin/env python3
"""Synthetic regression deterministic Project State API."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from project_state import build_project_state
from self_test_fixture import isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def copy_tracked(target: Path) -> None:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=SOURCE_ROOT,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = token.decode("utf-8")
        source = SOURCE_ROOT / rel
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-project-state-") as tmp:
        root = Path(tmp)
        copy_tracked(root)
        isolate_project_artifacts(root)

        write(
            root / "docs/requirements/REQ-001-state.md",
            """---
schema: 1
id: REQ-001
priority: high
source: brief
steps:
  - STEP-001
adrs:
  - ADR-001
---

# REQ-001 — Project State fixture

## Requirement

Navigator получает deterministic graph.

## Rationale

Проверить Project State API.

## Acceptance

- Связи нормализуются.
""",
        )
        write(
            root / "docs/adr/ADR-001-state.md",
            """---
schema: 1
id: ADR-001
status: proposed
date: 2026-10-01
deciders: []
supersedes: []
superseded_by: []
requirements:
  - REQ-001
steps:
  - STEP-001
---

# ADR-001 — Project State architecture

## Context

Synthetic.

## Problem

Graph contract.

## Decision

Use deterministic graph.

## Alternatives considered

### A

None.

## Consequences

Stable API.

## Security implications

Not applicable.

## Data / migration implications

Not applicable.

## Compatibility / operational implications

Read-only.
""",
        )
        write(
            root / "planning/tasks/STEP-001.md",
            """---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: high
phase: test
depends_on:
  - STEP-999
requirements:
  - REQ-001
adrs:
  - ADR-001
architecture_refs: []
risk_flags:
  - none
plan:
  status: draft
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
  execution_groups:
    state:
      title: Project State group
      steps:
        - 1
      dependsOn: []
      mutationPaths:
        - src/state
      verificationResponsibilities:
        - Verify Project State graph
      parallel: false
---

# STEP-001 — Project State fixture

## Goal

Проверить graph.

## Context

Synthetic.

## Scope

- Build fixture.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product.

## Acceptance criteria

- Deterministic result.

## Verification

- command: `python3 -V`

## Deliverables

- Graph.

## Implementation plan

### 1. Build graph

- Build fixture.

## Evidence

—

## Blocker / Failure reason

—
""",
        )
        write(
            root / "docs/open-questions/OQ-001-state.md",
            """---
schema: 1
id: OQ-001
status: open
affects:
  - STEP-001
created_at: 2026-10-01T00:00:00Z
resolved_at: null
---

# OQ-001 — Project State fixture

## Context

Synthetic.

## Decision needed

Resolve.

## Resolution

—
""",
        )

        state = build_project_state(root)
        summary = state["summary"]
        assert state["schemaVersion"] == 1, state
        assert state["status"] == "PASS", state
        assert state["integrity"] == "degraded", state
        assert summary["artifacts"] == 4, summary
        assert summary["byType"] == {"ADR": 1, "OQ": 1, "REQ": 1, "STEP": 1}, summary
        assert summary["missingReferences"] == 1, summary
        assert summary["blockers"] == 1, summary
        step_node = next(node for node in state["graph"]["nodes"] if node["id"] == "STEP-001")
        assert step_node["metadata"]["executionGroups"][0]["id"] == "state", step_node

        edges = {
            (edge["source"], edge["target"], edge["relation"]): edge
            for edge in state["graph"]["edges"]
        }
        implemented = edges[("REQ-001", "STEP-001", "implemented_by")]
        assert implemented["declaredBy"] == ["REQ-001", "STEP-001"], implemented
        assert ("ADR-001", "REQ-001", "addresses") in edges, edges
        assert ("ADR-001", "STEP-001", "governs") in edges, edges
        assert ("OQ-001", "STEP-001", "affects") in edges, edges
        assert ("STEP-001", "MISSING:STEP-999", "depends_on") in edges, edges

        missing = [
            node
            for node in state["graph"]["nodes"]
            if node["id"] == "MISSING:STEP-999"
        ]
        assert len(missing) == 1 and missing[0]["status"] == "missing", missing

        diagnostics = state["diagnostics"]
        assert diagnostics == [
            {
                "code": "MISSING_REFERENCE",
                "source": "STEP-001",
                "target": "STEP-999",
                "relation": "depends_on",
            }
        ], diagnostics

        blockers = state["insights"]["blockers"]
        assert blockers == [
            {
                "nodeId": "OQ-001",
                "kind": "open_question",
                "affects": ["STEP-001"],
                "impactCount": 1,
            }
        ], blockers

    print("PROJECT STATE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
