#!/usr/bin/env python3
"""Regression suite versioned Intent Basis и stale-intent resume guard."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from execution_status import (
    INTENT_BASIS_SCHEMA_VERSION,
    IntentResumeError,
    begin_command,
    load_status,
    resolve_execution,
    resolve_root,
    start_execution,
)
from harness_ux import harness_resume


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def manifest() -> str:
    return """sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
  principles: docs/principles
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
repository:
  gitPolicy: .harness/git-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
"""


def requirement() -> str:
    return """---
schema: 1
id: REQ-001
priority: medium
source: intent-resume-self-test
steps:
  - STEP-001
adrs:
  - ADR-001
---

# REQ-001 — Resume intent

## Requirement

Resume preserves the original semantic contract.

## Rationale

A mechanical cursor is not sufficient.

## Acceptance

- Changed intent blocks resume.
"""


def adr() -> str:
    return """---
schema: 1
id: ADR-001
status: accepted
date: 2026-10-05
supersedes: []
superseded_by: []
---

# ADR-001 — Intent basis

## Context

Resume must be deterministic.

## Problem

The runtime may restart after semantic work began.

## Decision

Bind resume to canonical planning fingerprints.

## Alternatives considered

Use chat history.

## Consequences

Stale intent blocks execution.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

Legacy running commands without a basis fail closed.
"""


def principle() -> str:
    return """---
schema: 1
id: PRN-001
status: active
severity: blocking
scope: project
requirements: []
adrs: []
superseded_by: null
---

# PRN-001 — Deterministic resume

## Rule

Resume must use canonical repository state.

## Rationale

Chat history is not authoritative.

## Applies to

All STEP semantic execution.

## Exceptions / approved deviation

None.
"""


def task() -> str:
    return """---
schema: 1
id: STEP-001
status: in_progress
type: implementation
priority: medium
phase: implementation
depends_on: []
requirements:
  - REQ-001
adrs:
  - ADR-001
architecture_refs: []
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: 2026-10-05T00:00:00+00:00
---

# STEP-001 — Intent resume fixture

## Goal

Implement intent-aware resume.

## Context

Synthetic fixture.

## Scope

- Resume guard.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product changes.

## Acceptance criteria

- Resume is deterministic.

## Verification

- intent-resume-self-test.py.

## Deliverables

- Resume guard.

## Implementation plan

1. Capture canonical basis.
2. Compare it before resume.

## Evidence

—

## Blocker / Failure reason

—
"""


def task_with_execution_groups(group_path: str) -> str:
    value = task()
    metadata_needle = """  planned_at: 2026-10-05T00:00:00+00:00
---"""
    metadata_replacement = f"""  planned_at: 2026-10-05T00:00:00+00:00
  execution_groups:
    core:
      title: Core
      steps:
        - 1
        - 2
      dependsOn: []
      mutationPaths:
        - {group_path}
      verificationResponsibilities:
        - Verify core behavior
      parallel: false
---"""
    if metadata_needle not in value:
        raise AssertionError("execution-groups metadata anchor missing")
    value = value.replace(metadata_needle, metadata_replacement, 1)

    # execution_groups references numbered "### N." plan steps; the base
    # fixture intentionally uses legacy prose numbering for unrelated tests.
    plan_needle = """## Implementation plan

1. Capture canonical basis.
2. Compare it before resume.
"""
    plan_replacement = """## Implementation plan

### 1. Capture canonical basis

Capture canonical basis.

### 2. Compare before resume

