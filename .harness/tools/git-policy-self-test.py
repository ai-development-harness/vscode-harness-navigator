#!/usr/bin/env python3
"""End-to-end regression fail-closed Git policy через публичный validator."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return proc


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-git-policy-") as tmp:
        root = Path(tmp) / "repo"
        shutil.copytree(
            source,
            root,
            ignore=shutil.ignore_patterns(".git", ".harness/local", "__pycache__", "*.pyc"),
        )
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.email", "harness-test@example.invalid")
        run(root, "git", "config", "user.name", "Harness Test")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        baseline = run(
            root,
            "python3",
            ".harness/tools/validate.py",
            "--mode",
            "manual",
            check=False,
        )
        if baseline.returncode != 0:
            raise AssertionError(
                "baseline repository must validate before policy mutation:\n"
                + baseline.stdout
                + baseline.stderr
            )

        policy_path = root / ".harness/git-policy.toml"
        policy = policy_path.read_text(encoding="utf-8")
        policy = policy.replace(
            'require_clean_worktree = false',
            'require_clean_worktree = false\nrequire_clean_worktre = true',
        )
        policy_path.write_text(policy, encoding="utf-8", newline="\n")
        typo = run(
            root,
            "python3",
            ".harness/tools/validate.py",
            "--mode",
            "manual",
            check=False,
        )
        output = typo.stdout + typo.stderr
        assert typo.returncode != 0, output
        assert "unsupported push settings: require_clean_worktre" in output, output

    print("GIT POLICY SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
