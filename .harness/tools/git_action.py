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
import secrets
import subprocess
from typing import Any

GIT_MUTATION_TIMEOUT_SECONDS = 120
PR_PROVIDER_TIMEOUT_SECONDS = 60

from document_contract import atomic_write_text
from execution_status import read_side_effect_checkpoint, write_side_effect_checkpoint
from side_effect_recovery import recovery_decision
from harness_config import ConfigError
from git_preflight import (
    GitPreflightError,
    PR_STATE_PATH,
    Repo,
    commit_preflight,
    commit_semantic_checks,
    policy,
    pr_finish_preflight,
    pr_preflight,
    push_preflight,
    sync_preflight,
)
from pr_provider import (
    ProviderError,
    create_pr as provider_create_pr,
    open_prs as provider_open_prs,
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
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Выполнить deterministic mutation, передавая captured semantic input по stdin."""
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            env={**os.environ, **env} if env else None,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=GIT_MUTATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitActionError(
            "MUTATION_TIMEOUT",
            f"Git mutation timed out after {GIT_MUTATION_TIMEOUT_SECONDS}s",
            argv=argv,
            timeoutSeconds=GIT_MUTATION_TIMEOUT_SECONDS,
        ) from exc
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


def _commit_snapshot(root: Path) -> dict[str, str | None]:
    """Branch, HEAD и дерево индекса — то, что проверяет preflight/validator."""
    repo = Repo(root)
    return {
        "branch": repo.branch(),
        "head": repo.head(),
        "tree": repo.git("write-tree").stdout.strip(),
    }


# Reflog-запись `git commit` пишется под тем же ref lock, что и сам update ref,
# поэтому уникальный GIT_REFLOG_ACTION доказывает, какой commit создал именно
# этот вызов, — независимо от hooks, меняющих index или message (#131).
REFLOG_SCAN_LIMIT = 64


def _commit_marker() -> str:
    return f"harness-commit {secrets.token_hex(8)}"


def _commit_created_by(repo: Repo, marker: str) -> dict[str, str] | None:
    """Exact local branch ref + OID, созданные этим `git commit`.

    Hook может переключить branch до primary commit, поэтому искать marker
    только в validated branch недостаточно. Сканируем reflog всех local branch
    refs и принимаем ownership только при единственной паре (ref, OID).
    """
    refs = [
        item.strip()
        for item in repo.git("for-each-ref", "--format=%(refname)", "refs/heads").stdout.splitlines()
        if item.strip()
    ]
    matches: set[tuple[str, str]] = set()
    for ref in refs:
        log = repo.git(
            "log", "-g", "-n", str(REFLOG_SCAN_LIMIT), "--format=%H%x00%gs",
            ref, check=False,
        )
        for line in log.stdout.splitlines():
            oid, _, subject = line.partition("\0")
            if subject.startswith(marker + ":"):
                matches.add((ref, oid))
    if not matches:
        # Hook перевёл HEAD в detached state: primary commit сдвинул сам HEAD,
        # и marker есть только в reflog HEAD.
        detached = repo.git("symbolic-ref", "-q", "HEAD", check=False).returncode != 0
        log = repo.git(
            "log", "-g", "-n", str(REFLOG_SCAN_LIMIT), "--format=%H%x00%gs",
            "HEAD", check=False,
        )
        head_matches = {
            oid for oid, _, subject in (line.partition("\0") for line in log.stdout.splitlines())
            if subject.startswith(marker + ":")
        }
        if detached and len(head_matches) == 1:
            matches = {("HEAD", next(iter(head_matches)))}
    # Несколько разных refs/OID означают, что hook выполнил дополнительные
    # ref/commit mutations с унаследованным marker: ownership неоднозначен.
    if len(matches) != 1:
        return None
    ref, oid = next(iter(matches))
    return {"ref": ref, "oid": oid}


def _compensate_unvalidated_commit(
    root: Path,
    snapshot: dict[str, str | None],
    created: dict[str, str] | None,
    parents: list[str],
    current_branch: str | None,
) -> dict[str, Any]:
    """Удалить только доказанный primary commit с фактически обновлённого ref.

    Hook вправе переключить branch до commit. Поэтому CAS выполняется не по
    validated branch, а по exact ref из reflog marker. Ref возвращается к
    первому parent primary commit (или удаляется для root commit). Working tree
    не трогаем. Index возвращаем к validated tree только если commit произошёл
    на той же branch, которую валидировал Harness.
    """
    repo = Repo(root)
    if created is None:
        return {
            "status": "not_compensated",
            "message": "commit created by this action is not uniquely identified in local branch reflogs",
        }
    after = created["oid"]
    ref = created["ref"]
    created_branch = ref.removeprefix("refs/heads/")
    if parents:
        target = parents[0]
        deref = ["--no-deref"] if ref == "HEAD" else []
        moved = repo.git(
            "update-ref", "-m", "harness: revert unvalidated commit", *deref,
            ref, target, after, check=False,
        )
    elif ref == "HEAD":
        return {
            "status": "not_compensated",
            "message": f"detached root commit {after}; HEAD left as is for manual review",
        }
    else:
        target = None
        moved = repo.git("update-ref", "-d", ref, after, check=False)
    if moved.returncode:
        return {
            "status": "not_compensated",
            "message": f"{ref} moved concurrently; not reverted: {moved.stderr.strip()}",
        }

    validated_branch = str(snapshot["branch"])
    if current_branch == created_branch == validated_branch:
        index = repo.git("read-tree", str(snapshot["tree"]), check=False)
        restored_index = index.returncode == 0
        index_note = (
            "index restored to validated tree, hook changes left unstaged in working tree"
            if restored_index else "index restore failed: " + index.stderr.strip()
        )
    else:
        # При branch-switch index относится уже к другому checkout. Его
        # destructive restore к tree исходной ветки был бы потерей hook/user state.
        restored_index = False
        index_note = (
            "index not restored because hook changed branch; "
            f"current branch is {current_branch or '(detached)'}"
        )
    return {
        "status": "reverted",
        "message": (
            f"{ref} returned to {target or '(unborn)'} by CAS; "
            f"unvalidated commit {after} is reachable only via reflog; " + index_note
        ),
        "revertedCommit": after,
        "revertedRef": ref,
        "indexRestored": restored_index,
    }


def _side_effect_read(root: Path, command: str) -> dict[str, Any] | None:
    try:
        return read_side_effect_checkpoint(root, command)
    except (OSError, ValueError) as exc:
        raise GitActionError(
            "SIDE_EFFECT_CHECKPOINT_INVALID",
            f"cannot read side-effect checkpoint for {command}: {exc}",
        ) from exc


def _side_effect_write(
    root: Path,
    command: str,
    *,
    kind: str,
    phase: str,
    proof: dict[str, Any],
) -> None:
    try:
        write_side_effect_checkpoint(
            root,
            command,
            kind=kind,
            phase=phase,
            proof=proof,
        )
    except (OSError, ValueError) as exc:
        raise GitActionError(
            "SIDE_EFFECT_CHECKPOINT_WRITE_FAILED",
            f"cannot persist side-effect checkpoint for {command}: {exc}",
        ) from exc


def _live_remote_head(root: Path, remote: str, branch: str) -> str | None:
    """Read provider-facing Git ref without relying on stale tracking refs."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", remote, f"refs/heads/{branch}"],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=GIT_MUTATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitActionError(
            "SIDE_EFFECT_RECOVERY_PROBE_FAILED",
            f"cannot observe remote ref {remote}/{branch}: {exc}",
        ) from exc
    if proc.returncode != 0:
        raise GitActionError(
            "SIDE_EFFECT_RECOVERY_PROBE_FAILED",
            proc.stderr.strip() or f"cannot observe remote ref {remote}/{branch}",
        )
    rows = [line for line in proc.stdout.splitlines() if line.strip()]
    if not rows:
        return None
    if len(rows) != 1:
        raise GitActionError(
            "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
            f"remote probe returned multiple refs for {remote}/{branch}",
            refs=rows,
        )
    oid = rows[0].split()[0]
    if re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", oid) is None:
        raise GitActionError(
            "SIDE_EFFECT_RECOVERY_PROBE_FAILED",
            f"remote ref returned invalid object id for {remote}/{branch}",
        )
    return oid


