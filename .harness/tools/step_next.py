#!/usr/bin/env python3
"""Deterministic resolver for STEP NEXT.

STEP NEXT is a recommendation, not sprint planning. The resolver uses only
repository facts with an explicit stable ordering:

1. resumable STEP execution before new work;
2. in-progress STEP before planned STEP;
3. priority: critical > high > medium > low;
4. larger transitive downstream impact first;
5. more explicit non-none risk flags first (visibility tie-breaker, not severity);
6. canonical roadmap order (STEP id/path order).

The result always exposes the ranking breakdown so UI/agent can explain why a
STEP was recommended without LLM reasoning.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from execution_status import unresolved_executions
from harness_config import task_directory
from planning_contract import (
    adr_ids,
    canonical_adr_path,
    dependency_ids,
    implementation_prerequisite_failures,
    read_task,
    relevant_open_questions,
)
from document_contract import parse_document
from review_contract import latest_review


PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}
ACTIVE_STATUSES = {"planned", "in_progress", "blocked"}
STEP_ID_SEARCH = re.compile(r"\bSTEP-\d{3,}\b")


class StepNextError(ValueError):
    """Canonical STEP state cannot be ranked safely."""


def _title(task: dict[str, Any], step_id: str) -> str:
    prefix = f"# {step_id} — "
    h1 = task.get("h1")
    if isinstance(h1, str) and h1.startswith(prefix):
        return h1[len(prefix) :].strip()
    return ""


def _tasks(root: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order: list[str] = []
    tasks: dict[str, dict[str, Any]] = {}
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        step_id = path.stem
        task = read_task(root, step_id)
        meta = task["frontmatter"]
        if meta.get("id") != step_id:
            raise StepNextError(f"{step_id}: frontmatter id mismatch")
        priority = meta.get("priority")
        if priority not in PRIORITY_RANK:
            raise StepNextError(f"{step_id}: unsupported priority {priority!r}")
        order.append(step_id)
        tasks[step_id] = task
    return order, tasks


def _downstream_impact(
    tasks: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Count transitive active dependents for each STEP."""
    reverse: dict[str, set[str]] = {step_id: set() for step_id in tasks}
    for step_id, task in tasks.items():
        for dependency in dependency_ids(task):
            if dependency in reverse:
                reverse[dependency].add(step_id)

    result: dict[str, int] = {}
    for step_id in tasks:
        seen: set[str] = set()
        stack = list(reverse[step_id])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(reverse.get(current, ()))
        result[step_id] = sum(
            1
            for dependent in seen
            if tasks[dependent]["frontmatter"].get("status") in ACTIVE_STATUSES
        )
    return result


def _risk_flags(task: dict[str, Any]) -> list[str]:
    raw = task["frontmatter"].get("risk_flags")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise StepNextError(
            f"{task['frontmatter'].get('id')}: risk_flags must be a string array"
        )
    return sorted(item for item in raw if item != "none")


def _planning_blockers(root: Path, task: dict[str, Any]) -> list[str]:
    """Known deterministic blockers that make PLAN unable to become Ready."""
    blockers: list[str] = []
    step_id = str(task["frontmatter"].get("id"))

    phase = task["frontmatter"].get("phase")
    if not isinstance(phase, str) or not phase.strip() or phase.upper() == "TBD":
        blockers.append("phase-is-tbd")

    for item in relevant_open_questions(root, task):
        if item.get("status") == "open":
            blockers.append(f"open-question:{item.get('id')}")

    for adr_id in adr_ids(task):
        path = canonical_adr_path(root, adr_id)
        adr = parse_document(path)
        if adr["frontmatter"].get("status") != "accepted":
            blockers.append(f"adr-not-accepted:{adr_id}")

    return blockers


def _fresh_command(
    root: Path,
    step_id: str,
    task: dict[str, Any],
) -> tuple[str | None, list[str]]:
    meta = task["frontmatter"]
    status = meta.get("status")
    if status not in {"planned", "in_progress"}:
        return None, [f"status:{status}"]

    # A current FAIL review is an exact factual request for FIX. PASS with a
    # still non-completed STEP is reconciliation drift rather than new work.
    review = latest_review(root, step_id, require_current_revision=True)
    if review is not None:
        verdict = review.get("verdict")
        if verdict == "FAIL":
            return f"STEP FIX {step_id}", []
        if verdict == "PASS":
            return None, ["current-review-pass-but-step-not-completed"]
        if verdict == "BLOCKED":
            return None, ["current-review-blocked"]

    plan = meta.get("plan")
    plan_status = plan.get("status") if isinstance(plan, dict) else None
    if plan_status != "ready":
        blockers = _planning_blockers(root, task)
        if blockers:
            return None, blockers
        # Dependency completion is intentionally not required for PLAN.
        return f"STEP PLAN {step_id}", []

    failures = implementation_prerequisite_failures(root, step_id)
    if failures:
        return None, failures
    return f"STEP IMPLEMENT {step_id}", []



def resolve_step_action(root: Path, step_id: str) -> dict[str, Any]:
    """Resolve the exact next canonical action for one STEP without ranking."""

    if step_id.isdigit() and len(step_id) >= 3:
        step_id = f"STEP-{step_id}"
    try:
        task = read_task(root, step_id)
        command, reasons = _fresh_command(root, step_id, task)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {
            "status": "BLOCKED",
            "reasonCode": "STEP_ACTION_STATE_INVALID",
            "stepId": step_id,
            "message": str(exc),
        }

    meta = task["frontmatter"]
    if command is None:
        return {
            "status": "BLOCKED",
            "reasonCode": "STEP_ACTION_BLOCKED",
            "stepId": step_id,
            "stepType": meta.get("type"),
            "lifecycleStatus": meta.get("status"),
            "reasons": reasons,
        }
    return {
        "status": "PASS",
        "stepId": step_id,
        "stepType": meta.get("type"),
        "lifecycleStatus": meta.get("status"),
        "command": command,
    }


