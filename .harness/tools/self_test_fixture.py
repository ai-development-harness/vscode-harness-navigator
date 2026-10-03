#!/usr/bin/env python3
"""Изоляция project-owned state в synthetic self-tests Harness."""
from __future__ import annotations

from pathlib import Path
import re
import shutil

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
)
from projection_contract import write_projections
from template_contract import template_targets


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
    # Pre-INIT validator сверяет templates с protocol baseline побайтно. В
    # synthetic copy заменяем только её inherited project templates, не host project.
    for path, content in template_targets(root).items():
        atomic_write_text(path, content)
    write_projections(root)
