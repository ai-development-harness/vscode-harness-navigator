#!/usr/bin/env python3
"""Deterministic executor безопасных Git mutations после preflight.

Semantic inputs остаются у модели/пользователя: staging scope, commit type,
commit message и PR prose. После этого mechanical mutation выполняет этот tool:
он повторно запускает canonical preflight, исполняет разрешённый Git/provider
action и проверяет postcondition. Provider mechanics GIT PR также deterministic:
модель задаёт только semantic title/body, а find/reuse/create/state делает tool.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import atomic_write_text
from harness_config import ConfigError
from git_preflight import (
    GitPreflightError,
    PR_STATE_PATH,
    Repo,
    commit_preflight,
    pr_finish_preflight,
    pr_preflight,
    push_preflight,
    sync_preflight,
)


class GitActionError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details


def _run(
    root: Path,
    argv: list[str],
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Выполнить deterministic mutation, передавая captured semantic input по stdin."""
    proc = subprocess.run(
        argv,
        cwd=root,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise GitActionError(
            "MUTATION_FAILED",
            proc.stderr.strip() or proc.stdout.strip() or "Git mutation failed",
            argv=argv,
            exitCode=proc.returncode,
        )
    return proc


def _safe_local_git_input(
    root: Path,
    value: Path,
    *,
    label: str,
    blocked_code: str,
    missing_code: str,
) -> Path:
    """Вернуть exact lexical input path и запретить symlink traversal."""
    base = root.resolve()
    allowed = base / ".harness" / "local" / "git"
    if ".." in value.parts:
        raise GitActionError(
            blocked_code,
            f"{label} file must stay under .harness/local/git/ without '..'",
        )
    candidate = value if value.is_absolute() else base / value
    candidate = Path(os.path.abspath(str(candidate)))

    try:
        rel_root = candidate.relative_to(base)
        rel_allowed = candidate.relative_to(allowed)
    except ValueError as exc:
        raise GitActionError(
            blocked_code,
            f"{label} file must stay under .harness/local/git/",
        ) from exc
    if not rel_allowed.parts:
        raise GitActionError(
            missing_code,
            f"{label} file must be a regular file: {candidate}",
        )

    cursor = base
    for part in rel_root.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GitActionError(
                blocked_code,
                f"{label} file path must not contain symlinks",
            )

    if not candidate.is_file():
        raise GitActionError(
            missing_code,
            f"{label} file must be a regular file: {candidate}",
        )
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise GitActionError(
            blocked_code,
            f"{label} file escapes .harness/local/git/",
        ) from exc
    return candidate


def _message_path(root: Path, value: Path) -> Path:
    return _safe_local_git_input(
        root,
        value,
        label="commit message",
        blocked_code="COMMIT_MESSAGE_PATH_BLOCKED",
        missing_code="COMMIT_MESSAGE_MISSING",
    )


def _input_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat(follow_symlinks=False)
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _cleanup_consumed_input(
    path: Path | None,
    identity: tuple[int, int, int, int] | None,
) -> str | None:
    """Best-effort unlink exact consumed file; primary side effect уже SUCCESS."""
    if path is None or identity is None:
        return None
    try:
        if path.is_symlink():
            return f"cleanup skipped for {path}: path became a symlink"
        if not path.exists():
            return None
        if _input_identity(path) != identity:
            return f"cleanup skipped for {path}: input changed after consumption"
        path.unlink()
    except OSError as exc:
        return f"cleanup failed for {path}: {exc}"
    return None


def _validate_commit_message(
    message: str,
    *,
    commit_type: str,
    gate: dict[str, Any],
) -> None:
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    checks = gate.get("semanticChecks", {})
    limit = checks.get("subjectMaxLength")
    if not subject:
        raise GitActionError("COMMIT_MESSAGE_INVALID", "commit subject is empty")
    if isinstance(limit, int) and len(subject) > limit:
        raise GitActionError(
            "COMMIT_MESSAGE_INVALID",
            f"commit subject exceeds configured limit {limit}",
        )
    if checks.get("messageStyle") == "conventional":
        pattern = rf"^{re.escape(commit_type)}(?:\([^)]+\))?!?:\s+\S"
        if re.match(pattern, subject) is None:
            raise GitActionError(
                "COMMIT_MESSAGE_INVALID",
                f"subject must be Conventional Commit with type {commit_type}",
            )
    if checks.get("requireBody") and not any(line.strip() for line in lines[1:]):
        raise GitActionError("COMMIT_MESSAGE_INVALID", "commit body is required by policy")


def execute_commit(
    root: Path,
    *,
    commit_type: str,
    slug: str,
    message_file: Path,
) -> dict[str, Any]:
    """Создать commit; при exact protected-branch plan создать required branch."""
    repo = Repo(root)
    created_branch: str | None = None
    try:
        gate = commit_preflight(root, commit_type=commit_type, slug=slug)
    except GitPreflightError as exc:
        if exc.code != "PROTECTED_BRANCH_REQUIRES_NEW_BRANCH":
            raise
        required = exc.details.get("requiredBranch")
        if not isinstance(required, str) or not required:
            raise GitActionError(
                "REQUIRED_BRANCH_UNRESOLVED",
                "preflight requires branch creation but returned no exact branch",
            ) from exc
        exists = repo.git(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{required}",
            check=False,
        )
        if exists.returncode == 0:
            raise GitActionError(
                "REQUIRED_BRANCH_EXISTS",
                f"required branch already exists: {required}",
            ) from exc
        _run(root, ["git", "switch", "-c", required])
        if Repo(root).branch() != required:
            raise GitActionError("BRANCH_POSTCONDITION_FAILED", "created branch is not current")
        created_branch = required
        gate = commit_preflight(root, commit_type=commit_type, slug=slug)

    path = _message_path(root, message_file)
    message_identity = _input_identity(path)
    message = path.read_text(encoding="utf-8")
    if _input_identity(path) != message_identity:
        raise GitActionError(
            "COMMIT_MESSAGE_CHANGED",
            "commit message file changed while being read",
        )
    _validate_commit_message(message, commit_type=commit_type, gate=gate)

    before = Repo(root).head()
    argv = ["git", "commit"]
    if gate.get("sign"):
        argv.append("-S")
    if gate.get("allowEmpty") and not gate.get("staged"):
        argv.append("--allow-empty")
    # Git должен потребить ровно ту строку, которую Harness уже прочитал и
    # провалидировал. Повторное чтение mutable path через "-F <file>" создаёт
    # TOCTOU между validation и primary side effect при concurrent sessions.
    argv.extend(["-F", "-"])
    _run(root, argv, input_text=message)
    after = Repo(root).head()
    if not after or after == before:
        raise GitActionError("COMMIT_POSTCONDITION_FAILED", "Git HEAD did not advance")

    cleanup_warning = _cleanup_consumed_input(path, message_identity)
    result = {
        "status": "SUCCESS",
        "action": "commit",
        "branch": Repo(root).branch(),
        "createdBranch": created_branch,
        "head": after,
        "mutation": {"argv": argv},
    }
    if cleanup_warning is not None:
        result["cleanupWarnings"] = [cleanup_warning]
    return result


def execute_push(root: Path) -> dict[str, Any]:
    gate = push_preflight(root)
    plan = gate.get("mutationPlan", {})
    argv = plan.get("argv")
    if not isinstance(argv, list) or argv[:2] != ["git", "push"]:
        raise GitActionError("UNSAFE_MUTATION_PLAN", "push preflight returned invalid argv")
    if any(str(item).startswith("--force") or item == "-f" for item in argv):
        raise GitActionError("UNSAFE_MUTATION_PLAN", "force push is forbidden")
    head = Repo(root).head()
    _run(root, [str(item) for item in argv])
    repo = Repo(root)
    remote_head = repo.remote_ref(str(gate["remote"]), str(gate["branch"]))
    if head is None or remote_head != head:
        raise GitActionError(
            "PUSH_POSTCONDITION_FAILED",
            "configured remote branch does not match local HEAD after push",
            localHead=head,
            remoteHead=remote_head,
        )
    return {
        "status": "SUCCESS",
        "action": "push",
        "branch": gate["branch"],
        "remote": gate["remote"],
        "head": head,
        "afterPush": gate.get("afterPush"),
        "mutation": {"argv": argv},
    }


def _pr_input_path(root: Path, value: Path, *, label: str) -> Path:
    """Разрешить semantic PR input без symlink traversal."""
    return _safe_local_git_input(
        root,
        value,
        label=label,
        blocked_code="PR_INPUT_PATH_BLOCKED",
        missing_code="PR_INPUT_MISSING",
    )


def _provider_json(root: Path, argv: list[str]) -> Any:
    proc = subprocess.run(
        argv,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise GitActionError(
            "PR_PROVIDER_FAILED",
            proc.stderr.strip() or proc.stdout.strip() or "PR provider command failed",
            argv=argv,
            exitCode=proc.returncode,
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitActionError(
            "PR_PROVIDER_INVALID_JSON",
            "PR provider returned invalid JSON",
            argv=argv,
        ) from exc


def _open_prs(root: Path, gate: dict[str, Any]) -> list[dict[str, Any]]:
    """Query exact open head/base PRs through configured provider tool."""
    tool = str(gate["preferredTool"])
    if gate.get("provider") != "github" or tool != "gh":
        raise GitActionError(
            "PR_PROVIDER_UNSUPPORTED",
            "deterministic PR action currently supports provider=github, tool=gh",
        )
    data = _provider_json(
        root,
        [
            tool,
            "pr",
            "list",
            "--head",
            str(gate["branch"]),
            "--base",
            str(gate["base"]),
            "--state",
            "open",
            "--limit",
            "10",
            "--json",
            "number,url,state,headRefName,headRefOid,baseRefName,isDraft,title",
        ],
    )
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise GitActionError("PR_PROVIDER_INVALID_JSON", "PR list must be a JSON array")
    exact = [
        item
        for item in data
        if item.get("headRefName") == gate["branch"]
        and item.get("baseRefName") == gate["base"]
        and item.get("state") == "OPEN"
    ]
    return exact


def _validate_provider_pr(gate: dict[str, Any], item: dict[str, Any]) -> None:
    number = item.get("number")
    url = item.get("url")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise GitActionError("PR_PROVIDER_INVALID_JSON", "PR number is missing or invalid")
    if not isinstance(url, str) or not url.strip():
        raise GitActionError("PR_PROVIDER_INVALID_JSON", "PR URL is missing")
    if item.get("headRefName") != gate["branch"]:
        raise GitActionError("PR_POSTCONDITION_FAILED", "provider PR head branch mismatch")
    if item.get("baseRefName") != gate["base"]:
        raise GitActionError("PR_POSTCONDITION_FAILED", "provider PR base branch mismatch")
    if item.get("headRefOid") != gate["publishedHead"]:
        raise GitActionError(
            "PR_POSTCONDITION_FAILED",
            "provider PR head OID does not match exact published HEAD",
            expected=gate["publishedHead"],
            actual=item.get("headRefOid"),
        )


def _return_branch(root: Path, *, head: str, base: str) -> str:
    repo = Repo(root)
    previous = repo.git(
        "rev-parse",
        "--abbrev-ref",
        "@{-1}",
        check=False,
    )
    candidate = previous.stdout.strip() if previous.returncode == 0 else ""
    if candidate and candidate not in {"HEAD", head}:
        exists = repo.git(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{candidate}",
            check=False,
        )
        if exists.returncode == 0:
            return candidate

    base_exists = repo.git(
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{base}",
        check=False,
    )
    if base_exists.returncode:
        raise GitActionError(
            "PR_RETURN_BRANCH_MISSING",
            f"neither previous local branch nor PR base exists locally: {base}",
        )
    return base


def _persist_pr_state(
    root: Path,
    *,
    gate: dict[str, Any],
    item: dict[str, Any],
) -> str:
    path = root / PR_STATE_PATH
    return_branch = _return_branch(
        root,
        head=str(gate["branch"]),
        base=str(gate["base"]),
    )
    state = {
        "version": 1,
        "pr": item["number"],
        "headBranch": gate["branch"],
        "baseBranch": gate["base"],
        "returnBranch": return_branch,
        "url": item["url"],
    }

    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GitActionError(
                "INVALID_PR_STATE",
                f"cannot read existing {PR_STATE_PATH}: {exc}",
            ) from exc
        identity = ("pr", "headBranch", "baseBranch")
        if any(existing.get(key) != state[key] for key in identity):
            raise GitActionError(
                "PR_STATE_CONFLICT",
                "existing local PR state belongs to another PR/head/base",
            )
        # Preserve a previously proven return branch across idempotent re-run
        # only while that local ref still exists and is not the PR head.
        previous_return = existing.get("returnBranch")
        if isinstance(previous_return, str) and previous_return.strip():
            valid_return = Repo(root).git(
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{previous_return}",
                check=False,
            )
            if valid_return.returncode == 0 and previous_return != gate["branch"]:
                state["returnBranch"] = previous_return

    atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return path.relative_to(root).as_posix()


def execute_pr(
    root: Path,
    *,
    title_file: Path | None = None,
    body_file: Path | None = None,
) -> dict[str, Any]:
    """Find/reuse/create GitHub PR and persist deterministic local lifecycle state."""
    gate = pr_preflight(root)
    body_path = (
        _pr_input_path(root, body_file, label="PR body")
        if body_file is not None
        else None
    )
    title_path = (
        _pr_input_path(root, title_file, label="PR title")
        if title_file is not None
        else None
    )
    body_identity = _input_identity(body_path) if body_path is not None else None
    title_identity = _input_identity(title_path) if title_path is not None else None
    existing = _open_prs(root, gate)
    if len(existing) > 1:
        raise GitActionError(
            "PR_AMBIGUOUS",
            "multiple open PRs match configured head/base",
            prs=[item.get("number") for item in existing],
        )

    reused = bool(existing)
    if existing:
        if not gate.get("reuseExisting"):
            raise GitActionError(
                "PR_ALREADY_EXISTS",
                "an open PR already exists and pull_request.reuse_existing=false",
                pr=existing[0].get("number"),
            )
        item = existing[0]
    else:
        if body_file is None:
            raise GitActionError(
                "PR_BODY_REQUIRED",
                "creating a PR requires --body-file",
            )
        assert body_path is not None
        body = body_path.read_text(encoding="utf-8")
        if _input_identity(body_path) != body_identity:
            raise GitActionError(
                "PR_BODY_CHANGED",
                "PR body file changed while being read",
            )
        if not body.strip():
            raise GitActionError("PR_BODY_INVALID", "PR body must not be empty")

        if gate.get("titleFromCommit"):
            title = Repo(root).git("log", "-1", "--pretty=%s").stdout.strip()
        else:
            if title_file is None:
                raise GitActionError(
                    "PR_TITLE_REQUIRED",
                    "policy requires semantic --title-file",
                )
            assert title_path is not None
            title = title_path.read_text(encoding="utf-8").strip()
            if _input_identity(title_path) != title_identity:
                raise GitActionError(
                    "PR_TITLE_CHANGED",
                    "PR title file changed while being read",
                )
        if not title or "\n" in title or "\r" in title:
            raise GitActionError("PR_TITLE_INVALID", "PR title must be one non-empty line")

        argv = [
            str(gate["preferredTool"]),
            "pr",
            "create",
            "--head",
            str(gate["branch"]),
            "--base",
            str(gate["base"]),
            "--title",
            title,
            "--body-file",
            "-",
        ]
        if gate.get("draft"):
            argv.append("--draft")
        # GitHub CLI поддерживает --body-file -; provider получает captured
        # body через stdin и больше не переоткрывает mutable semantic input.
        _run(root, argv, input_text=body)

        existing = _open_prs(root, gate)
        if len(existing) != 1:
            raise GitActionError(
                "PR_POSTCONDITION_FAILED",
                "provider did not expose exactly one open PR after create",
                matchCount=len(existing),
            )
        item = existing[0]

    _validate_provider_pr(gate, item)
    state_file = _persist_pr_state(root, gate=gate, item=item)

    # Semantic title/body — одноразовый transport. Удаляем только после
    # provider postcondition + durable pr-state; на любом предыдущем exception
    # inputs остаются для диагностики/retry.
    cleanup_warnings = [
        warning
        for warning in (
            _cleanup_consumed_input(body_path, body_identity),
            _cleanup_consumed_input(title_path, title_identity),
        )
        if warning is not None
    ]

    result = {
        "status": "SUCCESS",
        "action": "pr",
        "pr": item["number"],
        "url": item["url"],
        "branch": gate["branch"],
        "base": gate["base"],
        "head": gate["publishedHead"],
        "reused": reused,
        "draft": bool(item.get("isDraft")),
        "stateFile": state_file,
    }
    if cleanup_warnings:
        result["cleanupWarnings"] = cleanup_warnings
    return result


def execute_sync(root: Path) -> dict[str, Any]:
    gate = sync_preflight(root)
    plan = gate.get("mutationPlan", {})
    operation = plan.get("operation")
    if operation in {"report", "noop"}:
        return {
            "status": "SUCCESS",
            "action": "sync",
            "mutated": False,
            "branch": gate["branch"],
            "ahead": gate.get("ahead"),
            "behind": gate.get("behind"),
        }

    argv = plan.get("argv")
    expected_prefix = ["git", "merge", "--ff-only"]
    if not isinstance(argv, list) or argv[:3] != expected_prefix:
        raise GitActionError("UNSAFE_MUTATION_PLAN", "sync preflight returned non-ff-only argv")
    _run(root, [str(item) for item in argv])
    repo = Repo(root)
    head = repo.head()
    remote_head = repo.remote_ref(str(gate["remote"]), str(gate["branch"]))
    if head is None or remote_head != head:
        raise GitActionError(
            "SYNC_POSTCONDITION_FAILED",
            "local HEAD does not match configured remote after ff-only sync",
        )
    return {
        "status": "SUCCESS",
        "action": "sync",
        "mutated": True,
        "branch": gate["branch"],
        "head": head,
        "mutation": {"argv": argv},
    }


def execute_pr_finish(
    root: Path,
    *,
    pr_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate = pr_finish_preflight(root, pr_data=pr_data)
    steps = gate.get("mutationPlan", {}).get("steps")
    if not isinstance(steps, list):
        raise GitActionError("UNSAFE_MUTATION_PLAN", "PR finish plan has no ordered steps")

    executed: list[dict[str, Any]] = []
    for step in steps:
        argv = step.get("argv") if isinstance(step, dict) else None
        if not isinstance(argv, list) or not argv or argv[0] != "git":
            raise GitActionError("UNSAFE_MUTATION_PLAN", "PR finish contains invalid argv")
        _run(root, [str(item) for item in argv])
        executed.append({"operation": step.get("operation"), "argv": argv})

    repo = Repo(root)
    if repo.branch() != gate["returnBranch"]:
        raise GitActionError(
            "PR_FINISH_POSTCONDITION_FAILED",
            "current branch does not match verified return branch",
        )
    removed = repo.git(
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{gate['branch']}",
        check=False,
    )
    if removed.returncode == 0:
        raise GitActionError(
            "PR_FINISH_POSTCONDITION_FAILED",
            "verified PR head branch still exists locally",
        )

    state_file = gate.get("stateFile")
    if gate.get("deleteStateFileAfterSuccess") and isinstance(state_file, str):
        (root / state_file).unlink(missing_ok=True)

    return {
        "status": "SUCCESS",
        "action": "pr-finish",
        "pr": gate["pr"],
        "returnBranch": gate["returnBranch"],
        "executed": executed,
        "stateFileDeleted": bool(gate.get("deleteStateFileAfterSuccess")),
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Git mutation executor")
    parser.add_argument("action", choices=["commit", "push", "pr", "sync", "pr-finish"])
    parser.add_argument("--commit-type")
    parser.add_argument("--slug")
    parser.add_argument("--message-file", type=Path)
    parser.add_argument("--title-file", type=Path)
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = repo_root()

    try:
        if args.action == "commit":
            if not args.commit_type or not args.slug or args.message_file is None:
                raise GitActionError(
                    "COMMIT_INPUT_REQUIRED",
                    "commit requires --commit-type, --slug and --message-file",
                )
            result = execute_commit(
                root,
                commit_type=args.commit_type,
                slug=args.slug,
                message_file=args.message_file,
            )
        elif args.action == "push":
            result = execute_push(root)
        elif args.action == "pr":
            result = execute_pr(
                root,
                title_file=args.title_file,
                body_file=args.body_file,
            )
        elif args.action == "sync":
            result = execute_sync(root)
        else:
            result = execute_pr_finish(root)
    except (GitActionError, GitPreflightError, ConfigError, OSError, UnicodeError) as exc:
        code = getattr(exc, "code", "CONFIG_OR_IO_ERROR")
        result = {
            "status": "BLOCKED",
            "action": args.action,
            "reasonCode": code,
            "message": str(exc),
        }
        details = getattr(exc, "details", None)
        if details:
            result["details"] = details
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"BLOCKED: {code}: {exc}")
        return 2

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"SUCCESS: {args.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
