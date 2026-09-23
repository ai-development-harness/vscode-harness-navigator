#!/usr/bin/env python3
"""Synthetic regression for deterministic Harness UX commands."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from execution_status import start_execution
from harness_ux import (
    harness_config,
    harness_resume,
    harness_status,
    step_list,
    step_show,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(args, cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-ux-v1-") as tmp:
        root = Path(tmp)
        write(
            root / ".harness/manifest.yaml",
            """harness:
  version: "1"
  release: "0.7.0"
project:
  initialized: true
  name: ux-self-test
execution:
  maxFixReviewCycles: 3
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
repository:
  gitPolicy: .harness/git-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
""",
        )
        write(
            root / ".harness/git-policy.toml",
            """[pull_request]
provider = "github"
preferred_tool = "gh"
""",
        )
        write(root / ".harness/harness-update.toml", "[source]\n")
        shutil.copy2(
            source / ".harness/command-transitions.json",
            root / ".harness/command-transitions.json",
        )
        write(
            root / "planning/tasks/STEP-001.md",
            """---
schema: 1
id: STEP-001
status: in_progress
type: implementation
priority: high
phase: test
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: test
  content_hash: test
  reviewed_report: null
  planned_at: null
---

# STEP-001 — UX self test
""",
        )

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "ux@example.invalid")
        run(root, "git", "config", "user.name", "UX Test")
        write(root / ".gitignore", ".harness/local/\n")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        listed = step_list(root)
        assert listed["status"] == "PASS", listed
        assert [item["id"] for item in listed["steps"]] == ["STEP-001"], listed

        shown = step_show(root, "001")
        assert shown["status"] == "PASS", shown
        assert shown["step"]["id"] == "STEP-001", shown
        assert shown["step"]["title"] == "UX self test", shown

        config = harness_config(root)
        assert config["status"] == "PASS", config
        assert config["sources"]["gitPolicy"] == ".harness/git-policy.toml", config

        status = harness_status(root)
        assert status["status"] == "PASS", status
        assert status["project"]["name"] == "ux-self-test", status
        assert status["git"]["branch"] == "main", status

        first = start_execution(root, "STEP RUN 001")
        resumed = harness_resume(root)
        assert resumed["status"] == "PASS", resumed
        assert resumed["executionId"] == first["executionId"], resumed
        assert resumed["command"] == "STEP RUN STEP-001", resumed

        start_execution(root, "GIT CHECK")
        ambiguous = harness_resume(root)
        assert ambiguous["status"] == "BLOCKED", ambiguous
        assert ambiguous["reasonCode"] == "MULTIPLE_RESUMABLE_EXECUTIONS", ambiguous

    print("HARNESS UX SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
