#!/usr/bin/env python3
"""Recurring Correction → Structural Enforcement contract.

Модуль разделяет две ответственности:

1. deterministic evidence aggregation:
   - Review Contract v3 evidence-gated findings агрегируются по stable category/fingerprint;
   - один и тот же finding на той же reviewed revision считается один раз;
   - дополнительные structured signals принимаются только в закрытом envelope;
   - chat/transcript/session memory не являются допустимым source kind;

2. validation semantic proposal:
   - один случай не считается recurring без explicit caller override;
   - выбранный enforcement обязан быть самым сильным feasible уровнем ladder;
   - deterministic enforcement обязан иметь negative regression fixture;
   - architecture-level proposal никогда не разрешает silent mutation.

Tool не меняет code/ADR/docs. Он только строит/валидирует proposal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from document_contract import parse_document, parse_utc_timestamp
from harness_config import review_directory, resolve_repo_path
from review_contract import repository_revision
from review_findings import FINDING_CONTRACT_VERSION, parse_machine_findings


SCHEMA_VERSION = 1
RECURRING_THRESHOLD = 2
MAX_SUPPLIED_EVENTS = 128
MAX_SCOPE_ITEMS = 32
MAX_EVIDENCE_REFS = 64

REVIEW_CATEGORIES = {"implementation", "evidence", "contract"}
SUPPLEMENTAL_CATEGORIES = REVIEW_CATEGORIES | {
    "process",
    "architecture",
    "validation",
    "decision",
}

# Эти source kinds могут доказать ещё одно фактическое occurrence класса ошибки.
# Repair/progress/decision records полезны как corroborating context, но не должны
# искусственно удваивать тот же defect occurrence.
COUNTABLE_SOURCE_KINDS = {
    "review_finding",
    "audit_finding",
    "reconcile_finding",
    "validator_failure",
}
SUPPLEMENTAL_SOURCE_KINDS = {
    "repair_stop",
    "progress_stop",
    "audit_finding",
    "reconcile_finding",
    "validator_failure",
    "durable_decision",
}

MECHANISM_LADDER = (
    "architecture-ownership",
    "schema-type",
    "validator-lint",
    "regression-test",
    "durable-instruction",
)
DETERMINISTIC_MECHANISMS = set(MECHANISM_LADDER[:-1])
ARCHITECTURE_ROUTES = {"architecture-change", "ADR", "OQ/RESEARCH"}

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_CLASS_KEY_RE = re.compile(r"[A-Za-z0-9._:/-]{3,300}")


class StructuralEnforcementError(ValueError):
    """Evidence/proposal cannot be trusted; caller must fail closed."""


def _single_line(value: object, *, label: str, max_chars: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StructuralEnforcementError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\n" in result or "\r" in result:
        raise StructuralEnforcementError(f"{label} must be a single line")
    if len(result) > max_chars:
        raise StructuralEnforcementError(
            f"{label} exceeds {max_chars} characters"
        )
    return result


def _string_list(
    value: object,
    *,
    label: str,
    max_items: int,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise StructuralEnforcementError(f"{label} must be an array")
    if not allow_empty and not value:
        raise StructuralEnforcementError(f"{label} must not be empty")
    if len(value) > max_items:
        raise StructuralEnforcementError(
            f"{label} exceeds maximum of {max_items} items"
        )
    result = [
        _single_line(item, label=f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise StructuralEnforcementError(f"{label} must not contain duplicates")
    return result


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _review_class_key(category: str, fingerprint: str) -> str:
    return f"review:{category}:{fingerprint}"


def _review_occurrence_id(
    *,
    step_id: str,
    reviewed_revision: object,
    report: str,
    fingerprint: str,
) -> str:
    """Deduplicate repeated reports of the same finding on the same subject.

    Если report содержит canonical reviewed_revision, identity строится из неё.
    Если structured report revision не содержит, fallback — immutable report
    path: это консервативно считает такой report отдельным occurrence.
    """
    revision_identity: object
    if isinstance(reviewed_revision, dict) and reviewed_revision:
        revision_identity = reviewed_revision
    else:
        revision_identity = {"report": report}
    return _stable_digest(
        {
            "stepId": step_id,
            "reviewedRevision": revision_identity,
            "fingerprint": fingerprint,
        }
    )


def _event_id(event: dict[str, Any]) -> str:
    return _stable_digest(
        {
            "sourceKind": event["sourceKind"],
            "classKey": event["classKey"],
            "occurrenceId": event["occurrenceId"],
            "evidenceRef": event["evidenceRef"],
        }
    )


def collect_review_evidence(
    root: Path,
    *,
    step_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Collect only current Review Contract v3 evidence-gated findings.

    Legacy review history is intentionally skipped, because converting prose to
    recurring classes would reintroduce semantic guessing. Historical v1/v2 reports are skipped, because they predate the Evidence Gate. Malformed v3 machine
    findings fail closed.
    """
    root = root.resolve()
    base = review_directory(root)
    if not base.is_dir():
        return [], 0

    if step_id is None:
        paths = sorted(base.glob("STEP-*/REVIEW-*.md"))
    else:
        paths = sorted((base / step_id).glob("REVIEW-*.md"))

    events: list[dict[str, Any]] = []
    skipped_legacy = 0

    for path in paths:
        if path.is_symlink():
            raise StructuralEnforcementError(
                f"review evidence must not be a symlink: {path.relative_to(root)}"
            )
        document = parse_document(path)
        meta = document["frontmatter"]

        if meta.get("kind") != "step_review":
            raise StructuralEnforcementError(
                f"{path.relative_to(root)}: kind must be step_review"
            )

        report_step = meta.get("step_id")
        if not isinstance(report_step, str) or not report_step:
            raise StructuralEnforcementError(
                f"{path.relative_to(root)}: step_id is missing"
            )
        parent_step = path.parent.name
        if report_step != parent_step:
            raise StructuralEnforcementError(
                f"{path.relative_to(root)}: step_id does not match directory"
            )
        if step_id is not None and report_step != step_id:
            raise StructuralEnforcementError(
                f"{path.relative_to(root)}: unexpected STEP evidence"
            )

        if meta.get("finding_contract") != FINDING_CONTRACT_VERSION:
            skipped_legacy += 1
            continue

        try:
            findings = parse_machine_findings(document)
        except (ValueError, TypeError) as exc:
            raise StructuralEnforcementError(
                f"{path.relative_to(root)}: invalid Review Contract v3 findings: {exc}"
            ) from exc

        report = path.relative_to(root).as_posix()
        reviewed_revision = meta.get("reviewed_revision")
        created_at = meta.get("created_at")
        observed_at = (
            created_at
            if isinstance(created_at, str)
            and parse_utc_timestamp(created_at) is not None
            else None
        )

        for finding in findings:
            category = str(finding["category"])
            fingerprint = str(finding["fingerprint"])
            if category not in REVIEW_CATEGORIES or _SHA256_RE.fullmatch(fingerprint) is None:
                raise StructuralEnforcementError(
                    f"{report}: malformed structured finding identity"
                )
            occurrence_id = _review_occurrence_id(
                step_id=report_step,
                reviewed_revision=reviewed_revision,
                report=report,
                fingerprint=fingerprint,
            )
            event = {
                "sourceKind": "review_finding",
                "classKey": _review_class_key(category, fingerprint),
                "occurrenceId": occurrence_id,
                "category": category,
                "evidenceRef": report,
                "observedAt": observed_at,
                "signal": str(finding["title"]),
                "findingFingerprint": fingerprint,
                "stepId": report_step,
                "verification": "repository-local-structured",
                "countsTowardFrequency": True,
            }
            event["evidenceId"] = _event_id(event)
            events.append(event)

    return events, skipped_legacy


