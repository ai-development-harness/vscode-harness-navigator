#!/usr/bin/env python3
"""Synthetic regression deterministic STEP NEXT recommendation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from command_dispatch import start_dispatch
from execution_status import complete_command, start_execution
from step_next import resolve_step_action, resolve_step_next


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
        # Tracked path, удалённый из working tree, но не из index (обычный `rm`
        # без `git rm`), fixture не нужен — пропускаем вместо traceback.
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def step_text(
    step_id: str,
    *,
    priority: str = "medium",
    status: str = "planned",
    depends: list[str] | None = None,
    risks: list[str] | None = None,
) -> str:
    deps = depends or []
    flags = risks or ["none"]
    dep_yaml = "[]"
    if deps:
        dep_yaml = "\n" + "\n".join(f"  - {item}" for item in deps)
    risk_yaml = "\n" + "\n".join(f"  - {item}" for item in flags)
    return f"""---
schema: 1
id: {step_id}
status: {status}
type: implementation
priority: {priority}
phase: test
depends_on: {dep_yaml}
requirements: []
adrs: []
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


def reset_steps(root: Path) -> None:
    directory = root / "planning/tasks"
    for path in directory.glob("STEP-*.md"):
        path.unlink()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-step-next-") as tmp:
        root = Path(tmp)
        copy_tracked(root)
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
