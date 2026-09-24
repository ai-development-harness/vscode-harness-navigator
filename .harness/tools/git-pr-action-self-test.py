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

    mutate_path = os.environ.get("FAKE_MUTATE_BODY_PATH")
    if mutate_path:
        Path(mutate_path).write_text(
            "## Raced body\\n\\nThis must not reach the provider.\\n",
            encoding="utf-8",
        )

    body_file = value("--body-file")
    body = sys.stdin.read() if body_file == "-" else Path(body_file).read_text()

    item = {
        "number": 17,
        "url": "https://example.invalid/pr/17",
        "state": "OPEN",
        "headRefName": value("--head"),
        "headRefOid": os.environ["FAKE_HEAD_OID"],
        "baseRefName": value("--base"),
        "isDraft": "--draft" in args,
        "title": value("--title"),
        "body": body,
        "bodyFile": body_file,
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
        old_mutate = os.environ.get("FAKE_MUTATE_BODY_PATH")
        os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
        os.environ["FAKE_GH_STATE"] = str(provider_state)
        os.environ["FAKE_HEAD_OID"] = run(root, "git", "rev-parse", "HEAD")

        try:
            # Create path derives title from exact commit subject and persists
            # local lifecycle state mechanically. Optional semantic title input
            # тоже является one-shot transport и удаляется после SUCCESS.
            title_input = root / ".harness/local/git/pr-title.md"
            title_input.write_text(
                "unused while title_from_commit=true\n",
                encoding="utf-8",
            )
            expected_body = body.read_text(encoding="utf-8")
            os.environ["FAKE_MUTATE_BODY_PATH"] = str(body)
            created = execute_pr(
                root,
                title_file=title_input,
                body_file=body,
            )
            os.environ.pop("FAKE_MUTATE_BODY_PATH", None)

            assert created["status"] == "SUCCESS", created
            assert created["reused"] is False, created
            assert created["pr"] == 17, created
            assert created["branch"] == "feature/pr-action", created
            assert created["base"] == "main", created
            assert created.get("cleanupWarnings"), created
            assert body.is_file(), "raced source body was unexpectedly deleted"
            assert "Raced body" in body.read_text(encoding="utf-8")
            assert not title_input.exists(), "successful PR action left unchanged title file"

            provider = json.loads(provider_state.read_text(encoding="utf-8"))
            assert provider["title"] == "feat: deterministic provider PR", provider
            assert provider["bodyFile"] == "-", provider
            assert provider["body"] == expected_body, provider

            # Unchanged inputs on an idempotent successful PR action are still
            # one-shot transport and are cleaned normally.
            reuse_body = root / ".harness/local/git/pr-body-reuse.md"
            reuse_title = root / ".harness/local/git/pr-title-reuse.md"
            reuse_body.write_text("reuse body\n", encoding="utf-8")
            reuse_title.write_text("reuse title\n", encoding="utf-8")
            reused_with_inputs = execute_pr(
                root,
                body_file=reuse_body,
                title_file=reuse_title,
            )
            assert reused_with_inputs["status"] == "SUCCESS", reused_with_inputs
            assert reused_with_inputs["reused"] is True, reused_with_inputs
            assert not reuse_body.exists(), reuse_body
            assert not reuse_title.exists(), reuse_title

            body.unlink()

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

            # Regression #85: semantic input symlink не должен позволять cleanup
            # удалить durable pr-state target после успешного reuse.
            state_before_symlink = state_path.read_bytes()
            body_link = root / ".harness/local/git/pr-body-link.md"
            body_link.symlink_to("pr-state.json")
            try:
                execute_pr(root, body_file=body_link)
            except GitActionError as exc:
                assert exc.code == "PR_INPUT_PATH_BLOCKED", exc.code
            else:
                raise AssertionError("PR body symlink was accepted")
            assert body_link.is_symlink(), body_link
            assert state_path.read_bytes() == state_before_symlink

            # Parent symlink запрещён так же, как leaf symlink.
            actual_dir = root / ".harness/local/git-input-target"
            actual_dir.mkdir(parents=True)
            parent_body = actual_dir / "body.md"
            parent_body.write_text("keep target\n", encoding="utf-8")
            alias_dir = root / ".harness/local/git/alias"
            alias_dir.symlink_to(actual_dir, target_is_directory=True)
            try:
                execute_pr(root, body_file=alias_dir / "body.md")
            except GitActionError as exc:
                assert exc.code == "PR_INPUT_PATH_BLOCKED", exc.code
            else:
                raise AssertionError("PR body parent symlink was accepted")
            assert alias_dir.is_symlink(), alias_dir
            assert parent_body.read_text(encoding="utf-8") == "keep target\n"

            # Exact provider head OID is a postcondition, not trusted prose.
            original = json.loads(provider_state.read_text(encoding="utf-8"))
            broken = dict(original)
            broken["headRefOid"] = "0" * 40
            provider_state.write_text(json.dumps(broken), encoding="utf-8")
            retry_body = root / ".harness/local/git/pr-body-retry.md"
            retry_body.write_text(
                "## Retry\n\nKeep me when provider validation fails.\n",
                encoding="utf-8",
            )
            retry_title = root / ".harness/local/git/pr-title-retry.md"
            retry_title.write_text("keep retry title\n", encoding="utf-8")
            try:
                execute_pr(
                    root,
                    title_file=retry_title,
                    body_file=retry_body,
                )
            except GitActionError as exc:
                assert exc.code == "PR_POSTCONDITION_FAILED", exc.code
            else:
                raise AssertionError("provider head OID mismatch was accepted")
            assert retry_body.is_file(), "failed PR action deleted retry body"
            assert retry_title.is_file(), "failed PR action deleted retry title"
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
            if old_mutate is None:
                os.environ.pop("FAKE_MUTATE_BODY_PATH", None)
            else:
                os.environ["FAKE_MUTATE_BODY_PATH"] = old_mutate

    print("GIT PR ACTION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
