#!/usr/bin/env python3
"""Synthetic end-to-end regression deterministic Git preflight."""
from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import tempfile

import git_action as git_action_module
from git_action import (
    execute_commit,
    execute_pr_finish,
    execute_push,
    execute_sync,
)
from git_preflight import (
    GitPreflightError,
    _planned_branch,
    commit_preflight,
    policy as load_policy,
    pr_preflight,
    pr_finish_preflight,
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


def expect_code(code: str, fn) -> Exception:
    """Как expect_blocked, но для GitActionError и GitPreflightError."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - проверяем structured code
        assert getattr(exc, "code", None) == code, (getattr(exc, "code", None), exc)
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
        initial_action = execute_push(project)
        assert initial_action["status"] == "SUCCESS", initial_action

        # Subsequent commit on protected branch requires deterministic branch plan.
        write(project, "README.md", "base\nchange\n")
        run(project, "git", "add", "README.md")
        blocked = expect_blocked(
            "PROTECTED_BRANCH_REQUIRES_NEW_BRANCH",
            lambda: commit_preflight(project, commit_type="feat", slug="User Search API"),
        )
        assert blocked.details["requiredBranch"] == "feature/user-search-api", blocked.details

        # Executor создаёт ровно required branch, повторяет preflight и commit,
        # используя semantic message как вход, но не оставляя mutation модели.
        message_file = project / ".harness/local/git/commit-message.txt"
        write(
            project,
            ".harness/local/git/commit-message.txt",
            "feat: change\n\nContext:\n- deterministic executor regression\n",
        )
        commit_action = execute_commit(
            project,
            commit_type="feat",
            slug="User Search API",
            message_file=message_file,
        )
        assert commit_action["status"] == "SUCCESS", commit_action
        assert commit_action["createdBranch"] == blocked.details["requiredBranch"], commit_action
        assert run(project, "git", "branch", "--show-current") == "feature/user-search-api"
        assert not message_file.exists()

        # Regression #89: Git должен получить validated in-memory snapshot, а
        # не повторно читать mutable commit-message path после validation.
        write(project, "snapshot-commit.txt", "snapshot\n")
        run(project, "git", "add", "snapshot-commit.txt")
        snapshot_message = project / ".harness/local/git/commit-message-snapshot.txt"
        write(
            project,
            ".harness/local/git/commit-message-snapshot.txt",
            "feat: captured snapshot\n\nContext:\n- validated before mutation\n",
        )
        original_action_run = git_action_module._run

        def racing_commit_run(
            action_root: Path,
            argv: list[str],
            *,
            input_text: str | None = None,
        ):
            if argv[:2] == ["git", "commit"]:
                snapshot_message.write_text(
                    "fix: raced message\n\nContext:\n- must not be committed\n",
                    encoding="utf-8",
                    newline="\n",
                )
            return original_action_run(
                action_root,
                argv,
                input_text=input_text,
            )

        git_action_module._run = racing_commit_run
        try:
            snapshot_action = execute_commit(
                project,
                commit_type="feat",
                slug="Snapshot Input",
                message_file=snapshot_message,
            )
        finally:
            git_action_module._run = original_action_run

        assert snapshot_action["status"] == "SUCCESS", snapshot_action
        assert snapshot_action["mutation"]["argv"][-2:] == ["-F", "-"], snapshot_action
        assert run(project, "git", "log", "-1", "--pretty=%s") == "feat: captured snapshot"
        assert snapshot_message.read_text(encoding="utf-8").startswith("fix: raced message")
        assert snapshot_action.get("cleanupWarnings"), snapshot_action
        snapshot_message.unlink()

        # Regression #85: commit input cleanup удаляет только exact validated
        # lexical transport path и не следует symlink к другому local state.
        write(project, "symlink-commit.txt", "staged\n")
        run(project, "git", "add", "symlink-commit.txt")

        failed_message = project / ".harness/local/git/commit-message-invalid.txt"
        write(
            project,
            ".harness/local/git/commit-message-invalid.txt",
            "not-a-conventional-subject\n",
        )
        try:
            execute_commit(
                project,
                commit_type="feat",
                slug="Failed Message",
                message_file=failed_message,
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == "COMMIT_MESSAGE_INVALID", exc
        else:
            raise AssertionError("invalid commit message was accepted")
        assert failed_message.is_file(), "failed commit deleted retry message"
        failed_message.unlink()

        message_target = project / ".harness/local/git/keep-message.txt"
        write(
            project,
            ".harness/local/git/keep-message.txt",
            "feat: protected target\n\nContext:\n- must survive\n",
        )
        message_link = project / ".harness/local/git/commit-message-link.txt"
        message_link.symlink_to("keep-message.txt")
        try:
            execute_commit(
                project,
                commit_type="feat",
                slug="Symlink Guard",
                message_file=message_link,
            )
        except Exception as exc:
            assert getattr(exc, "code", None) == "COMMIT_MESSAGE_PATH_BLOCKED", exc
        else:
            raise AssertionError("commit message symlink was accepted")
        assert message_link.is_symlink(), message_link
        assert message_target.is_file(), message_target
        run(project, "git", "reset", "--hard", "HEAD")
        message_link.unlink()
        message_target.unlink()

        # Regression #110: невалидный message на protected branch отклоняется
        # до `git switch -c` и не оставляет репозиторий на новой ветке.
        run(project, "git", "switch", "main")
        write(project, "early-message.txt", "staged\n")
        run(project, "git", "add", "early-message.txt")
        write(project, ".harness/local/git/early.txt", "bad subject\n")
        expect_code(
            "COMMIT_MESSAGE_INVALID",
            lambda: execute_commit(
                project,
                commit_type="feat",
                slug="Early Message",
                message_file=project / ".harness/local/git/early.txt",
            ),
        )
        assert run(project, "git", "branch", "--show-current") == "main"
        assert not run(project, "git", "branch", "--list", "feature/early-message")
        run(project, "git", "reset", "-q", "--hard", "HEAD")
        (project / ".harness/local/git/early.txt").unlink()
        run(project, "git", "switch", "feature/user-search-api")

        # Regression #110: commit type проверяется и вне protected branches.
        expect_blocked(
            "INVALID_COMMIT_TYPE",
            lambda: commit_preflight(project, commit_type="chore", slug="x"),
        )
        write(project, ".harness/local/git/type.txt", "chore: x\n\nContext:\n- y\n")
        expect_code(
            "INVALID_COMMIT_TYPE",
            lambda: execute_commit(
                project,
                commit_type="chore",
                slug="x",
                message_file=project / ".harness/local/git/type.txt",
            ),
        )
        (project / ".harness/local/git/type.txt").unlink()

        # Regression #110: лишний placeholder в name_pattern — BLOCKED, не KeyError.
        broken = load_policy(project)
        broken["branch"] = {**broken["branch"], "name_pattern": "{prefix}/{slug}-{extra}"}
        expect_blocked("INVALID_GIT_POLICY", lambda: _planned_branch(broken, "feat", "x"))

        # Regression #107: изменение индекса между validation и commit — BLOCKED,
        # HEAD не двигается.
        write(project, "toctou-a.txt", "a\n")
        run(project, "git", "add", "toctou-a.txt")
        write(project, ".harness/local/git/toctou.txt", "feat: toctou\n\nContext:\n- x\n")
        head_before = run(project, "git", "rev-parse", "HEAD")
        original_commit_preflight = git_action_module.commit_preflight

        def racing_commit_preflight(*args, **kwargs):
            gate = original_commit_preflight(*args, **kwargs)
            write(project, "toctou-b.txt", "unvalidated\n")
            run(project, "git", "add", "toctou-b.txt")
            return gate

        git_action_module.commit_preflight = racing_commit_preflight
        try:
            expect_code(
                "COMMIT_INPUT_CHANGED",
                lambda: execute_commit(
                    project,
                    commit_type="feat",
                    slug="toctou",
                    message_file=project / ".harness/local/git/toctou.txt",
                ),
            )
        finally:
            git_action_module.commit_preflight = original_commit_preflight
        assert run(project, "git", "rev-parse", "HEAD") == head_before
        run(project, "git", "reset", "-q", "--hard", "HEAD")
        (project / ".harness/local/git/toctou.txt").unlink()

        # Regression #110: non-UTF-8 имя файла не превращается в traceback.
        if os.name == "posix":
            raw_name = project / os.fsdecode(b"raw-\xff.txt")
            raw_name.write_text("x\n", encoding="utf-8")
            run(project, "git", "add", "-A")
            raw_gate = commit_preflight(project, commit_type="feat", slug="raw")
            assert raw_gate["status"] == "PASS", raw_gate
            assert any(name.startswith("raw-") for name in raw_gate["staged"]), raw_gate
            run(project, "git", "reset", "-q", "--hard", "HEAD")

        # Regression #107: ветка `+name` — это forced refspec; BLOCKED до push.
        run(project, "git", "switch", "-q", "-c", "+forced")
        expect_blocked("INVALID_BRANCH_NAME", lambda: push_preflight(project))
        run(project, "git", "switch", "-q", "feature/user-search-api")
        run(project, "git", "branch", "-D", "+forced")

        # Existing protected branch cannot be pushed after bootstrap.
        run(project, "git", "switch", "main")
        expect_blocked("PROTECTED_BRANCH_PUSH_BLOCKED", lambda: push_preflight(project))
        run(project, "git", "switch", "feature/user-search-api")

        # New feature branch gets an exact non-force push plan with upstream setup.
        push_gate = push_preflight(project)
        assert push_gate["status"] == "PASS", push_gate
        validated = run(project, "git", "rev-parse", "HEAD")
        # Regression #107: публикуется явный validated commit, а не имя ветки.
        assert push_gate["mutationPlan"]["argv"][-1] == (
            f"{validated}:refs/heads/feature/user-search-api"
        ), push_gate
        assert push_gate["mutationPlan"]["setUpstream"] is True, push_gate
        assert "--force" not in push_gate["mutationPlan"]["argv"], push_gate

        # Regression #107: HEAD сдвинулся после preflight — push BLOCKED.
        original_push_preflight = git_action_module.push_preflight

        def racing_push_preflight(*args, **kwargs):
            gate = original_push_preflight(*args, **kwargs)
            run(project, "git", "commit", "-q", "--allow-empty", "-m", "unvalidated")
            return gate

        git_action_module.push_preflight = racing_push_preflight
        try:
            expect_code("PUSH_INPUT_CHANGED", lambda: execute_push(project))
        finally:
            git_action_module.push_preflight = original_push_preflight
        run(project, "git", "reset", "-q", "--hard", validated)

        push_action = execute_push(project)
        assert push_action["status"] == "SUCCESS", push_action
        assert push_action["head"] == validated, push_action
        assert run(
            project, "git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
        ) == "origin/feature/user-search-api"
        assert push_action["afterPush"] == "create-if-missing", push_action

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
        sync_action = execute_sync(project)
        assert sync_action["status"] == "SUCCESS" and sync_action["mutated"] is True, sync_action

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


        # Independent merged-PR lifecycle regression. Provider metadata is injected
        # directly so test remains network-free; Git ancestry/state stays real.
        finish_remote = base / "finish-remote.git"
        run(base, "git", "init", "--bare", "-q", str(finish_remote))
        finish_project = base / "finish-project"
        finish_project.mkdir()
        run(finish_project, "git", "init", "-q", "-b", "main")
        run(finish_project, "git", "config", "user.email", "finish@example.invalid")
        run(finish_project, "git", "config", "user.name", "Finish Test")
        run(finish_project, "git", "remote", "add", "origin", str(finish_remote))
        write(finish_project, ".harness/manifest.yaml", manifest())
        write(finish_project, ".harness/git-policy.toml", policy())
        write(finish_project, ".harness/tools/validate.py", validator())
        write(finish_project, ".github/pull_request_template.md", "# PR\n")
        write(finish_project, ".gitignore", ".harness/local/\n")
        write(finish_project, "README.md", "finish base\n")
        run(finish_project, "git", "add", ".")
        run(finish_project, "git", "commit", "-qm", "initial")
        run(finish_project, "git", "push", "-q", "-u", "origin", "main")
        run(finish_project, "git", "switch", "-c", "feature/finish")
        write(finish_project, "finish.txt", "done\n")
        run(finish_project, "git", "add", "finish.txt")
        run(finish_project, "git", "commit", "-qm", "feat: finish")
        run(finish_project, "git", "push", "-q", "-u", "origin", "feature/finish")
        finish_head = run(finish_project, "git", "rev-parse", "HEAD")

        merger = base / "finish-merger"
        run(base, "git", "clone", "-q", str(finish_remote), str(merger))
        run(merger, "git", "config", "user.email", "merge@example.invalid")
        run(merger, "git", "config", "user.name", "Merge Test")
        run(merger, "git", "switch", "-c", "main", "--track", "origin/main")
        run(merger, "git", "merge", "--squash", "origin/feature/finish")
        run(merger, "git", "commit", "-qm", "squash PR")
        run(merger, "git", "push", "-q", "origin", "main")

        pr_state = {
            "version": 1,
            "pr": 42,
            "headBranch": "feature/finish",
            "baseBranch": "main",
            "returnBranch": "main",
            "url": "https://example.invalid/pr/42",
        }
        write(
            finish_project,
            ".harness/local/git/pr-state.json",
            json.dumps(pr_state, ensure_ascii=False, indent=2) + "\n",
        )
        merged_pr = {
            "number": 42,
            "state": "MERGED",
            "mergedAt": "2026-09-22T00:00:00Z",
            "headRefName": "feature/finish",
            "headRefOid": finish_head,
            "baseRefName": "main",
            "url": "https://example.invalid/pr/42",
        }

        write(finish_project, "dirty.tmp", "dirty\n")
        expect_blocked(
            "PR_FINISH_DIRTY_WORKTREE",
            lambda: pr_finish_preflight(finish_project, pr_data=merged_pr),
        )
        (finish_project / "dirty.tmp").unlink()

        finish_gate = pr_finish_preflight(finish_project, pr_data=merged_pr)
        assert finish_gate["status"] == "PASS", finish_gate
        assert finish_gate["returnBranch"] == "main", finish_gate
        assert finish_gate["resumed"] is False, finish_gate
        assert finish_gate["gitAncestryMerged"] is False, finish_gate
        assert finish_gate["mergedHeadOid"] == finish_head, finish_gate
        assert finish_gate["mutationPlan"]["steps"][-1]["mode"] == "provider-verified-head", finish_gate
        assert finish_gate["mutationPlan"]["steps"][-1]["argv"] == [
            "git", "update-ref", "-d", "refs/heads/feature/finish", finish_head
        ], finish_gate
        assert finish_gate["mutationPlan"]["forceDeleteForbidden"] is True
        assert finish_gate["mutationPlan"]["deleteRemoteBranch"] is False

        # Crash-window regression: первый mutation step уже успел переключить
        # return branch, но local PR state и feature ref ещё существуют.
        run(finish_project, "git", "switch", "main")
        resumed_gate = pr_finish_preflight(finish_project, pr_data=merged_pr)
        assert resumed_gate["status"] == "PASS", resumed_gate
        assert resumed_gate["resumed"] is True, resumed_gate
        assert resumed_gate["currentBranch"] == "main", resumed_gate
        assert all(
            step["operation"] != "switch-return-branch"
            for step in resumed_gate["mutationPlan"]["steps"]
        ), resumed_gate

        finish_action = execute_pr_finish(finish_project, pr_data=merged_pr)
        assert finish_action["status"] == "SUCCESS", finish_action
        assert finish_action["returnBranch"] == "main", finish_action
        assert finish_action["stateFileDeleted"] is True, finish_action
        assert run(finish_project, "git", "branch", "--show-current") == "main"
        assert not (finish_project / ".harness/local/git/pr-state.json").exists()
        missing = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/feature/finish"],
            cwd=finish_project,
        )
        assert missing.returncode != 0

        # Второе crash-window: branch cleanup завершён, но state file удалить
        # не успели. Повторный FINISH должен стать безопасным no-op + state cleanup.
        write(
            finish_project,
            ".harness/local/git/pr-state.json",
            json.dumps(pr_state, ensure_ascii=False, indent=2) + "\n",
        )
        cleanup_gate = pr_finish_preflight(finish_project, pr_data=merged_pr)
        assert cleanup_gate["status"] == "PASS", cleanup_gate
        assert cleanup_gate["resumed"] is True, cleanup_gate
        assert cleanup_gate["mutationPlan"]["steps"] == [], cleanup_gate
        cleanup_action = execute_pr_finish(finish_project, pr_data=merged_pr)
        assert cleanup_action["status"] == "SUCCESS", cleanup_action
        assert not (finish_project / ".harness/local/git/pr-state.json").exists()

    print("GIT PREFLIGHT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
