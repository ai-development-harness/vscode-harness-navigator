#!/usr/bin/env python3
"""Runtime-neutral role-specific Context Contracts for STEP semantic work.

Resolver возвращает repository refs и exact section projections. Он не
summarize-ит semantic content, не зависит от runtime provider и никогда не
fallback-ит на full-repository scan.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core_reasoning_principles import (
    CoreReasoningPrincipleError,
    select_core_reasoning_principles,
)
from document_contract import DocumentError, parse_document
from harness_config import get, load_manifest, resolve_repo_path
from planning_contract import (
    adr_ids,
    architecture_refs,
    canonical_adr_path,
    canonical_requirement_path,
    dependency_ids,
    read_task,
    relevant_open_questions,
    requirement_ids,
    task_path,
)
from review_contract import repository_revision

SCHEMA_VERSION = 1
ROLES = {"planner", "implementer", "reviewer"}
ROLE_COMMAND = {
    "planner": "STEP PLAN",
    "implementer": "STEP IMPLEMENT",
    "reviewer": "STEP REVIEW",
}
ROLE_SECTIONS = {
    "planner": {
        "step": ["Goal", "Context", "Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification"],
        "requirement": ["Requirement", "Rationale", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria"],
        "oq": ["Context", "Decision needed"],
    },
    "implementer": {
        "step": ["Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification", "Implementation plan"],
        "requirement": ["Requirement", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria", "Evidence"],
        "oq": ["Decision needed"],
    },
    "reviewer": {
        "step": ["Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification", "Implementation plan", "Evidence"],
        "requirement": ["Requirement", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria", "Evidence"],
        "oq": ["Context", "Decision needed"],
    },
}
OPTIONAL_SECTIONS = {
    "planner": {"oq": ["Resolution"]},
    "implementer": {"oq": ["Resolution"]},
    "reviewer": {"oq": ["Resolution"]},
}


class ContextContractError(ValueError):
    """Context нельзя безопасно разрешить; caller обязан остановить semantic stage."""


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ContextContractError(f"context path escapes repository: {path}") from exc


def _projection(
    root: Path,
    path: Path,
    artifact: str,
    sections: list[str],
    *,
    optional_sections: list[str] | None = None,
) -> dict[str, Any]:
    try:
        doc = parse_document(path)
    except (DocumentError, OSError, UnicodeDecodeError) as exc:
        raise ContextContractError(f"{artifact}: cannot parse context artifact: {exc}") from exc
    missing = [name for name in sections if name not in doc["sections"]]
    if missing:
        raise ContextContractError(
            f"{artifact}: required sections missing: " + ", ".join(missing)
        )
    selected = list(sections)
    for name in optional_sections or []:
        if name in doc["sections"] and name not in selected:
            selected.append(name)
    return {
        "artifact": artifact,
        "path": _rel(root, path),
        "sections": selected,
    }


def _architecture_projection(root: Path, ref: str) -> dict[str, Any]:
    path_part, marker, fragment = ref.partition("#")
    if not path_part:
        raise ContextContractError(f"architecture ref has empty path: {ref}")
    path = (root / path_part).resolve()
    _rel(root, path)
    if not path.is_file():
        raise ContextContractError(f"architecture ref file not found: {ref}")
    return {
        "artifact": ref,
        "path": _rel(root, path),
        "anchor": fragment if marker else None,
        "sections": [],
    }


def _active_principles(root: Path) -> list[dict[str, Any]]:
    """Вернуть project-wide active PRN candidates для semantic applicability pass."""
    manifest = load_manifest(root)
    configured = get(manifest, "sources.principles")
    if configured is None:
        return []
    directory = resolve_repo_path(root, configured, label="manifest sources.principles")
    if not directory.is_dir():
        raise ContextContractError(
            f"configured principles directory missing: {_rel(root, directory)}"
        )

    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("PRN-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            doc = parse_document(path)
        except (DocumentError, OSError, UnicodeDecodeError) as exc:
            raise ContextContractError(
                f"{_rel(root, path)}: cannot parse Project Principle: {exc}"
            ) from exc
        meta = doc["frontmatter"]
        if meta.get("status") != "active":
            continue
        artifact = str(meta.get("id") or path.stem)
        result.append(
            _projection(
                root,
                path,
                artifact,
                ["Rule", "Applies to", "Exceptions / approved deviation"],
            )
        )
    return result


def _build_context_contract(root: Path, step_id: str, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ContextContractError(f"role must be one of {sorted(ROLES)}")

    root = root.resolve()
    sections = ROLE_SECTIONS[role]
    task = read_task(root, step_id)
    required: list[dict[str, Any]] = [
        _projection(root, task_path(root, step_id), step_id, sections["step"])
    ]

    for req_id in requirement_ids(task):
        required.append(
            _projection(
                root,
                canonical_requirement_path(root, req_id),
                req_id,
                sections["requirement"],
            )
        )
    for adr_id in adr_ids(task):
        required.append(
            _projection(
                root,
                canonical_adr_path(root, adr_id),
                adr_id,
                sections["adr"],
            )
        )
    for dependency_id in dependency_ids(task):
        required.append(
            _projection(
                root,
                task_path(root, dependency_id),
                dependency_id,
                sections["dependency"],
            )
        )
    for item in relevant_open_questions(root, task):
        required.append(
            _projection(
                root,
                item["path"],
                str(item["id"]),
                sections["oq"],
                optional_sections=OPTIONAL_SECTIONS[role]["oq"],
            )
        )
    required.extend(
        _architecture_projection(root, ref)
        for ref in architecture_refs(task)
    )

    # Applicability PRN — semantic judgement. Deterministic resolver therefore
    # даёт planner/reviewer только compact section projections всех active PRN,
    # а не пытается угадывать applicability и не читает их целиком.
    if role in {"planner", "reviewer"}:
        required.extend(_active_principles(root))

    seen: set[tuple[str, str, tuple[str, ...], str | None]] = set()
    unique: list[dict[str, Any]] = []
    for item in required:
        key = (
            str(item["artifact"]),
            str(item["path"]),
            tuple(item.get("sections") or []),
            item.get("anchor"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    artifact_count = len(unique)
    section_count = sum(len(item.get("sections") or []) for item in unique)
    try:
        core_principles = select_core_reasoning_principles(
            root,
            task,
            role=role,
            artifact_count=artifact_count,
            section_count=section_count,
        )
    except CoreReasoningPrincipleError as exc:
        raise ContextContractError(
            f"Core Reasoning Principles selection failed: {exc}"
        ) from exc

    optional = [
        {
            "trigger": "material integration/security/domain boundary discovered",
            "action": "request explicit expansion with repository-relative path and reason",
        },
        {
            "trigger": "verification/review evidence references an additional file",
            "action": "request explicit expansion with repository-relative path and reason",
        },
    ]
    contract: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "runtimeNeutral": True,
        "role": role,
        "command": f"{ROLE_COMMAND[role]} {step_id}",
        "stepId": step_id,
        "repositoryRevision": repository_revision(root),
        "required": unique,
        "coreReasoningPrinciples": core_principles,
        "optionalExpansions": optional,
        "forbiddenOrUnnecessary": [
            ".harness/tools/**",
            "planning/** unrelated to current STEP",
            "docs/** unrelated to explicit canonical links",
            ".agents/skills/** except selected command skill, listed coreReasoningPrinciples leaves, or explicitly invoked core capability",
        ],
    }
    manifest_chars = len(
        json.dumps(
            contract,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    contract["metrics"] = {
        "artifactCount": artifact_count,
        "sectionCount": section_count,
        "corePrincipleCount": len(core_principles),
        "corePrincipleChars": sum(
            int(item.get("chars") or 0)
            for item in core_principles
        ),
        "manifestChars": manifest_chars,
        "fullRepositoryPreload": False,
    }
    return contract


def build_context_contract(root: Path, step_id: str, role: str) -> dict[str, Any]:
    """Public fail-closed resolver boundary."""
    try:
        return _build_context_contract(root, step_id, role)
    except ContextContractError:
        raise
    except (DocumentError, OSError, UnicodeError, ValueError) as exc:
        raise ContextContractError(
            f"context resolution failed for {step_id}/{role}: {exc}"
        ) from exc


def validate_expansion(root: Path, path: str, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise ContextContractError("context expansion requires a non-empty reason")
    candidate = resolve_repo_path(root, path, label="context expansion")
    rel = _rel(root, candidate)
    if rel == ".harness/tools" or rel.startswith(".harness/tools/"):
        raise ContextContractError("tool source is forbidden in normal semantic context")
    if not candidate.is_file():
        raise ContextContractError(f"expanded context file not found: {rel}")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "path": rel,
        "reason": reason.strip(),
    }
