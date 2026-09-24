#!/usr/bin/env python3
"""Regression self-test Git path transport в specialized review gate."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from review_gates import _git_changed_paths, required_reviewers


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")


def manifest() -> str:
    return """review:
  security: auto
  tests: auto
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""


def task() -> str:
    return """---
schema: 1
id: STEP-001
status: planned
type: documentation
priority: medium
phase: test
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — Review path transport

## Goal

Проверить точную передачу Git paths.
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-review-paths-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(root / "planning/tasks/STEP-001.md", task())
        write(root / "README.md", "fixture\n")

        git(root, "init", "-q")
        git(root, "config", "user.email", "harness-test@example.invalid")
        git(root, "config", "user.name", "Harness Test")
        git(root, "add", ".")
        git(root, "commit", "-qm", "fixture")

        # Unstaged tracked Unicode path: default Git quoting раньше превращал
        # кириллицу в escaped octal sequence и ломал path heuristics.
        unicode_code = root / "src/кириллица.ts"
        write(unicode_code, "export const value = 1;\n")
        git(root, "add", "--", unicode_code.relative_to(root).as_posix())
        git(root, "commit", "-qm", "add unicode code path")
        write(unicode_code, "export const value = 2;\n")

        # Staged path нужен для отдельного --cached collector.
        staged_security = root / "security/секрет файл.md"
        write(staged_security, "security fixture\n")
        git(root, "add", "--", staged_security.relative_to(root).as_posix())

        # Untracked paths проверяют ls-files -z. Newline обязан остаться частью
        # одного имени, а trailing whitespace нельзя strip-нуть.
        newline_path = root / "docs/строка\nперенос.md"
        trailing_path = root / "docs/trailing-space "
        write(newline_path, "newline path\n")
        write(trailing_path, "trailing path\n")

        paths, mode = _git_changed_paths(root)
        assert mode == "worktree", (mode, paths)
        expected = {
            "src/кириллица.ts",
            "security/секрет файл.md",
            "docs/строка\nперенос.md",
            "docs/trailing-space ",
        }
        assert expected.issubset(set(paths)), paths
        assert "docs/строка" not in paths and "перенос.md" not in paths, paths

        gate = required_reviewers(root, "STEP-001")
        assert "security" in gate["required"], gate
        assert "tests" in gate["required"], gate
        assert "src/кириллица.ts" in gate["changedPaths"], gate
        assert "docs/строка\nперенос.md" in gate["changedPaths"], gate

        # Реальный dirty product surface также обязан быть инвариантен к
        # появлению Harness-owned report: worktree/paths/required/basis не меняются.
        dirty_report = root / "planning/reviews/STEP-001/REVIEW-20981231T235959Z.md"
        write(dirty_report, "dirty report fixture\n")
        dirty_with_report = required_reviewers(root, "STEP-001")
        assert dirty_with_report["surfaceMode"] == gate["surfaceMode"] == "worktree", (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["changedPaths"] == gate["changedPaths"], (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["required"] == gate["required"], (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["basis"] == gate["basis"], (
            gate,
            dirty_with_report,
        )
        dirty_report.unlink()

        # Clean-tree fallback использует diff-tree и обязан сохранять те же raw
        # path boundaries/Unicode после commit.
        git(root, "add", ".")
        git(root, "commit", "-qm", "commit path fixtures")
        fallback_paths, fallback_mode = _git_changed_paths(root)
        assert fallback_mode == "clean-tree-fallback", (fallback_mode, fallback_paths)
        assert expected.issubset(set(fallback_paths)), fallback_paths

        # Regression #77: Harness-owned report не является product surface и не
        # имеет права переключать режим/required/basis только фактом резервирования.
        fallback_gate = required_reviewers(root, "STEP-001")
        report_path = root / "planning/reviews/STEP-001/REVIEW-20990101T000000Z.md"
        write(report_path, "reserved report fixture\n")

        after_report_paths, after_report_mode = _git_changed_paths(root)
        assert after_report_mode == fallback_mode, (
            fallback_mode,
            after_report_mode,
            after_report_paths,
        )
        assert after_report_paths == fallback_paths, (
            fallback_paths,
            after_report_paths,
        )

        after_report_gate = required_reviewers(root, "STEP-001")
        assert after_report_gate["surfaceMode"] == fallback_gate["surfaceMode"], (
            fallback_gate,
            after_report_gate,
        )
        assert after_report_gate["required"] == fallback_gate["required"], (
            fallback_gate,
            after_report_gate,
        )
        assert after_report_gate["basis"] == fallback_gate["basis"], (
            fallback_gate,
            after_report_gate,
        )
        report_path.unlink()

        # Regression #80: durable baseline восстанавливает полный multi-commit
        # surface. Security path намеренно не находится в последнем commit.
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()

        auth_path = root / "src/auth/session.py"
        write(auth_path, "export const secureSession = true;\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline security change")

        tests_path = root / "tests/session.test.ts"
        write(tests_path, "export const tested = true;\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline test change")

        docs_path = root / "docs/implementation-note.md"
        write(docs_path, "implementation note\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "baseline docs change")

        baseline_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=baseline,
        )
        assert baseline_gate["surfaceMode"] == "implementation-baseline", baseline_gate
        assert baseline_gate["baselineStatus"] == "valid", baseline_gate
        assert baseline_gate["implementationBaseline"] == baseline, baseline_gate
        assert "src/auth/session.py" in baseline_gate["changedPaths"], baseline_gate
        assert "tests/session.test.ts" in baseline_gate["changedPaths"], baseline_gate
        assert "docs/implementation-note.md" in baseline_gate["changedPaths"], baseline_gate
        assert {"security", "tests"}.issubset(set(baseline_gate["required"])), baseline_gate

        # Regression #80: committed rename security-path -> neutral-path должен
        # оставлять в exact surface обе стороны rename. Иначе --name-only
        # скрывает source path и preselector может пропустить security reviewer.
        rename_source = root / "src/auth/legacy_session.py"
        write(rename_source, "export const legacySession = true;\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "add sensitive rename source")
        rename_baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()

        rename_destination = root / "src/core/state.py"
        rename_destination.parent.mkdir(parents=True, exist_ok=True)
        git(
            root,
            "mv",
            rename_source.relative_to(root).as_posix(),
            rename_destination.relative_to(root).as_posix(),
        )
        git(root, "commit", "-qm", "rename sensitive path to neutral path")
        rename_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=rename_baseline,
        )
        assert "src/auth/legacy_session.py" in rename_gate["changedPaths"], rename_gate
        assert "src/core/state.py" in rename_gate["changedPaths"], rename_gate
        assert "security" in rename_gate["required"], rename_gate

        # Тот же invariant нужен до commit: staged rename не должен терять
        # source security path в worktree component baseline surface.
        staged_source = root / "src/auth/staged_secret.py"
        write(staged_source, "export const stagedSecret = true;\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "add staged rename source")
        staged_baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        staged_destination = root / "src/core/staged_state.py"
        git(
            root,
            "mv",
            staged_source.relative_to(root).as_posix(),
            staged_destination.relative_to(root).as_posix(),
        )
        staged_rename_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=staged_baseline,
        )
        assert "src/auth/staged_secret.py" in staged_rename_gate["changedPaths"], (
            staged_rename_gate
        )
        assert "src/core/staged_state.py" in staged_rename_gate["changedPaths"], (
            staged_rename_gate
        )
        assert "security" in staged_rename_gate["required"], staged_rename_gate
        git(root, "commit", "-qm", "commit staged sensitive rename")

        # Copy из sensitive source в нейтральный destination тоже обязан
        # сохранить source path в classification surface. Для unmodified source
        # нужен --find-copies-harder, иначе Git показывает только added target.
        copy_source = root / "src/auth/copy_secret.py"
        write(copy_source, "export const copySecret = true;\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "add sensitive copy source")
        copy_baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        copy_destination = root / "src/core/copied_state.py"
        write(copy_destination, copy_source.read_text(encoding="utf-8"))
        git(root, "add", ".")
        git(root, "commit", "-qm", "copy sensitive source to neutral path")
        copy_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=copy_baseline,
        )
        assert "src/auth/copy_secret.py" in copy_gate["changedPaths"], copy_gate
        assert "src/core/copied_state.py" in copy_gate["changedPaths"], copy_gate
        assert "security" in copy_gate["required"], copy_gate

        # Committed baseline surface объединяется с текущим dirty product diff,
        # но operational state/report artifacts в него не попадают.
        dirty_product = root / "src/runtime.ts"
        write(dirty_product, "export const runtime = 1;\n")
        write(
            root / ".harness/local/execution/execution-status.json",
            '{"schemaVersion":1,"executions":[]}\n',
        )
        dirty_baseline_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=baseline,
        )
        assert dirty_baseline_gate["surfaceMode"] == "implementation-baseline", (
            dirty_baseline_gate
        )
        assert "src/runtime.ts" in dirty_baseline_gate["changedPaths"], dirty_baseline_gate
        assert not any(
            path.startswith(".harness/local/")
            for path in dirty_baseline_gate["changedPaths"]
        ), dirty_baseline_gate

        stable_report = root / "planning/reviews/STEP-001/REVIEW-20990102T000000Z.md"
        write(stable_report, "reserved report fixture\n")
        after_baseline_report = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=baseline,
        )
        assert after_baseline_report["basis"] == dirty_baseline_gate["basis"], (
            dirty_baseline_gate,
            after_baseline_report,
        )
        assert (
            after_baseline_report["changedPathsHash"]
            == dirty_baseline_gate["changedPathsHash"]
        ), (dirty_baseline_gate, after_baseline_report)
        stable_report.unlink()

        # Invalid/missing proof не угадывает committed STEP diff и явно
        # переключается в conservative fallback.
        invalid_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline="0" * 40,
        )
        assert invalid_gate["surfaceMode"] == "clean-tree-fallback", invalid_gate
        assert invalid_gate["baselineStatus"] == "invalid", invalid_gate
        assert {"security", "tests"}.issubset(set(invalid_gate["required"])), invalid_gate

        # Existing commit, который не является ancestor текущего HEAD, также
        # недопустим как baseline. Создаём detached root commit без изменения
        # HEAD/worktree, чтобы отдельно покрыть ancestor proof.
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        non_ancestor = subprocess.run(
            ["git", "commit-tree", tree, "-m", "detached baseline fixture"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        non_ancestor_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=non_ancestor,
        )
        assert (
            non_ancestor_gate["surfaceMode"] == "clean-tree-fallback"
        ), non_ancestor_gate
        assert non_ancestor_gate["baselineStatus"] == "invalid", non_ancestor_gate
        assert "not an ancestor" in str(non_ancestor_gate["baselineReason"]), (
            non_ancestor_gate
        )
        assert {"security", "tests"}.issubset(
            set(non_ancestor_gate["required"])
        ), non_ancestor_gate

        missing_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=None,
        )
        assert missing_gate["surfaceMode"] == "clean-tree-fallback", missing_gate
        assert missing_gate["baselineStatus"] == "missing", missing_gate
        assert {"security", "tests"}.issubset(set(missing_gate["required"])), missing_gate

    # Regression #117: ошибка Git не является пустой surface. В repository
    # без commits staged/untracked файлы — полноценная review surface, а вне
    # Git repository сбор surface падает явно, а не отключает reviewers.
    with tempfile.TemporaryDirectory(prefix="harness-review-unborn-") as tmp:
        unborn = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=unborn, check=True)
        (unborn / "src").mkdir()
        (unborn / "src/auth.py").write_text("SECRET = 1\n", encoding="utf-8")
        (unborn / "notes.md").write_text("untracked\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/auth.py"], cwd=unborn, check=True)
        unborn_paths, unborn_mode = _git_changed_paths(unborn)
        assert "src/auth.py" in unborn_paths and "notes.md" in unborn_paths, (unborn_mode, unborn_paths)
    with tempfile.TemporaryDirectory(prefix="harness-review-nogit-") as tmp:
        try:
            _git_changed_paths(Path(tmp))
        except ValueError as exc:
            assert "cannot collect review surface" in str(exc), exc
        else:
            raise AssertionError("review surface outside Git repository was treated as empty")

    print("REVIEW GATES SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
