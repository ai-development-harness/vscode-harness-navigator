#!/usr/bin/env python3
"""Synthetic regression deterministic GitHub PR action."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from git_action import GitActionError, execute_pr


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


def copy(root: Path, rel: str) -> None:
    src = SOURCE_ROOT / rel
    dst = root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def fake_gh(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
state_path = Path(os.environ["FAKE_GH_STATE"])

if args[:2] == ["pr", "list"]:
    if state_path.is_file():
        print(json.dumps([json.loads(state_path.read_text())]))
    else:
        print("[]")
    raise SystemExit(0)

if args[:2] == ["pr", "create"]:
    def value(flag):
        return args[args.index(flag) + 1]

    item = {
        "number": 17,
        "url": "https://example.invalid/pr/17",
        "state": "OPEN",
        "headRefName": value("--head"),
        "headRefOid": os.environ["FAKE_HEAD_OID"],
        "baseRefName": value("--base"),
        "isDraft": "--draft" in args,
        "title": value("--title"),
    }
    state_path.write_text(json.dumps(item))
    print(item["url"])
    raise SystemExit(0)

print("unsupported fake gh invocation: " + " ".join(args), file=sys.stderr)
raise SystemExit(9)
""",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o755)


def prepare(root: Path) -> tuple[Path, Path]:
    copy(root, ".harness/manifest.yaml")
    copy(root, ".harness/git-policy.toml")
    copy(root, ".github/pull_request_template.md")

    remote = root.parent / "remote.git"
    run(root.parent, "git", "init", "--bare", "-q", str(remote))
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "pr-action@example.invalid")
    run(root, "git", "config", "user.name", "PR Action Test")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "chore: bootstrap fixture")
    run(root, "git", "remote", "add", "origin", str(remote))
    run(root, "git", "push", "-q", "-u", "origin", "main")

    run(root, "git", "switch", "-qc", "feature/pr-action")
    (root / "feature.txt").write_text("feature\n", encoding="utf-8")
    run(root, "git", "add", "feature.txt")
    run(root, "git", "commit", "-qm", "feat: deterministic provider PR")
    run(root, "git", "push", "-q", "-u", "origin", "feature/pr-action")

    body = root / ".harness/local/git/pr-body.md"
    body.parent.mkdir(parents=True, exist_ok=True)
    body.write_text(
        "## Summary\n\nDeterministic PR action fixture.\n",
        encoding="utf-8",
        newline="\n",
    )
    return remote, body


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-pr-action-") as tmp:
        root = Path(tmp) / "work"
        root.mkdir()
        _remote, body = prepare(root)

        fake_bin = root / ".fake-bin"
        fake = fake_bin / "gh"
        fake_gh(fake)
        provider_state = root / ".fake-gh-state.json"

        old_path = os.environ.get("PATH", "")
        old_state = os.environ.get("FAKE_GH_STATE")
        old_oid = os.environ.get("FAKE_HEAD_OID")
        os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
        os.environ["FAKE_GH_STATE"] = str(provider_state)
        os.environ["FAKE_HEAD_OID"] = run(root, "git", "rev-parse", "HEAD")

        try:
            # Create path derives title from exact commit subject and persists
            # local lifecycle state mechanically.
            created = execute_pr(root, body_file=body)
            assert created["status"] == "SUCCESS", created
            assert created["reused"] is False, created
            assert created["pr"] == 17, created
            assert created["branch"] == "feature/pr-action", created
            assert created["base"] == "main", created

            provider = json.loads(provider_state.read_text(encoding="utf-8"))
            assert provider["title"] == "feat: deterministic provider PR", provider

            state_path = root / ".harness/local/git/pr-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            assert state == {
                "version": 1,
                "pr": 17,
                "headBranch": "feature/pr-action",
                "baseBranch": "main",
                "returnBranch": "main",
                "url": "https://example.invalid/pr/17",
            }, state

            # Idempotent retry reuses provider PR and needs no semantic files.
            reused = execute_pr(root)
            assert reused["status"] == "SUCCESS", reused
            assert reused["reused"] is True, reused
            assert reused["pr"] == 17, reused

            # Exact provider head OID is a postcondition, not trusted prose.
            original = json.loads(provider_state.read_text(encoding="utf-8"))
            broken = dict(original)
            broken["headRefOid"] = "0" * 40
            provider_state.write_text(json.dumps(broken), encoding="utf-8")
            try:
                execute_pr(root)
            except GitActionError as exc:
                assert exc.code == "PR_POSTCONDITION_FAILED", exc.code
            else:
                raise AssertionError("provider head OID mismatch was accepted")
            provider_state.write_text(json.dumps(original), encoding="utf-8")

            # reuse_existing=false never creates a duplicate silently.
            policy = root / ".harness/git-policy.toml"
            policy.write_text(
                policy.read_text(encoding="utf-8").replace(
                    "reuse_existing = true",
                    "reuse_existing = false",
                    1,
                ),
                encoding="utf-8",
                newline="\n",
            )
            try:
                execute_pr(root)
            except GitActionError as exc:
                assert exc.code == "PR_ALREADY_EXISTS", exc.code
            else:
                raise AssertionError("existing PR was duplicated with reuse_existing=false")
        finally:
            os.environ["PATH"] = old_path
            if old_state is None:
                os.environ.pop("FAKE_GH_STATE", None)
            else:
                os.environ["FAKE_GH_STATE"] = old_state
            if old_oid is None:
                os.environ.pop("FAKE_HEAD_OID", None)
            else:
                os.environ["FAKE_HEAD_OID"] = old_oid

    print("GIT PR ACTION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