def normalize_supplied_evidence(value: object) -> list[dict[str, Any]]:
    """Validate optional structured evidence produced by other Harness surfaces.

    Core tool does not parse arbitrary audit/reconcile prose. Caller may provide
    only already-structured facts. Transcript/chat kinds are impossible because
    they are absent from the closed sourceKind set.
    """
    if value is None:
        return []
    if not isinstance(value, dict):
        raise StructuralEnforcementError("evidence envelope must be an object")
    if set(value) != {"schemaVersion", "events"}:
        raise StructuralEnforcementError(
            "evidence envelope keys must be schemaVersion, events"
        )
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise StructuralEnforcementError(
            f"evidence schemaVersion must be {SCHEMA_VERSION}"
        )
    raw_events = value.get("events")
    if not isinstance(raw_events, list):
        raise StructuralEnforcementError("evidence.events must be an array")
    if len(raw_events) > MAX_SUPPLIED_EVENTS:
        raise StructuralEnforcementError(
            f"evidence.events exceeds {MAX_SUPPLIED_EVENTS}"
        )

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            raise StructuralEnforcementError(
                f"evidence.events[{index}] must be an object"
            )
        allowed = {
            "sourceKind",
            "classKey",
            "occurrenceId",
            "category",
            "evidenceRef",
            "observedAt",
            "signal",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise StructuralEnforcementError(
                f"evidence.events[{index}] unsupported keys: "
                + ", ".join(unknown)
            )

        source_kind = _single_line(
            raw.get("sourceKind"),
            label=f"evidence.events[{index}].sourceKind",
        )
        if source_kind not in SUPPLEMENTAL_SOURCE_KINDS:
            raise StructuralEnforcementError(
                f"evidence.events[{index}].sourceKind must be one of "
                f"{sorted(SUPPLEMENTAL_SOURCE_KINDS)}"
            )

        class_key = _single_line(
            raw.get("classKey"),
            label=f"evidence.events[{index}].classKey",
            max_chars=300,
        )
        if _CLASS_KEY_RE.fullmatch(class_key) is None:
            raise StructuralEnforcementError(
                f"evidence.events[{index}].classKey has invalid format"
            )

        occurrence_id = _single_line(
            raw.get("occurrenceId"),
            label=f"evidence.events[{index}].occurrenceId",
            max_chars=300,
        )
        category = _single_line(
            raw.get("category"),
            label=f"evidence.events[{index}].category",
        )
        if category not in SUPPLEMENTAL_CATEGORIES:
            raise StructuralEnforcementError(
                f"evidence.events[{index}].category must be one of "
                f"{sorted(SUPPLEMENTAL_CATEGORIES)}"
            )

        evidence_ref = _single_line(
            raw.get("evidenceRef"),
            label=f"evidence.events[{index}].evidenceRef",
            max_chars=1000,
        )
        observed_at = _single_line(
            raw.get("observedAt"),
            label=f"evidence.events[{index}].observedAt",
        )
        if parse_utc_timestamp(observed_at) is None:
            raise StructuralEnforcementError(
                f"evidence.events[{index}].observedAt must be timezone-aware ISO-8601"
            )

        signal = _single_line(
            raw.get("signal"),
            label=f"evidence.events[{index}].signal",
            max_chars=1000,
        )

        event = {
            "sourceKind": source_kind,
            "classKey": class_key,
            "occurrenceId": occurrence_id,
            "category": category,
            "evidenceRef": evidence_ref,
            "observedAt": observed_at,
            "signal": signal,
            "findingFingerprint": None,
            "stepId": None,
            "verification": "supplied-structured-not-locally-reparsed",
            "countsTowardFrequency": source_kind in COUNTABLE_SOURCE_KINDS,
        }
        event["evidenceId"] = _event_id(event)
        if event["evidenceId"] in seen_ids:
            raise StructuralEnforcementError(
                f"duplicate supplied evidence event at index {index}"
            )
        seen_ids.add(str(event["evidenceId"]))
        result.append(event)

    return result


def aggregate_evidence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate stable classes and deduplicate factual occurrences."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["classKey"]), []).append(event)

    classes: list[dict[str, Any]] = []
    for class_key in sorted(grouped):
        items = grouped[class_key]
        categories = sorted({str(item["category"]) for item in items})
        if len(categories) != 1:
            raise StructuralEnforcementError(
                f"classKey {class_key!r} mixes categories: {categories}"
            )

        countable = [
            item for item in items if bool(item.get("countsTowardFrequency"))
        ]
        occurrence_ids = sorted(
            {str(item["occurrenceId"]) for item in countable}
        )
        evidence_ids = sorted({str(item["evidenceId"]) for item in items})
        source_counts: dict[str, int] = {}
        for item in items:
            key = str(item["sourceKind"])
            source_counts[key] = source_counts.get(key, 0) + 1

        fingerprints = sorted(
            {
                str(item["findingFingerprint"])
                for item in items
                if isinstance(item.get("findingFingerprint"), str)
            }
        )
        classes.append(
            {
                "classKey": class_key,
                "category": categories[0],
                "occurrenceCount": len(occurrence_ids),
                "recurring": len(occurrence_ids) >= RECURRING_THRESHOLD,
                "occurrenceIds": occurrence_ids,
                "evidenceIds": evidence_ids,
                "reviewFingerprints": fingerprints,
                "sourceCounts": dict(sorted(source_counts.items())),
            }
        )

    return classes


def build_preflight(
    root: Path,
    *,
    step_id: str | None = None,
    supplied_evidence: object = None,
) -> dict[str, Any]:
    review_events, skipped_legacy = collect_review_evidence(
        root,
        step_id=step_id,
    )
    supplied = normalize_supplied_evidence(supplied_evidence)
    events = review_events + supplied
    classes = aggregate_evidence(events)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "repositoryRevision": repository_revision(root.resolve()),
        "scopeStepId": step_id,
        "recurringThreshold": RECURRING_THRESHOLD,
        "classes": classes,
        "evidence": sorted(events, key=lambda item: str(item["evidenceId"])),
        "metrics": {
            "reviewEvents": len(review_events),
            "suppliedEvents": len(supplied),
            "skippedLegacyReviews": skipped_legacy,
            "classCount": len(classes),
            "recurringClassCount": sum(
                1 for item in classes if bool(item["recurring"])
            ),
        },
    }


