#!/usr/bin/env python3
"""Deterministic writers for semantic PLAN/REVIEW model outputs.

LLM отвечает только за semantic payload. Этот модуль владеет:
- STEP Markdown/frontmatter mutation для plan draft;
- planning fingerprints и Ready stamp;
- exact repository revision и specialized review gate metadata;
- immutable report timestamp/name/frontmatter;
- canonical Markdown rendering и post-write validation.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from document_contract import (
    atomic_write_text,
    create_durable_report,
    markdown_headings,
    render_document,
)
from execution_status import (
    implementation_baseline_for_step,
    review_expectation_for_step,
    stamp_plan,
)
from harness_config import planning_review_directory, review_directory
from planning_contract import (
    plan_content_hash,
    planning_context_basis,
    read_task,
    step_completion_proof,
    task_path,
    validate_planning_review_report,
)
from review_contract import (
    CATEGORIES,
    SEVERITIES,
    repository_revision,
    validate_review_report,
)
from projection_contract import ProjectionDerivationError, write_projections
from review_gates import required_reviewers
from verification import render_verification_entries, validate_verification_entries


class SemanticArtifactError(ValueError):
    """Invalid semantic payload or failed canonical artifact write."""


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SemanticArtifactError(f"{label} must be an object")
    return value


def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise SemanticArtifactError(
            f"{label} has unsupported keys: " + ", ".join(unexpected)
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticArtifactError(f"{label} must be a non-empty string")
    return value.strip()


def _single_line(value: Any, label: str) -> str:
    result = _text(value, label)
    if "\n" in result or "\r" in result:
        raise SemanticArtifactError(f"{label} must be a single line")
    return result


def _string_array(value: Any, label: str, *, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        raise SemanticArtifactError(f"{label} must be an array")
    result = [
        _single_line(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if required and not result:
        raise SemanticArtifactError(f"{label} must not be empty")
    return result


def _implementation_plan(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SemanticArtifactError("implementationPlan must be a non-empty array")
    steps: list[dict[str, Any]] = []
    allowed = {"title", "actions", "files", "tests", "risks"}
    for index, raw in enumerate(value, 1):
        item = _require_object(raw, f"implementationPlan[{index}]")
        _exact_keys(item, allowed, f"implementationPlan[{index}]")
        steps.append(
            {
                "title": _single_line(
                    item.get("title"),
                    f"implementationPlan[{index}].title",
                ),
                "actions": _string_array(
                    item.get("actions"),
                    f"implementationPlan[{index}].actions",
                    required=True,
                ),
                "files": _string_array(
                    item.get("files"),
                    f"implementationPlan[{index}].files",
                ),
                "tests": _string_array(
                    item.get("tests"),
                    f"implementationPlan[{index}].tests",
                ),
                "risks": _string_array(
                    item.get("risks"),
                    f"implementationPlan[{index}].risks",
                ),
            }
        )
    return steps


def _render_implementation_plan(steps: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(steps, 1):
        lines.extend([f"### {index}. {item['title']}", ""])
        for action in item["actions"]:
            lines.append(f"- {action}")
        for label, key in (
            ("Files", "files"),
            ("Tests", "tests"),
            ("Risks", "risks"),
        ):
            values = item[key]
            if values:
                lines.extend(["", f"**{label}:**"])
                lines.extend(f"- {value}" for value in values)
        lines.append("")
    return "\n".join(lines).strip()


def _replace_h2_section(body: str, title: str, value: str) -> str:
    """Replace one real H2 section while preserving all other body bytes semantically."""
    normalized = body.replace("\r\n", "\n")
    lines = normalized.split("\n")
    headings = [
        (index, heading)
        for index, level, heading in markdown_headings(normalized)
        if level == 2
    ]
    matches = [index for index, heading in headings if heading == title]
    if len(matches) != 1:
        raise SemanticArtifactError(
            f"expected exactly one ## {title} section, found {len(matches)}"
        )
    start = matches[0]
    following = [index for index, _ in headings if index > start]
    end = min(following) if following else len(lines)
    replacement = [f"## {title}", "", value.strip(), ""]
    return "\n".join(lines[:start] + replacement + lines[end:]).strip()


def write_plan_draft(root: Path, step_id: str, payload: Any) -> dict[str, Any]:
    """Persist semantic plan/Verification payload without letting model edit metadata."""
    data = _require_object(payload, "plan payload")
    _exact_keys(data, {"implementationPlan", "verification"}, "plan payload")
    implementation_steps = _implementation_plan(data.get("implementationPlan"))
    implementation_plan = _render_implementation_plan(implementation_steps)
    verification = validate_verification_entries(data.get("verification"))
    verification_text = render_verification_entries(verification)

    task = read_task(root, step_id)
    meta = deepcopy(task["frontmatter"])
    plan = meta.get("plan")
    if not isinstance(plan, dict):
        raise SemanticArtifactError("STEP frontmatter.plan must be an object")
    revision = plan.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SemanticArtifactError("STEP plan.revision must be a non-negative integer")

    body = _replace_h2_section(task["body"], "Verification", verification_text)
    body = _replace_h2_section(body, "Implementation plan", implementation_plan)
    meta["plan"] = {
        "status": "draft",
        "revision": revision,
        "context_basis": None,
        "content_hash": None,
        "reviewed_report": None,
        "planned_at": None,
    }
    atomic_write_text(task["path"], render_document(meta, body))

    # Re-read canonical artifact: return only facts from the persisted version.
    read_task(root, step_id)
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "stepId": step_id,
        "planStatus": "draft",
        "contextBasis": planning_context_basis(root, step_id),
        "planContentHash": plan_content_hash(root, step_id),
        "implementationPlan": implementation_steps,
        "verification": verification,
    }


def _planning_payload(payload: Any) -> tuple[str, list[str], str]:
    data = _require_object(payload, "planning review payload")
    _exact_keys(data, {"verdict", "findings", "rationale"}, "planning review payload")
    verdict = data.get("verdict")
    if verdict not in {"pass", "blocked"}:
        raise SemanticArtifactError("planning review verdict must be pass or blocked")
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        raise SemanticArtifactError("planning review findings must be an array")
    findings = [_text(item, f"findings[{index}]") for index, item in enumerate(raw_findings)]
    if verdict == "pass" and findings:
        raise SemanticArtifactError("PASS planning review must have no findings")
    if verdict == "blocked" and not findings:
        raise SemanticArtifactError("BLOCKED planning review requires findings")
    rationale = _text(data.get("rationale"), "planning review rationale")
    return verdict, findings, rationale


def write_planning_review(root: Path, step_id: str, payload: Any) -> dict[str, Any]:
    """Create validated immutable planning review and stamp matching PASS plan."""
    verdict, findings, rationale = _planning_payload(payload)
    task = read_task(root, step_id)
    plan = task["frontmatter"].get("plan")
    if not isinstance(plan, dict) or plan.get("status") != "draft":
        raise SemanticArtifactError("planning review requires plan.status=draft")

    basis = planning_context_basis(root, step_id)
    plan_hash = plan_content_hash(root, step_id)
    directory = planning_review_directory(root) / step_id

    def content_factory(created_at: str) -> str:
        display = created_at.replace("T", " ")[:16]
        frontmatter = {
            "schema": 1,
            "kind": "planning_review",
            "step_id": step_id,
            "verdict": verdict,
            "reviewer_role": "reviewer",
            "finding_count": len(findings),
            "context_basis": basis,
            "plan_content_hash": plan_hash,
            "created_at": created_at,
        }
        findings_text = (
            "\n".join(f"- {item}" for item in findings)
            if findings
            else "- Material semantic contradictions не обнаружены."
        )
        body = f"""# Planning Review {step_id} — {display}

