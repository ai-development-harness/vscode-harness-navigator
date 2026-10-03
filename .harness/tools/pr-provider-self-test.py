#!/usr/bin/env python3
"""Synthetic regressions for deterministic GitHub/Gitea PR provider adapters."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

import pr_provider
from pr_provider import (
    ProviderError,
    create_pr,
    ensure_cli,
    open_prs,
    parse_remote_identity,
    provider_context,
    validate_provider_tool,
)


def run(root: Path, *args: str) -> str:
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
            f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout.strip()


def fake_tea(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

args = sys.argv[1:]
state = Path(os.environ["FAKE_TEA_STATE"])
mode = os.environ.get("FAKE_TEA_LOGIN_MODE", "valid")

if args[:3] == ["login", "status", "--output"] and args[3:] == ["json"]:
    if mode == "ambiguous":
        rows = [
            {"name": "one", "url": "https://git.example.com", "valid": True},
            {"name": "two", "url": "https://git.example.com/", "valid": True},
        ]
    elif mode == "invalid":
        rows = [{"name": "work", "url": "https://git.example.com", "valid": False}]
    elif mode == "other":
        rows = [{"name": "other", "url": "https://other.example.com", "valid": True}]
    else:
        rows = [{"name": "work", "url": "https://git.example.com", "valid": True}]
    print(json.dumps(rows))
    raise SystemExit(0)

if args[:2] == ["pulls", "create"]:
    def value(flag):
        return args[args.index(flag) + 1]
    if value("--login") != "work":
        print("wrong login", file=sys.stderr)
        raise SystemExit(8)
    if value("--repo") != "team/project":
        print("wrong repo", file=sys.stderr)
        raise SystemExit(8)
    body = sys.stdin.read() if value("--description-file") == "-" else ""
    item = {
        "number": 23,
        "html_url": "https://git.example.com/team/project/pulls/23",
        "state": "open",
        "title": ("WIP: " if "--draft" in args else "") + value("--title"),
        "head": {"ref": value("--head"), "sha": os.environ["FAKE_HEAD_OID"]},
        "base": {"ref": value("--base"), "sha": "b" * 40},
        "merged": False,
        "body": body,
    }
    state.write_text(json.dumps(item), encoding="utf-8")
    print(item["html_url"])
    raise SystemExit(0)

if args and args[0] == "api":
    if "--login" not in args or args[args.index("--login") + 1] != "work":
        print("wrong api login", file=sys.stderr)
        raise SystemExit(8)
    endpoint = args[-1]
    if endpoint.startswith("/repos/team/project/pulls/"):
        if not state.is_file():
            print("404 not found", file=sys.stderr)
            raise SystemExit(1)
        print(state.read_text())
        raise SystemExit(0)

if args[:2] == ["whoami", "--login"]:
    raise SystemExit(0)

print("unsupported fake tea invocation: " + " ".join(args), file=sys.stderr)
raise SystemExit(9)
""",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o755)


def assert_code(callable_, expected: str) -> ProviderError:
    try:
        callable_()
    except ProviderError as exc:
        assert exc.code == expected, (expected, exc.code, str(exc), exc.details)
        return exc
    raise AssertionError(f"expected {expected}")