def _proposal_mechanism(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StructuralEnforcementError("mechanism must be an object")
    allowed = {"kind", "rationale", "higherLevelsRejected", "decisionRoute"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StructuralEnforcementError(
            "mechanism unsupported keys: " + ", ".join(unknown)
        )

    kind = _single_line(value.get("kind"), label="mechanism.kind")
    if kind not in MECHANISM_LADDER:
        raise StructuralEnforcementError(
            f"mechanism.kind must be one of {list(MECHANISM_LADDER)}"
        )
    rationale = _single_line(
        value.get("rationale"),
        label="mechanism.rationale",
        max_chars=2000,
    )

    raw_rejected = value.get("higherLevelsRejected")
    if not isinstance(raw_rejected, list):
        raise StructuralEnforcementError(
            "mechanism.higherLevelsRejected must be an array"
        )

    selected_index = MECHANISM_LADDER.index(kind)
    expected_higher = list(MECHANISM_LADDER[:selected_index])
    normalized_rejected: list[dict[str, str]] = []
    for index, item in enumerate(raw_rejected):
        if not isinstance(item, dict) or set(item) != {"kind", "reason"}:
            raise StructuralEnforcementError(
                f"mechanism.higherLevelsRejected[{index}] must contain kind, reason"
            )
        rejected_kind = _single_line(
            item.get("kind"),
            label=f"mechanism.higherLevelsRejected[{index}].kind",
        )
        reason = _single_line(
            item.get("reason"),
            label=f"mechanism.higherLevelsRejected[{index}].reason",
            max_chars=1200,
        )
        normalized_rejected.append({"kind": rejected_kind, "reason": reason})

    actual_higher = [item["kind"] for item in normalized_rejected]
    if actual_higher != expected_higher:
        raise StructuralEnforcementError(
            "mechanism must justify every stronger ladder level in order; "
            f"expected {expected_higher}, got {actual_higher}"
        )

    route = value.get("decisionRoute")
    if kind == "architecture-ownership":
        route = _single_line(route, label="mechanism.decisionRoute")
        if route not in ARCHITECTURE_ROUTES:
            raise StructuralEnforcementError(
                f"mechanism.decisionRoute must be one of {sorted(ARCHITECTURE_ROUTES)}"
            )
    elif route is not None:
        raise StructuralEnforcementError(
            "mechanism.decisionRoute is allowed only for architecture-ownership"
        )

    return {
        "kind": kind,
        "rationale": rationale,
        "higherLevelsRejected": normalized_rejected,
        "decisionRoute": route,
    }


def _candidate_scope(root: Path, value: object) -> list[str]:
    items = _string_list(
        value,
        label="candidateScope",
        max_items=MAX_SCOPE_ITEMS,
    )
    result: list[str] = []
    for index, item in enumerate(items):
        raw = Path(item)
        if raw.is_absolute() or ".." in raw.parts:
            raise StructuralEnforcementError(
                f"candidateScope[{index}] must be repository-relative"
            )
        if item in {".", ".git"} or item.startswith(".git/"):
            raise StructuralEnforcementError(
                f"candidateScope[{index}] cannot target Git internals"
            )
        result.append(raw.as_posix())
    return result


def _proof(
    root: Path,
    value: object,
    *,
    mechanism_kind: str,
    require_existing_fixture: bool,
) -> dict[str, Any] | None:
    if mechanism_kind == "durable-instruction":
        if value is not None:
            raise StructuralEnforcementError(
                "durable-instruction must not pretend to have deterministic proof"
            )
        return None

    if not isinstance(value, dict):
        raise StructuralEnforcementError(
            "deterministic enforcement requires proof object"
        )
    required_keys = {
        "fixture",
        "command",
        "oldMistakeExpectedFailure",
        "correctedStateExpectedPass",
    }
    if set(value) != required_keys:
        raise StructuralEnforcementError(
            "proof keys must be fixture, command, oldMistakeExpectedFailure, "
            "correctedStateExpectedPass"
        )

    fixture = _single_line(value.get("fixture"), label="proof.fixture")
    raw_path = Path(fixture)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise StructuralEnforcementError("proof.fixture must be repository-relative")
    fixture_path = resolve_repo_path(
        root,
        fixture,
        label="structural enforcement regression fixture",
    )
    if require_existing_fixture and (
        not fixture_path.is_file() or fixture_path.is_symlink()
    ):
        raise StructuralEnforcementError(
            f"implemented deterministic rule requires existing regular fixture: {fixture}"
        )

    command = _string_list(
        value.get("command"),
        label="proof.command",
        max_items=32,
    )
    return {
        "fixture": raw_path.as_posix(),
        "command": command,
        "oldMistakeExpectedFailure": _single_line(
            value.get("oldMistakeExpectedFailure"),
            label="proof.oldMistakeExpectedFailure",
            max_chars=1600,
        ),
        "correctedStateExpectedPass": _single_line(
            value.get("correctedStateExpectedPass"),
            label="proof.correctedStateExpectedPass",
            max_chars=1600,
        ),
    }


def validate_proposal(
    root: Path,
    preflight: dict[str, Any],
    payload: object,
    *,
    explicit_single: bool = False,
    require_existing_fixture: bool = False,
) -> dict[str, Any]:
    """Validate semantic classification against deterministic evidence."""
    if not isinstance(payload, dict):
        raise StructuralEnforcementError("proposal payload must be an object")
    allowed = {
        "schemaVersion",
        "status",
        "classKey",
        "recurringErrorClass",
        "mechanism",
        "candidateScope",
        "proof",
        "evidenceIds",
        "gaps",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise StructuralEnforcementError(
            "proposal unsupported keys: " + ", ".join(unknown)
        )
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise StructuralEnforcementError(
            f"proposal schemaVersion must be {SCHEMA_VERSION}"
        )
    status = _single_line(payload.get("status"), label="proposal.status")
    if status not in {"PASS", "INCONCLUSIVE"}:
        raise StructuralEnforcementError(
            "proposal.status must be PASS|INCONCLUSIVE"
        )

    class_key = _single_line(
        payload.get("classKey"),
        label="proposal.classKey",
        max_chars=300,
    )
    classes = {
        str(item["classKey"]): item
        for item in preflight.get("classes", [])
        if isinstance(item, dict)
    }
    selected = classes.get(class_key)
    if selected is None:
        raise StructuralEnforcementError(
            f"proposal.classKey is not present in evidence aggregation: {class_key}"
        )

    recurring = bool(selected["recurring"])
    if status == "PASS" and not recurring and not explicit_single:
        raise StructuralEnforcementError(
            "single occurrence is not a recurring pattern; explicit caller request is required"
        )

    recurring_error_class = _single_line(
        payload.get("recurringErrorClass"),
        label="proposal.recurringErrorClass",
        max_chars=1600,
    )
    mechanism = _proposal_mechanism(payload.get("mechanism"))
    scope = _candidate_scope(root, payload.get("candidateScope"))
    proof = _proof(
        root,
        payload.get("proof"),
        mechanism_kind=str(mechanism["kind"]),
        require_existing_fixture=require_existing_fixture,
    )

    evidence_ids = _string_list(
        payload.get("evidenceIds"),
        label="proposal.evidenceIds",
        max_items=MAX_EVIDENCE_REFS,
    )
    available_ids = set(str(item) for item in selected["evidenceIds"])
    unknown_evidence = sorted(set(evidence_ids) - available_ids)
    if unknown_evidence:
        raise StructuralEnforcementError(
            "proposal references evidence outside selected class: "
            + ", ".join(unknown_evidence)
        )

    # PASS recurring proposal must actually cite enough distinct factual
    # occurrences to establish recurrence. Corroborating stop/decision events do
    # not substitute for the second occurrence.
    selected_events = {
        str(item["evidenceId"]): item
        for item in preflight.get("evidence", [])
        if isinstance(item, dict) and item.get("classKey") == class_key
    }
    cited_occurrences = {
        str(selected_events[evidence_id]["occurrenceId"])
        for evidence_id in evidence_ids
        if evidence_id in selected_events
        and bool(selected_events[evidence_id].get("countsTowardFrequency"))
    }
    required_occurrences = 1 if explicit_single and not recurring else RECURRING_THRESHOLD
    if status == "PASS" and len(cited_occurrences) < required_occurrences:
        raise StructuralEnforcementError(
            "proposal evidence does not cite enough distinct factual occurrences"
        )

    gaps = _string_list(
        payload.get("gaps", []),
        label="proposal.gaps",
        max_items=32,
        allow_empty=True,
    )
    if status == "INCONCLUSIVE" and not gaps:
        raise StructuralEnforcementError(
            "INCONCLUSIVE proposal requires explicit gaps"
        )

    architecture_required = mechanism["kind"] == "architecture-ownership"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "repositoryRevision": preflight["repositoryRevision"],
        "class": {
            "classKey": class_key,
            "category": selected["category"],
            "recurringErrorClass": recurring_error_class,
            "occurrenceCount": selected["occurrenceCount"],
            "recurring": recurring,
            "explicitSingleOverride": bool(explicit_single and not recurring),
            "sourceCounts": selected["sourceCounts"],
        },
        "evidenceIds": evidence_ids,
        "mechanism": mechanism,
        "candidateScope": scope,
        "proof": proof,
        "gaps": gaps,
        "architectureDecisionRequired": architecture_required,
        "automaticMutationAllowed": False,
        "regressionFixtureRequired": mechanism["kind"] in DETERMINISTIC_MECHANISMS,
        "implementedFixtureVerified": bool(
            require_existing_fixture
            and mechanism["kind"] in DETERMINISTIC_MECHANISMS
        ),
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json_file(path: Path, *, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StructuralEnforcementError(f"cannot read {label}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate recurring structured corrections and validate structural enforcement proposals."
    )
    parser.add_argument("--step", dest="step_id")
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument(
        "--explicit-single",
        action="store_true",
        help="Allow a one-off class only when the human explicitly requested structuralization.",
    )
    parser.add_argument(
        "--implemented",
        action="store_true",
        help="Require the deterministic regression fixture to exist as a regular repository file.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = repo_root()
    try:
        supplied = None
        if args.evidence_file is not None:
            evidence_path = resolve_repo_path(
                root,
                args.evidence_file.as_posix(),
                label="structural enforcement evidence file",
            )
            supplied = _load_json_file(evidence_path, label="evidence file")

        preflight = build_preflight(
            root,
            step_id=args.step_id,
            supplied_evidence=supplied,
        )
        if args.payload_file is None:
            result = preflight
        else:
            payload_path = resolve_repo_path(
                root,
                args.payload_file.as_posix(),
                label="structural enforcement proposal payload",
            )
            payload = _load_json_file(payload_path, label="proposal payload")
            result = validate_proposal(
                root,
                preflight,
                payload,
                explicit_single=args.explicit_single,
                require_existing_fixture=args.implemented,
            )
    except (StructuralEnforcementError, OSError, UnicodeError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reason": str(exc),
        }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result.get("status") == "PASS":
        if "classes" in result:
            recurring = [
                item for item in result["classes"] if item.get("recurring")
            ]
            print(
                "STRUCTURAL ENFORCEMENT: PASS "
                f"({len(recurring)} recurring classes)"
            )
        else:
            print(
                "STRUCTURAL ENFORCEMENT PROPOSAL: PASS "
                f"({result['mechanism']['kind']})"
            )
    else:
        print(
            "STRUCTURAL ENFORCEMENT: "
            f"{result.get('status')} — {result.get('reason', '')}"
        )

    return 0 if result.get("status") in {"PASS", "INCONCLUSIVE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MECHANISM_LADDER",
    "RECURRING_THRESHOLD",
    "StructuralEnforcementError",
    "aggregate_evidence",
    "build_preflight",
    "collect_review_evidence",
    "normalize_supplied_evidence",
    "validate_proposal",
]
