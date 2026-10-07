#!/usr/bin/env python3
"""Regression effective Harness checkout copy after HARNESS UPDATE."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from self_test_fixture import copy_effective_harness_checkout


def run(root: Path, *args: str) -> None:
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
            f"{' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stdout}\n{proc.stderr}"
        )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-effective-fixture-") as td:
        base = Path(td)
        source = base / "source"
        target = base / "target"
        source.mkdir()
        target.mkdir()

        write(
            source / ".harness/manifest.yaml",
            "repository:\n  harnessUpdatePolicy: .harness/harness-update.toml\n",
        )
        write(
            source / ".harness/harness-update.toml",
            "[ownership]\n"
            "harness_owned = [\n  \".harness/tools/**\",\n]\n"
            "shared = [\n  \".github/**\",\n]\n"
            "marker_merge = [\n  \"README.md\",\n]\n",
        )
        write(source / "README.md", "tracked\n")

        run(source, "git", "init", "-q", "-b", "main")
        run(source, "git", "config", "user.email", "fixture@example.invalid")
        run(source, "git", "config", "user.name", "Fixture")
        run(source, "git", "add", ".")
        run(source, "git", "commit", "-qm", "baseline")

        write(source / ".harness/tools/new-tool.py", "print('managed')\n")
        write(source / "notes/local.txt", "project untracked\n")

        copy_effective_harness_checkout(source, target)

        assert (target / "README.md").read_text(encoding="utf-8") == "tracked\n"
        assert (target / ".harness/tools/new-tool.py").read_text(
            encoding="utf-8"
        ) == "print('managed')\n"
        assert not (target / "notes/local.txt").exists()

    print("self-test fixture effective checkout: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
