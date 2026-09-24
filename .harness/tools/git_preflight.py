#!/usr/bin/env python3
"""Deterministic Git safety preflight AI Development Harness.

Назначение
----------
Проверить factual Git state и strict git-policy **до** mutation.

Tool сам не выполняет commit/push/PR/merge. Единственный допустимый side effect —
configured `git fetch`, необходимый для актуального ahead/behind и PR/sync
preflight. На PASS возвращается exact mutation plan, который исполняет caller.

Fail-closed границы
-------------------
- malformed/unknown git-policy key -> BLOCKED;
- detached HEAD -> BLOCKED;
- protected branch violation -> BLOCKED;
- remote-ahead при non-force policy -> BLOCKED;
- unpublished/mismatching PR head -> BLOCKED;
- diverged/dirty ff-only sync -> BLOCKED.

Публичные actions CLI: check, commit, push, pr, pr-finish, sync.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
import shutil
import subprocess
from typing import Any

from harness_config import ConfigError, load_git_policy

PR_STATE_PATH = Path(".harness/local/git/pr-state.json")


class GitPreflightError(RuntimeError):
    """Структурированный blocker, который CLI переводит в status=BLOCKED.

    `code` стабилен для automation/tests, `message` предназначен человеку,
    `details` хранит actionable данные вроде requiredBranch.
    """

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _require_safe_branch_name(name: str) -> None:
    """`+name` Git трактует в refspec как forced update, `-name` — как опцию (#107)."""
    if name.startswith(("+", "-")):
        raise GitPreflightError(
            "INVALID_BRANCH_NAME",
            f"branch name must not start with '+' or '-': {name}",
        )


class Repo:
    """Минимальный read-model над Git CLI.

    Wrapper централизует Git subprocess semantics, чтобы разные preflight actions
    одинаково трактовали branch/HEAD/worktree/remote state.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            # Non-UTF-8 имена файлов не должны превращаться в traceback (#110).
            encoding="utf-8",
            errors="surrogateescape",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and proc.returncode:
            raise GitPreflightError(
                "GIT_ERROR",
                proc.stderr.strip() or f"git {' '.join(args)} failed",
            )
        return proc

    def branch(self) -> str:
        proc = self.git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if proc.returncode:
            raise GitPreflightError("DETACHED_HEAD", "Git mutation requires an attached branch")
        value = proc.stdout.strip()
        if not value:
            raise GitPreflightError("DETACHED_HEAD", "cannot resolve current branch")
        _require_safe_branch_name(value)
        return value

    def has_head(self) -> bool:
        return self.git("rev-parse", "--verify", "HEAD", check=False).returncode == 0

    def head(self) -> str | None:
        if not self.has_head():
            return None
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit_count(self) -> int:
        if not self.has_head():
            return 0
        return int(self.git("rev-list", "--count", "HEAD").stdout.strip())

    def status(self) -> dict[str, Any]:
        """Вернуть factual staged/unstaged/untracked state без mutation."""
        staged = [p for p in self.git("diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
        unstaged = [p for p in self.git("diff", "--name-only", "-z").stdout.split("\0") if p]
        untracked = [
            p
            for p in self.git("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
            if p
        ]
        return {
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "clean": not staged and not unstaged and not untracked,
        }

    def staged_added(self) -> list[str]:
        out = self.git("diff", "--cached", "--name-only", "--diff-filter=A", "-z").stdout
        return [p for p in out.split("\0") if p]

    def remote_exists(self, remote: str) -> bool:
        return self.git("remote", "get-url", remote, check=False).returncode == 0

    def fetch(self, remote: str) -> None:
        """Обновить remote-tracking refs; это единственный сетевой side effect preflight."""
        proc = self.git("fetch", "--prune", remote, check=False)
        if proc.returncode:
            raise GitPreflightError(
                "FETCH_FAILED",
                proc.stderr.strip() or f"cannot fetch configured remote {remote}",
            )

    def remote_ref(self, remote: str, branch: str) -> str | None:
        ref = f"refs/remotes/{remote}/{branch}"
        proc = self.git("rev-parse", "--verify", ref, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def ahead_behind(self, remote: str, branch: str) -> tuple[int, int] | None:
        """Вернуть (local-ahead, remote-ahead) относительно configured remote branch."""
        if self.remote_ref(remote, branch) is None or not self.has_head():
            return None
        out = self.git(
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...refs/remotes/{remote}/{branch}",
        ).stdout.strip()
        left, right = out.split()
        return int(left), int(right)

    def upstream(self) -> str | None:
        proc = self.git(
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else None


def _dict(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise GitPreflightError("INVALID_GIT_POLICY", f"git-policy [{key}] must be a table")
    return value


def _bool(table: dict[str, Any], key: str, *, section: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise GitPreflightError("INVALID_GIT_POLICY", f"git-policy {section}.{key} must be boolean")
    return value


def _text(table: dict[str, Any], key: str, *, section: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GitPreflightError("INVALID_GIT_POLICY", f"git-policy {section}.{key} must be non-empty string")
    return value.strip()


def _exact_keys(table: dict[str, Any], allowed: set[str], *, section: str) -> None:
    unexpected = sorted(set(table) - allowed)
    if unexpected:
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            f"unsupported git-policy {section} settings: " + ", ".join(unexpected),
        )


# ---------------------------------------------------------------------------
# Strict policy boundary.
# Preflight не допускает "лишних" keys для forward-compatibility: неизвестный
# safety knob опаснее явного failure, потому что пользователь может ожидать
# поведение, которого engine не исполняет.
# ---------------------------------------------------------------------------
def policy(root: Path) -> dict[str, Any]:
    try:
        data = load_git_policy(root)
    except ConfigError as exc:
        raise GitPreflightError("INVALID_GIT_POLICY", str(exc)) from exc
    if data.get("version") != 1:
        raise GitPreflightError("INVALID_GIT_POLICY", "git-policy version must be 1")
    _exact_keys(
        data,
        {"version", "commit", "branch", "push", "pull_request", "sync"},
        section="top-level",
    )

    commit = _dict(data, "commit")
    branch = _dict(data, "branch")
    push = _dict(data, "push")
    pr = _dict(data, "pull_request")
    sync = _dict(data, "sync")

    _exact_keys(
        commit,
        {
            "style", "stage_mode", "subject_max_length", "require_body",
            "require_harness_validation", "require_single_logical_change",
            "include_verification", "include_traceability", "allow_empty",
            "sign", "types",
        },
        section="commit",
    )
    _exact_keys(
        branch,
        {
            "protected", "when_on_protected", "allow_initial_commit_on_protected",
            "name_pattern", "slug_max_length", "prefixes",
        },
        section="branch",
    )
    _exact_keys(
        push,
        {
            "remote", "set_upstream", "fetch_before_push",
            "force", "push_tags", "allow_protected",
            "allow_initial_push_to_protected", "require_harness_validation",
            "require_clean_worktree",
        },
        section="push",
    )
    _exact_keys(
        pr,
        {
            "after_push", "provider", "preferred_tool", "base", "draft",
            "reuse_existing", "title_from_commit", "body_template",
        },
        section="pull_request",
    )
    _exact_keys(sync, {"fetch_remote", "mode"}, section="sync")

    if commit.get("style") != "conventional":
        raise GitPreflightError("INVALID_GIT_POLICY", "commit.style must be conventional")
    if commit.get("stage_mode") not in {"all-safe", "tracked-only", "staged-only"}:
        raise GitPreflightError("INVALID_GIT_POLICY", "unsupported commit.stage_mode")
    if branch.get("when_on_protected") not in {"auto-create", "stay", "block"}:
        raise GitPreflightError("INVALID_GIT_POLICY", "unsupported branch.when_on_protected")
    if push.get("force") != "never":
        raise GitPreflightError("INVALID_GIT_POLICY", "push.force must be never")
    if pr.get("after_push") not in {"never", "ask", "create-if-missing"}:
        raise GitPreflightError("INVALID_GIT_POLICY", "unsupported pull_request.after_push")
    if sync.get("mode") not in {"report", "ff-only"}:
        raise GitPreflightError("INVALID_GIT_POLICY", "unsupported sync.mode")

    for key in (
        "require_body", "require_harness_validation", "require_single_logical_change",
        "include_verification", "include_traceability", "allow_empty", "sign",
    ):
        _bool(commit, key, section="commit")
    _bool(
        branch,
        "allow_initial_commit_on_protected",
        section="branch",
    )
    for key in (
        "set_upstream", "fetch_before_push", "push_tags", "allow_protected",
        "allow_initial_push_to_protected", "require_harness_validation",
        "require_clean_worktree",
    ):
        _bool(push, key, section="push")
    for key in ("draft", "reuse_existing", "title_from_commit"):
        _bool(pr, key, section="pull_request")

    subject_limit = commit.get("subject_max_length")
    if isinstance(subject_limit, bool) or not isinstance(subject_limit, int) or subject_limit <= 0:
        raise GitPreflightError("INVALID_GIT_POLICY", "commit.subject_max_length must be positive integer")

    commit_types = commit.get("types")
    protected = branch.get("protected")
    prefixes = branch.get("prefixes")
    if not isinstance(commit_types, dict) or not commit_types or not all(
        isinstance(k, str) and k and isinstance(v, str) and v
        for k, v in commit_types.items()
    ):
        raise GitPreflightError("INVALID_GIT_POLICY", "commit.types must be non-empty string mapping")
    if not isinstance(protected, list) or not protected or not all(isinstance(x, str) and x for x in protected):
        raise GitPreflightError("INVALID_GIT_POLICY", "branch.protected must be non-empty string list")
    if not isinstance(prefixes, dict) or set(prefixes) != set(commit_types) or not all(
        isinstance(k, str) and k and isinstance(v, str) and v
        for k, v in prefixes.items()
    ):
        raise GitPreflightError("INVALID_GIT_POLICY", "branch.prefixes must exactly match commit.types")
    _text(branch, "name_pattern", section="branch")
    name_pattern = branch["name_pattern"]
    if "{prefix}" not in name_pattern or "{slug}" not in name_pattern:
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            "branch.name_pattern must contain {prefix} and {slug}",
        )
    slug_limit = branch.get("slug_max_length")
    if isinstance(slug_limit, bool) or not isinstance(slug_limit, int) or slug_limit <= 0:
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            "branch.slug_max_length must be positive integer",
        )

    _text(push, "remote", section="push")
    for key in ("provider", "preferred_tool", "base", "body_template"):
        _text(pr, key, section="pull_request")
    body_template = Path(pr["body_template"])
    if body_template.is_absolute() or ".." in body_template.parts:
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            "pull_request.body_template must stay inside repository",
        )
    if not (root / body_template).is_file():
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            f"pull_request.body_template does not exist: {pr['body_template']}",
        )

    _text(sync, "fetch_remote", section="sync")
    return data


def _validator(root: Path) -> None:
    """Запустить общий Harness validator как обязательный вложенный gate."""
    validator = root / ".harness/tools/validate.py"
    if not validator.is_file():
        raise GitPreflightError("HARNESS_VALIDATOR_MISSING", "missing .harness/tools/validate.py")
    proc = subprocess.run(
        ["python3", str(validator), "--mode", "commit"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise GitPreflightError(
            "HARNESS_VALIDATION_FAILED",
            (proc.stdout + "\n" + proc.stderr).strip() or "Harness validation failed",
        )


def _result(action: str, **values: Any) -> dict[str, Any]:
    return {"status": "PASS", "action": action, **values}


def _protected(branch: str, config: dict[str, Any]) -> bool:
    return branch in config["branch"]["protected"]


def _slug(value: str, limit: int) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not normalized:
        raise GitPreflightError("INVALID_BRANCH_SLUG", "branch slug becomes empty after normalization")
    return normalized[:limit].rstrip("-")


def _planned_branch(config: dict[str, Any], commit_type: str | None, slug: str | None) -> str | None:
    if not commit_type or not slug:
        return None
    prefixes = config["branch"]["prefixes"]
    prefix = prefixes.get(commit_type)
    if not isinstance(prefix, str) or not prefix:
        raise GitPreflightError("INVALID_COMMIT_TYPE", f"unknown commit type: {commit_type}")
    limit = config["branch"].get("slug_max_length")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise GitPreflightError("INVALID_GIT_POLICY", "branch.slug_max_length must be positive integer")
    pattern = _text(config["branch"], "name_pattern", section="branch")
    if "{prefix}" not in pattern or "{slug}" not in pattern:
        raise GitPreflightError("INVALID_GIT_POLICY", "branch.name_pattern must contain {prefix} and {slug}")
    try:
        candidate = pattern.format(prefix=prefix, slug=_slug(slug, limit))
    except (KeyError, IndexError, ValueError) as exc:
        raise GitPreflightError(
            "INVALID_GIT_POLICY",
            f"branch.name_pattern supports only {{prefix}} and {{slug}}: {exc}",
        ) from exc
    _require_safe_branch_name(candidate)
    proc = subprocess.run(
        ["git", "check-ref-format", "--branch", candidate],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise GitPreflightError(
            "INVALID_BRANCH_NAME",
            proc.stderr.strip() or f"invalid branch name from policy: {candidate}",
        )
    return candidate


# ---------------------------------------------------------------------------
# Action: CHECK.
# Диагностический snapshot repository + configured remotes. Harness validation
# здесь отражается как поле результата, но CHECK сам остаётся обзорным действием.
# ---------------------------------------------------------------------------
def check(root: Path) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    branch = repo.branch()
    state = repo.status()
    validation = "not_requested"
    try:
        _validator(root)
        validation = "pass"
    except GitPreflightError as exc:
        validation = f"blocked:{exc.code}"
    return _result(
        "check",
        branch=branch,
        protected=_protected(branch, config),
        upstream=repo.upstream(),
        head=repo.head(),
        worktree=state,
        harnessValidation=validation,
        configured={
            "pushRemote": config["push"]["remote"],
            "prBase": config["pull_request"]["base"],
            "syncRemote": config["sync"]["fetch_remote"],
        },
    )


# ---------------------------------------------------------------------------
# Action: COMMIT.
# Проверяет staged state, allow_empty/stage_mode и protected-branch policy.
# Если нужна новая ветка, engine возвращает deterministic requiredBranch через
# structured blocker вместо самостоятельного branch creation.
# ---------------------------------------------------------------------------
def commit_semantic_checks(config: dict[str, Any]) -> dict[str, Any]:
    """Semantic commit-message checks из policy; не зависят от Git state."""
    commit_cfg = config["commit"]
    return {
        "requireSingleLogicalChange": bool(commit_cfg.get("require_single_logical_change")),
        "messageStyle": commit_cfg.get("style"),
        "subjectMaxLength": commit_cfg.get("subject_max_length"),
        "requireBody": bool(commit_cfg.get("require_body")),
        "includeVerification": bool(commit_cfg.get("include_verification")),
        "includeTraceability": bool(commit_cfg.get("include_traceability")),
    }


def commit_preflight(
    root: Path,
    *,
    commit_type: str | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    branch = repo.branch()
    state = repo.status()
    commit_cfg = config["commit"]
    branch_cfg = config["branch"]

    # Commit type входит в policy для любой ветки, не только protected (#110).
    if commit_type is not None and commit_type not in commit_cfg["types"]:
        raise GitPreflightError("INVALID_COMMIT_TYPE", f"unknown commit type: {commit_type}")

    if _bool(commit_cfg, "require_harness_validation", section="commit"):
        _validator(root)

    staged = state["staged"]
    if not staged and not _bool(commit_cfg, "allow_empty", section="commit"):
        raise GitPreflightError("EMPTY_COMMIT_BLOCKED", "no staged changes and commit.allow_empty=false")

    stage_mode = commit_cfg["stage_mode"]
    if stage_mode == "tracked-only" and repo.has_head():
        added = repo.staged_added()
        if added:
            raise GitPreflightError(
                "TRACKED_ONLY_NEW_FILES",
                "tracked-only commit contains staged added files: " + ", ".join(added),
            )

    protected = _protected(branch, config)
    initial = not repo.has_head()
    required_branch = None
    if protected:
        if initial and _bool(
            branch_cfg,
            "allow_initial_commit_on_protected",
            section="branch",
        ):
            pass
        else:
            mode = branch_cfg["when_on_protected"]
            if mode == "block":
                raise GitPreflightError(
                    "PROTECTED_BRANCH_COMMIT_BLOCKED",
                    f"commit on protected branch {branch} is blocked by policy",
                )
            if mode == "auto-create":
                required_branch = _planned_branch(config, commit_type, slug)
                message = f"commit on protected branch {branch} requires a new branch"
                if required_branch:
                    message += f": {required_branch}"
                raise GitPreflightError(
                    "PROTECTED_BRANCH_REQUIRES_NEW_BRANCH",
                    message,
                    currentBranch=branch,
                    requiredBranch=required_branch,
                    requiredAction="create_branch",
                )

    return _result(
        "commit",
        branch=branch,
        protected=protected,
        initialCommit=initial,
        stageMode=stage_mode,
        staged=staged,
        sign=_bool(commit_cfg, "sign", section="commit"),
        allowEmpty=_bool(commit_cfg, "allow_empty", section="commit"),
        semanticChecks=commit_semantic_checks(config),
        mutationPlan={
            "operation": "git commit",
            "forceForbidden": True,
        },
    )


def _require_remote(repo: Repo, remote: str) -> None:
    if not repo.remote_exists(remote):
        raise GitPreflightError("REMOTE_MISSING", f"configured Git remote does not exist: {remote}")


# ---------------------------------------------------------------------------
# Action: PUSH.
# Перед расчётом divergence при policy.fetch_before_push обновляет remote refs.
# Force запрещён policy contract-ом; любой remote-ahead блокируется заранее.
# ---------------------------------------------------------------------------
def push_preflight(root: Path) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    branch = repo.branch()
    push = config["push"]
    remote = _text(push, "remote", section="push")
    _require_remote(repo, remote)

    if _bool(push, "fetch_before_push", section="push"):
        repo.fetch(remote)

    # Публикуется ровно тот commit, который видел validator: executor пушит
    # явный `<oid>:refs/heads/<branch>`, а не то, куда ветка указывает позже (#107).
    validated_head = repo.head()

    if _bool(push, "require_harness_validation", section="push"):
        _validator(root)

    state = repo.status()
    if _bool(push, "require_clean_worktree", section="push") and not state["clean"]:
        raise GitPreflightError(
            "DIRTY_WORKTREE_PUSH_BLOCKED",
            "push.require_clean_worktree=true and worktree/index is not clean",
        )

    if validated_head is None:
        raise GitPreflightError("NO_COMMITS", "cannot push repository without commits")
    if repo.head() != validated_head or repo.branch() != branch:
        raise GitPreflightError(
            "PUSH_INPUT_CHANGED",
            "branch or HEAD changed during push preflight",
        )

    remote_oid = repo.remote_ref(remote, branch)
    relation = repo.ahead_behind(remote, branch)
    is_initial_remote_push = remote_oid is None and repo.commit_count() == 1
    protected = _protected(branch, config)

    if protected and not _bool(push, "allow_protected", section="push"):
        if not (
            is_initial_remote_push
            and _bool(
                push,
                "allow_initial_push_to_protected",
                section="push",
            )
        ):
            raise GitPreflightError(
                "PROTECTED_BRANCH_PUSH_BLOCKED",
                f"push to protected branch {branch} is blocked by policy",
            )

    ahead = None
    behind = None
    if relation is not None:
        ahead, behind = relation
        if behind > 0:
            raise GitPreflightError(
                "REMOTE_AHEAD",
                f"{remote}/{branch} contains {behind} commit(s) not in local HEAD; non-force PUSH is blocked",
            )

    args = ["git", "push"]
    if _bool(push, "push_tags", section="push"):
        args.append("--tags")
    # Полный refspec: имя ветки никогда не интерпретируется как `+force`/опция.
    # Upstream для oid-refspec Git не выставляет — это делает executor отдельно.
    args.extend([remote, f"{validated_head}:refs/heads/{branch}"])
    set_upstream = (
        _bool(push, "set_upstream", section="push")
        and repo.upstream() is None
    )

    return _result(
        "push",
        branch=branch,
        remote=remote,
        protected=protected,
        initialRemotePush=is_initial_remote_push,
        remoteBranchExists=remote_oid is not None,
        ahead=ahead,
        behind=behind,
        worktree=state,
        validatedHead=validated_head,
        mutationPlan={
            "argv": args,
            "forceForbidden": True,
            "setUpstream": set_upstream,
            "upstreamArgv": (
                ["git", "branch", f"--set-upstream-to={remote}/{branch}", branch]
                if set_upstream
                else None
            ),
            "pushTags": _bool(push, "push_tags", section="push"),
        },
        afterPush=config["pull_request"]["after_push"],
    )


_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def github_repo_selector(repo: Repo, remote: str) -> str | None:
    """`--repo` для gh из configured remote URL: `owner/repo` или `host/owner/repo`.

    Без явного `--repo` gh выбирает default repository сам — в fork-сценарии это
    может быть не `push.remote`, а `pr list --head` находит чужие PR с тем же
    именем ветки (#109). Читается raw `remote.<name>.url` (до insteadOf);
    нераспознанный URL (например, локальный путь) даёт None.
    """
    proc = repo.git("config", "--get", f"remote.{remote}.url", check=False)
    url = proc.stdout.strip()
    if proc.returncode or not url:
        return None
    match = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", url)
    if match is None:
        match = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!/)(.+)$", url)
    if match is None:
        return None
    host = match.group(1).lower()
    parts = [part for part in match.group(2).split("/") if part]
    if len(parts) < 2:
        return None
    owner, name = parts[-2], parts[-1].removesuffix(".git")
    if not (_REPO_PART.match(owner) and _REPO_PART.match(name)):
        return None
    if host in {"github.com", "www.github.com", "ssh.github.com"}:
        return f"{owner}/{name}"
    return f"{host}/{owner}/{name}"


# ---------------------------------------------------------------------------
# Action: PR.
# Требует, чтобы current local HEAD уже был **точно** опубликован в remote head
# branch. PR не должен создаваться для локальной revision, которой нет remote.
# ---------------------------------------------------------------------------
def pr_preflight(root: Path) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    branch = repo.branch()
    pr = config["pull_request"]
    push = config["push"]
    remote = _text(push, "remote", section="push")
    _require_remote(repo, remote)
    repo.fetch(remote)

    if not repo.has_head():
        raise GitPreflightError("NO_COMMITS", "cannot create PR without commits")

    remote_oid = repo.remote_ref(remote, branch)
    if remote_oid is None:
        raise GitPreflightError(
            "HEAD_NOT_PUBLISHED",
            f"head branch {branch} is not published to configured remote {remote}",
        )
    head = repo.head()
    if head != remote_oid:
        raise GitPreflightError(
            "HEAD_NOT_FULLY_PUBLISHED",
            f"local HEAD differs from {remote}/{branch}; push exact revision first",
        )

    provider = _text(pr, "provider", section="pull_request")
    preferred_tool = _text(pr, "preferred_tool", section="pull_request")
    if shutil.which(preferred_tool) is None:
        raise GitPreflightError(
            "PR_TOOL_UNAVAILABLE",
            f"configured pull_request.preferred_tool is unavailable: {preferred_tool}",
        )

    base = _text(pr, "base", section="pull_request")
    if repo.remote_ref(remote, base) is None:
        raise GitPreflightError(
            "PR_BASE_MISSING",
            f"configured PR base does not exist on {remote}: {base}",
        )

    body_template = _text(pr, "body_template", section="pull_request")
    template_path = (root / body_template).resolve()
    try:
        template_path.relative_to(root.resolve())
    except ValueError as exc:
        raise GitPreflightError("PR_TEMPLATE_ESCAPE", "PR body template escapes repository") from exc
    if not template_path.is_file():
        raise GitPreflightError("PR_TEMPLATE_MISSING", f"PR body template missing: {body_template}")

    return _result(
        "pr",
        branch=branch,
        remote=remote,
        repoSelector=github_repo_selector(repo, remote),
        publishedHead=remote_oid,
        provider=provider,
        preferredTool=preferred_tool,
        base=base,
        bodyTemplate=body_template,
        draft=_bool(pr, "draft", section="pull_request"),
        reuseExisting=_bool(pr, "reuse_existing", section="pull_request"),
        titleFromCommit=_bool(pr, "title_from_commit", section="pull_request"),
        mutationPlan={
            "provider": provider,
            "tool": preferred_tool,
            "head": branch,
            "base": base,
            "draft": _bool(pr, "draft", section="pull_request"),
        },
    )



# ---------------------------------------------------------------------------
# Action: PR FINISH.
# Provider state доказывает merge, local state восстанавливает return branch.
# Engine ничего не переключает/удаляет: он возвращает exact ordered plan.
# ---------------------------------------------------------------------------
def _load_pr_state(root: Path) -> dict[str, Any] | None:
    path = root / PR_STATE_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GitPreflightError("INVALID_PR_STATE", f"cannot read {PR_STATE_PATH}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise GitPreflightError("INVALID_PR_STATE", "PR state must be schema version 1")
    for key in ("headBranch", "baseBranch", "returnBranch"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise GitPreflightError("INVALID_PR_STATE", f"PR state {key} must be non-empty string")
    number = data.get("pr")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise GitPreflightError("INVALID_PR_STATE", "PR state pr must be a positive integer")
    return data


def _github_pr_view(root: Path, config: dict[str, Any], selector: str | int) -> dict[str, Any]:
    pr = config["pull_request"]
    provider = _text(pr, "provider", section="pull_request")
    tool = _text(pr, "preferred_tool", section="pull_request")
    if provider != "github" or tool != "gh":
        raise GitPreflightError(
            "PR_FINISH_TOOL_UNSUPPORTED",
            "GIT PR FINISH currently requires pull_request.provider=github and preferred_tool=gh",
        )
    if shutil.which(tool) is None:
        raise GitPreflightError("PR_TOOL_UNAVAILABLE", f"configured PR tool is unavailable: {tool}")
    remote = _text(config["push"], "remote", section="push")
    repo_selector = github_repo_selector(Repo(root), remote)
    if repo_selector is None:
        raise GitPreflightError(
            "PR_REPO_UNRESOLVED",
            f"cannot resolve GitHub repository from remote {remote} URL",
        )
    proc = subprocess.run(
        [
            tool, "pr", "view", str(selector), "--repo", repo_selector,
            "--json", "number,state,mergedAt,headRefName,headRefOid,baseRefName,url",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise GitPreflightError(
            "PR_NOT_FOUND",
            proc.stderr.strip() or f"cannot resolve Pull Request for {selector}",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitPreflightError("PR_QUERY_INVALID", "PR tool returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise GitPreflightError("PR_QUERY_INVALID", "PR tool returned non-object JSON")
    return data


def pr_finish_preflight(root: Path, *, pr_data: dict[str, Any] | None = None) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    current_branch = repo.branch()
    worktree = repo.status()
    if not worktree["clean"]:
        raise GitPreflightError(
            "PR_FINISH_DIRTY_WORKTREE",
            "GIT PR FINISH requires a clean index/worktree",
        )

    local_state = _load_pr_state(root)
    if local_state is not None:
        allowed_branches = {
            local_state["headBranch"],
            local_state["returnBranch"],
        }
        if current_branch not in allowed_branches:
            raise GitPreflightError(
                "PR_STATE_HEAD_MISMATCH",
                "current branch is neither PR head nor recorded return branch: "
                f"{current_branch}",
            )

    remote = _text(config["push"], "remote", section="push")
    _require_remote(repo, remote)
    repo.fetch(remote)

    selector: str | int = local_state["pr"] if local_state is not None else current_branch
    data = pr_data if pr_data is not None else _github_pr_view(root, config, selector)

    number = data.get("number")
    state = data.get("state")
    merged_at = data.get("mergedAt")
    provider_head_branch = data.get("headRefName")
    head_oid = data.get("headRefOid")
    base_branch = data.get("baseRefName")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise GitPreflightError("PR_QUERY_INVALID", "PR number is missing or invalid")
    if state != "MERGED" or not isinstance(merged_at, str) or not merged_at.strip():
        raise GitPreflightError("PR_NOT_MERGED", f"Pull Request #{number} is not merged")
    if not isinstance(head_oid, str) or re.fullmatch(r"[0-9a-fA-F]{40}", head_oid) is None:
        raise GitPreflightError("PR_QUERY_INVALID", "PR headRefOid is missing or invalid")
    if not isinstance(base_branch, str) or not base_branch.strip():
        raise GitPreflightError("PR_QUERY_INVALID", "PR base branch is missing")

    if local_state is not None:
        if local_state["pr"] != number:
            raise GitPreflightError(
                "PR_STATE_NUMBER_MISMATCH",
                f"local PR state number {local_state['pr']} differs from provider PR #{number}",
            )
        if local_state["baseBranch"] != base_branch:
            raise GitPreflightError(
                "PR_STATE_BASE_MISMATCH",
                f"local PR state base {local_state['baseBranch']} differs from provider base {base_branch}",
            )
        head_branch = local_state["headBranch"]
        return_branch = local_state["returnBranch"]
    else:
        head_branch = current_branch
        return_branch = base_branch

    if not isinstance(provider_head_branch, str) or provider_head_branch != head_branch:
        raise GitPreflightError(
            "PR_HEAD_MISMATCH",
            f"merged PR head {provider_head_branch!r} does not match expected branch {head_branch!r}",
        )
    if return_branch == head_branch:
        raise GitPreflightError(
            "PR_FINISH_INVALID_RETURN_BRANCH",
            "return branch equals PR head branch",
        )

    # PR FINISH — многошаговая mutation. После crash текущая ветка уже может
    # быть returnBranch. В этом случае local PR state + provider MERGED state
    # позволяют безопасно продолжить оставшиеся sync/delete steps.
    resumed = current_branch == return_branch
    head_ref = f"refs/heads/{head_branch}"
    head_proc = repo.git("rev-parse", "--verify", head_ref, check=False)
    local_head_oid = head_proc.stdout.strip() if head_proc.returncode == 0 else None

    if current_branch == head_branch:
        current_head = repo.head()
        if current_head != head_oid:
            raise GitPreflightError(
                "PR_HEAD_SHA_MISMATCH",
                f"local HEAD {current_head!r} differs from merged PR head {head_oid!r}",
            )
    elif resumed:
        if local_head_oid is not None and local_head_oid != head_oid:
            raise GitPreflightError(
                "PR_HEAD_SHA_MISMATCH",
                f"local PR branch {head_branch} moved after merge: "
                f"{local_head_oid!r} != {head_oid!r}",
            )
    else:
        raise GitPreflightError(
            "PR_STATE_HEAD_MISMATCH",
            f"cannot finish PR from unrelated branch {current_branch}",
        )

    local_return = f"refs/heads/{return_branch}"
    if repo.git("show-ref", "--verify", "--quiet", local_return, check=False).returncode:
        raise GitPreflightError(
            "RETURN_BRANCH_MISSING",
            f"local return branch does not exist: {return_branch}",
        )
    remote_return = f"refs/remotes/{remote}/{return_branch}"
    if repo.git("rev-parse", "--verify", remote_return, check=False).returncode:
        raise GitPreflightError(
            "RETURN_BRANCH_REMOTE_MISSING",
            f"remote return branch does not exist: {remote}/{return_branch}",
        )

    relation = repo.git(
        "rev-list", "--left-right", "--count", f"{local_return}...{remote_return}"
    ).stdout.strip().split()
    local_ahead, remote_ahead = int(relation[0]), int(relation[1])
    if local_ahead > 0 and remote_ahead > 0:
        raise GitPreflightError(
            "RETURN_BRANCH_DIVERGED",
            f"{return_branch} diverged from {remote}/{return_branch}",
        )
    if local_ahead > 0:
        raise GitPreflightError(
            "RETURN_BRANCH_LOCAL_AHEAD",
            f"{return_branch} contains local commits not present on {remote}/{return_branch}",
        )

    ancestry_merged: bool | None = None
    if local_head_oid is not None:
        ancestry = repo.git(
            "merge-base",
            "--is-ancestor",
            head_ref,
            remote_return,
            check=False,
        )
        ancestry_merged = ancestry.returncode == 0

    steps: list[dict[str, Any]] = []
    if current_branch != return_branch:
        steps.append(
            {"operation": "switch-return-branch", "argv": ["git", "switch", return_branch]}
        )
    if remote_ahead > 0:
        steps.append(
            {
                "operation": "sync-return-branch",
                "argv": ["git", "merge", "--ff-only", f"{remote}/{return_branch}"],
            }
        )

    if local_head_oid is not None:
        if ancestry_merged:
            delete_step = {
                "operation": "delete-local-pr-branch",
                "mode": "git-merged",
                "argv": ["git", "branch", "-d", head_branch],
            }
        else:
            # Squash/rebase merge не сохраняет ancestry feature branch. Provider
            # доказал MERGED exact headRefOid, а local ref выше сверена с этим
            # OID. update-ref с old OID работает как compare-and-swap.
            delete_step = {
                "operation": "delete-local-pr-branch",
                "mode": "provider-verified-head",
                "argv": ["git", "update-ref", "-d", head_ref, head_oid],
            }
        steps.append(delete_step)

    return _result(
        "pr-finish",
        pr=number,
        url=data.get("url"),
        branch=head_branch,
        currentBranch=current_branch,
        resumed=resumed,
        base=base_branch,
        returnBranch=return_branch,
        remote=remote,
        returnBranchAhead=local_ahead,
        returnBranchBehind=remote_ahead,
        mergedHeadOid=head_oid,
        gitAncestryMerged=ancestry_merged,
        worktree=worktree,
        stateFile=str(PR_STATE_PATH) if local_state is not None else None,
        deleteStateFileAfterSuccess=local_state is not None,
        mutationPlan={
            "steps": steps,
            "deleteRemoteBranch": False,
            "forceDeleteForbidden": True,
        },
    )


# ---------------------------------------------------------------------------
# Action: SYNC.
# В ff-only mode preflight не делает merge сам: он либо блокирует divergence/
# local-ahead/dirty worktree, либо возвращает exact git merge --ff-only plan.
# ---------------------------------------------------------------------------
def sync_preflight(root: Path) -> dict[str, Any]:
    config = policy(root)
    repo = Repo(root)
    branch = repo.branch()
    sync = config["sync"]
    remote = _text(sync, "fetch_remote", section="sync")
    _require_remote(repo, remote)
    repo.fetch(remote)

    if not repo.has_head():
        raise GitPreflightError("NO_COMMITS", "cannot sync repository without commits")

    remote_oid = repo.remote_ref(remote, branch)
    if remote_oid is None:
        return _result(
            "sync",
            branch=branch,
            remote=remote,
            mode=sync["mode"],
            remoteBranchExists=False,
            ahead=None,
            behind=None,
            mutationPlan={"operation": "report", "reason": "remote branch does not exist"},
        )

    relation = repo.ahead_behind(remote, branch)
    assert relation is not None
    ahead, behind = relation
    mode = sync["mode"]
    plan: dict[str, Any] = {"operation": "report"}

    if mode == "ff-only":
        if ahead > 0 and behind > 0:
            raise GitPreflightError(
                "SYNC_DIVERGED",
                f"local and {remote}/{branch} have diverged",
            )
        if ahead > 0:
            raise GitPreflightError(
                "SYNC_LOCAL_AHEAD",
                "ff-only sync cannot discard local commits",
            )
        if behind > 0:
            state = repo.status()
            if not state["clean"]:
                raise GitPreflightError(
                    "SYNC_DIRTY_WORKTREE",
                    "ff-only sync requires clean index/worktree",
                )
            plan = {
                "operation": "git merge --ff-only",
                "argv": ["git", "merge", "--ff-only", f"{remote}/{branch}"],
            }
        else:
            plan = {"operation": "noop"}

    return _result(
        "sync",
        branch=branch,
        remote=remote,
        mode=mode,
        remoteBranchExists=True,
        ahead=ahead,
        behind=behind,
        upstream=repo.upstream(),
        mutationPlan=plan,
    )


def _print(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(result["status"])
    print(f"action: {result.get('action')}")
    for key in ("pr", "branch", "returnBranch", "remote", "base", "ahead", "behind"):
        if key in result:
            print(f"{key}: {result[key]}")


# ---------------------------------------------------------------------------
# CLI boundary: любые GitPreflightError/ConfigError/OSError нормализуются в
# status=BLOCKED + reasonCode. Exit 2 означает safety blocker, exit 0 — PASS.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Git safety preflight")
    parser.add_argument("action", choices=["check", "commit", "push", "pr", "pr-finish", "sync"])
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--commit-type")
    parser.add_argument("--slug")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        if args.action == "check":
            result = check(root)
        elif args.action == "commit":
            result = commit_preflight(
                root,
                commit_type=args.commit_type,
                slug=args.slug,
            )
        elif args.action == "push":
            result = push_preflight(root)
        elif args.action == "pr":
            result = pr_preflight(root)
        elif args.action == "pr-finish":
            result = pr_finish_preflight(root)
        else:
            result = sync_preflight(root)
    except (GitPreflightError, ConfigError, OSError) as exc:
        code = exc.code if isinstance(exc, GitPreflightError) else "CONFIG_OR_IO_ERROR"
        result = {
            "status": "BLOCKED",
            "action": args.action,
            "reasonCode": code,
            "message": str(exc),
        }
        if isinstance(exc, GitPreflightError) and exc.details:
            result["details"] = exc.details
        _print(result, as_json=args.as_json)
        return 2

    _print(result, as_json=args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
