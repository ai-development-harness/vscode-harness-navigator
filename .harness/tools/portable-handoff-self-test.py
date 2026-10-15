#!/usr/bin/env python3
"""#300: переносимый Git handoff в двух независимых клонах, без auto-resume."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from portable_handoff import check_handoff, write_handoff
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> str:
    process = subprocess.run(
        args, cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=45,
    )
    assert process.returncode == 0, (args, process.stdout, process.stderr)
    return process.stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def step() -> str:
    return """---
schema: 1
id: STEP-017
status: in_progress
type: implementation
priority: high
phase: backend
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

# STEP-017 — Portable handoff test

## Goal

- Finish a feature without transferring the runtime session.

## Context

- A repository is shared by Git.

## Scope

- Preserve project intent and planned work.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated paths

## Out of scope

- Repeating external side effects.

## Acceptance criteria

- Published handoff cannot authorize unverified execution.

## Verification

- manual: inspect implementation

## Deliverables

- Git-backed handoff.

## Implementation plan

—

## Evidence

—

## Blocker / Failure reason

—
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-portable-handoff-") as temp:
        root = Path(temp)
        desktop = root / "desktop"
        laptop = root / "laptop"
        remote = root / "origin.git"
        desktop.mkdir()
        copy_effective_harness_checkout(SOURCE_ROOT, desktop)
        isolate_project_artifacts(desktop)

        manifest = desktop / ".harness/manifest.yaml"
        raw = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in raw
        write(manifest, raw.replace("initialized: false", "initialized: true", 1))
        task = desktop / "planning/tasks/STEP-017.md"
        write(task, step())

        run(root, "git", "init", "--bare", "-q", "-b", "main", str(remote))
        run(desktop, "git", "init", "-q", "-b", "main")
        run(desktop, "git", "config", "user.email", "portable@example.invalid")
        run(desktop, "git", "config", "user.name", "Portable Test")
        run(desktop, "git", "remote", "add", "origin", str(remote))
        run(desktop, "git", "add", ".")
        run(desktop, "git", "commit", "-qm", "fixture")
        before_handoff = run(desktop, "git", "rev-parse", "HEAD")
        run(desktop, "git", "push", "-q", "-u", "origin", "main")

        exported = write_handoff(desktop, "STEP-017")
        assert exported["status"] == "PASS", exported
        assert exported["safeToResume"] is False, exported
        assert exported["gitActionsExecuted"] is False, exported
        assert exported["sourceGitHead"] == before_handoff, exported
        target = desktop / exported["path"]
        assert target.exists(), target
        assert not run(desktop, "git", "ls-files", exported["path"]), exported

        # Handoff, который ещё не закоммичен, не является portable proof.
        premature = check_handoff(desktop, "STEP-017")
        assert premature["status"] == "BLOCKED", premature
        assert premature["reasonCode"] == "REPOSITORY_STATE_INVALID", premature

        run(desktop, "git", "add", exported["path"])
        run(desktop, "git", "commit", "-qm", "publish portable step handoff")
        run(desktop, "git", "push", "-q", "origin", "main")
        run(root, "git", "clone", "-q", "--branch", "main", str(remote), str(laptop))
        assert not (laptop / ".harness/local/execution/execution-status.json").exists()

        restored = check_handoff(laptop, "STEP-017")
        assert restored["status"] == "PASS", restored
        assert restored["reasonCode"] == "HANDOFF_PROVEN_NOT_EXECUTION", restored
        assert restored["safeToResume"] is False and restored["nextCommand"] is None
        assert restored["sourceGitHead"] == before_handoff

        raw_cli = run(
            laptop, sys.executable, ".harness/tools/portable-handoff.py",
            "--check", "--step", "STEP-017", "--json",
        )
        assert json.loads(raw_cli) == restored

        # Никакое расхождение с опубликованным STEP не может быть
        # замаскировано прежним handoff.
        laptop_task = laptop / "planning/tasks/STEP-017.md"
        changed = laptop_task.read_text(encoding="utf-8").replace(
            "Finish a feature", "Finish a changed feature"
        )
        write(laptop_task, changed)
        dirty = check_handoff(laptop, "STEP-017")
        assert dirty["status"] == "BLOCKED", dirty
        assert dirty["reasonCode"] == "REPOSITORY_STATE_INVALID", dirty

        run(laptop, "git", "config", "user.email", "portable@example.invalid")
        run(laptop, "git", "config", "user.name", "Portable Test")
        run(laptop, "git", "add", "planning/tasks/STEP-017.md")
        run(laptop, "git", "commit", "-qm", "change STEP intent")
        changed_head = check_handoff(laptop, "STEP-017")
        assert changed_head["reasonCode"] in {
            "HANDOFF_STEP_CHANGED", "HANDOFF_CONTRACT_STALE",
        }, changed_head

        # Вернуть чистый контрольный Git commit (disposable fixture).
        run(laptop, "git", "reset", "--hard", "HEAD~1")
        run(laptop, "git", "switch", "-q", "-c", "alternate")
        wrong_branch = check_handoff(laptop, "STEP-017")
        assert wrong_branch["reasonCode"] == "HANDOFF_BRANCH_CHANGED", wrong_branch
        run(laptop, "git", "switch", "-q", "main")
        assert check_handoff(laptop, "STEP-017")["status"] == "PASS"

        # #302: A продолжил писать product code после handoff publication,
        # но STEP/REQ/ADR не поменял. Старый ancestry-only proof пропускал
        # такой snapshot как актуальный — теперь он обязан быть BLOCKED.
        write(laptop / "src/continued.txt", "new code after handoff\n")
        run(laptop, "git", "add", "src/continued.txt")
        run(laptop, "git", "commit", "-qm", "product code advanced after handoff")
        outdated = check_handoff(laptop, "STEP-017")
        assert outdated["reasonCode"] == "HANDOFF_OUTDATED", outdated
        run(laptop, "git", "reset", "--hard", "HEAD~1")
        assert check_handoff(laptop, "STEP-017")["status"] == "PASS"

        # Даже если новый STEP/REQ не менялся, в publication commit нельзя
        # незаметно добавить product changes ПОСЛЕ формирования fingerprints.
        mixed = root / "mixed"
        run(root, "git", "clone", "-q", "--branch", "main", str(remote), str(mixed))
        run(mixed, "git", "config", "user.email", "portable@example.invalid")
        run(mixed, "git", "config", "user.name", "Portable Test")
        run(mixed, "git", "reset", "--hard", "HEAD~1")
        new_handoff = write_handoff(mixed, "STEP-017")
        assert new_handoff["status"] == "PASS", new_handoff
        write(mixed / "src/extra.txt", "unpublished changes with handoff\n")
        run(mixed, "git", "add", new_handoff["path"], "src/extra.txt")
        run(mixed, "git", "commit", "-qm", "invalid mixed handoff publication")
        mixed_result = check_handoff(mixed, "STEP-017")
        assert mixed_result["reasonCode"] == "HANDOFF_PUBLICATION_MIXED", mixed_result

        # Неизвестные поля, потенциальные credentials и session IDs
        # запрещены schema allowlist: writer/validator не импортирует их.
        handoff_path = laptop / restored["path"]
        record = json.loads(handoff_path.read_text(encoding="utf-8"))
        record["nativeSessionId"] = "provider-should-not-be-in-git"
        write(handoff_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        changed_file = check_handoff(laptop, "STEP-017")
        assert changed_file["status"] == "BLOCKED", changed_file
        run(laptop, "git", "add", restored["path"])
        run(laptop, "git", "commit", "-qm", "bad handoff payload fixture")
        bad = check_handoff(laptop, "STEP-017")
        assert bad["reasonCode"] == "HANDOFF_SCHEMA_INVALID", bad

        # Python bool — наследник int, но версия схемы должна быть
        # именно целочисленной. True нельзя читать как schemaVersion=1.
        record.pop("nativeSessionId")
        record["schemaVersion"] = True
        write(handoff_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
        run(laptop, "git", "add", restored["path"])
        run(laptop, "git", "commit", "-qm", "boolean schema fixture")
        invalid_version = check_handoff(laptop, "STEP-017")
        assert invalid_version["reasonCode"] == "HANDOFF_SCHEMA_INVALID", invalid_version

    print("PORTABLE HANDOFF SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
