#!/usr/bin/env python3
"""Synthetic regression deterministic STEP NEXT recommendation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

import step_next as step_next_module
from command_dispatch import start_dispatch
from execution_status import complete_command, start_execution
from step_next import resolve_step_action, resolve_step_next


from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)

def step_text(
    step_id: str,
    *,
    priority: str = "medium",
    status: str = "planned",
    step_type: str = "implementation",
    depends: list[str] | None = None,
    adrs: list[str] | None = None,
    risks: list[str] | None = None,
) -> str:
    deps = depends or []
    linked_adrs = adrs or []
    flags = risks or ["none"]
    dep_yaml = "[]"
    if deps:
        dep_yaml = "\n" + "\n".join(f"  - {item}" for item in deps)
    adr_yaml = "[]"
    if linked_adrs:
        adr_yaml = "\n" + "\n".join(f"  - {item}" for item in linked_adrs)
    risk_yaml = "\n" + "\n".join(f"  - {item}" for item in flags)
    return f"""---
schema: 1
id: {step_id}
status: {status}
type: {step_type}
priority: {priority}
phase: test
depends_on: {dep_yaml}
requirements: []
adrs: {adr_yaml}
architecture_refs: []
risk_flags: {risk_yaml}
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Next fixture {step_id}

## Goal

Проверить STEP NEXT.

## Context

Synthetic.

## Scope

- Next selection.

## Mutation policy

### Allowed

- synthetic.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product.

## Acceptance criteria

- Deterministic recommendation.

## Verification

- command: `python3 -V`

## Deliverables

- Recommendation.

## Implementation plan

TBD.

## Evidence

—

## Blocker / Failure reason

—
"""


def write_step(root: Path, step_id: str, **kwargs) -> None:
    path = root / f"planning/tasks/{step_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step_text(step_id, **kwargs), encoding="utf-8", newline="\n")


def write_adr(root: Path, adr_id: str, *, status: str = "proposed") -> None:
    path = root / f"docs/adr/{adr_id}-synthetic.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema: 1
id: {adr_id}
status: {status}
date: 2026-10-04
deciders: []
supersedes: []
superseded_by: []
requirements: []
steps: []
---

# {adr_id} — Synthetic ADR

## Context

Synthetic STEP NEXT regression fixture.
""",
        encoding="utf-8",
        newline="\n",
    )


