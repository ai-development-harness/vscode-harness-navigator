#!/usr/bin/env python3
"""Deterministic provenance/update planning for project/third-party repository skills.

The semantic agent fetches and inspects exact upstream bytes into .harness/local/**.
This module never uses the network and never executes third-party scripts. It owns:
- a machine-readable PROVENANCE.json beside an installed skill;
- safe regular-file snapshots with symlink/path rejection;
- three-way BASE/OURS/THEIRS classification for future SKILL UPDATE;
- explicit conflict/unavailable states without mutating installed skill content.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from document_contract import atomic_write_text


SCHEMA_VERSION = 1
PROVENANCE_FILE = "PROVENANCE.json"
UPSTREAM_FILE = "UPSTREAM.md"
SKILL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}$")
SHA_RE = re.compile(r"[0-9a-f]{7,64}$")
MAX_FILES = 512
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


class SkillProvenanceError(ValueError):
    """Skill provenance/update planning is unsafe or malformed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, label: str, *, max_chars: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillProvenanceError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\n" in result or "\r" in result:
        raise SkillProvenanceError(f"{label} must be a single line")
    if len(result) > max_chars:
        raise SkillProvenanceError(f"{label} exceeds {max_chars} chars")
    return result


def _slug(value: str) -> str:
    value = _text(value, "skill")
    if SKILL_RE.fullmatch(value) is None:
        raise SkillProvenanceError("skill must match [a-z0-9][a-z0-9-]{0,63}")
    return value


def _revision(value: Any, label: str) -> str:
    value = _text(value, label)
    if SHA_RE.fullmatch(value) is None:
        raise SkillProvenanceError(f"{label} must be an immutable commit-like hex revision")
    return value


def _skill_dir(root: Path, slug: str) -> Path:
    path = (root / ".agents" / "skills" / _slug(slug)).resolve()
    base = (root / ".agents" / "skills").resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise SkillProvenanceError("skill path escapes .agents/skills") from exc
    if not path.is_dir() or path.is_symlink():
        raise SkillProvenanceError(f"installed skill directory missing/unsafe: {slug}")
    return path


