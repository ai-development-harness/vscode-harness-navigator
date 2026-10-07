#!/usr/bin/env python3
"""Provider-neutral High-Rigor protocol for Arena and Interrogate.

The Harness control plane decides *whether* high-rigor is applicable and validates
trace/budget/independence invariants. Runtime adapters decide *how* to spawn the
requested seats. No provider/model slug is part of canonical Harness semantics.

All fan-out input/output files are transient and must live under
.harness/local/high-rigor/. This tool never launches models itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from harness_config import ConfigError, high_rigor_config, resolve_repo_path
from planning_contract import read_task
from review_contract import repository_revision


SCHEMA_VERSION = 1
MODES = {"arena", "interrogate"}
PHASES = {"plan", "review", "architecture", "audit"}
POLICIES = {"disabled", "explicit", "risk"}
PARTICIPANT_STATUSES = {"completed", "failed", "unsupported"}
ARENA_ROLES = {"candidate", "judge"}
INTERROGATE_ROLES = {"reviewer"}
RUN_ID_RE = re.compile(r"HR-[A-Za-z0-9][A-Za-z0-9._-]{2,80}")

RISK_FLAGS = {
    "security-sensitive",
    "data-migration",
    "destructive",
    "public-api",
    "architecture",
    "concurrency",
    "external-integration",
    "performance-critical",
    "release-critical",
}
ARENA_RISK_FLAGS = RISK_FLAGS
INTERROGATE_RISK_FLAGS = RISK_FLAGS

LOCAL_ROOT = Path(".harness/local/high-rigor")


class HighRigorError(ValueError):
    """Activation/trace cannot be trusted; caller must fail closed."""


def _text(value: object, *, label: str, max_chars: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HighRigorError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\r" in result:
        result = result.replace("\r\n", "\n").replace("\r", "\n")
    if len(result) > max_chars:
        raise HighRigorError(f"{label} exceeds {max_chars} characters")
    return result


def _single_line(value: object, *, label: str, max_chars: int = 500) -> str:
    result = _text(value, label=label, max_chars=max_chars)
    if "\n" in result:
        raise HighRigorError(f"{label} must be a single line")
    return result


def _string_list(
    value: object,
    *,
    label: str,
    max_items: int,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise HighRigorError(f"{label} must be an array")
    if not allow_empty and not value:
        raise HighRigorError(f"{label} must not be empty")
    if len(value) > max_items:
        raise HighRigorError(f"{label} exceeds {max_items} items")
    result = [
        _single_line(item, label=f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise HighRigorError(f"{label} must not contain duplicates")
    return result


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _local_path(root: Path, value: object, *, label: str) -> tuple[Path, str]:
    rel = _single_line(value, label=label, max_chars=1000)
    raw = Path(rel)
    if raw.is_absolute() or ".." in raw.parts:
        raise HighRigorError(f"{label} must be repository-relative")
    normalized = raw.as_posix()
    prefix = LOCAL_ROOT.as_posix() + "/"
    if not normalized.startswith(prefix):
        raise HighRigorError(
            f"{label} must live under {LOCAL_ROOT.as_posix()}/"
        )
    try:
        path = resolve_repo_path(root, normalized, label=label)
    except ConfigError as exc:
        raise HighRigorError(str(exc)) from exc

    # Lexical path components are part of the trust boundary. A symlinked
    # parent could otherwise make a local-looking trace read another file.
    current = root.resolve()
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise HighRigorError(
                f"{label} must not contain symlink components: {normalized}"
            )
    return path, normalized


def _local_file(root: Path, value: object, *, label: str) -> dict[str, Any]:
    path, normalized = _local_path(root, value, label=label)
    if not path.is_file() or path.is_symlink():
        raise HighRigorError(f"{label} must be a regular file: {normalized}")
    try:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise HighRigorError(f"{label} must be readable UTF-8: {exc}") from exc
    return {
        "path": normalized,
        "sha256": _sha256_bytes(raw_bytes),
        "chars": len(text),
        "bytes": len(raw_bytes),
    }


def _task_facts(root: Path, step_id: str | None) -> dict[str, Any]:
    if step_id is None:
        return {
            "stepId": None,
            "stepType": None,
            "riskFlags": [],
        }
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    raw_flags = meta.get("risk_flags")
    if (
        not isinstance(raw_flags, list)
        or not raw_flags
        or any(not isinstance(item, str) or not item for item in raw_flags)
    ):
        raise HighRigorError("STEP risk_flags are malformed")
    unknown_flags = sorted(set(raw_flags) - (RISK_FLAGS | {"none"}))
    if unknown_flags:
        raise HighRigorError(
            "STEP risk_flags contain unsupported values: " + ", ".join(unknown_flags)
        )
    if "none" in raw_flags and len(set(raw_flags)) > 1:
        raise HighRigorError("STEP risk_flags cannot combine none with material risks")
    return {
        "stepId": step_id,
        "stepType": meta.get("type"),
        "riskFlags": sorted(set(raw_flags) - {"none"}),
    }


def activation(
    root: Path,
    *,
    mode: str,
    phase: str,
    step_id: str | None = None,
    requested: bool = False,
) -> dict[str, Any]:
    if mode not in MODES:
        raise HighRigorError(f"mode must be one of {sorted(MODES)}")
    if phase not in PHASES:
        raise HighRigorError(f"phase must be one of {sorted(PHASES)}")

    config = high_rigor_config(root)
    policy = str(config[mode])
    if policy not in POLICIES:
        raise HighRigorError(f"invalid high-rigor policy for {mode}: {policy}")

    facts = _task_facts(root, step_id)
    flags = set(facts["riskFlags"])
    matching = sorted(
        flags.intersection(
            ARENA_RISK_FLAGS if mode == "arena" else INTERROGATE_RISK_FLAGS
        )
    )

    # Mode/phase compatibility is semantic protocol, not provider behavior.
    phase_allowed = (
        mode == "arena" and phase in {"plan", "architecture"}
    ) or (
        mode == "interrogate" and phase in {"review", "audit"}
    )
    if not phase_allowed:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "SKIP",
            "mode": mode,
            "phase": phase,
            "policy": policy,
            **facts,
            "matchingRiskFlags": matching,
            "reasonCode": "MODE_PHASE_NOT_APPLICABLE",
            "requested": bool(requested),
            "config": config,
        }

    if policy == "disabled":
        status = "SKIP"
        reason = "POLICY_DISABLED"
    elif requested:
        status = "RUN"
        reason = "EXPLICIT_REQUEST"
    elif policy == "risk" and matching:
        status = "RUN"
        reason = "RISK_CONDITION"
    else:
        status = "SKIP"
        reason = (
            "EXPLICIT_REQUEST_REQUIRED"
            if policy == "explicit"
            else "RISK_CONDITION_NOT_MET"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "mode": mode,
        "phase": phase,
        "policy": policy,
        **facts,
        "matchingRiskFlags": matching,
        "reasonCode": reason,
        "requested": bool(requested),
        "repositoryRevision": repository_revision(root),
        "config": config,
    }


def _participant(
    root: Path,
    raw: object,
    *,
    index: int,
    mode: str,
    candidate_input_hash: str | None,
    rubric_hash: str,
    max_input_chars: int,
    max_output_chars: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HighRigorError(f"participants[{index}] must be an object")
    allowed = {
        "seatId",
        "role",
        "runtimeId",
        "sessionExecutionId",
        "requestedModel",
        "actualModel",
        "fallbackReason",
        "status",
        "inputFile",
        "rubricFile",
        "outputFile",
        "error",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise HighRigorError(
            f"participants[{index}] unsupported keys: " + ", ".join(unknown)
        )

    seat_id = _single_line(
        raw.get("seatId"), label=f"participants[{index}].seatId"
    )
    role = _single_line(
        raw.get("role"), label=f"participants[{index}].role"
    )
    expected_roles = ARENA_ROLES if mode == "arena" else INTERROGATE_ROLES
    if role not in expected_roles:
        raise HighRigorError(
            f"participants[{index}].role must be one of {sorted(expected_roles)}"
        )

    runtime_id = _single_line(
        raw.get("runtimeId"), label=f"participants[{index}].runtimeId"
    )
    raw_session_id = raw.get("sessionExecutionId")
    session_id = (
        None
        if raw_session_id is None
        else _single_line(
            raw_session_id,
            label=f"participants[{index}].sessionExecutionId",
        )
    )
    requested_model = _single_line(
        raw.get("requestedModel"),
        label=f"participants[{index}].requestedModel",
    )
    actual_model = raw.get("actualModel")
    if actual_model is not None:
        actual_model = _single_line(
            actual_model,
            label=f"participants[{index}].actualModel",
        )

    status = _single_line(
        raw.get("status"), label=f"participants[{index}].status"
    )
    if status not in PARTICIPANT_STATUSES:
        raise HighRigorError(
            f"participants[{index}].status must be one of "
            f"{sorted(PARTICIPANT_STATUSES)}"
        )

    input_info = _local_file(
        root,
        raw.get("inputFile"),
        label=f"participants[{index}].inputFile",
    )
    rubric_info = _local_file(
        root,
        raw.get("rubricFile"),
        label=f"participants[{index}].rubricFile",
    )
    if rubric_info["sha256"] != rubric_hash:
        raise HighRigorError(
            f"participants[{index}] did not receive the exact shared rubric"
        )

    if role in {"candidate", "reviewer"}:
        if candidate_input_hash is None:
            raise HighRigorError("shared participant input hash is unavailable")
        if input_info["sha256"] != candidate_input_hash:
            raise HighRigorError(
                f"participants[{index}] did not receive the exact shared input"
            )

    if input_info["chars"] + rubric_info["chars"] > max_input_chars:
        raise HighRigorError(
            f"participants[{index}] input exceeds per-seat context budget"
        )

    fallback_reason = raw.get("fallbackReason")
    if requested_model != actual_model:
        if status == "completed":
            fallback_reason = _single_line(
                fallback_reason,
                label=f"participants[{index}].fallbackReason",
                max_chars=1200,
            )
    elif fallback_reason is not None:
        fallback_reason = _single_line(
            fallback_reason,
            label=f"participants[{index}].fallbackReason",
            max_chars=1200,
        )

    output_info: dict[str, Any] | None = None
    error: str | None = None
    if status == "completed":
        if session_id is None:
            raise HighRigorError(
                f"participants[{index}] completed seat requires sessionExecutionId"
            )
        if actual_model is None:
            raise HighRigorError(
                f"participants[{index}] completed seat requires actualModel"
            )
        output_info = _local_file(
            root,
            raw.get("outputFile"),
            label=f"participants[{index}].outputFile",
        )
        if output_info["chars"] > max_output_chars:
            raise HighRigorError(
                f"participants[{index}] output exceeds per-seat output budget"
            )
        if raw.get("error") is not None:
            raise HighRigorError(
                f"participants[{index}] completed seat cannot contain error"
            )
    else:
        if raw.get("outputFile") is not None:
            raise HighRigorError(
                f"participants[{index}] non-completed seat cannot claim outputFile"
            )
        error = _single_line(
            raw.get("error"),
            label=f"participants[{index}].error",
            max_chars=1200,
        )

    return {
        "seatId": seat_id,
        "role": role,
        "runtimeId": runtime_id,
        "sessionExecutionId": session_id,
        "requestedModel": requested_model,
        "actualModel": actual_model,
        "fallbackReason": fallback_reason,
        "status": status,
        "input": input_info,
        "rubric": rubric_info,
        "output": output_info,
        "error": error,
    }


def _arena_synthesis(
    root: Path,
    value: object,
    *,
    completed_candidates: set[str],
    completed_judges: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HighRigorError("arena synthesis must be an object")
    allowed = {
        "baseSeatId",
        "judgeSeatId",
        "synthesisOutputFile",
        "grafts",
        "disagreements",
        "verificationRefs",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HighRigorError(
            "arena synthesis unsupported keys: " + ", ".join(unknown)
        )
    base = _single_line(value.get("baseSeatId"), label="arena.baseSeatId")
    judge = _single_line(value.get("judgeSeatId"), label="arena.judgeSeatId")
    if base not in completed_candidates:
        raise HighRigorError("arena.baseSeatId must be a completed candidate")
    if judge not in completed_judges:
        raise HighRigorError("arena.judgeSeatId must be a completed judge")
    if base == judge:
        raise HighRigorError("arena judge must be independent from candidate seats")

    synthesis_output = _local_file(
        root,
        value.get("synthesisOutputFile"),
        label="arena.synthesisOutputFile",
    )

    grafts_raw = value.get("grafts")
    if not isinstance(grafts_raw, list):
        raise HighRigorError("arena.grafts must be an array")
    grafts: list[dict[str, str]] = []
    for index, item in enumerate(grafts_raw):
        if not isinstance(item, dict) or set(item) != {"fromSeatId", "summary"}:
            raise HighRigorError(
                f"arena.grafts[{index}] must contain fromSeatId, summary"
            )
        seat = _single_line(
            item.get("fromSeatId"), label=f"arena.grafts[{index}].fromSeatId"
        )
        if seat not in completed_candidates:
            raise HighRigorError(
                f"arena.grafts[{index}] source must be a completed candidate"
            )
        grafts.append(
            {
                "fromSeatId": seat,
                "summary": _single_line(
                    item.get("summary"),
                    label=f"arena.grafts[{index}].summary",
                    max_chars=1200,
                ),
            }
        )

    disagreements = _string_list(
        value.get("disagreements", []),
        label="arena.disagreements",
        max_items=32,
        allow_empty=True,
    )
    verification_refs = _string_list(
        value.get("verificationRefs"),
        label="arena.verificationRefs",
        max_items=32,
    )
    return {
        "baseSeatId": base,
        "judgeSeatId": judge,
        "synthesisOutput": synthesis_output,
        "grafts": grafts,
        "disagreements": disagreements,
        "verificationRefs": verification_refs,
    }


def _interrogate_synthesis(
    root: Path,
    value: object,
    *,
    completed_reviewers: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HighRigorError("interrogate synthesis must be an object")
    allowed = {
        "leadOutputFile",
        "consensus",
        "disagreements",
        "leadJudgment",
        "deterministicGateRefs",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HighRigorError(
            "interrogate synthesis unsupported keys: " + ", ".join(unknown)
        )

    lead_output = _local_file(
        root,
        value.get("leadOutputFile"),
        label="interrogate.leadOutputFile",
    )

    def groups(field: str, *, min_seats: int) -> list[dict[str, Any]]:
        raw_groups = value.get(field, [])
        if not isinstance(raw_groups, list):
            raise HighRigorError(f"interrogate.{field} must be an array")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(raw_groups):
            if (
                not isinstance(item, dict)
                or set(item) != {"finding", "seatIds"}
            ):
                raise HighRigorError(
                    f"interrogate.{field}[{index}] must contain finding, seatIds"
                )
            seat_ids = _string_list(
                item.get("seatIds"),
                label=f"interrogate.{field}[{index}].seatIds",
                max_items=16,
            )
            unknown_seats = sorted(set(seat_ids) - completed_reviewers)
            if unknown_seats:
                raise HighRigorError(
                    f"interrogate.{field}[{index}] references incomplete/unknown "
                    f"reviewers: {unknown_seats}"
                )
            if len(seat_ids) < min_seats:
                raise HighRigorError(
                    f"interrogate.{field}[{index}] requires at least "
                    f"{min_seats} reviewer seats"
                )
            result.append(
                {
                    "finding": _single_line(
                        item.get("finding"),
                        label=f"interrogate.{field}[{index}].finding",
                        max_chars=1600,
                    ),
                    "seatIds": seat_ids,
                }
            )
        return result

    consensus = groups("consensus", min_seats=2)
    disagreements = groups("disagreements", min_seats=2)

    lead_judgment = value.get("leadJudgment")
    if not isinstance(lead_judgment, dict):
        raise HighRigorError("interrogate.leadJudgment must be an object")
    expected_buckets = {"actOn", "consider", "noted", "dismissed"}
    if set(lead_judgment) != expected_buckets:
        raise HighRigorError(
            "interrogate.leadJudgment keys must be actOn, consider, noted, dismissed"
        )
    normalized_judgment = {
        key: _string_list(
            lead_judgment[key],
            label=f"interrogate.leadJudgment.{key}",
            max_items=64,
            allow_empty=True,
        )
        for key in sorted(expected_buckets)
    }

    gate_refs = _string_list(
        value.get("deterministicGateRefs"),
        label="interrogate.deterministicGateRefs",
        max_items=32,
    )
    return {
        "leadOutput": lead_output,
        "consensus": consensus,
        "disagreements": disagreements,
        "leadJudgment": normalized_judgment,
        "deterministicGateRefs": gate_refs,
    }


def validate_trace(
    root: Path,
    payload: object,
    *,
    requested: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HighRigorError("trace payload must be an object")
    allowed = {
        "schemaVersion",
        "runId",
        "mode",
        "phase",
        "stepId",
        "sharedInputFile",
        "rubricFile",
        "participants",
        "synthesis",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HighRigorError(
            "trace payload unsupported keys: " + ", ".join(unknown)
        )
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise HighRigorError(f"schemaVersion must be {SCHEMA_VERSION}")

    run_id = _single_line(payload.get("runId"), label="runId")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise HighRigorError("runId must match HR-<stable-id>")

    mode = _single_line(payload.get("mode"), label="mode")
    phase = _single_line(payload.get("phase"), label="phase")
    step_id = payload.get("stepId")
    if step_id is not None:
        step_id = _single_line(step_id, label="stepId")

    active = activation(
        root,
        mode=mode,
        phase=phase,
        step_id=step_id,
        requested=requested,
    )
    if active["status"] != "RUN":
        raise HighRigorError(
            f"high-rigor trace is not authorized: {active['reasonCode']}"
        )
    config = active["config"]

    shared_input = _local_file(
        root,
        payload.get("sharedInputFile"),
        label="sharedInputFile",
    )
    rubric = _local_file(
        root,
        payload.get("rubricFile"),
        label="rubricFile",
    )
    if shared_input["chars"] + rubric["chars"] > int(config["maxInputCharsPerSeat"]):
        raise HighRigorError("shared input + rubric exceeds per-seat context budget")

    raw_participants = payload.get("participants")
    if not isinstance(raw_participants, list) or not raw_participants:
        raise HighRigorError("participants must be a non-empty array")
    if len(raw_participants) > int(config["maxSeats"]) + (1 if mode == "arena" else 0):
        raise HighRigorError("participant count exceeds configured high-rigor seats")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_participants):
        normalized.append(
            _participant(
                root,
                item,
                index=index,
                mode=mode,
                candidate_input_hash=shared_input["sha256"],
                rubric_hash=rubric["sha256"],
                max_input_chars=int(config["maxInputCharsPerSeat"]),
                max_output_chars=int(config["maxOutputCharsPerSeat"]),
            )
        )

    seat_ids = [str(item["seatId"]) for item in normalized]
    if len(seat_ids) != len(set(seat_ids)):
        raise HighRigorError("participant seatId values must be unique")

    run_prefix = f"{LOCAL_ROOT.as_posix()}/{run_id}/"
    traced_files: list[tuple[str, str]] = [
        ("sharedInputFile", str(shared_input["path"])),
        ("rubricFile", str(rubric["path"])),
    ]
    for item in normalized:
        traced_files.append(
            (f"{item['seatId']}.input", str(item["input"]["path"]))
        )
        traced_files.append(
            (f"{item['seatId']}.rubric", str(item["rubric"]["path"]))
        )
        if isinstance(item.get("output"), dict):
            traced_files.append(
                (f"{item['seatId']}.output", str(item["output"]["path"]))
            )
    for label, rel in traced_files:
        if not rel.startswith(run_prefix):
            raise HighRigorError(
                f"{label} must stay inside the current run directory {run_prefix}"
            )

    completed = [item for item in normalized if item["status"] == "completed"]
    execution_ids = [str(item["sessionExecutionId"]) for item in completed]
    if len(execution_ids) != len(set(execution_ids)):
        raise HighRigorError(
            "completed high-rigor seats require independent sessionExecutionId values"
        )

    output_paths = [
        str(item["output"]["path"])
        for item in completed
        if isinstance(item.get("output"), dict)
    ]
    if len(output_paths) != len(set(output_paths)):
        raise HighRigorError(
            "completed high-rigor seats must write separate output files"
        )
    protected_inputs = {
        str(shared_input["path"]),
        str(rubric["path"]),
        *[
            str(item["input"]["path"])
            for item in normalized
        ],
        *[
            str(item["rubric"]["path"])
            for item in normalized
        ],
    }
    if set(output_paths).intersection(protected_inputs):
        raise HighRigorError(
            "participant output must not overwrite shared/rubric/seat input files"
        )

    total_input_chars = sum(
        int(item["input"]["chars"]) + int(item["rubric"]["chars"])
        for item in normalized
    )
    total_output_chars = sum(
        int(item["output"]["chars"])
        for item in completed
        if isinstance(item.get("output"), dict)
    )
    total_chars = total_input_chars + total_output_chars
    if total_chars > int(config["maxTotalChars"]):
        raise HighRigorError(
            f"high-rigor trace exceeds total char budget: "
            f"{total_chars}>{config['maxTotalChars']}"
        )

    degradation: list[str] = []
    fallback_seats = [
        item["seatId"]
        for item in completed
        if item["requestedModel"] != item["actualModel"]
    ]
    failed_seats = [
        item["seatId"]
        for item in normalized
        if item["status"] == "failed"
    ]
    unsupported_seats = [
        item["seatId"]
        for item in normalized
        if item["status"] == "unsupported"
    ]
    if fallback_seats:
        degradation.append("MODEL_FALLBACK")
    if failed_seats:
        degradation.append("SEAT_FAILED")
    if unsupported_seats:
        degradation.append("SEAT_UNSUPPORTED")

    if mode == "arena":
        completed_candidates = {
            str(item["seatId"])
            for item in completed
            if item["role"] == "candidate"
        }
        completed_judges = {
            str(item["seatId"])
            for item in completed
            if item["role"] == "judge"
        }
        requested_candidates = [
            item for item in normalized if item["role"] == "candidate"
        ]
        if len(requested_candidates) != int(config["seats"]):
            raise HighRigorError(
                f"arena requires exactly configured candidate seats: {config['seats']}"
            )
        if len(completed_candidates) < 2:
            degradation.append("INSUFFICIENT_INDEPENDENT_CANDIDATES")
        if len(completed_judges) != 1:
            degradation.append("INDEPENDENT_JUDGE_UNAVAILABLE")
        requested_judges = [
            item for item in normalized if item["role"] == "judge"
        ]
        if len(requested_judges) != 1:
            raise HighRigorError("arena requires exactly one judge seat")
        synthesis = _arena_synthesis(
            root,
            payload.get("synthesis"),
            completed_candidates=completed_candidates,
            completed_judges=completed_judges,
        ) if completed_candidates and completed_judges else None
    else:
        reviewers = [item for item in normalized if item["role"] == "reviewer"]
        if len(reviewers) != int(config["seats"]):
            raise HighRigorError(
                f"interrogate requires exactly configured reviewer seats: {config['seats']}"
            )
        completed_reviewers = {
            str(item["seatId"])
            for item in completed
            if item["role"] == "reviewer"
        }
        if len(completed_reviewers) < 2:
            degradation.append("INSUFFICIENT_INDEPENDENT_REVIEWERS")
        synthesis = _interrogate_synthesis(
            root,
            payload.get("synthesis"),
            completed_reviewers=completed_reviewers,
        ) if completed_reviewers else None

    # Synthesis cannot silently disappear in an otherwise successful fan-out.
    if not degradation and synthesis is None:
        raise HighRigorError("successful high-rigor run requires synthesis")

    synthesis_chars = 0
    synthesis_path: str | None = None
    if isinstance(synthesis, dict):
        if mode == "arena":
            synthesis_output = synthesis.get("synthesisOutput")
        else:
            synthesis_output = synthesis.get("leadOutput")
        if isinstance(synthesis_output, dict):
            synthesis_chars = int(synthesis_output.get("chars") or 0)
            synthesis_path = str(synthesis_output.get("path"))
            if not synthesis_path.startswith(run_prefix):
                raise HighRigorError(
                    "lead/synthesis output must stay inside the current run directory"
                )
            if synthesis_path in protected_inputs or synthesis_path in output_paths:
                raise HighRigorError(
                    "lead/synthesis output must use a separate output file"
                )

    if synthesis_chars > int(config["maxOutputCharsPerSeat"]):
        raise HighRigorError(
            "lead/synthesis output exceeds configured output budget"
        )
    total_output_chars += synthesis_chars
    total_chars = total_input_chars + total_output_chars
    if total_chars > int(config["maxTotalChars"]):
        raise HighRigorError(
            f"high-rigor trace exceeds total char budget after synthesis: "
            f"{total_chars}>{config['maxTotalChars']}"
        )

    result_status = "PASS" if not degradation else "DEGRADED"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": result_status,
        "runId": run_id,
        "mode": mode,
        "phase": phase,
        "stepId": step_id,
        "activation": {
            "policy": active["policy"],
            "reasonCode": active["reasonCode"],
            "requested": active["requested"],
            "matchingRiskFlags": active["matchingRiskFlags"],
        },
        "repositoryRevision": active["repositoryRevision"],
        "sharedInput": shared_input,
        "rubric": rubric,
        "participants": normalized,
        "synthesis": synthesis,
        "degradationReasons": sorted(set(degradation)),
        "metrics": {
            "configuredSeats": int(config["seats"]),
            "completedSeats": len(completed),
            "distinctActualModels": len(
                {
                    str(item["actualModel"])
                    for item in completed
                    if item["actualModel"] is not None
                }
            ),
            "totalInputChars": total_input_chars,
            "totalOutputChars": total_output_chars,
            "totalChars": total_chars,
            "maxTotalChars": int(config["maxTotalChars"]),
        },
        "deterministicGatesReplaced": False,
    }


def _load_json(root: Path, value: Path, *, label: str) -> object:
    try:
        path, _ = _local_path(root, value.as_posix(), label=label)
        if not path.is_file() or path.is_symlink():
            raise HighRigorError(f"{label} must be a regular local file")
        return json.loads(path.read_text(encoding="utf-8"))
    except (ConfigError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HighRigorError(f"cannot read {label}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Authorize and validate provider-neutral high-rigor Arena/Interrogate runs."
    )
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--step")
    parser.add_argument("--requested", action="store_true")
    parser.add_argument("--trace-file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        if args.trace_file is None:
            result = activation(
                root,
                mode=args.mode,
                phase=args.phase,
                step_id=args.step,
                requested=args.requested,
            )
        else:
            payload = _load_json(
                root,
                args.trace_file,
                label="high-rigor trace file",
            )
            result = validate_trace(
                root,
                payload,
                requested=args.requested,
            )
    except (HighRigorError, ConfigError, OSError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reason": str(exc),
        }

    print(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.as_json
        else json.dumps(result, ensure_ascii=False)
    )
    return 0 if result.get("status") in {"PASS", "SKIP", "DEGRADED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HighRigorError",
    "activation",
    "validate_trace",
]
