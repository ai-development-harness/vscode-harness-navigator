#!/usr/bin/env python3
"""Integration: actual tagged v0.11.4 updater -> synthetic candidate, offline.

This test needs an upstream v0.11.4 Git tag in the current checkout. The
release-canary Git checkout intentionally has no Harness tags, so there this
test is skipped: the separate initialized-upgrade release gate owns the canary.
No GitHub/network access, production tags or canonical project files are
modified. All mutations take place in disposable Git repositories.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "v0.11.4"
SYNTHETIC_TARGET = "v99.0.0"


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        list(args), cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=120,
    )
    if check and proc.returncode:
        raise AssertionError(
            f"{' '.join(args)} ({proc.returncode})\n"
            f"stdout: {proc.stdout[-1800:]}\nstderr: {proc.stderr[-1800:]}"
        )
    return proc


def git(root: Path, *args: str) -> str:
    return run(root, "git", *args).stdout.strip()


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def candidate_from_current_checkout(source: Path) -> None:
    git(ROOT, "init", "--quiet", "--initial-branch=main", str(source))
    git(source, "config", "user.email", "upgrade-self-test@example.invalid")
    git(source, "config", "user.name", "Upgrade Self Test")
    # Fetch exact current HEAD and historical immutable tags through local Git.
    git(source, "fetch", "--quiet", "--tags", str(ROOT), "HEAD")
    git(source, "checkout", "--quiet", "-B", "main", "FETCH_HEAD")
    assert git(source, "rev-parse", "--verify", f"{BASELINE}^{{commit}}")

    lock_path = source / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["release"] = SYNTHETIC_TARGET.removeprefix("v")
    lock["source"]["ref"] = SYNTHETIC_TARGET
    # A candidate source SHA is created locally only; release identity remains
    # consistent with the synthetic target tag, not a published GitHub tag.
    lock["source"].pop("commit", None)
    write(lock_path, json.dumps(lock, indent=2) + "\n")

    manifest_path = source / ".harness/manifest.yaml"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest, count = re.subn(
        r'(?m)^(  release:)\s*"[^"]+"',
        rf'\g<1> "{SYNTHETIC_TARGET[1:]}"',
        manifest, count=1,
    )
    assert count == 1, "candidate manifest release cannot be updated"
    write(manifest_path, manifest)

    graph_path = source / ".harness/harness-update-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    def semver(value: str) -> tuple[int, int, int]:
        return tuple(int(part) for part in value.removeprefix("v").split("."))
    # Use the exact previous stable as the sole final hop even if this test is
    # executed after subsequent real releases have been published.
    graph["transitions"] = [
        edge for edge in graph["transitions"]
        if semver(edge["from"]) < semver(BASELINE)
    ]
    if graph.get("strategy") == "direct":
        for edge in graph["transitions"]:
            edge["to"] = SYNTHETIC_TARGET
    graph["transitions"].append({
        "from": BASELINE, "to": SYNTHETIC_TARGET,
        "kind": "standard", "reloadRequired": True,
    })
    graph["latest"] = SYNTHETIC_TARGET
    write(graph_path, json.dumps(graph, indent=2) + "\n")

    git(source, "add", ".harness/harness.lock.json",
        ".harness/manifest.yaml", ".harness/harness-update-graph.json")
    git(source, "commit", "--quiet", "-m", "synthetic release candidate")
    git(source, "tag", SYNTHETIC_TARGET)


def main() -> int:
    tag = run(ROOT, "git", "rev-parse", "--verify", "--quiet",
              f"refs/tags/{BASELINE}^{{commit}}", check=False)
    if tag.returncode:
        print(f"step-next upgrade integration: SKIP ({BASELINE} tag not available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="harness-previous-stable-upgrade-") as td:
        temp = Path(td)
        source = temp / "candidate-source"
        candidate_from_current_checkout(source)

        project = temp / "project-v0.11.4"
        git(temp, "clone", "--quiet", "--no-local", str(source), str(project))
        git(project, "checkout", "--quiet", "-B", "main", BASELINE)
        git(project, "config", "user.email", "upgrade-project@example.invalid")
        git(project, "config", "user.name", "Upgrade Project")

        # Product-owned tracked files must survive unchanged across updater.
        user_file = project / "docs/synthetic-owned-note.md"
        write(user_file, "# Project-owned\n\nNever replace on Harness upgrade.\n")
        git(project, "add", "docs/synthetic-owned-note.md")
        git(project, "commit", "--quiet", "-m", "project-owned fixture")
        original_user_bytes = user_file.read_bytes()
        templates = {p.relative_to(project).as_posix(): p.read_bytes()
                     for folder in (project / "docs", project / "planning")
                     for p in folder.rglob("TEMPLATE.md")}

        # A real v0.11.4 runtime creates a schema-v2 durable interrupted
        # command. It must survive updater/reload exactly, including identity.
        old_runtime = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, str(Path('.harness/tools').resolve())); "
            "from execution_status import start_execution; "
            "start_execution(Path('.'), 'HARNESS CONFIG')"
        )
        run(project, sys.executable, "-c", old_runtime)
        state_file = project / ".harness/local/execution/execution-status.json"
        original_state = state_file.read_bytes()
        identity = json.loads(original_state)["executions"][0]["executionId"]

        update_cmd = (
            sys.executable, ".harness/tools/harness-update.py",
            "apply", "--to", SYNTHETIC_TARGET,
            "--source-url", str(source), "--json",
        )
        statuses: list[str] = []
        for attempt in range(6):
            result = json.loads(run(project, *update_cmd).stdout)
            status = result.get("status")
            statuses.append(str(status))
            if status == "UPDATER_RELOAD_REQUIRED":
                continue
            assert status in {"UPDATED", "NO_UPDATE"}, result
            break
        else:
            raise AssertionError(f"updater did not settle: {statuses}")
        assert "UPDATER_RELOAD_REQUIRED" in statuses, statuses
        assert json.loads(
            (project / ".harness/harness.lock.json").read_text(encoding="utf-8")
        )["source"]["ref"] == SYNTHETIC_TARGET
        assert user_file.read_bytes() == original_user_bytes
        assert state_file.read_bytes() == original_state, "updater rewrote old local state"
        assert not (project / ".harness/local/update-journal/journal.json").exists()

        # Repeat APPLY must be a true NO_UPDATE, not a silent second mutation.
        repeat = json.loads(run(project, *update_cmd).stdout)
        assert repeat["status"] == "NO_UPDATE", repeat
        assert repeat.get("repositoryMutated") is False, repeat
        assert user_file.read_bytes() == original_user_bytes
        assert state_file.read_bytes() == original_state

        run(project, sys.executable, ".harness/tools/validate.py", "--mode", "update")
        # Project template/schema reconciliation belongs to later user work.
        assert all((project / rel).read_bytes() == data for rel, data in templates.items())
        # New runtime must resume the v0.11.4 record under the same identity.
        command = run(
            project, sys.executable, ".harness/tools/harness-dispatch.py",
            "start", "--command", "HARNESS RESUME",
        )
        payload = json.loads(command.stdout)
        assert payload.get("executionId") == identity, payload
        assert user_file.read_bytes() == original_user_bytes
    print("STEP NEXT PREVIOUS-STABLE UPGRADE INTEGRATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
