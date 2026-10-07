#!/usr/bin/env python3
"""Synthetic regression for initialized downstream upgrade qualification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


RUNNER = Path(__file__).with_name("release-upgrade-qualification.py")


def run(command: list[str], *, cwd: Path, expect: int = 0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"expected {expect}, got {proc.returncode}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return proc


def git(root: Path, *args: str) -> str:
    return run(["git", *args], cwd=root).stdout.strip()


def commit_all(root: Path, message: str) -> str:
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def init_repo(root: Path) -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Qualification Self Test")
    git(root, "config", "user.email", "qualification@example.invalid")


def candidate_source(root: Path) -> tuple[str, str]:
    root.mkdir()
    init_repo(root)
    write(
        root,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "release": "0.11.2",
                "source": {"repository": "ai-development-harness/ai-development-harness-template", "ref": "v0.11.2"},
            }
        ),
    )
    write(
        root,
        ".harness/harness-update-graph.json",
        json.dumps({"schemaVersion": 1, "latest": "v0.11.2", "transitions": []}),
    )
    write(
        root,
        ".harness/harness-update.toml",
        '[source]\ndefault_branch = "main"\n',
    )
    stable = commit_all(root, "stable")
    git(root, "tag", "v0.11.2", stable)
    # Regression #272: mirror clone must not preserve this stale ref as the
    # updater-visible default branch after candidate preparation.
    git(root, "update-ref", "refs/remotes/origin/main", stable)

    write(
        root,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "release": "0.11.3",
                "source": {"repository": "ai-development-harness/ai-development-harness-template", "ref": "v0.11.3"},
            }
        ),
    )
    write(
        root,
        ".harness/harness-update-graph.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "latest": "v0.11.3",
                "transitions": [
                    {
                        "from": "v0.11.2",
                        "to": "v0.11.3",
                        "kind": "standard",
                        "reloadRequired": False,
                    }
                ],
            }
        ),
    )
    candidate = commit_all(root, "candidate")
    return stable, candidate


def updater_source(*, mutate_project_owned: bool) -> str:
    mutation = ""
    if mutate_project_owned:
        mutation = (
            "        Path('planning/reviews/TEMPLATE.md').write_text("
            "'mutated by updater\\n', encoding='utf-8')\n"
        )
    return f"""#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("action")
parser.add_argument("--to", required=True)
parser.add_argument("--source-url", required=True)
parser.add_argument("--json", action="store_true")
args = parser.parse_args()

import subprocess

root = Path(__file__).resolve().parents[2]
candidate_oid = subprocess.run(
    ["git", "-C", args.source_url, "rev-parse", f"refs/tags/{{args.to}}^{{{{commit}}}}"],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
).stdout.strip()
routing_oid = subprocess.run(
    ["git", "-C", args.source_url, "rev-parse", "refs/remotes/origin/main^{{commit}}"],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
).stdout.strip()
if routing_oid != candidate_oid:
    print(json.dumps({{"status":"BLOCKED","reasonCode":"NO_UPDATE_PATH"}}))
    raise SystemExit(2)
local = root / ".harness" / "local"
local.mkdir(parents=True, exist_ok=True)
reload_marker = local / "reload-seen"

if not reload_marker.exists():
    reload_marker.write_text("1", encoding="utf-8")
    result = {{"status": "UPDATER_RELOAD_REQUIRED", "current": "v0.11.2"}}
else:
    lock_path = root / ".harness" / "harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["source"]["ref"] == args.to:
        result = {{"status": "NO_UPDATE", "repositoryMutated": False}}
    else:
        lock["release"] = args.to.removeprefix("v")
        lock["source"]["ref"] = args.to
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
{mutation}        result = {{"status": "UPDATED", "current": args.to}}

