#!/usr/bin/env python3
"""First-class deterministic contract Project Principles (PRN-NNN)."""
from __future__ import annotations
from pathlib import Path
import re
from typing import Any
from document_contract import ADR_ID_RE, DocumentError, REQ_ID_RE, exact_h1, parse_document, require_nonempty_sections, require_schema, string_list
from harness_config import adr_directory, get, load_manifest, principles_directory, requirements_directory

PRN_ID_RE = re.compile(r"PRN-[0-9]{3,}")
STATUSES = {"active", "superseded", "deprecated"}
SEVERITIES = {"blocking", "advisory"}
SECTIONS = ("Rule", "Rationale", "Applies to", "Exceptions / approved deviation")

def _configured(root: Path, dotted: str) -> bool:
    return get(load_manifest(root), dotted) is not None

def _canonical_ids(root: Path, dotted: str, directory: Path, pattern: str) -> set[str] | None:
    if not _configured(root, dotted):
        return None
    result: set[str] = set()
    for path in sorted(directory.glob(pattern)):
        if path.name == "TEMPLATE.md":
            continue
        try:
            doc = parse_document(path)
        except (DocumentError, OSError, UnicodeDecodeError):
            continue
        artifact_id = doc["frontmatter"].get("id")
        if isinstance(artifact_id, str):
            result.add(artifact_id)
    return result

def canonical_principles(root: Path) -> dict[str, dict[str, Any]]:
    if not _configured(root, "sources.principles"):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(principles_directory(root).glob("PRN-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            doc = parse_document(path)
        except (DocumentError, OSError, UnicodeDecodeError):
            continue
        prn_id = doc["frontmatter"].get("id")
        if isinstance(prn_id, str):
            result[prn_id] = doc
    return result

def validate_principles(root: Path) -> list[str]:
    if not _configured(root, "sources.principles"):
        return []
    errors: list[str] = []
    seen: dict[str, list[Path]] = {}
    directory = principles_directory(root)
    for path in sorted(directory.glob("PRN-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        try:
            doc = parse_document(path)
        except (DocumentError, OSError, UnicodeDecodeError) as exc:
            errors.append(f"principles: {path.relative_to(root)}: {exc}")
            continue
        prn_id = doc["frontmatter"].get("id")
        if isinstance(prn_id, str):
            seen.setdefault(prn_id, []).append(path)
    for prn_id, paths in sorted(seen.items()):
        if len(paths) > 1:
            errors.append(f"principles: duplicate canonical id {prn_id}: " + ", ".join(p.relative_to(root).as_posix() for p in paths))

    known_requirements = _canonical_ids(root, "sources.requirements", requirements_directory(root) if _configured(root, "sources.requirements") else root, "REQ-*.md")
    known_adrs = _canonical_ids(root, "sources.adrDirectory", adr_directory(root) if _configured(root, "sources.adrDirectory") else root, "ADR-*.md")
    principles = canonical_principles(root)
    for prn_id, doc in sorted(principles.items()):
        prefix = f"principles: {doc['path'].relative_to(root)}"
        errors.extend(f"{prefix}: {e}" for e in require_schema(doc))
        if PRN_ID_RE.fullmatch(prn_id) is None:
            errors.append(f"{prefix}: invalid id")
            continue
        if not doc["path"].name.startswith(prn_id + "-"):
            errors.append(f"{prefix}: filename/id mismatch")
        if not exact_h1(doc, prn_id):
            errors.append(f"{prefix}: invalid H1")
        meta = doc["frontmatter"]
        if meta.get("status") not in STATUSES:
            errors.append(f"{prefix}: status must be active|superseded|deprecated")
        if meta.get("severity") not in SEVERITIES:
            errors.append(f"{prefix}: severity must be blocking|advisory")
        if meta.get("scope") != "project":
            errors.append(f"{prefix}: scope must be project")
        for key, pattern, known in (("requirements", REQ_ID_RE, known_requirements), ("adrs", ADR_ID_RE, known_adrs)):
            values, issues = string_list(meta.get(key), key)
            errors.extend(f"{prefix}: {issue}" for issue in issues)
            for value in values:
                if pattern.fullmatch(value) is None:
                    errors.append(f"{prefix}: invalid {key} reference {value}")
                elif known is not None and value not in known:
                    errors.append(f"{prefix}: unknown {key} reference {value}")
        superseded_by = meta.get("superseded_by")
        if superseded_by is not None and (not isinstance(superseded_by, str) or PRN_ID_RE.fullmatch(superseded_by) is None):
            errors.append(f"{prefix}: superseded_by must be null or PRN-NNN")
        if superseded_by == prn_id:
            errors.append(f"{prefix}: principle cannot supersede itself")
        if meta.get("status") == "superseded":
            if not isinstance(superseded_by, str):
                errors.append(f"{prefix}: superseded principle requires superseded_by")
            elif superseded_by not in principles:
                errors.append(f"{prefix}: superseding principle does not exist: {superseded_by}")
        elif superseded_by is not None:
            errors.append(f"{prefix}: only superseded principle may set superseded_by")
        errors.extend(f"{prefix}: {e}" for e in require_nonempty_sections(doc, SECTIONS))
    return errors

def active_blocking_principles(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for prn_id, doc in sorted(canonical_principles(root).items()):
        meta = doc["frontmatter"]
        if meta.get("status") != "active" or meta.get("severity") != "blocking":
            continue
        result[prn_id] = {"frontmatter": {"schema": meta.get("schema"), "id": prn_id, "status": "active", "severity": "blocking", "scope": meta.get("scope")}, "sections": {name: doc["sections"].get(name, "") for name in SECTIONS}}
    return result