def _local_dir(root: Path, value: str, label: str) -> Path:
    raw = Path(_text(value, label))
    base = root.resolve()
    lexical = raw if raw.is_absolute() else base / raw
    lexical = Path(str(lexical.absolute()))
    allowed = base / ".harness" / "local"
    try:
        relative = lexical.relative_to(base)
        lexical.relative_to(allowed)
    except ValueError as exc:
        raise SkillProvenanceError(f"{label} must stay under .harness/local/**") from exc

    cursor = base
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SkillProvenanceError(f"{label} path must not contain symlinks")

    if not lexical.is_dir():
        raise SkillProvenanceError(f"{label} must be a real directory")
    candidate = lexical.resolve(strict=True)
    try:
        candidate.relative_to(allowed.resolve())
    except ValueError as exc:
        raise SkillProvenanceError(f"{label} escapes .harness/local/**") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def snapshot_tree(directory: Path, *, exclude_metadata: bool = False) -> dict[str, str]:
    """Return stable path->sha256 for a bounded regular-file tree."""
    directory = directory.resolve()
    if not directory.is_dir() or directory.is_symlink():
        raise SkillProvenanceError(f"snapshot root is not a safe directory: {directory}")
    result: dict[str, str] = {}
    total = 0
    entries = sorted(directory.rglob("*"), key=lambda item: item.as_posix())
    for path in entries:
        if path.is_symlink():
            raise SkillProvenanceError(f"symlink is not allowed in skill bundle: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SkillProvenanceError(f"non-regular file in skill bundle: {path}")
        rel = path.relative_to(directory).as_posix()
        if exclude_metadata and rel in {PROVENANCE_FILE, UPSTREAM_FILE}:
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise SkillProvenanceError(f"skill file exceeds {MAX_FILE_BYTES} bytes: {rel}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise SkillProvenanceError(
                f"skill bundle exceeds {MAX_TOTAL_BYTES} total bytes"
            )
        result[rel] = _sha256(path)
        if len(result) > MAX_FILES:
            raise SkillProvenanceError(f"skill bundle exceeds {MAX_FILES} files")
    if "SKILL.md" not in result:
        raise SkillProvenanceError("skill bundle must contain SKILL.md")
    return result


def _provenance_path(root: Path, slug: str) -> Path:
    return _skill_dir(root, slug) / PROVENANCE_FILE


def load_provenance(root: Path, slug: str) -> dict[str, Any]:
    path = _provenance_path(root, slug)
    if not path.is_file() or path.is_symlink():
        raise SkillProvenanceError(f"{PROVENANCE_FILE} missing for skill {slug}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillProvenanceError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SkillProvenanceError("provenance must be a JSON object")
    required = {"schemaVersion", "skill", "source", "installation", "update"}
    if set(value) != required:
        raise SkillProvenanceError("provenance has unsupported/missing top-level keys")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise SkillProvenanceError(f"schemaVersion must be {SCHEMA_VERSION}")
    if value.get("skill") != _slug(slug):
        raise SkillProvenanceError("provenance skill does not match directory")
    source = value.get("source")
    installation = value.get("installation")
    update = value.get("update")
    if not isinstance(source, dict) or set(source) != {
        "repository", "path", "inspectedRevision", "installedRevision", "license"
    }:
        raise SkillProvenanceError("source contract is malformed")
    _text(source.get("repository"), "source.repository")
    _text(source.get("path"), "source.path")
    _revision(source.get("inspectedRevision"), "source.inspectedRevision")
    _revision(source.get("installedRevision"), "source.installedRevision")
    _text(source.get("license"), "source.license")
    if not isinstance(installation, dict) or set(installation) != {
        "recordedAt", "localModified", "adaptationRationale", "forkSince",
        "upstreamFiles", "installedFiles"
    }:
        raise SkillProvenanceError("installation contract is malformed")
    if not isinstance(installation.get("localModified"), bool):
        raise SkillProvenanceError("installation.localModified must be boolean")
    rationale = installation.get("adaptationRationale")
    if not isinstance(rationale, list) or any(
        not isinstance(item, str) or not item.strip() for item in rationale
    ):
        raise SkillProvenanceError("installation.adaptationRationale must be string array")
    fork_since = installation.get("forkSince")
    if fork_since is not None:
        _revision(fork_since, "installation.forkSince")
    for field in ("upstreamFiles", "installedFiles"):
        mapping = installation.get(field)
        if not isinstance(mapping, dict) or "SKILL.md" not in mapping:
            raise SkillProvenanceError(f"installation.{field} must be a file hash map")
        for path_value, hash_value in mapping.items():
            _text(path_value, f"installation.{field}.path")
            if not isinstance(hash_value, str) or not hash_value.startswith("sha256:"):
                raise SkillProvenanceError(f"installation.{field}[{path_value}] must be sha256")
    if not isinstance(update, dict) or set(update) != {
        "latestCheckedUpstreamRevision", "status"
    }:
        raise SkillProvenanceError("update contract is malformed")
    latest = update.get("latestCheckedUpstreamRevision")
    if latest is not None:
        _revision(latest, "update.latestCheckedUpstreamRevision")
    if update.get("status") not in {
        "clean", "upstream-changed", "local-fork", "conflict", "unavailable"
    }:
        raise SkillProvenanceError("update.status is invalid")
    return value


def record_install(
    root: Path,
    slug: str,
    upstream_dir: str,
    *,
    repository: str,
    source_path: str,
    inspected_revision: str,
    installed_revision: str,
    license_value: str,
    adaptation_rationale: list[str],
) -> dict[str, Any]:
    slug = _slug(slug)
    installed = _skill_dir(root, slug)
    upstream = _local_dir(root, upstream_dir, "upstream-dir")
    upstream_files = snapshot_tree(upstream)
    installed_files = snapshot_tree(installed, exclude_metadata=True)
    local_modified = installed_files != upstream_files
    rationale = [
        _text(item, f"adaptationRationale[{index}]")
        for index, item in enumerate(adaptation_rationale)
    ]
    if local_modified and not rationale:
        raise SkillProvenanceError(
            "adapted install requires at least one adaptation rationale"
        )
    inspected = _revision(inspected_revision, "inspectedRevision")
    installed_rev = _revision(installed_revision, "installedRevision")
    value = {
        "schemaVersion": SCHEMA_VERSION,
        "skill": slug,
        "source": {
            "repository": _text(repository, "repository"),
            "path": _text(source_path, "sourcePath"),
            "inspectedRevision": inspected,
            "installedRevision": installed_rev,
            "license": _text(license_value, "license"),
        },
        "installation": {
            "recordedAt": _utc_now(),
            "localModified": local_modified,
            "adaptationRationale": rationale,
            "forkSince": installed_rev if local_modified else None,
            "upstreamFiles": upstream_files,
            "installedFiles": installed_files,
        },
        "update": {
            "latestCheckedUpstreamRevision": installed_rev,
            "status": "local-fork" if local_modified else "clean",
        },
    }
    atomic_write_text(
        installed / PROVENANCE_FILE,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    load_provenance(root, slug)
    return value


def _path_state(base: str | None, ours: str | None, theirs: str | None) -> tuple[str, str]:
    if ours == theirs:
        return ("unchanged" if ours == base else "converged", "none")
    if ours == base:
        if theirs is None:
            return "upstream-delete", "delete"
        return "upstream-change", "take-upstream"
    if theirs == base:
        return "local-change", "keep-local"
    if base is None:
        if ours is None:
            return "upstream-new", "take-upstream"
        if theirs is None:
            return "local-new", "keep-local"
        return "new-path-collision", "conflict"
    if ours is None and theirs != base:
        return "local-delete-upstream-change", "conflict"
    if theirs is None and ours != base:
        return "upstream-delete-local-change", "conflict"
    return "both-changed", "conflict"


def plan_update(
    root: Path,
    slug: str,
    *,
    candidate_dir: str | None,
    candidate_revision: str | None,
    unavailable: bool = False,
) -> dict[str, Any]:
    slug = _slug(slug)
    provenance = load_provenance(root, slug)
    installed_dir = _skill_dir(root, slug)
    current = snapshot_tree(installed_dir, exclude_metadata=True)
    base = provenance["installation"]["upstreamFiles"]

    if unavailable:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "unavailable",
            "skill": slug,
            "installedRevision": provenance["source"]["installedRevision"],
            "latestCheckedUpstreamRevision": None,
            "localDriftSinceInstall": current != provenance["installation"]["installedFiles"],
            "paths": [],
            "conflicts": [],
            "provenancePatch": {
                "latestCheckedUpstreamRevision": None,
                "status": "unavailable",
            },
        }
    if candidate_dir is None or candidate_revision is None:
        raise SkillProvenanceError(
            "candidate-dir and candidate-revision are required unless --unavailable"
        )
    candidate_path = _local_dir(root, candidate_dir, "candidate-dir")
    candidate = snapshot_tree(candidate_path)
    candidate_rev = _revision(candidate_revision, "candidateRevision")

    path_results: list[dict[str, Any]] = []
    conflicts: list[str] = []
    local_delta = False
    upstream_delta = False
    for path in sorted(set(base) | set(current) | set(candidate)):
        b = base.get(path)
        o = current.get(path)
        t = candidate.get(path)
        if o != b:
            local_delta = True
        if t != b:
            upstream_delta = True
        state, action = _path_state(b, o, t)
        if action == "conflict":
            conflicts.append(path)
        path_results.append({
            "path": path,
            "base": b,
            "ours": o,
            "theirs": t,
            "state": state,
            "action": action,
        })

    if conflicts:
        status = "conflict"
    elif local_delta:
        status = "local-fork"
    elif upstream_delta:
        status = "upstream-changed"
    else:
        status = "clean"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "skill": slug,
        "installedRevision": provenance["source"]["installedRevision"],
        "latestCheckedUpstreamRevision": candidate_rev,
        "localDriftSinceInstall": current != provenance["installation"]["installedFiles"],
        "localModifiedRelativeToUpstream": local_delta,
        "upstreamChanged": upstream_delta,
        "paths": path_results,
        "conflicts": conflicts,
        "safeToAutoApply": status in {"clean", "upstream-changed"} and not conflicts,
        "provenancePatch": {
            "latestCheckedUpstreamRevision": candidate_rev,
            "status": status,
        },
    }


def _payload(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record skill provenance and build read-only future update plans."
    )
    sub = parser.add_subparsers(dest="operation", required=True)

    record = sub.add_parser("record-install")
    record.add_argument("skill")
    record.add_argument("--payload-file", required=True)
    record.add_argument("--pretty", action="store_true")

    plan = sub.add_parser("plan")
    plan.add_argument("skill")
    plan.add_argument("--candidate-dir")
    plan.add_argument("--candidate-revision")
    plan.add_argument("--unavailable", action="store_true")
    plan.add_argument("--pretty", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("skill")
    status.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        if args.operation == "record-install":
            payload = _payload(args.payload_file)
            if not isinstance(payload, dict):
                raise SkillProvenanceError("record-install payload must be an object")
            allowed = {
                "upstreamDir", "repository", "sourcePath", "inspectedRevision",
                "installedRevision", "license", "adaptationRationale"
            }
            if set(payload) != allowed:
                raise SkillProvenanceError("record-install payload has unsupported/missing keys")
            result = record_install(
                root,
                args.skill,
                payload["upstreamDir"],
                repository=payload["repository"],
                source_path=payload["sourcePath"],
                inspected_revision=payload["inspectedRevision"],
                installed_revision=payload["installedRevision"],
                license_value=payload["license"],
                adaptation_rationale=payload["adaptationRationale"],
            )
            result = {"status": "PASS", "provenance": result}
        elif args.operation == "plan":
            result = plan_update(
                root,
                args.skill,
                candidate_dir=args.candidate_dir,
                candidate_revision=args.candidate_revision,
                unavailable=args.unavailable,
            )
        else:
            prov = load_provenance(root, args.skill)
            current = snapshot_tree(_skill_dir(root, args.skill), exclude_metadata=True)
            result = {
                "schemaVersion": SCHEMA_VERSION,
                "status": "PASS",
                "skill": args.skill,
                "provenance": prov,
                "localDriftSinceInstall": current != prov["installation"]["installedFiles"],
            }
    except (OSError, UnicodeError, json.JSONDecodeError, SkillProvenanceError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reason": str(exc),
        }
    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    ))
    return 0 if result.get("status") not in {"BLOCKED", "conflict", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