def _step_id_from_execution(item: dict[str, Any]) -> str | None:
    for value in (item.get("command"), item.get("rootCommand")):
        if isinstance(value, str):
            match = STEP_ID_SEARCH.search(value)
            if match:
                return match.group(0)
    return None


def _ranking(
    *,
    source: str,
    lifecycle: str,
    task: dict[str, Any],
    downstream: int,
    roadmap_index: int,
) -> dict[str, Any]:
    priority = str(task["frontmatter"].get("priority"))
    risks = _risk_flags(task)
    source_rank = 0 if source == "execution" else 1
    if source == "execution":
        lifecycle_rank = 0 if lifecycle == "RESUME" else 1
    else:
        lifecycle_rank = 0 if lifecycle == "in_progress" else 1
    return {
        "sourceRank": source_rank,
        "lifecycleRank": lifecycle_rank,
        "priorityRank": PRIORITY_RANK[priority],
        "priority": priority,
        "downstreamImpact": downstream,
        "riskFlagCount": len(risks),
        "riskFlags": risks,
        "roadmapIndex": roadmap_index,
        "sortKey": [
            source_rank,
            lifecycle_rank,
            PRIORITY_RANK[priority],
            -downstream,
            -len(risks),
            roadmap_index,
        ],
    }


def _candidate(
    *,
    step_id: str,
    task: dict[str, Any],
    command: str,
    source: str,
    lifecycle: str,
    downstream: int,
    roadmap_index: int,
    execution_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "stepId": step_id,
        "title": _title(task, step_id),
        "command": command,
        "source": source,
        "status": task["frontmatter"].get("status"),
        "ranking": _ranking(
            source=source,
            lifecycle=lifecycle,
            task=task,
            downstream=downstream,
            roadmap_index=roadmap_index,
        ),
    }
    if execution_id is not None:
        result["executionId"] = execution_id
        result["resolverStatus"] = lifecycle
    return result


def resolve_step_next(root: Path) -> dict[str, Any]:
    """Return one exact recommendation plus compact ranked alternatives."""
    try:
        order, tasks = _tasks(root)
        roadmap_index = {step_id: index for index, step_id in enumerate(order)}
        downstream = _downstream_impact(tasks)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": "STEP_NEXT_STATE_INVALID",
            "message": str(exc),
        }

    candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    # Existing STEP work always outranks starting another STEP.
    try:
        executions = unresolved_executions(root)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": "STEP_NEXT_EXECUTION_STATE_INVALID",
            "message": str(exc),
        }

    seen_execution_steps: set[str] = set()
    for item in executions:
        if item.get("status") not in {"RESUME", "NEXT"}:
            continue
        command = item.get("command")
        if not isinstance(command, str) or not command.startswith("STEP "):
            continue
        step_id = _step_id_from_execution(item)
        if step_id is None or step_id not in tasks:
            continue
        # Multiple local records for one STEP should not multiply candidates.
        if step_id in seen_execution_steps:
            continue
        seen_execution_steps.add(step_id)
        candidates.append(
            _candidate(
                step_id=step_id,
                task=tasks[step_id],
                command=command,
                source="execution",
                lifecycle=str(item["status"]),
                downstream=downstream[step_id],
                roadmap_index=roadmap_index[step_id],
                execution_id=str(item.get("executionId") or ""),
            )
        )

    # Fresh candidates are still useful as alternatives, but cannot beat
    # resumable work because sourceRank is lower priority.
    for step_id in order:
        if step_id in seen_execution_steps:
            continue
        task = tasks[step_id]
        try:
            command, reasons = _fresh_command(root, step_id, task)
        except (OSError, ValueError) as exc:
            blocked.append({"stepId": step_id, "reasons": [str(exc)]})
            continue
        if command is None:
            blocked.append({"stepId": step_id, "reasons": reasons})
            continue
        candidates.append(
            _candidate(
                step_id=step_id,
                task=task,
                command=command,
                source="fresh",
                lifecycle=str(task["frontmatter"].get("status")),
                downstream=downstream[step_id],
                roadmap_index=roadmap_index[step_id],
            )
        )

    # Deduplicate exact command if same STEP is both execution + fresh.
    by_command: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        existing = by_command.get(candidate["command"])
        if (
            existing is None
            or tuple(candidate["ranking"]["sortKey"])
            < tuple(existing["ranking"]["sortKey"])
        ):
            by_command[candidate["command"]] = candidate
    ranked = sorted(
        by_command.values(),
        key=lambda item: tuple(item["ranking"]["sortKey"]),
    )

    if not ranked:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": "NO_EXECUTABLE_STEP",
            "eligibleCount": 0,
            "blockedCount": len(blocked),
            "blockers": blocked[:10],
        }

    selected = ranked[0]
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "reasonCode": (
            "RESUME_STEP_EXECUTION"
            if selected["source"] == "execution"
            else "STEP_RECOMMENDATION"
        ),
        "command": selected["command"],
        "selected": selected,
        "eligibleCount": len(ranked),
        "blockedCount": len(blocked),
        "alternatives": ranked[1:5],
        "rankingPolicy": [
            "resume-existing-execution",
            "in-progress-before-planned",
            "priority-critical-high-medium-low",
            "larger-transitive-downstream-impact",
            "risk-flag-count-for-visibility-only",
            "canonical-roadmap-order",
        ],
    }


__all__ = ["StepNextError", "resolve_step_next"]