## Scope checked

- STEP contract
- Semantic dependency contracts
- Linked REQ/Accepted ADR/Open Questions
- Architecture refs
- Proposed Implementation plan
- Verification feasibility

## Findings

{findings_text}

## Verdict rationale

{rationale}
"""
        return render_document(frontmatter, body)

    path, _created_at = create_durable_report(
        "PLAN-REVIEW-",
        directory=directory,
        content_factory=content_factory,
    )
    errors = validate_planning_review_report(
        root, path, expected_step_id=step_id
    )
    if errors:
        path.unlink(missing_ok=True)
        raise SemanticArtifactError(
            "generated planning review failed canonical validation: " + "; ".join(errors)
        )

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "PASS" if verdict == "pass" else "BLOCKED",
        "completionResult": "SUCCESS" if verdict == "pass" else "BLOCKED",
        "stepId": step_id,
        "verdict": verdict,
        "report": path.relative_to(root).as_posix(),
        "contextBasis": basis,
        "planContentHash": plan_hash,
    }
    if verdict == "pass":
        try:
            result["plan"] = stamp_plan(root, step_id)
        except (OSError, ValueError) as exc:
            result["status"] = "BLOCKED"
            result["completionResult"] = "BLOCKED"
            result["reasonCode"] = "PLAN_STAMP_BLOCKED"
            result["message"] = str(exc)
    return result


def _finding(value: Any, index: int) -> dict[str, str]:
    item = _require_object(value, f"findings[{index}]")
    allowed = {
        "title", "severity", "category", "location", "scenario",
        "impact", "fixDirection",
    }
    _exact_keys(item, allowed, f"findings[{index}]")
    result = {key: _text(item.get(key), f"findings[{index}].{key}") for key in allowed}
    if result["severity"] not in SEVERITIES:
        raise SemanticArtifactError(
            f"findings[{index}].severity must be one of {sorted(SEVERITIES)}"
        )
    if result["category"] not in CATEGORIES:
        raise SemanticArtifactError(
            f"findings[{index}].category must be one of {sorted(CATEGORIES)}"
        )
    return result


def _specialized_payload(value: Any) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    data = _require_object(value, "specializedReviews")
    _exact_keys(data, {"security", "tests"}, "specializedReviews")
    result: dict[str, dict[str, str]] = {}
    for kind, raw in data.items():
        item = _require_object(raw, f"specializedReviews.{kind}")
        _exact_keys(item, {"status", "evidence"}, f"specializedReviews.{kind}")
        status = item.get("status")
        if status not in {"pass", "fail", "blocked"}:
            raise SemanticArtifactError(
                f"specializedReviews.{kind}.status must be pass|fail|blocked"
            )
        result[kind] = {
            "status": status,
            "evidence": _text(
                item.get("evidence"), f"specializedReviews.{kind}.evidence"
            ),
        }
    return result


def _step_review_payload(payload: Any) -> dict[str, Any]:
    data = _require_object(payload, "step review payload")
    _exact_keys(
        data,
        {"verdict", "findings", "verificationObservations", "rationale", "specializedReviews"},
        "step review payload",
    )
    verdict = data.get("verdict")
    if verdict not in {"pass", "fail", "blocked"}:
        raise SemanticArtifactError("step review verdict must be pass|fail|blocked")
    raw = data.get("findings")
    if not isinstance(raw, list):
        raise SemanticArtifactError("step review findings must be an array")
    findings = [_finding(item, index) for index, item in enumerate(raw, 1)]
    if verdict == "pass" and findings:
        raise SemanticArtifactError("PASS step review must have no findings")
    if verdict == "fail":
        if not findings:
            raise SemanticArtifactError("FAIL step review requires findings")
        if any(item["category"] == "contract" for item in findings):
            raise SemanticArtifactError("FAIL cannot contain contract findings")
        if not any(item["category"] in {"implementation", "evidence"} for item in findings):
            raise SemanticArtifactError("FAIL requires implementation/evidence finding")
    if verdict == "blocked":
        if not findings:
            raise SemanticArtifactError("BLOCKED step review requires findings")
        if not any(item["category"] in {"contract", "evidence"} for item in findings):
            raise SemanticArtifactError("BLOCKED requires contract/evidence finding")
    return {
        "verdict": verdict,
        "findings": findings,
        "verificationObservations": _text(
            data.get("verificationObservations"), "verificationObservations"
        ),
        "rationale": _text(data.get("rationale"), "rationale"),
        "specializedReviews": _specialized_payload(data.get("specializedReviews")),
    }


def _specialized_meta(
    gate: dict[str, Any], supplied: dict[str, dict[str, str]]
) -> dict[str, Any]:
    required = set(gate["required"])
    missing = sorted(required - set(supplied))
    if missing:
        raise SemanticArtifactError(
            "required specialized review results are missing: " + ", ".join(missing)
        )
    meta: dict[str, Any] = {
        "gate_basis": gate["basis"],
        "required": sorted(required),
        "implementation_baseline": gate.get("implementationBaseline"),
        "surface_mode": gate.get("surfaceMode"),
        "changed_paths_hash": gate.get("changedPathsHash"),
        "baseline_status": gate.get("baselineStatus"),
        "baseline_reason": gate.get("baselineReason"),
    }
    for kind in ("security", "tests"):
        if kind in supplied:
            meta[kind] = supplied[kind]["status"]
            meta[f"{kind}_evidence"] = supplied[kind]["evidence"]
            meta[f"{kind}_reason"] = None
        else:
            meta[kind] = "not_required"
            meta[f"{kind}_evidence"] = None
            reasons = gate.get("reasons", {}).get(kind, [])
            meta[f"{kind}_reason"] = (
                "; ".join(reasons)
                if reasons
                else "not selected by deterministic review gate"
            )
    return meta


def _validate_specialized_verdict(
    verdict: str, specialized: dict[str, Any]
) -> None:
    statuses = [specialized["security"], specialized["tests"]]
    if "blocked" in statuses and verdict != "blocked":
        raise SemanticArtifactError(
            "specialized reviewer BLOCKED requires overall blocked verdict"
        )
    if verdict == "pass" and "fail" in statuses:
        raise SemanticArtifactError(
            "PASS cannot ignore specialized reviewer FAIL"
        )


def _render_findings(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "Material findings отсутствуют."
    chunks: list[str] = []
    for index, item in enumerate(findings, 1):
        chunks.extend(
            [
                f"### F-{index:03d} — {item['title']}",
                "",
                f"**Severity:** {item['severity']}",
                f"**Category:** {item['category']}",
                f"**Location:** {item['location']}",
                f"**Scenario:** {item['scenario']}",
                f"**Impact:** {item['impact']}",
                f"**Fix direction:** {item['fixDirection']}",
                "",
            ]
        )
    return "\n".join(chunks).strip()


def _complete_step_after_pass(root: Path, step_id: str) -> dict[str, Any]:
    """Close STEP only when the full type-specific completion proof is real.

    The immutable PASS review is created first for the exact implementation
    revision. Lifecycle metadata is then changed mechanically. If proof fails,
    the STEP bytes are restored; the PASS report remains durable evidence, but
    execution cannot claim completion.
    """
    path = task_path(root, step_id)
    original = path.read_text(encoding="utf-8")
    task = read_task(root, step_id)
    previous_status = task["frontmatter"].get("status")
    if previous_status == "completed":
        proof = step_completion_proof(root, step_id)
        return {
            "completed": bool(proof["complete"]),
            "previousStatus": previous_status,
            "proof": proof,
            "projections": [],
        }

    meta = deepcopy(task["frontmatter"])
    meta["status"] = "completed"
    atomic_write_text(path, render_document(meta, task["body"]))

    try:
        proof = step_completion_proof(root, step_id)
    except (OSError, ValueError) as exc:
        atomic_write_text(path, original)
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROOF_ERROR",
            "message": str(exc),
        }

    if not proof["complete"]:
        atomic_write_text(path, original)
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROOF_INCOMPLETE",
            "proof": proof,
        }

    try:
        projections = write_projections(root)
    except (ProjectionDerivationError, OSError, ValueError) as exc:
        atomic_write_text(path, original)
        # Best-effort restore of projections to the restored canonical state.
        try:
            write_projections(root)
        except (ProjectionDerivationError, OSError, ValueError):
            pass
        return {
            "completed": False,
            "previousStatus": previous_status,
            "reasonCode": "STEP_COMPLETION_PROJECTION_FAILED",
            "message": str(exc),
            "proof": proof,
        }

    return {
        "completed": True,
        "previousStatus": previous_status,
        "proof": proof,
        "projections": projections,
    }


def write_step_review(root: Path, step_id: str, payload: Any) -> dict[str, Any]:
    """Create one validated immutable implementation review for exact revision."""
    data = _step_review_payload(payload)
    baseline = implementation_baseline_for_step(root, step_id)
    baseline_sha = (
        baseline.get("gitHead")
        if isinstance(baseline, dict)
        else None
    )
    gate = required_reviewers(
        root,
        step_id,
        implementation_baseline=baseline_sha,
    )
    revision = repository_revision(root)
    try:
        expectation = review_expectation_for_step(root, step_id)
    except ValueError as exc:
        raise SemanticArtifactError(
            "STEP REVIEW expectation is ambiguous or missing: " + str(exc)
        ) from exc

    # Verdict принимается только внутри active STEP REVIEW, чья expectation
    # зафиксирована dispatcher-ом до semantic handoff. Без неё writer не может
    # доказать, что reviewer видел именно текущую revision (#112).
    if expectation is None:
        raise SemanticArtifactError(
            f"STEP REVIEW verdict requires an active STEP REVIEW {step_id} "
            "execution with stamped expectation; start it through harness-dispatch.py"
        )
    expected_revision = expectation.get("repositoryRevision")
    expected_gate_basis = expectation.get("gateBasis")
    if revision != expected_revision:
        raise SemanticArtifactError(
            "STEP REVIEW repository revision changed after semantic handoff"
        )
    if gate["basis"] != expected_gate_basis:
        raise SemanticArtifactError(
            "STEP REVIEW gate basis changed after semantic handoff"
        )

    specialized = _specialized_meta(gate, data["specializedReviews"])
    _validate_specialized_verdict(data["verdict"], specialized)
    directory = review_directory(root) / step_id

    def content_factory(created_at: str) -> str:
        display = created_at.replace("T", " ")[:16]
        frontmatter = {
            "schema": 1,
            "kind": "step_review",
            "step_id": step_id,
            "verdict": data["verdict"],
            "reviewer_role": "reviewer",
            "created_at": created_at,
            "reviewed_revision": revision,
            "specialized_reviews": specialized,
        }
        body = f"""# STEP REVIEW {step_id} — {display}