def main() -> int:
    # Remote parser must support https, scp-like ssh and ssh:// self-hosted forms.
    expected = ("git.example.com", "team", "project")
    for value in (
        "https://git.example.com/team/project.git",
        "git@git.example.com:team/project.git",
        "ssh://git@git.example.com/team/project.git",
    ):
        identity = parse_remote_identity(value)
        assert (identity.host, identity.owner, identity.repo) == expected, identity

    validate_provider_tool("github", "gh")
    validate_provider_tool("gitea", "tea")
    assert_code(lambda: validate_provider_tool("gitea", "gh"), "PR_PROVIDER_TOOL_MISMATCH")
    assert_code(lambda: validate_provider_tool("forgejo", "tea"), "PR_PROVIDER_UNSUPPORTED")

    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = ""
    try:
        missing_gh = assert_code(
            lambda: ensure_cli("github", "gh", host="github.com"),
            "PROVIDER_CLI_NOT_FOUND",
        )
        assert "https://cli.github.com/" in missing_gh.details["documentation"]
        missing_tea = assert_code(
            lambda: ensure_cli("gitea", "tea", host="git.example.com"),
            "PROVIDER_CLI_NOT_FOUND",
        )
        assert "tea login add" in missing_tea.details["authCommand"]
        assert "https://about.gitea.com/products/tea/" in missing_tea.details["documentation"]
    finally:
        os.environ["PATH"] = old_path

    with tempfile.TemporaryDirectory(prefix="harness-pr-provider-") as tmp:
        root = Path(tmp)
        run(root, "git", "init", "-q")
        run(root, "git", "remote", "add", "origin", "ssh://git@git.example.com/team/project.git")
        fake_bin = root / "bin"
        fake_tea(fake_bin / "tea")
        state = root / "tea-state.json"

        previous = {
            "PATH": os.environ.get("PATH"),
            "FAKE_TEA_STATE": os.environ.get("FAKE_TEA_STATE"),
            "FAKE_TEA_LOGIN_MODE": os.environ.get("FAKE_TEA_LOGIN_MODE"),
            "FAKE_HEAD_OID": os.environ.get("FAKE_HEAD_OID"),
        }
        os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
        os.environ["FAKE_TEA_STATE"] = str(state)
        os.environ["FAKE_HEAD_OID"] = "a" * 40
        os.environ["FAKE_TEA_LOGIN_MODE"] = "valid"

        gate = {
            "provider": "gitea",
            "preferredTool": "tea",
            "remote": "origin",
            "branch": "feature/gitea",
            "base": "main",
            "draft": True,
        }
        try:
            ctx = provider_context(root, gate)
            assert ctx.identity.host == "git.example.com", ctx
            assert ctx.identity.slug == "team/project", ctx
            assert ctx.login == "work", ctx

            assert open_prs(root, gate) == []
            create_pr(
                root,
                gate,
                title="feat: gitea provider",
                body="## Summary\n\nSelf-hosted Gitea.\n",
            )
            items = open_prs(root, gate)
            assert len(items) == 1, items
            item = items[0]
            assert item["number"] == 23, item
            assert item["headRefName"] == "feature/gitea", item
            assert item["headRefOid"] == "a" * 40, item
            assert item["baseRefName"] == "main", item
            assert item["isDraft"] is True, item

            os.environ["FAKE_TEA_LOGIN_MODE"] = "ambiguous"
            assert_code(lambda: provider_context(root, gate), "PROVIDER_LOGIN_AMBIGUOUS")

            os.environ["FAKE_TEA_LOGIN_MODE"] = "other"
            exc = assert_code(lambda: provider_context(root, gate), "PROVIDER_AUTH_REQUIRED")
            assert "tea login add" in exc.details["authCommand"]

            os.environ["FAKE_TEA_LOGIN_MODE"] = "invalid"
            assert_code(lambda: provider_context(root, gate), "PROVIDER_AUTH_REJECTED")

            # Provider stderr is normalized without leaking obvious token syntax.
            proc_run = pr_provider._run
            os.environ["FAKE_TEA_LOGIN_MODE"] = "valid"
            bad = fake_bin / "bad-provider"
            bad.write_text(
                "#!/bin/sh\necho 'token=super-secret' >&2\nexit 1\n",
                encoding="utf-8",
            )
            bad.chmod(0o755)
            leaked = assert_code(
                lambda: proc_run(root, [str(bad)]),
                "PR_PROVIDER_FAILED",
            )
            assert "super-secret" not in str(leaked)
            assert "<redacted>" in str(leaked)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    print("PR PROVIDER SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
