#!/usr/bin/env python3
"""Synthetic end-to-end regression deterministic Git preflight."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile

from git_preflight import (
    GitPreflightError,
    commit_preflight,
    pr_preflight,
    push_preflight,
    sync_preflight,
)


def run(root: Path, *args: str) -> str:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout.strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def policy() -> str:
    return """version = 1

[commit]
style = "conventional"
stage_mode = "all-safe"
subject_max_length = 72
require_body = true
require_harness_validation = true
require_single_logical_change = true
include_verification = true
include_traceability = true
allow_empty = false
sign = false

[commit.types]
feat = "feature"
fix = "fix"

[branch]
protected = ["main"]
when_on_protected = "auto-create"
allow_initial_commit_on_protected = true
name_pattern = "{prefix}/{slug}"
slug_max_length = 32

[branch.prefixes]
feat = "feature"
fix = "bugfix"

[push]
remote = "origin"
set_upstream = true
fetch_before_push = true
force = "never"
push_tags = false
allow_protected = false
allow_initial_push_to_protected = true
require_harness_validation = true
require_clean_worktree = false

[pull_request]
after_push = "create-if-missing"
provider = "github"
preferred_tool = "git"
base = "main"
draft = false
reuse_existing = true
title_from_commit = true
body_template = ".github/pull_request_template.md"

[sync]
fetch_remote = "origin"
mode = "ff-only"
"""


def manifest() -> str:
    return """repository:
  gitPolicy: .harness/git-policy.toml
"""


def validator() -> str:
    return """#!/usr/bin/env python3
print("HARNESS VALIDATION: PASS")
raise SystemExit(0)
"""


def expect_blocked(code: str, fn) -> GitPreflightError:
    try:
        fn()
    except GitPreflightError as exc:
        assert exc.code == code, (exc.code, exc)
        return exc
    raise AssertionError(f"expected blocker {code}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-git-preflight-") as tmp:
        base = Path(tmp)
        remote = base / "remote.git"
        run(base, "git", "init", "--bare", "-q", str(remote))

        project = base / "project"
        project.mkdir()
        run(project, "git", "init", "-q", "-b", "main")
        run(project, "git", "config", "user.email", "preflight@example.invalid")
        run(project, "git", "config", "user.name", "Preflight Test")
        run(project, "git", "remote", "add", "origin", str(remote))

        write(project, ".harness/manifest.yaml", manifest())
        write(project, ".harness/git-policy.toml", policy())
        write(project, ".harness/tools/validate.py", validator())
        write(project, ".github/pull_request_template.md", "# PR\n")
        write(project, "README.md", "base\n")
        run(project, "git", "add", ".")
        run(project, "git", "commit", "-qm", "initial")

        # Initial protected push is the only protected push allowed by policy.
        initial_push = push_preflight(project)
        assert initial_push["status"] == "PASS", initial_push
        assert initial_push["protected"] is True
        assert initial_push["initialRemotePush"] is True
        run(project, *initial_push["mutationPlan"]["argv"])

        # Subsequent commit on protected branch requires deterministic branch plan.
        write(project, "README.md", "base\nchange\n")
        run(project, "git", "add", "README.md")
        blocked = expect_blocked(
            "PROTECTED_BRANCH_REQUIRES_NEW_BRANCH",
            lambda: commit_preflight(project, commit_type="feat", slug="User Search API"),
        )
        assert blocked.details["requiredBranch"] == "feature/user-search-api", blocked.details

        # Agent creates exact planned branch, then final commit gate can pass.
        run(project, "git", "switch", "-c", blocked.details["requiredBranch"])
        commit_gate = commit_preflight(project, commit_type="feat", slug="User Search API")
        assert commit_gate["status"] == "PASS", commit_gate
        assert commit_gate["staged"] == ["README.md"], commit_gate
        run(project, "git", "commit", "-qm", "feat: change")

        # Existing protected branch cannot be pushed after bootstrap.
        run(project, "git", "switch", "main")
        expect_blocked("PROTECTED_BRANCH_PUSH_BLOCKED", lambda: push_preflight(project))
        run(project, "git", "switch", "feature/user-search-api")

        # New feature branch gets an exact non-force push plan with upstream setup.
        push_gate = push_preflight(project)
        assert push_gate["status"] == "PASS", push_gate
        assert "--set-upstream" in push_gate["mutationPlan"]["argv"], push_gate
        assert "--force" not in push_gate["mutationPlan"]["argv"], push_gate
        run(project, *push_gate["mutationPlan"]["argv"])

        # PR gate requires exact published HEAD and configured base/tool/template.
        pr_gate = pr_preflight(project)
        assert pr_gate["status"] == "PASS", pr_gate
        assert pr_gate["base"] == "main", pr_gate
        assert pr_gate["preferredTool"] == "git", pr_gate

        # Another clone advances the remote feature branch.
        other = base / "other"
        run(base, "git", "clone", "-q", str(remote), str(other))
        run(other, "git", "config", "user.email", "other@example.invalid")
        run(other, "git", "config", "user.name", "Other")
        run(other, "git", "switch", "feature/user-search-api")
        write(other, "remote.txt", "remote ahead\n")
        run(other, "git", "add", "remote.txt")
        run(other, "git", "commit", "-qm", "remote ahead")
        run(other, "git", "push", "-q", "origin", "feature/user-search-api")

        # PUSH blocks remote-ahead deterministically.
        expect_blocked("REMOTE_AHEAD", lambda: push_preflight(project))

        # SYNC ff-only is allowed only on a clean behind-only branch.
        sync_gate = sync_preflight(project)
        assert sync_gate["status"] == "PASS", sync_gate
        assert sync_gate["ahead"] == 0 and sync_gate["behind"] == 1, sync_gate
        assert sync_gate["mutationPlan"]["argv"] == [
            "git",
            "merge",
            "--ff-only",
            "origin/feature/user-search-api",
        ], sync_gate
        run(project, *sync_gate["mutationPlan"]["argv"])

        # Exact published revision restored after ff-only sync.
        pr_after_sync = pr_preflight(project)
        assert pr_after_sync["status"] == "PASS", pr_after_sync

        # Preflight сам fail-closed валидирует policy даже для action без
        # Harness validator invocation.
        broken_policy = policy().replace(
            '[sync]\nfetch_remote = "origin"',
            '[sync]\nfetch_remote = "origin"\nunknown_safety_key = true',
        )
        write(project, ".harness/git-policy.toml", broken_policy)
        expect_blocked("INVALID_GIT_POLICY", lambda: sync_preflight(project))
        write(project, ".harness/git-policy.toml", policy())

        # Local unpublished commit blocks PR until PUSH.
        write(project, "local.txt", "local only\n")
        run(project, "git", "add", "local.txt")
        run(project, "git", "commit", "-qm", "local")
        expect_blocked("HEAD_NOT_FULLY_PUBLISHED", lambda: pr_preflight(project))

    print("GIT PREFLIGHT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
