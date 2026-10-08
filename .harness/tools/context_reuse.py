#!/usr/bin/env python3
"""Bounded, source-pinned context hints and rejected hypotheses for AI roles.

Hints are never authority: they are only a navigation aid to avoid repeated
codebase rediscovery. Exact file hashes must match before they are surfaced.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from document_contract import atomic_write_text

ROLES = {"planner", "implementer", "reviewer"}
MAX_SUMMARY_CHARS = 6000
MAX_HYPOTHESES = 5


def _path(root: Path, step_id: str, role: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None or role not in ROLES:
        raise ValueError("invalid STEP/role for context reuse")
    return root / ".harness/local/context-reuse" / f"{step_id}-{role}.json"


def _digest(root: Path, rel: str) -> str:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        raise ValueError("context source must be a repository-relative file")
    root_abs = root.resolve()
    path = root / rel
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"context source is not a regular file: {rel}")
    try:
        path.resolve().relative_to(root_abs)
    except ValueError as exc:
        raise ValueError("context source escapes repository") from exc
    return hashlib.sha256(path.read_bytes()).hexdigest()


def store(
    root: Path, step_id: str, role: str, paths: list[str],
    summary: str, rejected: list[dict[str, str]] | None = None,
) -> None:
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        raise ValueError("context summary must be 1..6000 characters")
    if not isinstance(paths, list) or not paths or len(paths) > 64:
        raise ValueError("context source path list must contain 1..64 paths")
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate context source path")
    hypotheses = rejected or []
    if not isinstance(hypotheses, list) or len(hypotheses) > MAX_HYPOTHESES:
        raise ValueError("rejected hypotheses must be bounded")
    for item in hypotheses:
        if not isinstance(item, dict) or set(item) != {"hypothesis", "falsification"}:
            raise ValueError("rejected hypothesis requires hypothesis/falsification")
        if any(not isinstance(item[k], str) or len(item[k].strip()) < 12 for k in item):
            raise ValueError("rejected hypothesis must have substantial evidence")
    digests = {name: _digest(root, name) for name in paths}
    payload = {
        "schemaVersion": 1, "stepId": step_id, "role": role,
        "sources": digests, "summary": summary.strip(),
        "rejectedHypotheses": hypotheses,
    }
    path = _path(root, step_id, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("context reuse path cannot be symlink")
    atomic_write_text(path, json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def lookup(root: Path, step_id: str, role: str, required: list[str]) -> dict[str, Any]:
    path = _path(root, step_id, role)
    if not path.is_file() or path.is_symlink():
        return {"status": "MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "INVALID"}
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        return {"status": "INVALID"}
    if payload.get("stepId") != step_id or payload.get("role") != role:
        return {"status": "INVALID"}
    sources = payload.get("sources")
    if not isinstance(sources, dict) or not sources or len(sources) > 64:
        return {"status": "INVALID"}
    if not set(required).issubset(sources):
        return {"status": "STALE", "reason": "required context changed"}
    try:
        fresh = all(_digest(root, name) == hashvalue for name, hashvalue in sources.items())
    except (ValueError, OSError):
        fresh = False
    if not fresh:
        return {"status": "STALE", "reason": "source bytes changed"}
    summary = payload.get("summary")
    rejected = payload.get("rejectedHypotheses")
    if not isinstance(summary, str) or len(summary) > MAX_SUMMARY_CHARS:
        return {"status": "INVALID"}
    if not isinstance(rejected, list) or len(rejected) > MAX_HYPOTHESES:
        return {"status": "INVALID"}
    return {
        "status": "REUSE_CANDIDATE", "sourcePaths": sorted(sources),
        "summary": summary, "rejectedHypotheses": rejected,
        "authority": "untrusted-navigational-hint-only",
    }