print(json.dumps(result))
"""


def baseline_project(root: Path, *, mutate_project_owned: bool = False) -> str:
    root.mkdir()
    init_repo(root)
    write(
        root,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "release": "0.11.2",
                "source": {"repository": "ai-development-harness/ai-development-harness-template", "ref": "v0.11.2"},
            }
        ),
    )
    write(root, ".harness/tools/harness-update.py", updater_source(mutate_project_owned=mutate_project_owned))
    write(
        root,
        ".harness/tools/migrate-project-schema.py",
        """#!/usr/bin/env python3
import argparse, json
p=argparse.ArgumentParser(); p.add_argument("--check", action="store_true"); p.add_argument("--json", action="store_true"); p.parse_args()
print(json.dumps({"status":"CURRENT","legacyPending":False}))
""",
    )
    write(
        root,
        ".harness/tools/harness-ux.py",
        """#!/usr/bin/env python3
import json, sys
print(json.dumps({"status":"PASS","command":sys.argv[1]}))
""",
    )
    write(root, ".harness/tools/validate.py", "raise SystemExit(0)\n")
    write(root, ".harness/tools/run-self-tests.py", "raise SystemExit(0)\n")
    write(root, "planning/reviews/TEMPLATE.md", "project-owned review template\n")
    write(root, "planning/init-reviews/INIT-REVIEW-1.md", "immutable init report\n")
    write(root, "docs/adr/ADR-001.md", "accepted decision\n")
    write(root, "docs/canary-state.md", "canary inventory\n")
    return commit_all(root, "baseline")


def invoke(
    runner_root: Path,
    baseline: Path,
    baseline_sha: str,
    source: Path,
    candidate_sha: str,
    *,
    expect: int,
) -> dict[str, object]:
    proc = run(
        [
            sys.executable,
            str(RUNNER),
            "--baseline-project",
            str(baseline),
            "--baseline-sha",
            baseline_sha,
            "--candidate-source",
            str(source),
            "--candidate-sha",
            candidate_sha,
            "--json",
        ],
        cwd=runner_root,
        expect=expect,
    )
    return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="initialized-upgrade-qualification-") as td:
        root = Path(td)
        source = root / "candidate"
        baseline = root / "baseline"
        _stable, candidate = candidate_source(source)
        baseline_sha = baseline_project(baseline)

        source_head = git(source, "rev-parse", "HEAD")
        baseline_head = git(baseline, "rev-parse", "HEAD")
        payload = invoke(root, baseline, baseline_sha, source, candidate, expect=0)
        assert payload["status"] == "PASS", payload
        assert payload["candidateRevision"] == candidate, payload
        assert payload["candidateRelease"] == "v0.11.3", payload
        assert any(item["result"] == "UPDATER_RELOAD_REQUIRED" for item in payload["stages"] if item["id"].startswith("apply-")), payload
        assert any(item["result"] == "NO_UPDATE" for item in payload["stages"] if item["id"].startswith("apply-")), payload
        assert git(source, "rev-parse", "HEAD") == source_head
        assert git(baseline, "rev-parse", "HEAD") == baseline_head
        assert git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""
        assert git(baseline, "status", "--porcelain=v1", "--untracked-files=all") == ""

        bad = root / "bad-baseline"
        bad_sha = baseline_project(bad, mutate_project_owned=True)
        failed = invoke(root, bad, bad_sha, source, candidate, expect=1)
        assert failed["status"] == "FAIL", failed
        assert failed["reasonCode"] == "PROJECT_OWNED_STATE_CHANGED", failed
        assert git(bad, "status", "--porcelain=v1", "--untracked-files=all") == ""

        write(
            source,
            ".harness/harness-update-graph.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "latest": "v0.11.2",
                    "transitions": [],
                }
            ),
        )
        not_prepared = commit_all(source, "candidate metadata mismatch")
        blocked = invoke(root, baseline, baseline_sha, source, not_prepared, expect=1)
        assert blocked["status"] == "FAIL", blocked
        assert blocked["reasonCode"] == "CANDIDATE_NOT_RELEASE_PREPARED", blocked

    print("initialized upgrade qualification self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
