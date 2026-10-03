#!/usr/bin/env python3
"""Provider adapters for deterministic Pull Request operations.

Module keeps GitHub/Gitea mechanics outside LLM-facing skills.  It resolves the
configured repository host, validates provider/tool pairs, checks provider CLI
availability/authentication and normalizes provider PR payloads to one Harness
contract.

Supported providers:
- github -> gh
- gitea  -> tea

Gitea uses Tea for both typed commands and authenticated API calls.  Tea login
selection is exact-host based; ambiguous matching profiles fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import quote, urlparse

PROVIDER_TIMEOUT_SECONDS = 60
SUPPORTED_PROVIDER_TOOLS = {
    "github": "gh",
    "gitea": "tea",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)\S+"),
    re.compile(r"(?i)(token[=:\s]+)\S+"),
    re.compile(r"(?i)(password[=:\s]+)\S+"),
)


class ProviderError(RuntimeError):
    """Stable provider blocker with safe machine-readable details."""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class RemoteIdentity:
    host: str
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class ProviderContext:
    provider: str
    tool: str
    remote: str
    identity: RemoteIdentity
    login: str | None = None


def _redact(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(r"\1<redacted>", result)
    return result


def cli_remediation(provider: str, tool: str, host: str | None = None) -> dict[str, Any]:
    """Return secret-free actionable installation/authentication guidance."""
    if provider == "github" and tool == "gh":
        auth_command = (
            f"gh auth login --hostname {host}"
            if host and host not in {"github.com", "www.github.com", "ssh.github.com"}
            else "gh auth login"
        )
        return {
            "provider": "github",
            "tool": "gh",
            "verifyCommand": "gh --version",
            "authCommand": auth_command,
            "documentation": [
                "https://cli.github.com/",
                "https://cli.github.com/manual/gh_auth_login",
            ],
        }
    if provider == "gitea" and tool == "tea":
        instance = host or "git.example.com"
        return {
            "provider": "gitea",
            "tool": "tea",
            "verifyCommand": "tea --version",
            "authCommand": (
                "tea login add --name <name> "
                f"--url https://{instance} --token <token>"
            ),
            "documentation": [
                "https://about.gitea.com/products/tea/",
                "https://gitea.com/gitea/tea",
            ],
        }
    return {"provider": provider, "tool": tool}


def validate_provider_tool(provider: str, tool: str) -> None:
    expected = SUPPORTED_PROVIDER_TOOLS.get(provider)
    if expected is None:
        raise ProviderError(
            "PR_PROVIDER_UNSUPPORTED",
            f"unsupported Pull Request provider: {provider}",
            provider=provider,
            supportedProviders=sorted(SUPPORTED_PROVIDER_TOOLS),
        )
    if tool != expected:
        raise ProviderError(
            "PR_PROVIDER_TOOL_MISMATCH",
            f"pull_request.provider={provider} requires preferred_tool={expected}, got {tool}",
            provider=provider,
            tool=tool,
            expectedTool=expected,
        )


def ensure_cli(provider: str, tool: str, *, host: str | None = None) -> None:
    validate_provider_tool(provider, tool)
    if shutil.which(tool) is not None:
        return
    help_data = cli_remediation(provider, tool, host)
    raise ProviderError(
        "PROVIDER_CLI_NOT_FOUND",
        (
            f"{tool} is required for pull_request.provider={provider} but was not found in PATH. "
            f"Install it using the official documentation listed in details.documentation, "
            f"verify installation with '{help_data.get('verifyCommand')}', and configure authentication "
            f"with '{help_data.get('authCommand')}'."
        ),
        **help_data,
    )


def _run(
    root: Path,
    argv: list[str],
    *,
    input_text: str | None = None,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(
            "PR_PROVIDER_TIMEOUT",
            f"PR provider command timed out after {PROVIDER_TIMEOUT_SECONDS}s",
            tool=argv[0] if argv else None,
            timeoutSeconds=PROVIDER_TIMEOUT_SECONDS,
        ) from exc
    except OSError as exc:
        raise ProviderError(
            "PROVIDER_CLI_EXEC_FAILED",
            f"cannot execute PR provider CLI: {_redact(str(exc))}",
            tool=argv[0] if argv else None,
        ) from exc

    if proc.returncode and not allow_failure:
        message = _redact(proc.stderr.strip() or proc.stdout.strip() or "PR provider command failed")
        low = message.lower()
        if any(token in low for token in ("unauthorized", "authentication", "bad credentials", "401", "forbidden", "403")):
            code = "PROVIDER_AUTH_REJECTED"
        elif any(token in low for token in ("connection refused", "timed out", "timeout", "no such host", "network is unreachable", "502", "503", "504")):
            code = "PROVIDER_API_UNAVAILABLE"
        else:
            code = "PR_PROVIDER_FAILED"
        raise ProviderError(
            code,
            message,
            tool=argv[0] if argv else None,
            exitCode=proc.returncode,
        )
    return proc


def _json_output(proc: subprocess.CompletedProcess[str], *, label: str) -> Any:
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            "PR_PROVIDER_INVALID_JSON",
            f"{label} returned invalid JSON",
        ) from exc


def _git_remote_url(root: Path, remote: str) -> str:
    proc = _run(
        root,
        ["git", "config", "--get", f"remote.{remote}.url"],
        allow_failure=True,
    )
    value = proc.stdout.strip()
    if proc.returncode or not value:
        raise ProviderError(
            "PR_REPO_UNRESOLVED",
            f"cannot resolve URL for configured remote {remote}",
            remote=remote,
        )
    return value


def parse_remote_identity(url: str) -> RemoteIdentity:
    """Parse https/ssh/scp-like Git URLs without accepting local paths."""
    value = url.strip()
    host: str | None = None
    path: str | None = None

    if re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.I):
        parsed = urlparse(value)
        host = parsed.hostname
        path = parsed.path
    else:
        match = re.match(r"^(?:[^@/]+@)?([^/:]+):(?!/)(.+)$", value)
        if match:
            host = match.group(1)
            path = match.group(2)

    if not host or not path:
        raise ProviderError(
            "PR_REPO_UNRESOLVED",
            f"cannot resolve provider repository from remote URL: {value}",
        )

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ProviderError(
            "PR_REPO_UNRESOLVED",
            f"remote URL does not contain owner/repository: {value}",
        )
    owner = parts[-2]
    repo = parts[-1].removesuffix(".git")
    safe = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe.fullmatch(owner) or not safe.fullmatch(repo):
        raise ProviderError(
            "PR_REPO_UNRESOLVED",
            f"remote owner/repository contains unsupported characters: {value}",
        )
    return RemoteIdentity(host=host.lower(), owner=owner, repo=repo)


def _normalize_url_host(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip() if "://" in value else "https://" + value.strip())
    return parsed.hostname.lower() if parsed.hostname else None


def _github_auth(root: Path, ctx: ProviderContext) -> None:
    proc = _run(
        root,
        [ctx.tool, "auth", "status", "--hostname", ctx.identity.host],
        allow_failure=True,
    )
    if proc.returncode == 0:
        return
    message = _redact(proc.stderr.strip() or proc.stdout.strip())
    low = message.lower()
    help_data = cli_remediation(ctx.provider, ctx.tool, ctx.identity.host)
    rejected = any(
        token in low
        for token in ("invalid token", "token is invalid", "expired", "bad credentials", "401", "403")
    )
    code = "PROVIDER_AUTH_REJECTED" if rejected else "PROVIDER_AUTH_REQUIRED"
    raise ProviderError(
        code,
        (
            f"gh is installed but authentication for {ctx.identity.host} "
            + ("is invalid or expired. " if rejected else "is not configured. ")
            + f"Run '{help_data['authCommand']}' and verify with "
            f"'gh auth status --hostname {ctx.identity.host}'."
        ),
        host=ctx.identity.host,
        **help_data,
    )


def _tea_status_rows(root: Path, tool: str) -> list[dict[str, Any]]:
    """Read Tea login status; fall back to login list for older compatible builds."""
    status = _run(root, [tool, "login", "status", "--output", "json"], allow_failure=True)
    if status.stdout.strip():
        try:
            data = json.loads(status.stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            rows = data.get("logins")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
            return [data]
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]

    listing = _run(root, [tool, "login", "list", "--output", "json"], allow_failure=True)
    if listing.returncode:
        raise ProviderError(
            "PROVIDER_AUTH_QUERY_FAILED",
            _redact(listing.stderr.strip() or listing.stdout.strip() or "cannot read Tea logins"),
            provider="gitea",
            tool=tool,
        )
    data = _json_output(listing, label="tea login list")
    if isinstance(data, dict):
        rows = data.get("logins")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    raise ProviderError("PR_PROVIDER_INVALID_JSON", "tea login list must return an object or array")


def _tea_login(root: Path, ctx: ProviderContext) -> str:
    rows = _tea_status_rows(root, ctx.tool)
    matches: list[dict[str, Any]] = []
    for row in rows:
        url = row.get("url") or row.get("URL")
        if _normalize_url_host(url) == ctx.identity.host:
            matches.append(row)

    if not matches:
        help_data = cli_remediation(ctx.provider, ctx.tool, ctx.identity.host)
        raise ProviderError(
            "PROVIDER_AUTH_REQUIRED",
            (
                f"Tea is installed but no login matches Gitea host {ctx.identity.host}. "
                f"Add one with '{help_data['authCommand']}'."
            ),
            host=ctx.identity.host,
            **help_data,
        )

    names = sorted(
        {
            str(row.get("name") or row.get("Name") or "").strip()
            for row in matches
            if str(row.get("name") or row.get("Name") or "").strip()
        }
    )
    if len(matches) > 1 or len(names) != 1:
        raise ProviderError(
            "PROVIDER_LOGIN_AMBIGUOUS",
            f"multiple Tea login profiles match host {ctx.identity.host}; select a single exact host profile",
            host=ctx.identity.host,
            loginNames=names,
        )

    row = matches[0]
    valid = row.get("valid")
    if valid is False:
        raise ProviderError(
            "PROVIDER_AUTH_REJECTED",
            f"Tea login {names[0]} for {ctx.identity.host} is present but authentication is invalid or expired",
            provider="gitea",
            tool=ctx.tool,
            host=ctx.identity.host,
            login=names[0],
        )

    # Older Tea output may not expose 'valid'.  Verify the exact selected login.
    if valid is not True:
        probe = _run(root, [ctx.tool, "whoami", "--login", names[0]], allow_failure=True)
        if probe.returncode:
            raise ProviderError(
                "PROVIDER_AUTH_REJECTED",
                f"Tea login {names[0]} for {ctx.identity.host} could not authenticate",
                provider="gitea",
                tool=ctx.tool,
                host=ctx.identity.host,
                login=names[0],
            )
    return names[0]


def provider_context(root: Path, gate: dict[str, Any]) -> ProviderContext:
    provider = str(gate.get("provider") or "")
    tool = str(gate.get("preferredTool") or "")
    remote = str(gate.get("remote") or "")
    validate_provider_tool(provider, tool)
    identity = parse_remote_identity(_git_remote_url(root, remote))
    ensure_cli(provider, tool, host=identity.host)
    ctx = ProviderContext(provider=provider, tool=tool, remote=remote, identity=identity)
    if provider == "github":
        _github_auth(root, ctx)
        return ctx
    login = _tea_login(root, ctx)
    return ProviderContext(
        provider=provider,
        tool=tool,
        remote=remote,
        identity=identity,
        login=login,
    )


def _normalize_github_pr(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "url": item.get("url"),
        "state": item.get("state"),
        "headRefName": item.get("headRefName"),
        "headRefOid": item.get("headRefOid"),
        "baseRefName": item.get("baseRefName"),
        "isDraft": bool(item.get("isDraft")),
        "title": item.get("title"),
        "mergedAt": item.get("mergedAt"),
    }


def _normalize_gitea_pr(item: dict[str, Any]) -> dict[str, Any]:
    head = item.get("head") if isinstance(item.get("head"), dict) else {}
    base = item.get("base") if isinstance(item.get("base"), dict) else {}
    state = str(item.get("state") or "").upper()
    merged = item.get("merged") is True
    if merged:
        state = "MERGED"
    elif state == "OPEN":
        state = "OPEN"
    elif state in {"CLOSED", "CLOSE"}:
        state = "CLOSED"
    title = item.get("title")
    draft = item.get("draft")
    if not isinstance(draft, bool):
        draft = isinstance(title, str) and bool(re.match(r"(?i)^\s*(?:WIP:|\[WIP\])", title))
    return {
        "number": item.get("number") or item.get("index"),
        "url": item.get("html_url") or item.get("url"),
        "state": state,
        "headRefName": head.get("ref") or item.get("headRefName"),
        "headRefOid": head.get("sha") or item.get("headRefOid"),
        "baseRefName": base.get("ref") or item.get("baseRefName"),
        "isDraft": draft,
        "title": title,
        "mergedAt": item.get("merged_at") or item.get("mergedAt"),
    }


def _tea_api(
    root: Path,
    ctx: ProviderContext,
    endpoint: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> Any:
    assert ctx.login is not None
    argv = [ctx.tool, "api", "--login", ctx.login]
    if method != "GET":
        argv.extend(["--method", method])
    input_text = None
    if body is not None:
        argv.extend(["--data", "@-"])
        input_text = json.dumps(body, ensure_ascii=False)
    argv.append(endpoint)
    proc = _run(root, argv, input_text=input_text)
    return _json_output(proc, label="tea api")


def open_prs(root: Path, gate: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = provider_context(root, gate)
    branch = str(gate["branch"])
    base = str(gate["base"])

    if ctx.provider == "github":
        proc = _run(
            root,
            [
                ctx.tool,
                "pr",
                "list",
                "--repo",
                ctx.identity.slug if ctx.identity.host in {"github.com", "www.github.com", "ssh.github.com"} else f"{ctx.identity.host}/{ctx.identity.slug}",
                "--head",
                branch,
                "--base",
                base,
                "--state",
                "open",
                "--limit",
                "10",
                "--json",
                "number,url,state,headRefName,headRefOid,baseRefName,isDraft,title",
            ],
        )
        data = _json_output(proc, label="gh pr list")
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ProviderError("PR_PROVIDER_INVALID_JSON", "gh pr list must return a JSON array")
        items = [_normalize_github_pr(item) for item in data]
    else:
        # Gitea exposes exact base/head lookup. Prefer it to paginated listing
        # so reuse cannot miss an older open PR when a repository has many PRs.
        endpoint = (
            f"/repos/{ctx.identity.owner}/{ctx.identity.repo}/pulls/"
            f"{quote(base, safe='')}/{quote(branch, safe='')}"
        )
        assert ctx.login is not None
        argv = [ctx.tool, "api", "--login", ctx.login, endpoint]
        proc = _run(root, argv, allow_failure=True)
        if proc.returncode:
            message = _redact(proc.stderr.strip() or proc.stdout.strip())
            low = message.lower()
            if any(token in low for token in ("404", "not found")):
                return []
            if any(token in low for token in ("unauthorized", "authentication", "bad credentials", "401", "forbidden", "403")):
                raise ProviderError(
                    "PROVIDER_AUTH_REJECTED",
                    message or "Gitea rejected Tea authentication",
                    provider="gitea",
                    tool=ctx.tool,
                    host=ctx.identity.host,
                )
            if any(token in low for token in ("connection refused", "timed out", "timeout", "no such host", "network is unreachable", "502", "503", "504")):
                raise ProviderError(
                    "PROVIDER_API_UNAVAILABLE",
                    message or "Gitea API is unavailable",
                    provider="gitea",
                    tool=ctx.tool,
                    host=ctx.identity.host,
                )
            raise ProviderError(
                "PR_PROVIDER_FAILED",
                message or "Gitea exact pull request query failed",
                provider="gitea",
                tool=ctx.tool,
                host=ctx.identity.host,
                exitCode=proc.returncode,
            )
        data = _json_output(proc, label="tea api pull lookup")
        if not isinstance(data, dict):
            raise ProviderError("PR_PROVIDER_INVALID_JSON", "Gitea exact pull lookup must return an object")
        items = [_normalize_gitea_pr(data)]

    return [
        item
        for item in items
        if item.get("headRefName") == branch
        and item.get("baseRefName") == base
        and item.get("state") == "OPEN"
    ]


def create_pr(root: Path, gate: dict[str, Any], *, title: str, body: str) -> None:
    ctx = provider_context(root, gate)
    if ctx.provider == "github":
        argv = [
            ctx.tool,
            "pr",
            "create",
            "--repo",
            ctx.identity.slug if ctx.identity.host in {"github.com", "www.github.com", "ssh.github.com"} else f"{ctx.identity.host}/{ctx.identity.slug}",
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
        _run(root, argv, input_text=body)
        return

    assert ctx.login is not None
    argv = [
        ctx.tool,
        "pulls",
        "create",
        "--login",
        ctx.login,
        "--repo",
        ctx.identity.slug,
        "--head",
        str(gate["branch"]),
        "--base",
        str(gate["base"]),
        "--title",
        title,
        "--description-file",
        "-",
    ]
    if gate.get("draft"):
        argv.append("--draft")
    try:
        _run(root, argv, input_text=body)
    except ProviderError as exc:
        if gate.get("draft") and exc.code == "PR_PROVIDER_FAILED":
            low = str(exc).lower()
            if "draft" in low and any(token in low for token in ("unknown", "unsupported", "flag")):
                raise ProviderError(
                    "PR_DRAFT_UNSUPPORTED",
                    "configured Tea/Gitea version does not support draft Pull Request creation",
                    provider="gitea",
                    tool=ctx.tool,
                    host=ctx.identity.host,
                ) from exc
        raise


def view_pr(
    root: Path,
    config: dict[str, Any],
    selector: str | int,
) -> dict[str, Any]:
    pr = config["pull_request"]
    gate = {
        "provider": pr.get("provider"),
        "preferredTool": pr.get("preferred_tool"),
        "remote": config["push"].get("remote"),
        "branch": str(selector) if isinstance(selector, str) else "",
        "base": pr.get("base"),
    }
    ctx = provider_context(root, gate)

    if ctx.provider == "github":
        repo_selector = (
            ctx.identity.slug
            if ctx.identity.host in {"github.com", "www.github.com", "ssh.github.com"}
            else f"{ctx.identity.host}/{ctx.identity.slug}"
        )
        proc = _run(
            root,
            [
                ctx.tool,
                "pr",
                "view",
                str(selector),
                "--repo",
                repo_selector,
                "--json",
                "number,state,mergedAt,headRefName,headRefOid,baseRefName,url,isDraft,title",
            ],
        )
        data = _json_output(proc, label="gh pr view")
        if not isinstance(data, dict):
            raise ProviderError("PR_QUERY_INVALID", "gh pr view returned non-object JSON")
        return _normalize_github_pr(data)

    if isinstance(selector, int):
        endpoint = f"/repos/{ctx.identity.owner}/{ctx.identity.repo}/pulls/{selector}"
    else:
        base = str(pr.get("base") or "")
        endpoint = (
            f"/repos/{ctx.identity.owner}/{ctx.identity.repo}/pulls/"
            f"{quote(base, safe='')}/{quote(selector, safe='')}"
        )
    data = _tea_api(root, ctx, endpoint)
    if not isinstance(data, dict):
        raise ProviderError("PR_QUERY_INVALID", "Gitea pull request query returned non-object JSON")
    return _normalize_gitea_pr(data)
