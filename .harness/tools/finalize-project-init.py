#!/usr/bin/env python3
"""Финальный deterministic gate PROJECT INIT.

--check выполняет только precondition validation.
Без --check tool становится mutator-ом: project.initialized=true фиксируется
только после PASS project/document/review/projection gates.

Любая postcondition failure откатывает manifest в exact pre-finalize state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from document_contract import atomic_write_text
from harness_config import (
    get,
    load_manifest,
    project_overview_path,
    requirements_directory,
    task_directory,
)
from planning_contract import latest_matching_init_review, open_questions
from project_integrity import validate_project_integrity
from project_migration import legacy_schema_pending
from projection_contract import validate_projections


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def preconditions(root: Path, name: str) -> list[str]:
    """Собрать все блокирующие условия INIT без mutation.

    Ошибки агрегируются, чтобы один запуск показал полный набор причин BLOCKED.
    """
    errors: list[str] = []
    manifest = load_manifest(root)
    if get(manifest, "project.initialized") is not False:
        errors.append("project.initialized must be false before finalize-init")
    if not name.strip():
        errors.append("project name must be non-empty")
    if legacy_schema_pending(root):
        errors.append("active legacy schema must be reconciled before INIT finalization")

    overview = project_overview_path(root)
    if not overview.is_file():
        errors.append(f"project overview missing: {overview.relative_to(root)}")
    real_requirements = [
        path for path in requirements_directory(root).glob("REQ-*.md")
        if path.name not in {"TEMPLATE.md", "REQ-001-template.md"}
    ]
    if not real_requirements:
        errors.append("INIT requires at least one non-template canonical REQ")
    if (requirements_directory(root) / "REQ-001-template.md").exists():
        errors.append("template REQ must be removed before INIT finalization")
    if not list(task_directory(root).glob("STEP-*.md")):
        errors.append("INIT requires at least one canonical STEP")

    errors.extend(validate_project_integrity(root, allow_legacy=False))
    errors.extend(validate_projections(root))

    for stage in ("requirements", "roadmap"):
        try:
            report = latest_matching_init_review(root, stage)
        except Exception as exc:
            errors.append(f"cannot validate INIT {stage} review: {exc}")
            continue
        if report is None:
            errors.append(f"missing PASS INIT {stage} review for current basis")

    for item in open_questions(root):
        if item.get("status") == "open" and "PROJECT" in set(item.get("affects") or []):
            errors.append(f"project-level blocker remains open: {item.get('id')}")
    return list(dict.fromkeys(errors))


def _replace_project_fields(text: str, name: str, timestamp: str) -> str:
    """Подготовить candidate manifest без записи на диск.

    Отсутствие bootstrap project field считается schema drift и блокирует INIT,
    а не приводит к добавлению нового поля эвристически.
    """
    replacements = {
        "initialized": "true",
        "name": json.dumps(name, ensure_ascii=False),
        "initializedAt": json.dumps(timestamp),
    }
    updated = text
    for key, value in replacements.items():
        pattern = re.compile(rf"(?m)^(  {re.escape(key)}:)\s*[^#\n]*(\s*(?:#.*)?)$")
        if pattern.search(updated) is None:
            raise ValueError(f"manifest project.{key} field not found")
        updated = pattern.sub(rf"\1 {value}\2", updated, count=1)
    return updated


def finalize(root: Path, name: str) -> dict[str, str]:
    """Атомарно зафиксировать initialized=true после PASS preconditions."""
    errors = preconditions(root, name)
    if errors:
        raise ValueError("; ".join(errors))

    path = root / ".harness" / "manifest.yaml"
    original = path.read_text(encoding="utf-8")
    timestamp = utc_now()
    candidate = _replace_project_fields(original, name.strip(), timestamp)

    atomic_write_text(path, candidate)
    try:
        post = validate_project_integrity(root, allow_legacy=False)
        if post:
            raise ValueError(
                "INIT postcondition failed; manifest rolled back: " + "; ".join(post)
            )
    except Exception as exc:
        # initialized=true является commit point INIT. Любой exception после
        # него обязан вернуть manifest в exact pre-finalize state.
        try:
            atomic_write_text(path, original)
        except Exception as rollback_exc:
            raise RuntimeError(
                f"INIT postcondition failed and manifest rollback failed: {rollback_exc}"
            ) from exc
        raise
    return {"status": "INITIALIZED", "name": name.strip(), "initializedAt": timestamp}


# ---------------------------------------------------------------------------
# CLI имеет два режима с одинаковым набором preconditions:
# --check -> read-only PASS/BLOCKED;
# default -> finalize + postcondition + rollback при ошибке.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.check:
        errors = preconditions(root, args.name)
        result = {"status": "PASS" if not errors else "BLOCKED", "errors": errors}
        code = 0 if not errors else 1
    else:
        try:
            result = finalize(root, args.name)
            code = 0
        except ValueError as exc:
            result = {"status": "BLOCKED", "error": str(exc)}
            code = 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        if result.get("error"):
            print(result["error"])
        for item in result.get("errors", []):
            print(f"- {item}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
