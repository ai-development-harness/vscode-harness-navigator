#!/usr/bin/env python3
"""Synthetic regressions repository-level validator hardening boundaries."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile


SOURCE_ROOT = Path(__file__).resolve().parents[2]


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


def copy_tracked(target: Path) -> None:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=SOURCE_ROOT,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = token.decode("utf-8")
        source = SOURCE_ROOT / rel
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    run(target, "git", "init", "-q", "-b", "main")
    run(target, "git", "config", "user.email", "hardening@example.invalid")
    run(target, "git", "config", "user.name", "Hardening Test")
    run(target, "git", "add", ".")
    run(target, "git", "commit", "-qm", "baseline")


def validate(root: Path) -> subprocess.CompletedProcess[str]:
    return run(
        root,
        "python3",
        ".harness/tools/validate.py",
        "--mode",
        "manual",
        check=False,
    )


def require_failure(proc: subprocess.CompletedProcess[str], needle: str) -> None:
    assert proc.returncode != 0, proc.stdout
    combined = proc.stdout + "\n" + proc.stderr
    assert needle in combined, combined


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-repository-hardening-") as tmp:
        root = Path(tmp)
        copy_tracked(root)

        baseline = validate(root)
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr

        # Комментарий с текстом ignore pattern не является действующим правилом.
        gitignore_path = root / ".gitignore"
        original_ignore = gitignore_path.read_text(encoding="utf-8")
        assert "AGENTS.local.md" in original_ignore
        gitignore_path.write_text(
            original_ignore.replace("AGENTS.local.md", "# AGENTS.local.md", 1),
            encoding="utf-8",
        )
        require_failure(validate(root), ".gitignore must ignore AGENTS.local.md")

        # Эквивалентный glob должен приниматься: проверяется Git semantics, а не substring.
        semantic_ignore = original_ignore
        semantic_ignore = semantic_ignore.replace("AGENTS.local.md\n", "", 1)
        semantic_ignore = semantic_ignore.replace("CLAUDE.local.md\n", "", 1)
        semantic_ignore = semantic_ignore.replace("PROJECT_BRIEF.local.md\n", "", 1)
        semantic_ignore += "\n*.local.md\n"
        gitignore_path.write_text(semantic_ignore, encoding="utf-8")
        semantic = validate(root)
        assert semantic.returncode == 0, semantic.stdout + semantic.stderr
        gitignore_path.write_text(original_ignore, encoding="utf-8")

        # Ignored/generated TOML вне Git index не входит в Harness config surface.
        ignored_toml = root / ".harness/local/broken.toml"
        ignored_toml.parent.mkdir(parents=True, exist_ok=True)
        ignored_toml.write_text("[broken\n", encoding="utf-8")
        ignored = validate(root)
        assert ignored.returncode == 0, ignored.stdout + ignored.stderr

        # Harness policy является safety boundary: typo не должен молча
        # отключать required-file gate.
        harness_policy_path = root / ".harness/harness-policy.toml"
        harness_policy_original = harness_policy_path.read_text(encoding="utf-8")
        harness_policy_path.write_text(
            harness_policy_original.replace("required_files = [", "required_filez = [", 1),
            encoding="utf-8",
        )
        require_failure(validate(root), "harness-policy: unsupported settings: required_filez")
        require_failure(validate(root), "harness-policy: required_files must be a string array")
        harness_policy_path.write_text(harness_policy_original, encoding="utf-8")

        # Codex role config не может выйти за canonical .codex/agents даже если
        # target существует и resolve() успешно его находит.
        codex_path = root / ".codex/config.toml"
        codex_original = codex_path.read_text(encoding="utf-8")
        codex_path.write_text(
            codex_original.replace(
                'config_file = "./agents/initializer.toml"',
                'config_file = "../README.md"',
                1,
            ),
            encoding="utf-8",
        )
        require_failure(validate(root), "config escapes .codex/agents")
        codex_path.write_text(codex_original, encoding="utf-8")

    print("REPOSITORY HARDENING SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
