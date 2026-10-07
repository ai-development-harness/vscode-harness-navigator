#!/usr/bin/env python3
"""Изоляция project-owned state в synthetic self-tests Harness."""
from __future__ import annotations

from pathlib import Path
import fnmatch
import re
import shutil
import subprocess

from document_contract import atomic_write_text
from harness_config import (
    adr_directory,
    audit_directory,
    init_review_directory,
    open_questions_directory,
    planning_review_directory,
    principles_directory,
    release_directory,
    requirements_directory,
    review_directory,
    skill_search_directory,
    task_directory,
    update_report_directory,
    load_update_policy,
)
from projection_contract import write_projections
from template_contract import template_targets


def _git_paths_z(root: Path, *args: str) -> list[str]:
    """Прочитать Git path list через NUL framing без quoting/whitespace loss."""

    proc = subprocess.run(
        ["git", *args, "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    return [
        token.decode("utf-8")
        for token in proc.stdout.split(b"\0")
        if token
    ]


def _updater_owned(path: str, policy: dict) -> bool:
    ownership = policy.get("ownership")
    if not isinstance(ownership, dict):
        raise ValueError("harness-update ownership must be a table")

    for class_name in ("harness_owned", "shared", "marker_merge"):
        patterns = ownership.get(class_name)
        if not isinstance(patterns, list) or not all(
            isinstance(item, str) and item for item in patterns
        ):
            raise ValueError(
                f"harness-update ownership.{class_name} must be a string array"
            )
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            return True
    return False


def copy_effective_harness_checkout(source_root: Path, target: Path) -> None:
    """Скопировать effective Harness surface для synthetic fixture.

    После HARNESS UPDATE новые managed files законно находятся в working tree
    existing project как untracked: updater не должен самостоятельно stage-ить
    пользовательский Git index. Поэтому одного git ls-files недостаточно.

    В fixture попадают все tracked files и только updater-managed untracked
    files. Произвольный project-owned untracked filesystem не копируется.
    """

    source_root = source_root.resolve()
    target = target.resolve()
    paths = set(_git_paths_z(source_root, "ls-files"))

    update_policy = load_update_policy(source_root)
    for rel in _git_paths_z(
        source_root,
        "ls-files",
        "--others",
        "--exclude-standard",
    ):
        if _updater_owned(rel, update_policy):
            paths.add(rel)

    for rel in sorted(paths):
        source = source_root / rel
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

def _remove_files(directory: Path, pattern: str, *, keep: set[str] | None = None) -> None:
    """Удалить canonical artifacts fixture, сохранив protocol scaffolding."""
    if not directory.is_dir():
        return
    preserved = keep or set()
    for path in directory.glob(pattern):
        if path.name in preserved:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()


def _clear_generated_directory(directory: Path) -> None:
    """Очистить durable generated state, не удаляя README/TEMPLATE."""
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.name in {"README.md", "TEMPLATE.md"}:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _reset_project_lifecycle(root: Path) -> None:
    """Вернуть synthetic fixture в pre-INIT lifecycle state.

    После удаления canonical REQ/ADR/STEP/OQ/PRN initialized project больше не
    является структурно согласованным. Поэтому synthetic baseline не должен
    наследовать host-project commit point PROJECT INIT.
    """
    path = root / ".harness" / "manifest.yaml"
    text = path.read_text(encoding="utf-8")
    replacements = {
        "initialized": "false",
        "name": "null",
        "initializedAt": "null",
    }
    updated = text
    for key, value in replacements.items():
        pattern = re.compile(
            rf"(?m)^(  {re.escape(key)}:)\s*[^#\n]*(\s*(?:#.*)?)$"
        )
        if pattern.search(updated) is None:
            raise ValueError(f"manifest project.{key} field not found")
        updated = pattern.sub(rf"\1 {value}\2", updated, count=1)
    if updated != text:
        atomic_write_text(path, updated)


def _restore_pre_init_templates(root: Path) -> None:
    """Восстановить exact protocol templates только внутри synthetic fixture.

    После PROJECT INIT templates становятся project-owned и могут законно
    отличаться от текущих protocol definitions. Но isolate_project_artifacts()
    переводит временную копию обратно в pre-INIT, где validator требует exact
    bootstrap baseline. Поэтому fixture должна нормализовать templates через
    единственный configured source of truth, не меняя host checkout.
    """
    for path, expected in template_targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != expected:
            atomic_write_text(path, expected)


def isolate_project_artifacts(root: Path) -> None:
    """Удалить inherited project artifacts из synthetic fixture.

    Self-tests копируют tracked checkout, чтобы использовать текущий Harness
    runtime. Canonical STEP/REQ/ADR/OQ/PRN, durable reports и projections при
    этом принадлежат host project и не должны влиять на synthetic expectations.
    После очистки fixture переводится в pre-INIT lifecycle state, а projections
    пересобираются из оставшегося canonical state.
    """
    _remove_files(task_directory(root), "STEP-*.md")
    _remove_files(
        requirements_directory(root),
        "REQ-*.md",
        keep={"REQ-001-template.md"},
    )
    _remove_files(adr_directory(root), "ADR-*.md")
    _remove_files(open_questions_directory(root), "OQ-*.md")
    _remove_files(principles_directory(root), "PRN-*.md")

    for directory in (
        review_directory(root),
        planning_review_directory(root),
        init_review_directory(root),
        audit_directory(root),
        release_directory(root),
        skill_search_directory(root),
        update_report_directory(root),
    ):
        _clear_generated_directory(directory)

    _reset_project_lifecycle(root)
    _restore_pre_init_templates(root)
    write_projections(root)
