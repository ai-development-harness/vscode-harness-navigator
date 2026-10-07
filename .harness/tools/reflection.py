#!/usr/bin/env python3
"""Structured post-work reflection from durable Harness evidence only.

Reflection is semantic learning, not authority. This module validates a closed
set of evidence sources, computes recurrence without transcript/session state,
enforces one-primary-target routing, detects duplicate lessons in durable
reflection history and writes an immutable report. It never mutates the target
artifact suggested by a lesson.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from document_contract import create_durable_report, render_document
from harness_config import audit_directory


SCHEMA_VERSION = 1
SOURCE_KINDS = {
    "review_finding",
    "repair_stop",
    "progress_stop",
    "completion_outcome",
    "audit_finding",
    "reconcile_finding",
    "verification_failure",
    "git_evidence",
    "durable_decision",
    "validator_failure",
}
TARGETS = {
    "core-tool-gate-validator",
    "core-reasoning-principle",
    "project-principle",
    "project-skill",
    "core-skill",
    "adr-req-oq-gap",
    "no-action",
}
SCOPES = {"core", "project", "none"}
TARGET_SCOPE = {
    "core-tool-gate-validator": "core",
    "core-reasoning-principle": "core",
    "core-skill": "core",
    "project-principle": "project",
    "project-skill": "project",
    "adr-req-oq-gap": "project",
    "no-action": "none",
}
RULE_TARGETS = {
    "core-tool-gate-validator",
    "core-reasoning-principle",
    "core-skill",
    "project-principle",
    "project-skill",
}
FP_RE = re.compile(r"sha256:[0-9a-f]{64}$")
LESSON_FP_RE = re.compile(r"(?m)^- Lesson fingerprint: (sha256:[0-9a-f]{64})\s*$")


class ReflectionError(ValueError):
    """Reflection evidence or semantic lesson contract is invalid."""


def _text(value: Any, label: str, *, max_chars: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReflectionError(f"{label} must be a non-empty string")
    result = value.strip()
    if len(result) > max_chars:
        raise ReflectionError(f"{label} exceeds {max_chars} chars")
    return result


def _single(value: Any, label: str, *, max_chars: int = 1000) -> str:
    result = _text(value, label, max_chars=max_chars)
    if "\n" in result or "\r" in result:
        raise ReflectionError(f"{label} must be a single line")
    return result


def _repo_file(root: Path, value: Any, label: str) -> str:
    raw = Path(_single(value, label))
    if raw.is_absolute() or ".." in raw.parts:
        raise ReflectionError(f"{label} must be a repository-relative path")
    candidate = (root / raw).resolve()
    base = root.resolve()
    try:
        rel = candidate.relative_to(base).as_posix()
    except ValueError as exc:
        raise ReflectionError(f"{label} escapes repository") from exc
    if rel.startswith(".harness/local/"):
        raise ReflectionError(f"{label} must point to durable evidence, not .harness/local")
    if not candidate.is_file() or candidate.is_symlink():
        raise ReflectionError(f"{label} must be an existing regular file: {rel}")
    return rel


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_evidence(root: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "explicitHumanRequest", "events"
    }:
        raise ReflectionError(
            "evidence envelope keys must be schemaVersion, explicitHumanRequest, events"
        )
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ReflectionError(f"evidence schemaVersion must be {SCHEMA_VERSION}")
    explicit = value.get("explicitHumanRequest")
    if not isinstance(explicit, bool):
        raise ReflectionError("explicitHumanRequest must be boolean")
    raw_events = value.get("events")
    if not isinstance(raw_events, list) or not raw_events or len(raw_events) > 200:
        raise ReflectionError("events must be a non-empty array with <= 200 items")

    events: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_events):
        label = f"events[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "id", "sourceKind", "classKey", "occurrenceId", "path", "fingerprint", "summary"
        }:
            raise ReflectionError(
                f"{label} keys must be id, sourceKind, classKey, occurrenceId, path, fingerprint, summary"
            )
        event_id = _single(raw.get("id"), f"{label}.id")
        if event_id in ids:
            raise ReflectionError(f"duplicate evidence id: {event_id}")
        ids.add(event_id)
        source = raw.get("sourceKind")
        if source not in SOURCE_KINDS:
            raise ReflectionError(f"{label}.sourceKind is unsupported")
        fingerprint = _single(raw.get("fingerprint"), f"{label}.fingerprint")
        if FP_RE.fullmatch(fingerprint) is None:
            raise ReflectionError(f"{label}.fingerprint must be sha256:...")
        events.append({
            "id": event_id,
            "sourceKind": source,
            "classKey": _single(raw.get("classKey"), f"{label}.classKey"),
            "occurrenceId": _single(raw.get("occurrenceId"), f"{label}.occurrenceId"),
            "path": _repo_file(root, raw.get("path"), f"{label}.path"),
            "fingerprint": fingerprint,
            "summary": _single(raw.get("summary"), f"{label}.summary", max_chars=4000),
        })

    # Same class/occurrence may be corroborated by several durable sources but
    # counts only once for recurrence.
    class_occurrences: dict[str, set[str]] = {}
    for event in events:
        class_occurrences.setdefault(event["classKey"], set()).add(event["occurrenceId"])
    recurring = {
        key: len(occurrences)
        for key, occurrences in class_occurrences.items()
        if len(occurrences) >= 2
    }
    high_cost = any(
        event["sourceKind"] in {"repair_stop", "progress_stop", "verification_failure"}
        for event in events
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "explicitHumanRequest": explicit,
        "events": events,
        "classOccurrences": {
            key: len(value) for key, value in sorted(class_occurrences.items())
        },
        "triggerRecommended": bool(recurring or high_cost),
        "triggerReasons": {
            "recurringClasses": recurring,
            "highCostSignal": high_cost,
        },
    }


def _existing_lesson_fingerprints(root: Path) -> set[str]:
    directory = audit_directory(root) / "reflections"
    if not directory.is_dir():
        return set()
    result: set[str] = set()
    for path in sorted(directory.glob("REFLECTION-*.md")):
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8")
        result.update(LESSON_FP_RE.findall(text))
    return result


def validate_lessons(
    root: Path,
    evidence: dict[str, Any],
    payload: Any,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or set(payload) != {"schemaVersion", "lessons", "rationale"}:
        raise ReflectionError("payload keys must be schemaVersion, lessons, rationale")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ReflectionError(f"payload schemaVersion must be {SCHEMA_VERSION}")
    _text(payload.get("rationale"), "rationale")
    raw_lessons = payload.get("lessons")
    if not isinstance(raw_lessons, list) or len(raw_lessons) > 50:
        raise ReflectionError("lessons must be an array with <= 50 items")

    by_id = {event["id"]: event for event in evidence["events"]}
    existing = _existing_lesson_fingerprints(root)
    seen_fingerprints: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_lessons):
        label = f"lessons[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "classKey", "summary", "scope", "primaryTarget",
            "evidenceIds", "rationale", "proposedAction"
        }:
            raise ReflectionError(
                f"{label} must contain classKey, summary, scope, primaryTarget, evidenceIds, rationale, proposedAction"
            )
        class_key = _single(raw.get("classKey"), f"{label}.classKey")
        scope = raw.get("scope")
        target = raw.get("primaryTarget")
        if scope not in SCOPES:
            raise ReflectionError(f"{label}.scope must be one of {sorted(SCOPES)}")
        if target not in TARGETS:
            raise ReflectionError(f"{label}.primaryTarget must be one of {sorted(TARGETS)}")
        if TARGET_SCOPE[target] != scope:
            raise ReflectionError(
                f"{label}: primaryTarget {target} requires scope={TARGET_SCOPE[target]}"
            )
        evidence_ids = raw.get("evidenceIds")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise ReflectionError(f"{label}.evidenceIds must be non-empty")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ReflectionError(f"{label}.evidenceIds must not contain duplicates")
        linked: list[dict[str, Any]] = []
        for offset, evidence_id in enumerate(evidence_ids):
            evidence_id = _single(evidence_id, f"{label}.evidenceIds[{offset}]")
            event = by_id.get(evidence_id)
            if event is None:
                raise ReflectionError(f"{label} references unknown evidence id {evidence_id}")
            if event["classKey"] != class_key:
                raise ReflectionError(
                    f"{label} evidence {evidence_id} belongs to another classKey"
                )
            linked.append(event)

        occurrences = len({event["occurrenceId"] for event in linked})
        recurring = occurrences >= 2
        if target in RULE_TARGETS and not recurring and not evidence["explicitHumanRequest"]:
            raise ReflectionError(
                f"{label}: one-off lesson cannot become durable rule/skill without explicit human request"
            )

        summary = _single(raw.get("summary"), f"{label}.summary", max_chars=4000)
        proposed = _single(
            raw.get("proposedAction"), f"{label}.proposedAction", max_chars=4000
        )
        rationale = _single(raw.get("rationale"), f"{label}.rationale", max_chars=4000)
        lesson_fp = _stable_hash({
            "classKey": class_key,
            "scope": scope,
            "primaryTarget": target,
            "summary": summary,
        })
        if lesson_fp in existing or lesson_fp in seen_fingerprints:
            raise ReflectionError(f"{label}: duplicate lesson fingerprint {lesson_fp}")
        seen_fingerprints.add(lesson_fp)
        result.append({
            "lessonFingerprint": lesson_fp,
            "classKey": class_key,
            "summary": summary,
            "scope": scope,
            "primaryTarget": target,
            "evidenceIds": list(evidence_ids),
            "occurrenceCount": occurrences,
            "recurring": recurring,
            "rationale": rationale,
            "proposedAction": proposed,
        })
    return result


def write_reflection(
    root: Path,
    evidence: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    lessons = validate_lessons(root, evidence, payload)
    directory = audit_directory(root) / "reflections"

    def content_factory(created_at: str) -> str:
        meta = {
            "schema": 1,
            "kind": "reflection",
            "lesson_count": len(lessons),
            "evidence_count": len(evidence["events"]),
            "created_at": created_at,
        }
        lines = [
            "# Structured Reflection",
            "",
            "## Trigger",
            "",
            f"- Recommended: {'yes' if evidence['triggerRecommended'] else 'no'}",
            f"- Explicit human request: {'yes' if evidence['explicitHumanRequest'] else 'no'}",
            "",
            "## Lessons",
            "",
        ]
        if not lessons:
            lines.append("- No durable lesson proposed.")
        for index, lesson in enumerate(lessons, 1):
            lines.extend([
                f"### LESSON-{index:03d}",
                "",
                f"- Lesson fingerprint: {lesson['lessonFingerprint']}",
                f"- Class: {lesson['classKey']}",
                f"- Scope: {lesson['scope']}",
                f"- Primary target: {lesson['primaryTarget']}",
                f"- Occurrences: {lesson['occurrenceCount']}",
                f"- Evidence IDs: {', '.join(lesson['evidenceIds'])}",
                "",
                lesson["summary"],
                "",
                f"Rationale: {lesson['rationale']}",
                "",
                f"Proposed action: {lesson['proposedAction']}",
                "",
            ])
        lines.extend([
            "## Evidence pointers",
            "",
        ])
        for event in evidence["events"]:
            lines.append(
                f"- {event['id']} — {event['sourceKind']} — {event['path']} — {event['fingerprint']}"
            )
        lines.extend([
            "",
            "## Boundary",
            "",
            "This report is a proposal only. automaticMutationAllowed=false",
            "",
            f"Reflection rationale: {_text(payload.get('rationale'), 'rationale')}",
            "",
        ])
        return render_document(meta, "\n".join(lines))

    path, created_at = create_durable_report(
        "REFLECTION-",
        directory=directory,
        content_factory=content_factory,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "report": path.relative_to(root).as_posix(),
        "createdAt": created_at,
        "lessonCount": len(lessons),
        "lessons": lessons,
        "automaticMutationAllowed": False,
    }


def _json_file(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Structured reflection over durable Harness evidence.")
    sub = parser.add_subparsers(dest="operation", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--evidence-file", required=True)
    scan.add_argument("--pretty", action="store_true")

    write = sub.add_parser("write")
    write.add_argument("--evidence-file", required=True)
    write.add_argument("--payload-file", required=True)
    write.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        evidence = load_evidence(root, _json_file(args.evidence_file))
        if args.operation == "scan":
            result = {"status": "PASS", **evidence, "automaticMutationAllowed": False}
        else:
            payload = _json_file(args.payload_file)
            if not isinstance(payload, dict):
                raise ReflectionError("payload must be an object")
            result = write_reflection(root, evidence, payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ReflectionError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": "REFLECTION_BLOCKED",
            "message": str(exc),
            "automaticMutationAllowed": False,
        }
    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    ))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
