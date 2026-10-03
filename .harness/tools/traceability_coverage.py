#!/usr/bin/env python3
"""Deterministic REQ → STEP → Evidence coverage graph.

Explicit repository IDs are the source of truth. LLM inference is intentionally
not used by this module. Completion/evidence freshness is delegated to the
existing step_completion_proof contract so coverage does not invent a second
definition of current proof.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from document_contract import DocumentError, parse_document
from harness_config import adr_directory, requirements_directory, task_directory
from planning_contract import (
    adr_ids,
    open_questions,
    read_task,
    requirement_ids,
    step_completion_proof,
)

SCHEMA_VERSION = 1

# These STEP types are an explicit deterministic rationale for work that may be
# legitimate without a product REQ. Only generic implementation work is treated
# as orphan when it has neither REQ nor ADR rationale.
NON_PRODUCT_ORPHAN_EXEMPT_TYPES = {
    "bugfix",
    "refactor",
    "research",
    "adr",
    "audit",
    "review",
    "hardening",
    "documentation",
    "release",
}


def _canonical_docs(directory: Path, pattern: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob(pattern)):
        if path.name == "TEMPLATE.md":
            continue
        try:
            doc = parse_document(path)
        except (DocumentError, OSError, UnicodeDecodeError):
            continue
        artifact_id = doc["frontmatter"].get("id")
        if isinstance(artifact_id, str):
            result[artifact_id] = doc
    return result


def _safe_proof(
    root: Path,
    step_id: str,
    provider: Callable[[Path, str], dict[str, Any]],
) -> dict[str, Any]:
    try:
        proof = provider(root, step_id)
    except Exception as exc:
        return {"complete": False, "reasons": [f"completion-proof-error:{exc}"]}
    reasons = proof.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    return {
        "complete": proof.get("complete") is True,
        "reasons": [str(item) for item in reasons],
    }


def build_coverage(
    root: Path,
    *,
    completion_provider: Callable[[Path, str], dict[str, Any]] = step_completion_proof,
) -> dict[str, Any]:
    root = root.resolve()
    reqs = _canonical_docs(requirements_directory(root), "REQ-*.md")
    adrs = _canonical_docs(adr_directory(root), "ADR-*.md")

    tasks: dict[str, dict[str, Any]] = {}
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        step_id = path.stem
        try:
            tasks[step_id] = read_task(root, step_id)
        except Exception:
            continue

    invalid: list[dict[str, str]] = []
    req_to_steps: dict[str, set[str]] = {req_id: set() for req_id in reqs}

    # REQ-side declarations are valid coverage only when STEP itself claims the
    # REQ. A one-sided REQ -> STEP link is a mismatch, not positive coverage.
    for req_id, req in sorted(reqs.items()):
        raw = req["frontmatter"].get("steps")
        declared = raw if isinstance(raw, list) else []
        for step_id in declared:
            if not isinstance(step_id, str):
                continue
            if step_id not in tasks:
                invalid.append({
                    "code": "UNKNOWN_STEP_REFERENCE",
                    "source": req_id,
                    "target": step_id,
                })
                continue
            if req_id not in requirement_ids(tasks[step_id]):
                invalid.append({
                    "code": "REVERSE_TRACEABILITY_MISMATCH",
                    "source": req_id,
                    "target": step_id,
                })
                continue
            req_to_steps[req_id].add(step_id)

    orphan_steps: list[dict[str, Any]] = []
    for step_id, task in sorted(tasks.items()):
        meta = task["frontmatter"]
        linked_reqs = requirement_ids(task)
        linked_adrs = adr_ids(task)

        # STEP-side claim is enough to say the STEP claims the REQ, but missing
        # reverse REQ linkage remains an explicit integrity finding.
        for req_id in linked_reqs:
            if req_id not in reqs:
                invalid.append({
                    "code": "UNKNOWN_REQ_REFERENCE",
                    "source": step_id,
                    "target": req_id,
                })
            else:
                req_to_steps[req_id].add(step_id)
                reverse = reqs[req_id]["frontmatter"].get("steps")
                if not isinstance(reverse, list) or step_id not in reverse:
                    invalid.append({
                        "code": "REVERSE_TRACEABILITY_MISMATCH",
                        "source": step_id,
                        "target": req_id,
                    })

        for adr_id in linked_adrs:
            if adr_id not in adrs:
                invalid.append({
                    "code": "UNKNOWN_ADR_REFERENCE",
                    "source": step_id,
                    "target": adr_id,
                })

        step_type = str(meta.get("type") or "")
        if (
            not linked_reqs
            and not linked_adrs
            and step_type not in NON_PRODUCT_ORPHAN_EXEMPT_TYPES
        ):
            orphan_steps.append({
                "stepId": step_id,
                "type": step_type,
                "reason": "no REQ, ADR or typed non-product rationale",
            })

    oqs = open_questions(root)
    known_targets = {"PROJECT", *reqs.keys(), *adrs.keys(), *tasks.keys()}
    blocking_oqs: list[dict[str, Any]] = []
    for oq in oqs:
        affects = [item for item in (oq.get("affects") or []) if isinstance(item, str)]
        if oq.get("status") == "open":
            blocking_oqs.append({"id": oq.get("id"), "affects": affects})
        for target in affects:
            if target not in known_targets:
                invalid.append({
                    "code": "UNKNOWN_OQ_TARGET",
                    "source": str(oq.get("id")),
                    "target": target,
                })

    proof_by_step = {
        step_id: _safe_proof(root, step_id, completion_provider)
        for step_id in tasks
    }

    requirements: list[dict[str, Any]] = []
    metrics = {
        "requirements": len(reqs),
        "coveredByStep": 0,
        "verified": 0,
        "uncovered": 0,
        "staleEvidence": 0,
        "openBlockingQuestions": len(blocking_oqs),
        "orphanSteps": len(orphan_steps),
        "invalidReferences": len(invalid),
    }

    for req_id, req in sorted(reqs.items()):
        linked = sorted(req_to_steps.get(req_id, set()))
        executable = [
            step_id
            for step_id in linked
            if tasks[step_id]["frontmatter"].get("status") not in {"deferred", "cancelled"}
        ]
        evidence = [
            step_id
            for step_id in executable
            if proof_by_step[step_id]["complete"]
        ]
        stale = [
            {
                "stepId": step_id,
                "reasons": proof_by_step[step_id]["reasons"],
            }
            for step_id in executable
            if tasks[step_id]["frontmatter"].get("status") == "completed"
            and not proof_by_step[step_id]["complete"]
        ]

        # OQ may block the REQ directly, its executable STEP, or an ADR used by
        # such STEP. This mirrors the existing planning notion of relevant OQ.
        executable_adrs = {
            adr_id
            for step_id in executable
            for adr_id in adr_ids(tasks[step_id])
        }
        affected_oq = sorted(
            str(item["id"])
            for item in blocking_oqs
            if "PROJECT" in item["affects"]
            or req_id in item["affects"]
            or any(step_id in item["affects"] for step_id in executable)
            or any(adr_id in item["affects"] for adr_id in executable_adrs)
        )

        if not executable:
            status = "uncovered"
            metrics["uncovered"] += 1
        else:
            metrics["coveredByStep"] += 1
            if affected_oq:
                status = "blocked"
            elif stale:
                status = "stale_evidence"
                metrics["staleEvidence"] += 1
            elif len(evidence) == len(executable):
                status = "verified"
                metrics["verified"] += 1
            else:
                status = "covered"

        requirements.append({
            "id": req_id,
            "priority": req["frontmatter"].get("priority"),
            "status": status,
            "stepCoverage": linked,
            "executableSteps": executable,
            "evidenceCoverage": evidence,
            "staleEvidence": stale,
            "blockingOpenQuestions": affected_oq,
            "releaseRelevant": req["frontmatter"].get("priority") in {"critical", "high"},
        })

    findings = bool(
        metrics["uncovered"]
        or metrics["staleEvidence"]
        or orphan_steps
        or invalid
        or blocking_oqs
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "WARN" if findings else "PASS",
        "metrics": metrics,
        "requirements": requirements,
        "orphanSteps": orphan_steps,
        "invalidReferences": invalid,
        "blockingOpenQuestions": blocking_oqs,
    }
