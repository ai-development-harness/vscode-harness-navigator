#!/usr/bin/env python3
"""Cross-process reliability regressions for #202/#203/#204 together.

These scenarios deliberately cross process boundaries so local execution state
is the only durable handoff. They complement unit/policy self-tests with:
- crash after Intent Basis persistence;
- STEP RUN resume across fresh processes;
- persisted progress blocker after response loss;
- concurrent stale completion vs current semantic resume;
- stale continuation/resume mutation cannot block or advance a newer invocation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from execution_status import load_status
from projection_contract import write_projections
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)
    isolate_project_artifacts(target)

def requirement() -> str:
    return """---
schema: 1
id: REQ-900
priority: medium
source: reliable-orchestration-fault-self-test
steps:
  - STEP-900
adrs: []
---

# REQ-900 — Reliable orchestration fault fixture

## Requirement

Interrupted orchestration must resume only against authoritative current state.

## Rationale

Process lifetime is not an orchestration source of truth.

## Acceptance

- Intent drift blocks resume.
- Repeated no-op resume is bounded.
"""


def task() -> str:
    return """---
schema: 1
id: STEP-900
status: planned
type: implementation
priority: medium
phase: implementation
depends_on: []
requirements:
  - REQ-900
adrs: []
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
---

# STEP-900 — Cross-process orchestration fixture

## Goal

Exercise reliable orchestration boundaries.

## Context

Synthetic cross-process fixture.

## Scope

- Intent persistence.
- Progress persistence.
- State authority.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product behavior.

## Acceptance criteria

- Resume is deterministic.
- Stale semantic result cannot commit current execution.

## Verification

- reliable-orchestration-fault-self-test.py.

## Deliverables

- Cross-process regression coverage.

## Implementation plan

1. Persist execution state.
2. Cross a process boundary.
3. Reconcile authoritative state.

## Evidence

—

## Blocker / Failure reason