def execute_commit(
    root: Path,
    *,
    commit_type: str,
    slug: str,
    message_file: Path,
) -> dict[str, Any]:
    """Создать commit с durable reconciliation при interrupted outcome."""
    recovered = _side_effect_read(root, "GIT COMMIT")
    if recovered is not None and recovered.get("kind") == "git_commit":
        proof = recovered.get("proof") if isinstance(recovered.get("proof"), dict) else {}
        phase = recovered.get("phase")
        before = proof.get("beforeHead")
        marker = proof.get("reflogMarker")
        expected_branch = proof.get("branch")
        expected_tree = proof.get("tree")
        if phase != "prepared" and isinstance(marker, str) and marker:
            repo = Repo(root)
            created_identity = _commit_created_by(repo, marker)
            if created_identity is not None:
                created = created_identity.get("oid")
                current = _commit_snapshot(root)
                if isinstance(created, str):
                    parents = repo.git("rev-list", "--parents", "-n", "1", created).stdout.split()[1:]
                    tree = repo.git("rev-parse", f"{created}^{{tree}}").stdout.strip()
                    if (
                        current.get("head") == created
                        and current.get("branch") == expected_branch
                        and tree == expected_tree
                        and parents == ([before] if before else [])
                    ):
                        verified = {
                            **proof,
                            "observedHead": created,
                            "recovered": True,
                        }
                        _side_effect_write(
                            root,
                            "GIT COMMIT",
                            kind="git_commit",
                            phase="postconditions_verified",
                            proof=verified,
                        )
                        return {
                            "status": "SUCCESS",
                            "action": "commit",
                            "branch": current.get("branch"),
                            "createdBranch": None,
                            "head": created,
                            "recovered": True,
                            "mutation": {"reconciled": True},
                        }
                raise GitActionError(
                    "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
                    "commit side effect exists but current branch/HEAD/tree/parent no longer proves the interrupted mutation",
                    checkpoint=proof,
                    current=current,
                )
            current = _commit_snapshot(root)
            if current.get("head") != before or current.get("branch") != expected_branch:
                raise GitActionError(
                    "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
                    "commit outcome is unknown and repository state changed since the checkpoint",
                    checkpoint=proof,
                    current=current,
                )

    # Message читается и проверяется до любых новых mutations.
    path = _message_path(root, message_file)
    message_identity = _input_identity(path)
    message = path.read_text(encoding="utf-8")
    if _input_identity(path) != message_identity:
        raise GitActionError(
            "COMMIT_MESSAGE_CHANGED",
            "commit message file changed while being read",
        )
    config = policy(root)
    if commit_type not in config["commit"]["types"]:
        raise GitActionError("INVALID_COMMIT_TYPE", f"unknown commit type: {commit_type}")
    _validate_commit_message(
        message,
        commit_type=commit_type,
        gate={"semanticChecks": commit_semantic_checks(config)},
    )

    snapshot = _commit_snapshot(root)
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
        repo = Repo(root)
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
        snapshot = _commit_snapshot(root)
        gate = commit_preflight(root, commit_type=commit_type, slug=slug)
    _validate_commit_message(message, commit_type=commit_type, gate=gate)

    if _commit_snapshot(root) != snapshot:
        raise GitActionError(
            "COMMIT_INPUT_CHANGED",
            "branch, HEAD or staged tree changed during commit preflight",
            validated=snapshot,
        )

    before = snapshot["head"]
    argv = ["git", "-c", "core.logAllRefUpdates=always", "commit"]
    if gate.get("sign"):
        argv.append("-S")
    if gate.get("allowEmpty") and not gate.get("staged"):
        argv.append("--allow-empty")
    argv.extend(["-F", "-"])
    marker = _commit_marker()
    proof = {
        "beforeHead": before,
        "branch": snapshot["branch"],
        "tree": snapshot["tree"],
        "reflogMarker": marker,
    }
    _side_effect_write(
        root, "GIT COMMIT", kind="git_commit", phase="prepared", proof=proof
    )
    _side_effect_write(
        root, "GIT COMMIT", kind="git_commit", phase="side_effect_started", proof=proof
    )

    _run(root, argv, input_text=message, env={"GIT_REFLOG_ACTION": marker})
    repo = Repo(root)
    created_identity = _commit_created_by(repo, marker)
    created = created_identity["oid"] if created_identity is not None else None
    after = repo.head()
    observed_proof = {**proof, "observedHead": after, "createdHead": created}
    _side_effect_write(
        root,
        "GIT COMMIT",
        kind="git_commit",
        phase="side_effect_observed",
        proof=observed_proof,
    )

    if not after or after == before:
        raise GitActionError("COMMIT_POSTCONDITION_FAILED", "Git HEAD did not advance")
    subject = created or after
    parents = repo.git("rev-list", "--parents", "-n", "1", subject).stdout.split()[1:]
    committed_tree = repo.git("rev-parse", f"{subject}^{{tree}}").stdout.strip()
    try:
        current_branch: str | None = repo.branch()
    except GitPreflightError:
        current_branch = None
    if (
        created is None
        or created != after
        or current_branch != snapshot["branch"]
        or parents != ([before] if before else [])
        or committed_tree != snapshot["tree"]
    ):
        compensation = _compensate_unvalidated_commit(
            root, snapshot, created_identity, parents, current_branch
        )
        raise GitActionError(
            "COMMIT_POSTCONDITION_FAILED",
            "created commit does not match validated branch/parent/tree; "
            + compensation["message"],
            head=after,
            validated=snapshot,
            parents=parents,
            tree=committed_tree,
            compensation=compensation,
        )

    verified_proof = {
        **observed_proof,
        "verifiedBranch": current_branch,
        "verifiedTree": committed_tree,
    }
    _side_effect_write(
        root,
        "GIT COMMIT",
        kind="git_commit",
        phase="postconditions_verified",
        proof=verified_proof,
    )

    cleanup_warning = _cleanup_consumed_input(path, message_identity)
    result = {
        "status": "SUCCESS",
        "action": "commit",
        "branch": repo.branch(),
        "createdBranch": created_branch,
        "head": after,
        "mutation": {"argv": argv},
    }
    if cleanup_warning is not None:
        result["cleanupWarnings"] = [cleanup_warning]
    return result

