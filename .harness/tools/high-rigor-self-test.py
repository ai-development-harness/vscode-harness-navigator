#!/usr/bin/env python3
"""Synthetic regressions for optional High-Rigor Arena/Interrogate."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile

from high_rigor import HighRigorError, activation, validate_trace


MANIFEST_EXPLICIT = """execution:
  maxFixReviewCycles: 3
  verificationCommandTimeoutSeconds: 300
review:
  security: auto
  tests: auto
highRigor:
  arena: explicit
  interrogate: explicit
  seats: 3
  maxSeats: 5
  maxInputCharsPerSeat: 80000
  maxOutputCharsPerSeat: 24000
  maxTotalChars: 400000
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""

STEP = """---
schema: 1
id: STEP-001
status: planned
type: refactor
priority: high
phase: P1
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - architecture
  - public-api
plan:
  status: not_planned
  revision: 0
---

# STEP-001 — High rigor fixture

## Goal

Refactor a public architecture boundary.

## Context

Fixture.

## Scope

- src

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

- preserve API compatibility

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
    write(root, ".harness/manifest.yaml", MANIFEST_EXPLICIT)
    write(root, "planning/tasks/STEP-001.md", STEP)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "high-rigor@example.invalid")
    git(root, "config", "user.name", "High Rigor Test")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")


def set_policy(root: Path, *, arena: str, interrogate: str) -> None:
    text = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
    import re
    text = re.sub(r"(?m)^  arena: .+$", f"  arena: {arena}", text)
    text = re.sub(
        r"(?m)^  interrogate: .+$",
        f"  interrogate: {interrogate}",
        text,
    )
    write(root, ".harness/manifest.yaml", text)


def local(root: Path, run: str, name: str, content: str) -> str:
    rel = f".harness/local/high-rigor/{run}/{name}"
    write(root, rel, content)
    return rel


def arena_trace(root: Path, *, run: str = "HR-arena-001") -> dict[str, object]:
    shared = local(
        root,
        run,
        "candidate-input.md",
        "Intent: propose a migration-safe public API refactor.\n",
    )
    rubric = local(
        root,
        run,
        "rubric.md",
        "1. correctness\n2. compatibility\n3. maintainability\n",
    )
    participants: list[dict[str, object]] = []
    for index, model in enumerate(("model-a", "model-b", "model-c"), 1):
        output = local(
            root,
            run,
            f"candidate-{index}.md",
            f"Candidate {index}: coherent independent proposal.\n",
        )
        participants.append(
            {
                "seatId": f"candidate-{index}",
                "role": "candidate",
                "runtimeId": "codex",
                "sessionExecutionId": f"session-candidate-{index}",
                "requestedModel": model,
                "actualModel": model,
                "fallbackReason": None,
                "status": "completed",
                "inputFile": shared,
                "rubricFile": rubric,
                "outputFile": output,
                "error": None,
            }
        )

    judge_input = local(
        root,
        run,
        "judge-input.md",
        "Judge candidate hashes/results against the shared rubric.\n",
    )
    judge_output = local(
        root,
        run,
        "judge-output.md",
        "Judge recommends candidate-2 and records criterion scores.\n",
    )
    participants.append(
        {
            "seatId": "judge-1",
            "role": "judge",
            "runtimeId": "claude",
            "sessionExecutionId": "session-judge-1",
            "requestedModel": "judge-model",
            "actualModel": "judge-model",
            "fallbackReason": None,
            "status": "completed",
            "inputFile": judge_input,
            "rubricFile": rubric,
            "outputFile": judge_output,
            "error": None,
        }
    )
    synthesis = local(
        root,
        run,
        "synthesis.md",
        "Base candidate-2; graft compatibility note from candidate-1.\n",
    )
    return {
        "schemaVersion": 1,
        "runId": run,
        "mode": "arena",
        "phase": "plan",
        "stepId": "STEP-001",
        "sharedInputFile": shared,
        "rubricFile": rubric,
        "participants": participants,
        "synthesis": {
            "baseSeatId": "candidate-2",
            "judgeSeatId": "judge-1",
            "synthesisOutputFile": synthesis,
            "grafts": [
                {
                    "fromSeatId": "candidate-1",
                    "summary": "Preserve its explicit compatibility rollback note.",
                }
            ],
            "disagreements": [
                "candidate-3 prefers a larger API surface than the selected base"
            ],
            "verificationRefs": [
                "STEP-001#Verification",
                "planning review gate",
            ],
        },
    }


def interrogate_trace(
    root: Path,
    *,
    run: str = "HR-interrogate-001",
) -> dict[str, object]:
    shared = local(
        root,
        run,
        "review-input.md",
        "Intent + exact review surface + surrounding contract.\n",
    )
    rubric = local(
        root,
        run,
        "rubric.md",
        "1. correctness\n2. security\n3. compatibility\n",
    )
    participants: list[dict[str, object]] = []
    for index, model in enumerate(("review-a", "review-b", "review-c"), 1):
        output = local(
            root,
            run,
            f"reviewer-{index}.md",
            f"Reviewer {index}: findings over the exact same surface.\n",
        )
        participants.append(
            {
                "seatId": f"reviewer-{index}",
                "role": "reviewer",
                "runtimeId": "codex",
                "sessionExecutionId": f"session-reviewer-{index}",
                "requestedModel": model,
                "actualModel": model,
                "fallbackReason": None,
                "status": "completed",
                "inputFile": shared,
                "rubricFile": rubric,
                "outputFile": output,
                "error": None,
            }
        )
    lead = local(
        root,
        run,
        "lead.md",
        "Lead judgment preserves consensus and explicit disagreement.\n",
    )
    return {
        "schemaVersion": 1,
        "runId": run,
        "mode": "interrogate",
        "phase": "review",
        "stepId": "STEP-001",
        "sharedInputFile": shared,
        "rubricFile": rubric,
        "participants": participants,
        "synthesis": {
            "leadOutputFile": lead,
            "consensus": [
                {
                    "finding": "Compatibility regression in public API.",
                    "seatIds": ["reviewer-1", "reviewer-2"],
                }
            ],
            "disagreements": [
                {
                    "finding": "Whether the fallback branch is reachable.",
                    "seatIds": ["reviewer-2", "reviewer-3"],
                }
            ],
            "leadJudgment": {
                "actOn": ["Compatibility regression in public API."],
                "consider": ["Fallback reachability needs targeted proof."],
                "noted": [],
                "dismissed": [],
            },
            "deterministicGateRefs": [
                "completion-gate:PASS",
                "verification:PASS",
            ],
        },
    }


def expect_rejected(fn) -> None:
    try:
        fn()
    except HighRigorError:
        return
    raise AssertionError("invalid high-rigor contract must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="high-rigor-") as tmp:
        root = Path(tmp)
        init_repo(root)

        # Normal mode under explicit policy does not fan out.
        ordinary = activation(
            root,
            mode="arena",
            phase="plan",
            step_id="STEP-001",
        )
        assert ordinary["status"] == "SKIP", ordinary
        assert ordinary["reasonCode"] == "EXPLICIT_REQUEST_REQUIRED"

        requested = activation(
            root,
            mode="arena",
            phase="plan",
            step_id="STEP-001",
            requested=True,
        )
        assert requested["status"] == "RUN", requested
        assert requested["reasonCode"] == "EXPLICIT_REQUEST"

        # Risk policy is deterministic from STEP machine facts.
        set_policy(root, arena="risk", interrogate="risk")
        risk = activation(
            root,
            mode="arena",
            phase="plan",
            step_id="STEP-001",
        )
        assert risk["status"] == "RUN", risk
        assert risk["reasonCode"] == "RISK_CONDITION"
        assert risk["matchingRiskFlags"] == ["architecture", "public-api"]

        malformed_step = (root / "planning/tasks/STEP-001.md").read_text(encoding="utf-8")
        write(
            root,
            "planning/tasks/STEP-001.md",
            malformed_step.replace("  - public-api", "  - unknown-risk"),
        )
        expect_rejected(
            lambda: activation(
                root,
                mode="arena",
                phase="plan",
                step_id="STEP-001",
            )
        )
        write(root, "planning/tasks/STEP-001.md", STEP)

        # Disabled cannot be overridden even by explicit request.
        set_policy(root, arena="disabled", interrogate="disabled")
        disabled = activation(
            root,
            mode="arena",
            phase="plan",
            step_id="STEP-001",
            requested=True,
        )
        assert disabled["status"] == "SKIP", disabled
        assert disabled["reasonCode"] == "POLICY_DISABLED"

        # Restore explicit for trace validation.
        set_policy(root, arena="explicit", interrogate="explicit")

        arena = arena_trace(root)
        arena_result = validate_trace(root, arena, requested=True)
        assert arena_result["status"] == "PASS", arena_result
        assert arena_result["metrics"]["configuredSeats"] == 3
        assert arena_result["metrics"]["completedSeats"] == 4
        assert arena_result["metrics"]["distinctActualModels"] == 4
        assert arena_result["synthesis"]["baseSeatId"] == "candidate-2"
        assert arena_result["deterministicGatesReplaced"] is False

        # Candidate inputs and rubric must be byte-identical.
        wrong_input = copy.deepcopy(arena)
        wrong_path = local(
            root,
            "HR-arena-001",
            "different-input.md",
            "Different candidate input.\n",
        )
        wrong_input["participants"][0]["inputFile"] = wrong_path
        expect_rejected(
            lambda: validate_trace(root, wrong_input, requested=True)
        )

        duplicate_session = copy.deepcopy(arena)
        duplicate_session["participants"][1]["sessionExecutionId"] = (
            duplicate_session["participants"][0]["sessionExecutionId"]
        )
        expect_rejected(
            lambda: validate_trace(root, duplicate_session, requested=True)
        )

        shared_output = copy.deepcopy(arena)
        shared_output["participants"][1]["outputFile"] = (
            shared_output["participants"][0]["outputFile"]
        )
        expect_rejected(
            lambda: validate_trace(root, shared_output, requested=True)
        )

        cross_run = copy.deepcopy(arena)
        cross_path = local(
            root,
            "HR-other-001",
            "candidate.md",
            "cross-run output\n",
        )
        cross_run["participants"][0]["outputFile"] = cross_path
        expect_rejected(
            lambda: validate_trace(root, cross_run, requested=True)
        )

        extra_judge = copy.deepcopy(arena)
        second_judge = copy.deepcopy(extra_judge["participants"][-1])
        second_judge["seatId"] = "judge-2"
        second_judge["sessionExecutionId"] = "session-judge-2"
        extra_judge["participants"].append(second_judge)
        expect_rejected(
            lambda: validate_trace(root, extra_judge, requested=True)
        )

        # Runtime/model dropout is explicit DEGRADED, never silent PASS.
        degraded = copy.deepcopy(arena)
        failed = degraded["participants"][2]
        failed["status"] = "unsupported"
        failed["sessionExecutionId"] = None
        failed["actualModel"] = None
        failed["outputFile"] = None
        failed["error"] = "configured additional model is unavailable"
        degraded_result = validate_trace(root, degraded, requested=True)
        assert degraded_result["status"] == "DEGRADED", degraded_result
        assert "SEAT_UNSUPPORTED" in degraded_result["degradationReasons"]

        # Model fallback is visible even if the seat completed successfully.
        fallback = copy.deepcopy(arena)
        fallback["participants"][0]["actualModel"] = "model-a-fallback"
        fallback["participants"][0]["fallbackReason"] = (
            "requested model unavailable; runtime used same-family fallback"
        )
        fallback_result = validate_trace(root, fallback, requested=True)
        assert fallback_result["status"] == "DEGRADED", fallback_result
        assert "MODEL_FALLBACK" in fallback_result["degradationReasons"]

        interrogate = interrogate_trace(root)
        interrogation = validate_trace(
            root,
            interrogate,
            requested=True,
        )
        assert interrogation["status"] == "PASS", interrogation
        assert interrogation["synthesis"]["consensus"][0]["seatIds"] == [
            "reviewer-1",
            "reviewer-2",
        ]
        assert interrogation["synthesis"]["disagreements"], interrogation
        assert interrogation["deterministicGatesReplaced"] is False

        # Interrogate consensus requires 2+ independent completed reviewers.
        bad_consensus = copy.deepcopy(interrogate)
        bad_consensus["synthesis"]["consensus"][0]["seatIds"] = ["reviewer-1"]
        expect_rejected(
            lambda: validate_trace(root, bad_consensus, requested=True)
        )

        # Trace cannot claim a run when policy did not authorize fan-out.
        expect_rejected(
            lambda: validate_trace(root, arena, requested=False)
        )

    print("high-rigor self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