## Scope checked

- Task contract
- REQ/ADR/OQ/architecture refs
- Implementation plan
- Diff/current code
- Tests/verification

## Findings

{_render_findings(data["findings"])}

## Verification observations

{data["verificationObservations"]}

## Verdict rationale

{data["rationale"]}
"""
        return render_document(frontmatter, body)

    path, _created_at = create_durable_report(
        "REVIEW-",
        directory=directory,
        content_factory=content_factory,
    )
    errors = validate_review_report(
        root,
        path,
        require_current_revision=True,
        expected_step_id=step_id,
    )
    if errors:
        path.unlink(missing_ok=True)
        raise SemanticArtifactError(
            "generated STEP review failed canonical validation: " + "; ".join(errors)
        )
    result = {
        "schemaVersion": 1,
        "status": data["verdict"].upper(),
        "completionResult": data["verdict"].upper(),
        "stepId": step_id,
        "verdict": data["verdict"],
        "report": path.relative_to(root).as_posix(),
        "reviewedRevision": revision,
        "specializedReviewGate": {
            "basis": gate["basis"],
            "required": gate["required"],
            "surfaceMode": gate["surfaceMode"],
            "implementationBaseline": gate["implementationBaseline"],
            "changedPathsHash": gate["changedPathsHash"],
        },
    }
    if data["verdict"] == "pass":
        completion = _complete_step_after_pass(root, step_id)
        result["stepCompletion"] = completion
        if not completion.get("completed"):
            result["completionResult"] = "BLOCKED"
            result["reasonCode"] = completion.get(
                "reasonCode",
                "STEP_COMPLETION_PROOF_INCOMPLETE",
            )
    return result


__all__ = [
    "SemanticArtifactError",
    "write_plan_draft",
    "write_planning_review",
    "write_step_review",
]