def reset_steps(root: Path) -> None:
    directory = root / "planning/tasks"
    for path in directory.glob("STEP-*.md"):
        path.unlink()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-step-next-") as tmp:
        root = Path(tmp)
        copy_tracked(root)
        isolate_project_artifacts(root)
        reset_steps(root)

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "next@example.invalid")
        run(root, "git", "config", "user.name", "Next Test")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # Priority is stronger than downstream/risk. Dependency completion is
        # intentionally NOT required for PLAN, so STEP-001 may be planned ahead.
        write_step(
            root,
            "STEP-001",
            priority="critical",
            depends=["STEP-010"],
        )
        write_step(root, "STEP-010", priority="low")
        first = resolve_step_next(root)
        assert first["status"] == "PASS", first
        assert first["command"] == "STEP PLAN STEP-001", first
        assert first["selected"]["ranking"]["priority"] == "critical", first

        exact = resolve_step_action(root, "STEP-001")
        assert exact["status"] == "PASS", exact
        assert exact["stepType"] == "implementation", exact
        assert exact["command"] == "STEP PLAN STEP-001", exact

        # ADR STEP owns its linked proposed ADR: requiring accepted before PLAN
        # would create a cyclic prerequisite. Ordinary implementation STEPs
        # remain blocked by the same proposed ADR status.
        reset_steps(root)
        write_adr(root, "ADR-1000", status="proposed")
        write_adr(root, "ADR-1001", status="proposed")
        write_step(
            root,
            "STEP-011",
            priority="critical",
            step_type="adr",
            adrs=["ADR-1000"],
        )
        write_step(
            root,
            "STEP-012",
            priority="high",
            adrs=["ADR-1001"],
        )

        adr_action = resolve_step_action(root, "STEP-011")
        assert adr_action["status"] == "PASS", adr_action
        assert adr_action["stepType"] == "adr", adr_action
        assert adr_action["command"] == "STEP PLAN STEP-011", adr_action

        implementation_action = resolve_step_action(root, "STEP-012")
        assert implementation_action["status"] == "BLOCKED", implementation_action
        assert (
            "adr-not-accepted:ADR-1001" in implementation_action["reasons"]
        ), implementation_action

        adr_next = resolve_step_next(root)
        assert adr_next["status"] == "PASS", adr_next
        assert adr_next["command"] == "STEP PLAN STEP-011", adr_next

        # Same priority: a STEP that unlocks more downstream active work wins.
        reset_steps(root)
        write_step(root, "STEP-002", priority="high")
        write_step(root, "STEP-003", priority="high")
        write_step(
            root,
            "STEP-004",
            priority="low",
            status="blocked",
            depends=["STEP-002"],
        )
        downstream = resolve_step_next(root)
        assert downstream["command"] == "STEP PLAN STEP-002", downstream
        assert downstream["selected"]["ranking"]["downstreamImpact"] == 1, downstream

        # Risk is only a deterministic visibility tie-breaker, not a severity
        # model. With all earlier ranking dimensions equal, explicit risk wins.
        reset_steps(root)
        write_step(root, "STEP-005", priority="medium")
        write_step(
            root,
            "STEP-006",
            priority="medium",
            risks=["security-sensitive", "public-api"],
        )
        risk = resolve_step_next(root)
        assert risk["command"] == "STEP PLAN STEP-006", risk
        assert risk["selected"]["ranking"]["riskFlagCount"] == 2, risk

        # Existing interrupted STEP execution always wins over higher-priority
        # fresh work. This preserves user continuity without LLM arbitration.
        write_step(root, "STEP-007", priority="critical")
        active = start_execution(root, "STEP PLAN STEP-005")
        assert active["status"] == "running", active
        continuity = resolve_step_next(root)
        assert continuity["command"] == "STEP PLAN STEP-005", continuity
        assert continuity["reasonCode"] == "RESUME_STEP_EXECUTION", continuity
        assert continuity["selected"]["source"] == "execution", continuity
        assert continuity["alternatives"][0]["command"] == "STEP PLAN STEP-007", continuity

        # REVIEW PASS and completion are different durable facts. A PASS review
        # with in-scope completion FAIL still requires canonical FIX; a semantic
        # completion blocker must not be converted into new implementation work.
        original_latest_review = step_next_module.latest_review
        try:
            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "FAIL",
            }
            completion_fix = resolve_step_action(root, "STEP-005")
            assert completion_fix["status"] == "PASS", completion_fix
            assert completion_fix["command"] == "STEP FIX STEP-005", completion_fix

            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "BLOCKED",
            }
            completion_blocked = resolve_step_action(root, "STEP-005")
            assert completion_blocked["status"] == "BLOCKED", completion_blocked
            assert (
                "current-review-completion-blocked"
                in completion_blocked["reasons"]
            ), completion_blocked
        finally:
            step_next_module.latest_review = original_latest_review

        # Dispatcher executes STEP NEXT itself; no next-step semantic skill is
        # needed to choose the recommendation.
        dispatched = start_dispatch(root, "STEP NEXT")
        assert dispatched["status"] == "DONE", dispatched
        result = dispatched["result"]
        assert result["status"] == "PASS", result
        assert result["command"] == "STEP PLAN STEP-005", result

        # Clean up the synthetic interrupted command to leave no hidden state.
        complete_command(
            root,
            active["rootCommand"],
            active["current"]["command"],
            "BLOCKED",
        )

    print("STEP NEXT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
