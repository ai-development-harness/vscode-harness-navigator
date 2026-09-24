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

        # Regression #110: Markdown setext H1 (`=======`) не merge-conflict marker,
        # а настоящий conflict block по-прежнему блокируется.
        setext = root / "docs/setext.md"
        setext.parent.mkdir(parents=True, exist_ok=True)
        setext.write_text("Title\n=======\n\ntext\n", encoding="utf-8")
        run(root, "git", "add", "docs/setext.md")
        setext_result = validate(root)
        assert setext_result.returncode == 0, setext_result.stdout + setext_result.stderr
        setext.write_text(
            "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n",
            encoding="utf-8",
        )
        require_failure(validate(root), "merge-conflict marker detected: docs/setext.md")
        run(root, "git", "rm", "-q", "-f", "docs/setext.md")

        # Regression #108: basename-паттерны действуют на любой глубине.
        for rel, needle in (
            ("apps/api/.env", "forbidden tracked file: apps/api/.env"),
            ("apps/api/.env.local", "forbidden tracked file: apps/api/.env.local"),
            ("deploy/id_ecdsa", "forbidden tracked file: deploy/id_ecdsa"),
            ("ops/prod.tfstate", "forbidden tracked file: ops/prod.tfstate"),
            ("certs/app.p12", "forbidden tracked file: certs/app.p12"),
            (".ssh/config", "forbidden tracked file: .ssh/config"),
            ("home/.ssh/known_hosts", "forbidden tracked file: home/.ssh/known_hosts"),
        ):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")
            run(root, "git", "add", "-f", rel)
            require_failure(validate(root), needle)
            run(root, "git", "rm", "-q", "-f", "--cached", rel)
            target.unlink()
        example = root / "apps/api/.env.example"
        example.parent.mkdir(parents=True, exist_ok=True)
        example.write_text("API_URL=\n", encoding="utf-8")
        run(root, "git", "add", "-f", "apps/api/.env.example")
        allowed_example = validate(root)
        assert allowed_example.returncode == 0, allowed_example.stdout + allowed_example.stderr
        run(root, "git", "rm", "-q", "-f", "apps/api/.env.example")

        # Regression #108: любые PEM/PGP private keys и токены, в том числе в binary.
        begin, end = "-----BEGIN", "-----END"
        secrets = {
            "ec": f"{begin} EC PRIVATE KEY-----\nMHcfixture\n{end} EC PRIVATE KEY-----\n",
            "pgp": f"{begin} PGP PRIVATE KEY BLOCK-----\nfixture\n{end} PGP PRIVATE KEY BLOCK-----\n",
            "enc": f"{begin} ENCRYPTED PRIVATE KEY-----\nfixture\n{end} ENCRYPTED PRIVATE KEY-----\n",
            "gh": "token = " + "gh" + "p_" + "A1b2C3d4" * 4 + "E5f6\n",
            "aws": "key = " + "AK" + "IA" + "Q3EGRSX5NLPY7ZTW\n",
        }
        labels = {
            "ec": "private key material",
            "pgp": "private key material",
            "enc": "private key material",
            "gh": "GitHub token",
            "aws": "AWS access key",
        }
        for name, content in secrets.items():
            rel = f"docs/secret-{name}.txt"
            (root / rel).write_text(content, encoding="utf-8")
            run(root, "git", "add", rel)
            require_failure(validate(root), f"{labels[name]} detected in tracked file: {rel}")
            run(root, "git", "rm", "-q", "-f", rel)
        binary = root / "docs/blob.bin"
        binary.write_bytes(b"\0\x01binary" + secrets["ec"].encode() + b"\0")
        run(root, "git", "add", "docs/blob.bin")
        require_failure(validate(root), "private key material detected in tracked file: docs/blob.bin")
        run(root, "git", "rm", "-q", "-f", "docs/blob.bin")
        doc_example = root / "docs/aws-example.md"
        doc_example.write_text("AWS doc key: " + "AK" + "IA" + "IOSFODNN7EXAMPLE\n", encoding="utf-8")
        run(root, "git", "add", "docs/aws-example.md")
        doc_result = validate(root)
        assert doc_result.returncode == 0, doc_result.stdout + doc_result.stderr
        run(root, "git", "rm", "-q", "-f", "docs/aws-example.md")

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

        # Shared Claude settings обязаны сохранять defense-in-depth запрет
        # прямого Git PUSH. Canonical policy всё равно остаётся git-action.py,
        # но adapter не должен тихо потерять restrictive deny rule.
        claude_path = root / ".claude/settings.json"
        claude_original = claude_path.read_text(encoding="utf-8")
        claude_path.write_text(
            claude_original.replace(
                '      "Bash(git push *)",\n',
                "",
                1,
            ),
            encoding="utf-8",
        )
        require_failure(
            validate(root),
            "Claude settings missing required Git deny rules: Bash(git push *)",
        )
        claude_path.write_text(claude_original, encoding="utf-8")

        # Regression #106: commit фиксирует staged blob. Private key, который
        # остался в index после очистки working copy, обязан блокировать commit.
        key_path = root / "docs/leaked-key.md"
        # Marker собирается из частей, чтобы сам test file не был key fixture.
        key_marker = "-----BEGIN" + " PRIVATE KEY-----"
        key_path.write_text(
            f"{key_marker}\nMIIEfixture\n-----END" + " PRIVATE KEY-----\n",
            encoding="utf-8",
        )
        run(root, "git", "add", "docs/leaked-key.md")
        key_path.write_text("clean working copy\n", encoding="utf-8")
        staged_key = run(
            root,
            "python3",
            ".harness/tools/validate.py",
            "--mode",
            "commit",
            check=False,
        )
        require_failure(
            staged_key,
            "private key material detected in staged file: docs/leaked-key.md",
        )
        run(root, "git", "rm", "-q", "--cached", "-f", "docs/leaked-key.md")
        key_path.unlink()

        # Regression #113: низкоуровневый execution-state CLI не должен
        # завершать IMPLEMENT/FIX SUCCESS в обход Verification dispatcher-а.
        for command, result in (
            ("STEP IMPLEMENT STEP-001", "SUCCESS"),
            ("STEP IMPLEMENT STEP-001", "PASS"),
            ("STEP FIX STEP-001", "SUCCESS"),
        ):
            bypass = run(
                root,
                "python3",
                ".harness/tools/execution-state.py",
                "complete",
                "--root",
                command,
                "--command",
                command,
                "--result",
                result,
                check=False,
            )
            assert bypass.returncode == 2, bypass.stdout + bypass.stderr
            assert "VERIFICATION_REQUIRES_DISPATCH" in bypass.stdout, bypass.stdout
        assert not (root / ".harness/local/execution-status.json").exists()

    print("REPOSITORY HARDENING SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