def execute_push(root: Path) -> dict[str, Any]:
    recovered = _side_effect_read(root, "GIT PUSH")
    if recovered is not None and recovered.get("kind") == "git_push":
        proof = recovered.get("proof") if isinstance(recovered.get("proof"), dict) else {}
        phase = recovered.get("phase")
        remote = proof.get("remote")
        branch = proof.get("branch")
        target = proof.get("localHead")
        baseline = proof.get("remoteHeadBefore")
        if (
            phase != "prepared"
            and isinstance(remote, str)
            and isinstance(branch, str)
            and isinstance(target, str)
        ):
            live = _live_remote_head(root, remote, branch)
            decision = recovery_decision(
                observed=live or "",
                expected=target,
                baseline=baseline if isinstance(baseline, str) else None,
            )
            if decision == "ALREADY_APPLIED":
                verified = {
                    **proof,
                    "observedRemoteHead": live,
                    "recovered": True,
                }
                _side_effect_write(
                    root,
                    "GIT PUSH",
                    kind="git_push",
                    phase="postconditions_verified",
                    proof=verified,
                )
                return {
                    "status": "SUCCESS",
                    "action": "push",
                    "branch": branch,
                    "remote": remote,
                    "head": target,
                    "afterPush": proof.get("afterPush"),
                    "recovered": True,
                    "mutation": {"reconciled": True},
                }
            if decision == "AMBIGUOUS":
                raise GitActionError(
                    "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
                    "remote branch no longer matches either pre-push or intended HEAD",
                    remote=remote,
                    branch=branch,
                    expectedHead=target,
                    remoteHeadBefore=baseline,
                    observedRemoteHead=live,
                )
            repo = Repo(root)
            if repo.head() != target or repo.branch() != branch:
                raise GitActionError(
                    "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
                    "push did not reach remote but local branch/HEAD changed before retry",
                    expectedHead=target,
                    currentHead=repo.head(),
                    branch=branch,
                )

    gate = push_preflight(root)
    plan = gate.get("mutationPlan", {})
    argv = plan.get("argv")
    validated = gate.get("validatedHead")
    branch = str(gate["branch"])
    remote = str(gate["remote"])
    if not isinstance(argv, list) or argv[:2] != ["git", "push"]:
        raise GitActionError("UNSAFE_MUTATION_PLAN", "push preflight returned invalid argv")
    if any(str(item).startswith(("--force", "+")) or item == "-f" for item in argv):
        raise GitActionError("UNSAFE_MUTATION_PLAN", "force push is forbidden")
    if not isinstance(validated, str) or argv[-1] != f"{validated}:refs/heads/{branch}":
        raise GitActionError("UNSAFE_MUTATION_PLAN", "push plan must publish the validated commit")
    repo = Repo(root)
    if repo.head() != validated or repo.branch() != branch:
        raise GitActionError(
            "PUSH_INPUT_CHANGED",
            "branch or HEAD changed after push preflight",
            validatedHead=validated,
        )

    before = _live_remote_head(root, remote, branch)
    proof = {
        "localHead": validated,
        "remote": remote,
        "branch": branch,
        "remoteHeadBefore": before,
        "afterPush": gate.get("afterPush"),
    }
    _side_effect_write(root, "GIT PUSH", kind="git_push", phase="prepared", proof=proof)
    _side_effect_write(
        root, "GIT PUSH", kind="git_push", phase="side_effect_started", proof=proof
    )

    _run(root, [str(item) for item in argv])
    live = _live_remote_head(root, remote, branch)
    observed_proof = {**proof, "observedRemoteHead": live}
    _side_effect_write(
        root,
        "GIT PUSH",
        kind="git_push",
        phase="side_effect_observed",
        proof=observed_proof,
    )
    if live != validated:
        raise GitActionError(
            "PUSH_POSTCONDITION_FAILED",
            "configured remote branch does not match validated HEAD after push",
            localHead=validated,
            remoteHead=live,
        )

    # Remote-tracking ref остаётся дополнительной local consistency check.
    repo = Repo(root)
    remote_head = repo.remote_ref(remote, branch)
    if remote_head != validated:
        raise GitActionError(
            "PUSH_POSTCONDITION_FAILED",
            "remote-tracking ref does not match validated HEAD after successful remote observation",
            localHead=validated,
            remoteHead=remote_head,
        )
    upstream_argv = plan.get("upstreamArgv")
    if upstream_argv:
        expected = ["git", "branch", f"--set-upstream-to={remote}/{branch}", branch]
        if upstream_argv != expected:
            raise GitActionError("UNSAFE_MUTATION_PLAN", "push preflight returned invalid upstream argv")
        _run(root, [str(item) for item in upstream_argv])

    _side_effect_write(
        root,
        "GIT PUSH",
        kind="git_push",
        phase="postconditions_verified",
        proof=observed_proof,
    )
    return {
        "status": "SUCCESS",
        "action": "push",
        "branch": branch,
        "remote": remote,
        "head": validated,
        "afterPush": gate.get("afterPush"),
        "mutation": {"argv": argv, "upstreamArgv": upstream_argv},
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
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=PR_PROVIDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitActionError(
            "PR_PROVIDER_TIMEOUT",
            f"PR provider timed out after {PR_PROVIDER_TIMEOUT_SECONDS}s",
            argv=argv,
            timeoutSeconds=PR_PROVIDER_TIMEOUT_SECONDS,
        ) from exc
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


def _repo_selector(gate: dict[str, Any]) -> str:
    """Явный GitHub repository из push remote; без него gh угадывает сам (#109)."""
    selector = gate.get("repoSelector")
    if not isinstance(selector, str) or not selector:
        raise GitActionError(
            "PR_REPO_UNRESOLVED",
            f"cannot resolve GitHub repository from remote {gate.get('remote')} URL",
        )
    return selector


def _open_prs(root: Path, gate: dict[str, Any]) -> list[dict[str, Any]]:
    """Query exact open head/base PRs through the configured provider adapter."""
    try:
        return provider_open_prs(root, gate)
    except ProviderError as exc:
        # git_action.py owns the public mutation error contract. Provider
        # internals are normalized here so existing callers never need to know
        # which adapter produced the blocker.
        raise GitActionError(exc.code, str(exc), **exc.details) from exc


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
        if not isinstance(existing, dict):
            # Иначе `.get` ниже падает AttributeError-traceback (#110).
            raise GitActionError("INVALID_PR_STATE", f"{PR_STATE_PATH} must be a JSON object")
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
    """Find/reuse/create provider PR с durable reconciliation unknown outcome."""
    gate = pr_preflight(root)
    recovery = _side_effect_read(root, "GIT PR")
    recovery_kind = recovery.get("kind") if isinstance(recovery, dict) else None
    if recovery is not None and recovery_kind not in {"provider_pr", "github_pr"}:
        raise GitActionError(
            "SIDE_EFFECT_CHECKPOINT_INVALID",
            f"GIT PR cannot recover side-effect kind {recovery_kind!r}",
        )
    # Новые executions используют provider-neutral kind. Legacy github_pr
    # продолжаем с исходным kind до terminal phase: contract запрещает менять
    # kind внутри active side-effect lifecycle.
    pr_side_effect_kind = recovery_kind if recovery is not None else "provider_pr"
    recovery_proof = (
        recovery.get("proof")
        if isinstance(recovery, dict) and isinstance(recovery.get("proof"), dict)
        else {}
    )
    if recovery is not None:
        expected = (
            recovery_proof.get("headBranch"),
            recovery_proof.get("baseBranch"),
            recovery_proof.get("headSha"),
        )
        actual = (gate.get("branch"), gate.get("base"), gate.get("publishedHead"))
        if expected != actual:
            raise GitActionError(
                "SIDE_EFFECT_RECOVERY_AMBIGUOUS",
                "PR recovery checkpoint does not match current head/base/revision",
                checkpoint=recovery_proof,
                current={"headBranch": actual[0], "baseBranch": actual[1], "headSha": actual[2]},
            )

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
        code = (
            "SIDE_EFFECT_RECOVERY_AMBIGUOUS"
            if recovery is not None
            else "PR_AMBIGUOUS"
        )
        raise GitActionError(
            code,
            "multiple open PRs match configured head/base",
            prs=[item.get("number") for item in existing],
        )

    reused = bool(existing)
    recovered_existing = bool(
        existing
        and recovery is not None
        and recovery.get("phase") != "prepared"
    )
    if existing:
        if not gate.get("reuseExisting") and not recovered_existing:
            raise GitActionError(
                "PR_ALREADY_EXISTS",
                "an open PR already exists and pull_request.reuse_existing=false",
                pr=existing[0].get("number"),
            )
        item = existing[0]
    else:
        if body_file is None:
            raise GitActionError("PR_BODY_REQUIRED", "creating a PR requires --body-file")
        assert body_path is not None
        body = body_path.read_text(encoding="utf-8")
        if _input_identity(body_path) != body_identity:
            raise GitActionError("PR_BODY_CHANGED", "PR body file changed while being read")
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
                raise GitActionError("PR_TITLE_CHANGED", "PR title file changed while being read")
        if not title or "\n" in title or "\r" in title:
            raise GitActionError("PR_TITLE_INVALID", "PR title must be one non-empty line")

        proof = {
            "headRepo": gate.get("headRepo"),
            "headBranch": gate["branch"],
            "baseBranch": gate["base"],
            "headSha": gate["publishedHead"],
        }
        _side_effect_write(root, "GIT PR", kind=pr_side_effect_kind, phase="prepared", proof=proof)
        _side_effect_write(
            root, "GIT PR", kind=pr_side_effect_kind, phase="side_effect_started", proof=proof
        )
        try:
            provider_create_pr(root, gate, title=title, body=body)
        except ProviderError as exc:
            raise GitActionError(exc.code, str(exc), **exc.details) from exc

        existing = _open_prs(root, gate)
        if len(existing) != 1:
            raise GitActionError(
                "PR_POSTCONDITION_FAILED",
                "provider did not expose exactly one open PR after create",
                matchCount=len(existing),
            )
        item = existing[0]
        observed = {
            **proof,
            "providerObjectId": item.get("number"),
            "providerUrl": item.get("url"),
        }
        _side_effect_write(
            root,
            "GIT PR",
            kind=pr_side_effect_kind,
            phase="side_effect_observed",
            proof=observed,
        )

    _validate_provider_pr(gate, item)
    state_file = _persist_pr_state(root, gate=gate, item=item)

    verified = {
        "headRepo": gate.get("headRepo"),
        "headBranch": gate["branch"],
        "baseBranch": gate["base"],
        "headSha": gate["publishedHead"],
        "providerObjectId": item.get("number"),
        "providerUrl": item.get("url"),
        "recovered": recovered_existing,
    }
    # Обычный reuse уже существующего PR не пересекает mutation boundary:
    # provider create не выполнялся, поэтому начинать SideEffectProof только
    # терминальной фазой нельзя. Если checkpoint уже есть, это recovery/create
    # lifecycle и его нужно довести до postconditions_verified.
    if recovery is not None or not reused:
        _side_effect_write(
            root,
            "GIT PR",
            kind=pr_side_effect_kind,
            phase="postconditions_verified",
            proof=verified,
        )

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
        "recovered": recovered_existing,
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
    except (GitActionError, GitPreflightError, ProviderError, ConfigError, OSError, UnicodeError) as exc:
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
