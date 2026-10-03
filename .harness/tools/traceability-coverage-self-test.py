#!/usr/bin/env python3
"""Synthetic fixtures for deterministic traceability coverage."""
from __future__ import annotations

from pathlib import Path
import tempfile

from traceability_coverage import build_coverage


MANIFEST = """sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  openQuestions: docs/open-questions
protocol:
  taskDirectory: planning/tasks
"""


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def req(rid: str, steps: tuple[str, ...], priority: str = "medium") -> str:
    step_yaml = "[]" if not steps else "\n" + "\n".join(f"  - {item}" for item in steps)
    return f"""---
schema: 1
id: {rid}
priority: {priority}
source: brief
steps: {step_yaml}
adrs: []
---

# {rid} — Requirement

## Requirement

Behavior.

## Rationale

Reason.

## Acceptance

- Observable.
"""


def step(
    sid: str,
    reqs: tuple[str, ...] = (),
    *,
    status: str = "planned",
    stype: str = "implementation",
    adrs: tuple[str, ...] = (),
) -> str:
    req_yaml = "[]" if not reqs else "\n" + "\n".join(f"  - {item}" for item in reqs)
    adr_yaml = "[]" if not adrs else "\n" + "\n".join(f"  - {item}" for item in adrs)
    return f"""---
schema: 1
id: {sid}
status: {status}
type: {stype}
priority: medium
phase: P1
depends_on: []
requirements: {req_yaml}
adrs: {adr_yaml}
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {sid} — Step

## Goal

Goal.

## Context

Typed context.

## Scope

- scope

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

- done

## Verification

- manual: check

## Deliverables

- code

## Implementation plan

Not planned.

## Evidence

Pending.

## Blocker / Failure reason

—
"""


def adr(aid: str) -> str:
    return f"""---
schema: 1
id: {aid}
status: accepted
date: 2026-01-01
deciders: []
supersedes: []
superseded_by: []
requirements: []
steps: []
---

# {aid} — Decision

## Context

Context.

## Problem

Problem.

## Decision

Decision.

## Alternatives considered

Alternative.

## Consequences

Consequence.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

None.
"""


def oq(oid: str, affects: tuple[str, ...]) -> str:
    affects_yaml = "\n".join(f"  - {item}" for item in affects)
    return f"""---
schema: 1
id: {oid}
status: open
affects:
{affects_yaml}
created_at: 2026-01-01T00:00:00Z
resolved_at: null
---

# {oid} — Question

## Context

Context.

## Decision needed

Decision.

## Resolution

Pending.
"""


def make_root(tmp: str) -> Path:
    root = Path(tmp)
    write(root, ".harness/manifest.yaml", MANIFEST)
    for directory in ("docs/requirements", "docs/adr", "docs/open-questions", "planning/tasks"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    return root


def provider(complete: set[str], stale: set[str] | None = None):
    stale = stale or set()
    def proof(_root: Path, step_id: str):
        if step_id in complete:
            return {"complete": True, "reasons": []}
        reason = "basis mismatch" if step_id in stale else "incomplete"
        return {"complete": False, "reasons": [reason]}
    return proof


def test_full_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        write(root, "docs/requirements/REQ-001-a.md", req("REQ-001", ("STEP-001",)))
        write(root, "planning/tasks/STEP-001.md", step("STEP-001", ("REQ-001",), status="completed"))
        first = build_coverage(root, completion_provider=provider({"STEP-001"}))
        second = build_coverage(root, completion_provider=provider({"STEP-001"}))
        assert first == second
        assert first["status"] == "PASS"
        assert first["metrics"]["verified"] == 1
        assert first["requirements"][0]["status"] == "verified"


def test_partial_and_split_requirement() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        write(root, "docs/requirements/REQ-001-a.md", req("REQ-001", ("STEP-001", "STEP-002")))
        write(root, "planning/tasks/STEP-001.md", step("STEP-001", ("REQ-001",), status="completed"))
        write(root, "planning/tasks/STEP-002.md", step("STEP-002", ("REQ-001",)))
        partial = build_coverage(root, completion_provider=provider({"STEP-001"}))
        item = partial["requirements"][0]
        assert item["status"] == "covered"
        assert item["evidenceCoverage"] == ["STEP-001"]
        assert item["executableSteps"] == ["STEP-001", "STEP-002"]

        verified = build_coverage(root, completion_provider=provider({"STEP-001", "STEP-002"}))
        assert verified["requirements"][0]["status"] == "verified"


def test_orphan_and_typed_maintenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        write(root, "planning/tasks/STEP-001.md", step("STEP-001"))
        write(root, "planning/tasks/STEP-002.md", step("STEP-002", stype="documentation"))
        write(root, "planning/tasks/STEP-003.md", step("STEP-003", stype="bugfix"))
        result = build_coverage(root, completion_provider=provider(set()))
        assert [item["stepId"] for item in result["orphanSteps"]] == ["STEP-001"]


def test_stale_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        write(root, "docs/requirements/REQ-001-a.md", req("REQ-001", ("STEP-001",)))
        write(root, "planning/tasks/STEP-001.md", step("STEP-001", ("REQ-001",), status="completed"))
        result = build_coverage(root, completion_provider=provider(set(), {"STEP-001"}))
        item = result["requirements"][0]
        assert item["status"] == "stale_evidence"
        assert item["staleEvidence"][0]["reasons"] == ["basis mismatch"]
        assert result["metrics"]["staleEvidence"] == 1


def test_open_oq_through_adr() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        write(root, "docs/requirements/REQ-001-a.md", req("REQ-001", ("STEP-001",)))
        write(root, "docs/adr/ADR-001-a.md", adr("ADR-001"))
        write(root, "planning/tasks/STEP-001.md", step("STEP-001", ("REQ-001",), adrs=("ADR-001",)))
        write(root, "docs/open-questions/OQ-001-gap.md", oq("OQ-001", ("ADR-001",)))
        result = build_coverage(root, completion_provider=provider({"STEP-001"}))
        item = result["requirements"][0]
        assert item["status"] == "blocked"
        assert item["blockingOpenQuestions"] == ["OQ-001"]


def test_broken_references_and_one_sided_link() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        # REQ claims STEP-001, but STEP does not claim REQ-001: invalid and not coverage.
        write(root, "docs/requirements/REQ-001-a.md", req("REQ-001", ("STEP-001",)))
        write(root, "planning/tasks/STEP-001.md", step("STEP-001"))
        write(root, "planning/tasks/STEP-002.md", step("STEP-002", ("REQ-999",), adrs=("ADR-999",)))
        write(root, "docs/open-questions/OQ-001-gap.md", oq("OQ-001", ("STEP-999",)))
        result = build_coverage(root, completion_provider=provider(set()))
        by_id = {item["id"]: item for item in result["requirements"]}
        assert by_id["REQ-001"]["status"] == "uncovered"
        codes = {item["code"] for item in result["invalidReferences"]}
        assert "REVERSE_TRACEABILITY_MISMATCH" in codes
        assert "UNKNOWN_REQ_REFERENCE" in codes
        assert "UNKNOWN_ADR_REFERENCE" in codes
        assert "UNKNOWN_OQ_TARGET" in codes


def main() -> int:
    test_full_coverage()
    test_partial_and_split_requirement()
    test_orphan_and_typed_maintenance()
    test_stale_evidence()
    test_open_oq_through_adr()
    test_broken_references_and_one_sided_link()
    print("traceability-coverage self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