—
"""


def mark_initialized(root: Path) -> None:
    path = root / ".harness/manifest.yaml"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "  initialized: false",
        "  initialized: true",
        1,
    )
    text = text.replace(
        "  name: null",
        '  name: "fault-hardening-fixture"',
        1,
    )
    text = text.replace(
        "  initializedAt: null",
        '  initializedAt: "2026-10-05T00:00:00+00:00"',
        1,
    )
    write(path, text)


def prepare(root: Path) -> None:
    copy_tracked(root)
    mark_initialized(root)
    write(root / "docs/requirements/REQ-900-fault.md", requirement())
    write(root / "planning/tasks/STEP-900.md", task())
    write_projections(root)

    shutil.rmtree(root / ".harness/local", ignore_errors=True)
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "fault-test@example.invalid")
    run(root, "git", "config", "user.name", "Fault Hardening Test")
    # Synthetic repositories must not inherit background Git housekeeping.
    # `git commit` may launch `git maintenance run --auto --detach`; that
    # detached process can outlive the direct command and race cleanup of the
    # TemporaryDirectory even after all explicit test workers were reaped.
    run(root, "git", "config", "gc.auto", "0")
    run(root, "git", "config", "maintenance.auto", "false")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "fault fixture")


def child_json(root: Path, body: str) -> dict:
    env = os.environ.copy()
    env["HARNESS_FIXTURE_ROOT"] = str(root)
    env["PYTHONPATH"] = str(root / ".harness/tools")
    script = (
        "import json, os\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['HARNESS_FIXTURE_ROOT'])\n"
        + body
        + "\nprint(json.dumps(result, ensure_ascii=False, separators=(',', ':')))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if not proc.stdout.strip():
        raise AssertionError(
            f"child produced no JSON (exit={proc.returncode}):\n{proc.stderr}"
        )
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"child emitted invalid JSON:\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    return result


def mutate_requirement(root: Path) -> None:
    path = root / "docs/requirements/REQ-900-fault.md"
    text = path.read_text(encoding="utf-8")
    needle = "Interrupted orchestration must resume only against authoritative current state."
    replacement = (
        "Interrupted orchestration must resume only against changed authoritative current state."
    )
    if needle not in text:
        raise AssertionError("REQ mutation anchor missing")
    write(path, text.replace(needle, replacement, 1))


def test_crash_after_intent_snapshot(root: Path) -> None:
    # start_execution persists current.context.intentBasis before any semantic
    # runtime handoff. Child exits immediately: the next process has only disk.
    started = child_json(
        root,
        (
            "from execution_status import start_execution\n"
            "value = start_execution(root, 'STEP PLAN STEP-900')\n"
            "result = {'executionId': value['executionId'], "
            "'intentBasis': value['current']['context'].get('intentBasis'), "
            "'progressTelemetry': value.get('progressTelemetry')}"
        ),
    )
    assert started["intentBasis"]["stepId"] == "STEP-900", started
    assert started["progressTelemetry"]["samples"], started

    mutate_requirement(root)
    resumed = child_json(
        root,
        (
            "from harness_ux import harness_resume\n"
            "result = harness_resume(root)"
        ),
    )
    assert resumed["status"] == "BLOCKED", resumed
    assert resumed["reasonCode"] == "INTENT_BASIS_STALE", resumed
    assert resumed["remediation"] == "STEP PLAN STEP-900", resumed

    state = load_status(root)
    active = state["executions"][0]
    assert active["status"] == "blocked", active
    assert active["blockedBy"]["reasonCode"] == "INTENT_BASIS_STALE", active


def test_step_run_progress_survives_process_loss(root: Path) -> None:
    started = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            "result = start_dispatch(root, 'STEP RUN STEP-900')"
        ),
    )
    assert started["status"] == "SEMANTIC", started
    assert started["command"] == "STEP PLAN STEP-900", started
    assert started["intentBasis"]["stepId"] == "STEP-900", started
    root_command = started["rootCommand"]

    # First new process resumes the same PLAN with no repository/material delta.
    first = child_json(
        root,
        (
            "from command_dispatch import resume_dispatch\n"
            f"result = resume_dispatch(root, {root_command!r})"
        ),
    )
    assert first["status"] == "SEMANTIC", first
    assert first["command"] == "STEP PLAN STEP-900", first

    # Second new process reaches the configured generic no-progress threshold.
    # Treat its response as lost: durability is verified by a third process.
    second = child_json(
        root,
        (
            "from command_dispatch import resume_dispatch\n"
            f"result = resume_dispatch(root, {root_command!r})"
        ),
    )
    assert second["status"] == "BLOCKED", second
    assert second["reasonCode"] == "EXECUTION_STAGNATION", second

    observed_after_response_loss = child_json(
        root,
        (
            "from harness_ux import harness_resume\n"
            "result = harness_resume(root)"
        ),
    )
    assert observed_after_response_loss["status"] == "BLOCKED", (
        observed_after_response_loss
    )
    assert observed_after_response_loss["reasonCode"] == "EXECUTION_STAGNATION", (
        observed_after_response_loss
    )

    # A late model answer from the pre-block handoff cannot resurrect state.
    late = child_json(
        root,
        (
            "from command_dispatch import complete_dispatch\n"
            f"result = complete_dispatch(root, {root_command!r}, "
            f"{started['command']!r}, 'SUCCESS', "
            f"execution_id={started['executionId']!r})"
        ),
    )
    assert late["status"] == "BLOCKED", late
    state = load_status(root)
    item = state["executions"][0]
    assert item["status"] == "blocked", item
    assert item["blockedBy"]["reasonCode"] == "EXECUTION_STAGNATION", item


def _spawn_barrier_worker(
    root: Path,
    barrier: Path,
    output: Path,
    body: str,
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["HARNESS_FIXTURE_ROOT"] = str(root)
    env["HARNESS_BARRIER"] = str(barrier)
    env["HARNESS_OUTPUT"] = str(output)
    env["PYTHONPATH"] = str(root / ".harness/tools")
    script = (
        "import json, os, time\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['HARNESS_FIXTURE_ROOT'])\n"
        "barrier = Path(os.environ['HARNESS_BARRIER'])\n"
        "output = Path(os.environ['HARNESS_OUTPUT'])\n"
        "deadline = time.time() + 10\n"
        "while not barrier.exists():\n"
        "    if time.time() > deadline:\n"
        "        raise TimeoutError('barrier timeout')\n"
        "    time.sleep(0.01)\n"
        + body
        + "\noutput.write_text(json.dumps(result, ensure_ascii=False), "
        "encoding='utf-8')\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_concurrent_stale_complete_vs_current_resume(root: Path) -> None:
    command = "PROJECT QUICK FIX: concurrency authority"
    first = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    assert first["status"] == "SEMANTIC", first

    blocked = child_json(
        root,
        (
            "from command_dispatch import complete_dispatch\n"
            f"result = complete_dispatch(root, {command!r}, {command!r}, "
            f"'BLOCKED', execution_id={first['executionId']!r})"
        ),
    )
    assert blocked["status"] == "BLOCKED", blocked

    current = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    assert current["status"] == "SEMANTIC", current
    assert current["executionId"] != first["executionId"], (first, current)

    barrier = root / ".concurrency-go"
    stale_output = root / ".stale-result.json"
    resume_output = root / ".resume-result.json"

    stale_worker = _spawn_barrier_worker(
        root,
        barrier,
        stale_output,
        (
            "from command_dispatch import complete_dispatch\n"
            f"result = complete_dispatch(root, {command!r}, {command!r}, "
            f"'SUCCESS', execution_id={first['executionId']!r})"
        ),
    )
    resume_worker = _spawn_barrier_worker(
        root,
        barrier,
        resume_output,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    time.sleep(0.1)
    barrier.touch()

    for worker in (stale_worker, resume_worker):
        stdout, stderr = worker.communicate(timeout=30)
        assert worker.returncode == 0, (worker.returncode, stdout, stderr)

    stale = json.loads(stale_output.read_text(encoding="utf-8"))
    resumed = json.loads(resume_output.read_text(encoding="utf-8"))
    assert stale["status"] == "BLOCKED", stale
    assert stale["reasonCode"] == "STALE_SEMANTIC_RESULT", stale
    assert stale["executionId"] == current["executionId"], stale

    assert resumed["status"] == "SEMANTIC", resumed
    assert resumed["executionId"] == current["executionId"], resumed

    state = load_status(root)
    running = [
        item
        for item in state["executions"]
        if item.get("rootCommand") == command
        and item.get("status") == "running"
    ]
    assert len(running) == 1, running
    assert running[0]["executionId"] == current["executionId"], running
    assert running[0]["current"]["attempt"] == 2, running[0]


def test_atomic_completion_binding(root: Path) -> None:
    """Force the old TOCTOU window and prove commit-point execution binding."""
    command = "PROJECT QUICK FIX: atomic completion authority"
    first = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    assert first["status"] == "SEMANTIC", first

    # In one process keep a stale pre-check view of execution A, move durable
    # state to a new execution B, then let complete_dispatch continue. The
    # initial authority check is deliberately fooled; only complete_command's
    # under-lock expected_execution_id check can reject the stale proposal.
    raced = child_json(
        root,
        (
            "import command_dispatch as dispatcher\n"
            f"command = {command!r}\n"
            "stale = dispatcher._active_execution(root, command)\n"
            f"dispatcher.complete_dispatch(root, command, command, 'BLOCKED', "
            f"execution_id={first['executionId']!r})\n"
            "current = dispatcher.start_dispatch(root, command)\n"
            "dispatcher._active_execution = lambda _root, _command: stale\n"
            f"result = dispatcher.complete_dispatch(root, command, command, "
            f"'SUCCESS', execution_id={first['executionId']!r})\n"
            "result['currentExecutionId'] = current['executionId']"
        ),
    )
    assert raced["status"] == "BLOCKED", raced
    assert raced["reasonCode"] == "STALE_SEMANTIC_RESULT", raced
    assert raced["currentExecutionId"] != first["executionId"], raced

    state = load_status(root)
    running = [
        item
        for item in state["executions"]
        if item.get("rootCommand") == command
        and item.get("status") == "running"
    ]
    assert len(running) == 1, running
    assert running[0]["executionId"] == raced["currentExecutionId"], running
    assert running[0]["current"]["status"] == "running", running[0]


def test_stale_verification_evidence_publication(root: Path) -> None:
    """Stale semantic completion must not publish Evidence into a successor."""
    root_command = "PROJECT QUICK FIX: verification evidence authority"
    first = child_json(
        root,
        (
            "import command_dispatch as dispatcher\n"
            f"root_command = {root_command!r}\n"
            "first = dispatcher.start_dispatch(root, root_command)\n"
            "writes = []\n"
            "successor = {}\n"
            "def fake_verification(_root, _step_id, **_kwargs):\n"
            "    dispatcher.complete_dispatch(\n"
            "        root, root_command, root_command, 'BLOCKED',\n"
            "        execution_id=first['executionId'],\n"
            "    )\n"
            "    successor.update(dispatcher.start_dispatch(root, root_command))\n"
            "    return {\n"
            "        'schemaVersion': 1, 'status': 'PASS', 'stepId': 'STEP-900',\n"
            "        'runAt': '2026-10-05T00:00:00+00:00',\n"
            "        'revision': {'git_head': None, 'worktree_hash': None},\n"
            "    }\n"
            "dispatcher.run_step_verification = fake_verification\n"
            "dispatcher.write_verification_evidence = (\n"
            "    lambda *_args, **_kwargs: writes.append('written')\n"
            ")\n"
            "early, details = dispatcher._verification_before_completion(\n"
            "    root, root_command, 'STEP IMPLEMENT STEP-900', 'SUCCESS', None,\n"
            "    expected_execution_id=first['executionId'],\n"
            ")\n"
            "result = {\n"
            "    'firstExecutionId': first['executionId'],\n"
            "    'successorExecutionId': successor.get('executionId'),\n"
            "    'early': early,\n"
            "    'details': details,\n"
            "    'writes': writes,\n"
            "}"
        ),
    )
    assert first["successorExecutionId"] != first["firstExecutionId"], first
    assert first["early"]["status"] == "BLOCKED", first
    assert first["early"]["reasonCode"] == "STALE_SEMANTIC_RESULT", first
    assert first["writes"] == [], first
    assert first["details"] is None, first

    state = load_status(root)
    running = [
        item
        for item in state["executions"]
        if item.get("rootCommand") == root_command
        and item.get("status") == "running"
    ]
    assert len(running) == 1, running
    assert running[0]["executionId"] == first["successorExecutionId"], running


def test_stale_continuation_mutation_binding(root: Path) -> None:
    """Stale continuation guards must never mutate the newer invocation."""
    command = "PROJECT QUICK FIX: continuation authority"
    first = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    assert first["status"] == "SEMANTIC", first

    blocked = child_json(
        root,
        (
            "from command_dispatch import complete_dispatch\n"
            f"result = complete_dispatch(root, {command!r}, {command!r}, "
            f"'BLOCKED', execution_id={first['executionId']!r})"
        ),
    )
    assert blocked["status"] == "BLOCKED", blocked

    current = child_json(
        root,
        (
            "from command_dispatch import start_dispatch\n"
            f"result = start_dispatch(root, {command!r})"
        ),
    )
    assert current["status"] == "SEMANTIC", current
    assert current["executionId"] != first["executionId"], (first, current)

    # Both continuation mutations are canonical read-modify-write operations.
    # A stale owner must be rejected under the execution-state lock and must
    # leave the current invocation completely untouched.
    raced = child_json(
        root,
        (
            "from execution_status import begin_command, block_execution\n"
            f"command = {command!r}\n"
            f"stale_id = {first['executionId']!r}\n"
            "result = {}\n"
            "for name, callback in (\n"
            "    ('begin', lambda: begin_command(root, command, command, expected_execution_id=stale_id)),\n"
            "    ('block', lambda: block_execution(root, command, command=command, expected_execution_id=stale_id)),\n"
            "):\n"
            "    try:\n"
            "        callback()\n"
            "    except ValueError as exc:\n"
            "        result[name] = {'code': getattr(exc, 'code', None), 'message': str(exc)}\n"
            "    else:\n"
            "        result[name] = {'code': 'UNEXPECTED_SUCCESS'}"
        ),
    )
    assert raced["begin"]["code"] == "STALE_SEMANTIC_RESULT", raced
    assert raced["block"]["code"] == "STALE_SEMANTIC_RESULT", raced

    state = load_status(root)
    running = [
        item
        for item in state["executions"]
        if item.get("rootCommand") == command
        and item.get("status") == "running"
    ]
    assert len(running) == 1, running
    assert running[0]["executionId"] == current["executionId"], running
    assert running[0]["current"]["status"] == "running", running[0]
    assert running[0]["current"]["attempt"] == 1, running[0]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross-process reliable orchestration regressions."
    )
    parser.add_argument(
        "--authority-stress-iterations",
        type=int,
        default=1,
        help=(
            "Repeat only the concurrent authority fixture cleanup this many "
            "times when combined with --authority-stress-only."
        ),
    )
    parser.add_argument(
        "--authority-stress-only",
        action="store_true",
        help="Run only the concurrent authority cleanup stress scenario.",
    )
    args = parser.parse_args()
    if args.authority_stress_iterations < 1:
        parser.error("--authority-stress-iterations must be >= 1")
    return args


def _run_authority_scenario(iterations: int) -> None:
    for iteration in range(iterations):
        prefix = f"harness-fault-authority-{iteration:03d}-"
        with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
            root = Path(tmp)
            prepare(root)
            test_concurrent_stale_complete_vs_current_resume(root)


def main() -> int:
    args = _parse_args()

    if not args.authority_stress_only:
        with tempfile.TemporaryDirectory(prefix="harness-fault-intent-") as tmp:
            root = Path(tmp)
            prepare(root)
            test_crash_after_intent_snapshot(root)

        with tempfile.TemporaryDirectory(prefix="harness-fault-progress-") as tmp:
            root = Path(tmp)
            prepare(root)
            test_step_run_progress_survives_process_loss(root)

    _run_authority_scenario(args.authority_stress_iterations)

    if not args.authority_stress_only:
        with tempfile.TemporaryDirectory(prefix="harness-fault-atomic-authority-") as tmp:
            root = Path(tmp)
            prepare(root)
            test_atomic_completion_binding(root)

        with tempfile.TemporaryDirectory(prefix="harness-fault-continuation-authority-") as tmp:
            root = Path(tmp)
            prepare(root)
            test_stale_continuation_mutation_binding(root)

        with tempfile.TemporaryDirectory(prefix="harness-fault-evidence-authority-") as tmp:
            root = Path(tmp)
            prepare(root)
            test_stale_verification_evidence_publication(root)

    print("RELIABLE ORCHESTRATION FAULT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
