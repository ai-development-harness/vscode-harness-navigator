#!/usr/bin/env python3
"""Synthetic regression suite deterministic STEP Verification."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from command_dispatch import complete_dispatch, start_dispatch
import hashlib
import os
import time

from verification import CAPTURE_TAIL_BYTES, EVIDENCE_START, _run_command, run_step_verification


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> str:
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
    return proc.stdout.strip()


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
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def command_line(command: str) -> str:
    tick = chr(96)
    return f"- command: {tick}{command}{tick}"


def task(verification: str) -> str:
    return f"""---
schema: 1
id: STEP-001
status: in_progress
type: implementation
priority: medium
phase: test
depends_on: []
requirements: []
adrs: []
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

# STEP-001 — Verification fixture

## Goal

Проверить deterministic verification.

## Context

Synthetic fixture.

## Scope

- verification runner.

## Mutation policy

### Allowed

- planning/tasks/STEP-001.md.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product changes.

## Acceptance criteria

- Verification PASS.

## Verification

{verification}

## Deliverables

- Evidence.

## Implementation plan

Synthetic.

## Evidence

—

## Blocker / Failure reason

—
"""


def prepare(root: Path) -> None:
    copy_tracked(root)
    path = root / "planning/tasks/STEP-001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        task(
            command_line('python3 -c "print(123)"')
            + "\n- manual: Подтвердить semantic condition"
        ),
        encoding="utf-8",
        newline="\n",
    )
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "verification@example.invalid")
    run(root, "git", "config", "user.name", "Verification Test")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "fixture")


def reset(root: Path) -> None:
    run(root, "git", "reset", "--hard", "HEAD")
    run(root, "git", "clean", "-fd")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-verification-") as tmp:
        root = Path(tmp)
        prepare(root)
        step = root / "planning/tasks/STEP-001.md"

        # Automated command runs without shell; unresolved manual check prevents
        # false PASS and writes factual generated Evidence.
        pending = run_step_verification(root, "STEP-001")
        assert pending["status"] == "MANUAL_REQUIRED", pending
        assert pending["manualPending"] == ["Подтвердить semantic condition"], pending
        evidence = step.read_text(encoding="utf-8")
        assert EVIDENCE_START in evidence
        assert "stdout sha256:" in evidence

        # Exact manual confirmation completes the same contract.
        passed = run_step_verification(
            root,
            "STEP-001",
            manual_results=[
                {
                    "check": "Подтвердить semantic condition",
                    "status": "PASS",
                    "observed": "Condition observed.",
                }
            ],
        )
        assert passed["status"] == "PASS", passed
        assert passed["commands"][0]["exitCode"] == 0, passed
        assert passed["manual"][0]["status"] == "PASS", passed
        evidence = step.read_text(encoding="utf-8")
        assert "Condition observed." in evidence
        assert "Status: PASS" in evidence

        # Non-zero exit is factual FAIL, not LLM interpretation.
        reset(root)
        step.write_text(
            task(command_line('python3 -c "import sys; sys.exit(7)"')),
            encoding="utf-8",
            newline="\n",
        )
        failed = run_step_verification(root, "STEP-001")
        assert failed["status"] == "FAIL", failed
        assert failed["commands"][0]["exitCode"] == 7, failed

        # Verification is required to be read-only. Unexpected repository
        # mutation becomes BLOCKED and generated Evidence is not forged.
        reset(root)
        step.write_text(
            task(
                command_line(
                    'python3 -c "from pathlib import Path; '
                    + "Path('mutated.txt').write_text('x')"
                    + '"'
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        mutated = run_step_verification(root, "STEP-001")
        assert mutated["status"] == "BLOCKED", mutated
        assert mutated["reasonCode"] == "VERIFICATION_MUTATED_REPOSITORY", mutated
        assert (root / "mutated.txt").exists()
        assert EVIDENCE_START not in step.read_text(encoding="utf-8")

        # Shell control syntax is rejected instead of silently using shell=True.
        reset(root)
        step.write_text(
            task(command_line('python3 -c "print(1)" && echo unsafe')),
            encoding="utf-8",
            newline="\n",
        )
        unsafe = run_step_verification(root, "STEP-001")
        assert unsafe["status"] == "BLOCKED", unsafe
        assert unsafe["reasonCode"] == "VERIFICATION_RUNTIME_BLOCKED", unsafe

        # Regression #115: timeout убивает всю process group, включая внуков,
        # которые иначе продолжили бы работать после Verification.
        if os.name == "posix":
            reset(root)
            leak = root / "leaked-grandchild.txt"
            grandchild = (
                "import subprocess, sys, time; "
                "subprocess.Popen([sys.executable, '-c', "
                "'import time, pathlib; time.sleep(2); pathlib.Path(\\'leaked-grandchild.txt\\').write_text(\\'x\\')']); "
                "time.sleep(30)"
            )
            timed = _run_command(root, f'python3 -c "{grandchild}"', timeout_seconds=1)
            assert timed["status"] == "FAIL" and timed["reasonCode"] == "TIMEOUT", timed
            time.sleep(3)
            assert not leak.exists(), "grandchild survived verification timeout"

        # Regression #115: большой вывод учитывается полностью (hash/bytes),
        # но в памяти хранится только bounded tail.
        size = 5 * 1024 * 1024
        big = _run_command(
            root,
            f'python3 -c "import sys; sys.stdout.buffer.write(b\'a\' * {size}); sys.exit(3)"',
            timeout_seconds=60,
        )
        assert big["stdoutBytes"] == size, big["stdoutBytes"]
        assert big["stdoutSha256"] == hashlib.sha256(b"a" * size).hexdigest()
        assert big["status"] == "FAIL" and len(big["stdoutTail"] or "") <= CAPTURE_TAIL_BYTES

        # Regression #115: Verification не может создавать/двигать refs.
        reset(root)
        step.write_text(
            task(command_line("git tag verification-side-effect")),
            encoding="utf-8",
            newline="\n",
        )
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "refs fixture")
        refs_mutated = run_step_verification(root, "STEP-001")
        assert refs_mutated["status"] == "BLOCKED", refs_mutated
        assert refs_mutated["reasonCode"] == "VERIFICATION_MUTATED_REFS", refs_mutated
        run(root, "git", "tag", "-d", "verification-side-effect")
        run(root, "git", "reset", "-q", "--hard", "HEAD~1")

        # Dispatcher enforces the runner before FIX/IMPLEMENT SUCCESS. Manual
        # pending returns the same semantic command; confirmed checks allow DONE.
        reset(root)
        dispatch = start_dispatch(root, "STEP FIX STEP-001")
        assert dispatch["status"] == "SEMANTIC", dispatch
        first_complete = complete_dispatch(
            root,
            dispatch["rootCommand"],
            dispatch["command"],
            "SUCCESS",
        )
        assert first_complete["status"] == "SEMANTIC", first_complete
        assert first_complete["reasonCode"] == "VERIFICATION_MANUAL_REQUIRED", first_complete

        final = complete_dispatch(
            root,
            dispatch["rootCommand"],
            dispatch["command"],
            "SUCCESS",
            details={
                "manualVerification": [
                    {
                        "check": "Подтвердить semantic condition",
                        "status": "PASS",
                        "observed": "Confirmed by semantic reviewer.",
                    }
                ]
            },
        )
        assert final["status"] == "DONE", final

    print("VERIFICATION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
