#!/usr/bin/env python3
"""Deterministic STEP context manifest для progressive disclosure.

Tool не пересказывает содержимое project artifacts и не делает semantic
выводов. Он разрешает configured canonical paths и возвращает минимальный
machine-readable набор входов, который нужен модели для конкретной фазы:
PLAN, IMPLEMENT или REVIEW.

Принцип: модель читает исходные релевантные документы, но не тратит context на
поиск путей, обход manifest, вычисление prerequisites/review gates/revision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from document_contract import parse_document
from planning_contract import (
    adr_ids,
    architecture_refs,
    canonical_adr_path,
    canonical_requirement_path,
    dependency_ids,
    implementation_prerequisite_failures,
    plan_content_hash,
    planning_context_basis,
    read_task,
    relevant_open_questions,
    requirement_ids,
    task_path,
)
from review_contract import repository_revision
from review_gates import required_reviewers


PHASES = {"plan", "implement", "review"}
_UNSPECIFIED_BASELINE = object()


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _architecture_input(root: Path, ref: str) -> dict[str, Any]:
    path_part, marker, fragment = ref.partition("#")
    path = (root / path_part).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise ValueError(f"architecture ref file not found: {ref}")
    return {
        "ref": ref,
        "path": _rel(root, path),
        "anchor": fragment if marker else None,
    }


def _unique_paths(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_step_context(
    root: Path,
    step_id: str,
    phase: str,
    *,
    implementation_baseline: dict[str, Any] | None | object = _UNSPECIFIED_BASELINE,
) -> dict[str, Any]:
    """Собрать exact context manifest без semantic summarization."""
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {sorted(PHASES)}")

    task = read_task(root, step_id)
    meta = task["frontmatter"]
    plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}

    dependencies: list[dict[str, Any]] = []
    for dependency_id in dependency_ids(task):
        dependency = read_task(root, dependency_id)
        dependency_meta = dependency["frontmatter"]
        dependencies.append(
            {
                "id": dependency_id,
                "path": _rel(root, task_path(root, dependency_id)),
                "status": dependency_meta.get("status"),
                "type": dependency_meta.get("type"),
            }
        )

    requirements = [
        {
            "id": req_id,
            "path": _rel(root, canonical_requirement_path(root, req_id)),
        }
        for req_id in requirement_ids(task)
    ]

    adrs: list[dict[str, Any]] = []
    for adr_id in adr_ids(task):
        path = canonical_adr_path(root, adr_id)
        document = parse_document(path)
        adrs.append(
            {
                "id": adr_id,
                "path": _rel(root, path),
                "status": document["frontmatter"].get("status"),
            }
        )

    architecture = [_architecture_input(root, ref) for ref in architecture_refs(task)]

    oqs: list[dict[str, Any]] = []
    for item in relevant_open_questions(root, task):
        path = item["path"]
        oqs.append(
            {
                "id": item.get("id"),
                "path": _rel(root, path),
                "status": item.get("status"),
                "affects": item.get("affects", []),
            }
        )

    read_paths = _unique_paths(
        [
            _rel(root, task_path(root, step_id)),
            *(item["path"] for item in dependencies),
            *(item["path"] for item in requirements),
            *(item["path"] for item in adrs),
            *(item["path"] for item in architecture),
            *(item["path"] for item in oqs),
        ]
    )

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "PASS",
        "phase": phase,
        "step": {
            "id": step_id,
            "path": _rel(root, task_path(root, step_id)),
            "status": meta.get("status"),
            "type": meta.get("type"),
            "priority": meta.get("priority"),
            "phase": meta.get("phase"),
            "riskFlags": meta.get("risk_flags", []),
            "plan": {
                "status": plan.get("status"),
                "revision": plan.get("revision"),
                "reviewedReport": plan.get("reviewed_report"),
            },
        },
        "semanticInputs": {
            "dependencies": dependencies,
            "requirements": requirements,
            "adrs": adrs,
            "architectureRefs": architecture,
            "openQuestions": oqs,
        },
        "readPaths": read_paths,
    }

    if phase == "plan":
        result["deterministic"] = {
            "contextBasis": planning_context_basis(root, step_id),
            "planContentHash": plan_content_hash(root, step_id),
            "dependencyCompletionRequired": False,
        }
    elif phase == "implement":
        failures = implementation_prerequisite_failures(root, step_id)
        result["deterministic"] = {
            "implementPrerequisites": {
                "status": "PASS" if not failures else "BLOCKED",
                "failures": failures,
            },
            "implementationBaseline": (
                None
                if implementation_baseline is _UNSPECIFIED_BASELINE
                else implementation_baseline
            ),
        }
    else:
        if implementation_baseline is _UNSPECIFIED_BASELINE:
            review_gate = required_reviewers(root, step_id)
            baseline_value = None
        else:
            baseline_sha = (
                implementation_baseline.get("gitHead")
                if isinstance(implementation_baseline, dict)
                else None
            )
            review_gate = required_reviewers(
                root,
                step_id,
                implementation_baseline=baseline_sha,
            )
            baseline_value = implementation_baseline
        result["deterministic"] = {
            "implementationBaseline": baseline_value,
            "specializedReviewGate": review_gate,
            "repositoryRevision": repository_revision(root),
        }

    return result


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build phase-specific deterministic STEP context manifest."
    )
    parser.add_argument("step_id")
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = (args.root or repo_root()).resolve()

    try:
        result = build_step_context(root, args.step_id, args.phase)
    except (OSError, UnicodeError, ValueError) as exc:
        blocked = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "phase": args.phase,
            "stepId": args.step_id,
            "error": str(exc),
        }
        if args.as_json:
            print(json.dumps(blocked, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"STEP CONTEXT: BLOCKED: {exc}")
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"STEP CONTEXT: PASS ({args.phase})")
        print("readPaths:")
        for path in result["readPaths"]:
            print(f"  - {path}")
        deterministic = result.get("deterministic", {})
        if phase_status := deterministic.get("implementPrerequisites"):
            print(f"implementPrerequisites: {phase_status['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