Compare it before resume.
"""
    if plan_needle not in value:
        raise AssertionError("execution-groups plan anchor missing")
    return value.replace(plan_needle, plan_replacement, 1)


def prepare(root: Path) -> None:
    write(root / ".harness/manifest.yaml", manifest())
    write(root / ".harness/git-policy.toml", '[push]\nremote = "origin"\n')
    write(
        root / ".harness/harness-update.toml",
        '[state]\nreport_directory = "planning/harness-updates"\n',
    )
    shutil.copy2(
        SOURCE_ROOT / ".harness/command-transitions.json",
        root / ".harness/command-transitions.json",
    )
    write(root / "docs/requirements/REQ-001-resume.md", requirement())
    write(root / "docs/adr/ADR-001-intent.md", adr())
    write(root / "docs/principles/PRN-001-resume.md", principle())
    write(root / "docs/architecture.md", "# Architecture\n")
    write(root / "planning/tasks/STEP-001.md", task())


def clear_execution(root: Path) -> None:
    # Только тестовый сброс между независимыми synthetic executions:
    # в реальном проекте потеря каталога при сохранённом marker блокируется.
    shutil.rmtree(root / ".harness/local/execution", ignore_errors=True)
    (root / ".harness/.execution-checkpoint-known").unlink(missing_ok=True)


def start_review(root: Path) -> dict:
    execution = start_execution(root, "STEP REVIEW STEP-001")
    basis = execution["current"]["context"]["intentBasis"]
    assert basis["schemaVersion"] == INTENT_BASIS_SCHEMA_VERSION, basis
    assert basis["stepId"] == "STEP-001", basis
    assert basis["operation"] == "REVIEW", basis
    assert basis["planContentRequired"] is True, basis
    assert basis["contextBasis"].startswith("sha256:"), basis
    assert basis["planContentHash"].startswith("sha256:"), basis
    assert basis["contextComponents"], basis
    return execution


def mutate_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"fixture mutation anchor missing in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-intent-resume-") as tmp:
        root = Path(tmp)
        prepare(root)

        # Unchanged authoritative inputs remain resumable.
        execution = start_review(root)
        resolved = resolve_execution(root, execution, mutate=False)
        assert resolved["status"] == "RESUME", resolved
        stored_basis = execution["current"]["context"]["intentBasis"]
        resumed = begin_command(root, execution["rootCommand"], execution["current"]["command"])
        assert resumed["current"]["context"]["intentBasis"] == stored_basis, resumed

        # Unrelated repository mutation is intentionally outside Intent Basis.
        clear_execution(root)
        execution = start_review(root)
        write(root / "notes.txt", "unrelated change\n")
        unrelated = resolve_execution(root, execution, mutate=False)
        assert unrelated["status"] == "RESUME", unrelated
        (root / "notes.txt").unlink()

        # Linked REQ semantic change invalidates resume.
        clear_execution(root)
        execution = start_review(root)
        req_path = root / "docs/requirements/REQ-001-resume.md"
        mutate_once(req_path, "Changed intent blocks resume.", "Changed intent blocks resume safely.")
        req_stale = resolve_execution(root, execution, mutate=False)
        assert req_stale["status"] == "BLOCKED", req_stale
        assert req_stale["reasonCode"] == "INTENT_BASIS_STALE", req_stale
        assert any(
            item["component"].startswith("REQ@REQ-001")
            for item in req_stale["intent"]["causes"]
        ), req_stale
        write(req_path, requirement())

        # Linked ADR change receives an architecture-specific blocker.
        clear_execution(root)
        execution = start_review(root)
        adr_path = root / "docs/adr/ADR-001-intent.md"
        mutate_once(
            adr_path,
            "Bind resume to canonical planning fingerprints.",
            "Bind resume to a changed architecture contract.",
        )
        adr_stale = resolve_execution(root, execution, mutate=False)
        assert adr_stale["reasonCode"] == "ARCHITECTURE_BASIS_CHANGED", adr_stale
        write(adr_path, adr())

        # STEP contract mutation is distinguished from generic upstream drift.
        clear_execution(root)
        execution = start_review(root)
        step_path = root / "planning/tasks/STEP-001.md"
        mutate_once(
            step_path,
            "- Resume is deterministic.",
            "- Resume is deterministic and versioned.",
        )
        step_stale = resolve_execution(root, execution, mutate=False)
        assert step_stale["reasonCode"] == "TASK_CONTRACT_CHANGED", step_stale
        write(step_path, task())

        # Ready plan (including executionGroups through plan_content_hash) is
        # a semantic input of IMPLEMENT/REVIEW/FIX and cannot change on resume.
        clear_execution(root)
        execution = start_review(root)
        mutate_once(
            step_path,
            "2. Compare it before resume.",
            "2. Compare it before every resume.",
        )
        plan_stale = resolve_execution(root, execution, mutate=False)
        assert plan_stale["reasonCode"] == "PLAN_BASIS_STALE", plan_stale
        assert plan_stale["remediation"] == "STEP PLAN STEP-001", plan_stale
        write(step_path, task())

        # Execution-group graph is part of plan_content_hash even when
        # the human-readable Implementation plan body itself did not change.
        clear_execution(root)
        write(step_path, task_with_execution_groups("src/core"))
        execution = start_review(root)
        write(step_path, task_with_execution_groups("src/other"))
        group_stale = resolve_execution(root, execution, mutate=False)
        assert group_stale["status"] == "BLOCKED", group_stale
        assert group_stale["reasonCode"] == "PLAN_BASIS_STALE", group_stale
        assert group_stale["remediation"] == "STEP PLAN STEP-001", group_stale
        write(step_path, task())

        # PLAN is allowed to write/replace Implementation plan; only its input
        # context is frozen, avoiding a false stale result after interrupted PLAN.
        clear_execution(root)
        planning = start_execution(root, "STEP PLAN STEP-001")
        mutate_once(
            step_path,
            "2. Compare it before resume.",
            "2. Replace plan output during PLAN.",
        )
        plan_output = resolve_execution(root, planning, mutate=False)
        assert plan_output["status"] == "RESUME", plan_output
        write(step_path, task())

        # Active blocking Project Principle participates in schema-v4 context.
        clear_execution(root)
        execution = start_review(root)
        principle_path = root / "docs/principles/PRN-001-resume.md"
        mutate_once(
            principle_path,
            "Resume must use canonical repository state.",
            "Resume must use canonical repository state and exact fingerprints.",
        )
        principle_stale = resolve_execution(root, execution, mutate=False)
        assert principle_stale["reasonCode"] == "INTENT_BASIS_STALE", principle_stale
        assert any(
            item["component"].startswith("PRN@PRN-001")
            for item in principle_stale["intent"]["causes"]
        ), principle_stale
        write(principle_path, principle())

        # Legacy/diagnostic fresh start may have incomplete canonical inputs.
        # Preserve the original capture failure, then fail-closed on resume
        # instead of inventing a basis from the later repository state.
        clear_execution(root)
        req_path.unlink()
        unavailable_start = start_execution(root, "STEP REVIEW STEP-001")
        capture_error = unavailable_start["current"]["context"]["intentBasisError"]
        assert capture_error["reasonCode"] == "INTENT_BASIS_UNAVAILABLE", capture_error
        unavailable_resume = resolve_execution(root, unavailable_start, mutate=False)
        assert unavailable_resume["status"] == "BLOCKED", unavailable_resume
        assert unavailable_resume["reasonCode"] == "INTENT_BASIS_UNAVAILABLE", unavailable_resume
        write(req_path, requirement())

        # Future/unknown sub-schema remains readable but is never best-effort resumed.
        clear_execution(root)
        execution = start_review(root)
        status_path = root / ".harness/local/execution/execution-status.json"
        raw = json.loads(status_path.read_text(encoding="utf-8"))
        raw["executions"][0]["current"]["context"]["intentBasis"]["schemaVersion"] = 99
        write(status_path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        loaded = load_status(root)
        assert loaded["executions"][0]["current"]["context"]["intentBasis"]["schemaVersion"] == 99
        unsupported = resolve_root(root, "STEP REVIEW STEP-001")
        assert unsupported["status"] == "BLOCKED", unsupported
        assert unsupported["reasonCode"] == "INTENT_BASIS_SCHEMA_UNSUPPORTED", unsupported

        # HARNESS RESUME propagates exact stale reason/remediation and persists
        # the blocker instead of collapsing it into NO_RESUMABLE_EXECUTION.
        clear_execution(root)
        start_review(root)
        mutate_once(req_path, "Changed intent blocks resume.", "Changed intent blocks resume safely.")
        resume = harness_resume(root)
        assert resume["status"] == "BLOCKED", resume
        assert resume["reasonCode"] == "INTENT_BASIS_STALE", resume
        assert resume["remediation"] == "STEP PLAN STEP-001", resume
        state = load_status(root)
        active = state["executions"][0]
        assert active["status"] == "blocked", active
        assert active["blockedBy"]["reasonCode"] == "INTENT_BASIS_STALE", active
        write(req_path, requirement())

        # Explicit repetition of the same interrupted command is guarded too.
        clear_execution(root)
        start_review(root)
        mutate_once(req_path, "Changed intent blocks resume.", "Changed intent blocks resume safely.")
        try:
            start_execution(root, "STEP REVIEW STEP-001")
        except IntentResumeError as exc:
            assert exc.code == "INTENT_BASIS_STALE", exc
            assert exc.details["remediation"] == "STEP PLAN STEP-001", exc.details
        else:
            raise AssertionError("stale explicit resume unexpectedly succeeded")

    print("INTENT RESUME SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
