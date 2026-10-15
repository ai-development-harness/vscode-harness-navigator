#!/usr/bin/env python3
"""Deterministic impact propagation for planning-contract evolution.

The authoritative freshness decision remains planning_context_basis. This module
only explains that result with component fingerprints from the same schema-v4
planning snapshot and projects affected STEP surface. It never rewrites
downstream artifacts and never promotes code to source of truth.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import re
from typing import Any

from document_contract import parse_document
from harness_config import (
    adr_directory,
    open_questions_directory,
    principles_directory,
    requirements_directory,
    task_directory,
)
from planning_contract import (
    adr_ids,
    architecture_refs,
    canonical_adr_path,
    dependency_ids,
    planning_context_basis,
    planning_context_components,
    read_task,
    relevant_open_questions,
    requirement_ids,
)

SCHEMA_VERSION = 1
_CHANGED_ID_RE = re.compile(r"^(?:REQ|ADR|STEP|OQ|PRN)-\d{3,}$")


class ImpactAnalysisError(ValueError):
    """Impact surface cannot be derived safely from canonical artifacts."""


def _decode_components(values: Any, *, allow_empty: bool) -> dict[str, str]:
    if values is None and allow_empty:
        return {}
    if not isinstance(values, list):
        raise ImpactAnalysisError("plan.context_components must be a string array")
    if not values and allow_empty:
        return {}

    result: dict[str, str] = {}
    for index, item in enumerate(values):
        if not isinstance(item, str) or "=" not in item:
            raise ImpactAnalysisError(
                f"plan.context_components[{index}] must be COMPONENT=sha256"
            )
        key, digest = item.rsplit("=", 1)
        if not key or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ImpactAnalysisError(
                f"plan.context_components[{index}] has invalid fingerprint"
            )
        if key in result:
            raise ImpactAnalysisError(
                f"duplicate plan.context_components key: {key}"
            )
        result[key] = digest
    return result


def compare_component_sets(
    stored: list[str],
    current: list[str],
) -> list[dict[str, str]]:
    before = _decode_components(stored, allow_empty=False)
    after = _decode_components(current, allow_empty=False)
    changes: list[dict[str, str]] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append({"component": key, "change": "added"})
        elif key not in after:
            changes.append({"component": key, "change": "removed"})
        elif before[key] != after[key]:
            changes.append({"component": key, "change": "changed"})
    return changes


def plan_staleness(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    plan = task["frontmatter"].get("plan")
    if not isinstance(plan, dict):
        return {
            "status": "invalid",
            "causes": [{"component": f"STEP@{step_id}", "change": "invalid-plan"}],
            "action": f"STEP PLAN {step_id}",
        }
    if plan.get("status") != "ready":
        return {
            "status": "not_ready",
            "causes": [],
            "action": f"STEP PLAN {step_id}",
        }

    stored_basis = plan.get("context_basis")
    current_basis = planning_context_basis(root, step_id)
    if stored_basis == current_basis:
        return {"status": "fresh", "causes": [], "action": None}

    stored_components = plan.get("context_components")
    # Compatibility: Ready plans created before this capability still fail-safe
    # on the authoritative basis mismatch, but cannot claim a component cause
    # that was never durably recorded.
    if stored_components in (None, []):
        causes = [{"component": "PLANNING_CONTEXT", "change": "changed"}]
    else:
        if not isinstance(stored_components, list):
            raise ImpactAnalysisError(
                f"{step_id}: plan.context_components must be a string array"
            )
        causes = compare_component_sets(
            stored_components,
            planning_context_components(root, step_id),
        )
        if not causes:
            causes = [{"component": "PLANNING_CONTEXT", "change": "changed"}]

    return {
        "status": "stale",
        "causes": causes,
        "action": f"STEP PLAN {step_id}",
        "storedBasis": stored_basis,
        "currentBasis": current_basis,
    }


def _changed_component_key(value: str) -> str:
    if value.startswith("ARCH@") and len(value) > len("ARCH@"):
        return value
    if _CHANGED_ID_RE.fullmatch(value):
        prefix = value.split("-", 1)[0]
        return f"{prefix}@{value}"
    raise ImpactAnalysisError(
        f"unsupported changed artifact {value!r}; expected REQ/ADR/STEP/OQ/PRN ID or ARCH@ref"
    )


def _linked_component_keys(root: Path, step_id: str) -> set[str]:
    """Return known current component identities without duplicating hashes."""
    task = read_task(root, step_id)
    keys = {f"STEP@{step_id}"}
    keys.update(f"REQ@{item}" for item in requirement_ids(task))
    keys.update(f"ADR@{item}" for item in adr_ids(task))
    keys.update(f"STEP@{item}" for item in dependency_ids(task))
    keys.update(f"ARCH@{item}" for item in architecture_refs(task))
    keys.update(
        f"OQ@{item['id']}"
        for item in relevant_open_questions(root, task)
        if isinstance(item.get("id"), str)
    )

    plan = task["frontmatter"].get("plan")
    if isinstance(plan, dict):
        stored = _decode_components(
            plan.get("context_components"),
            allow_empty=True,
        )
        keys.update(stored)
    try:
        current = _decode_components(
            planning_context_components(root, step_id),
            allow_empty=True,
        )
    except (OSError, ValueError):
        current = {}
    keys.update(current)
    return keys


def _replacement_reasons(
    root: Path,
    task: dict[str, Any],
    changed_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    for linked_id in adr_ids(task):
        path = canonical_adr_path(root, linked_id)
        document = parse_document(path)
        superseded_by = document["frontmatter"].get("superseded_by")
        values = superseded_by if isinstance(superseded_by, list) else []
        for replacement in values:
            if isinstance(replacement, str) and replacement in changed_ids:
                reasons.append(
                    f"linked architecture decision {linked_id} superseded by: {replacement}"
                )
    return reasons


def _reason_for_component(key: str) -> str:
    kind, _, value = key.partition("@")
    labels = {
        "REQ": "linked requirement changed",
        "ADR": "linked architecture decision changed",
        "STEP": "STEP/dependency contract changed",
        "OQ": "relevant open question changed",
        "PRN": "project principle changed",
        "ARCH": "architecture reference changed",
    }
    return f"{labels.get(kind, 'planning component changed')}: {value}"


def affected_steps(root: Path, changed: list[str]) -> dict[str, Any]:
    if not isinstance(changed, list) or not changed:
        raise ImpactAnalysisError("changed artifacts must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in changed):
        raise ImpactAnalysisError("changed artifacts must be non-empty strings")

    normalized = sorted(set(item.strip() for item in changed))
    changed_keys = {_changed_component_key(item): item for item in normalized}
    changed_ids = set(normalized)
    affected: list[dict[str, Any]] = []

    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        step_id = path.stem
        task = read_task(root, step_id)
        linked = _linked_component_keys(root, step_id)
        reasons = [
            _reason_for_component(key)
            for key in sorted(changed_keys)
            if key in linked
        ]
        reasons.extend(_replacement_reasons(root, task, changed_ids))
        reasons = sorted(set(reasons))
        if not reasons:
            continue

        freshness = plan_staleness(root, step_id)
        affected.append(
            {
                "step": step_id,
                "reasons": reasons,
                "plan": freshness["status"],
                "causes": freshness.get("causes", []),
                "action": freshness.get("action"),
            }
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "changed": normalized,
        "affected": affected,
    }


def _canonical_change_exists(root: Path, changed_id: str) -> bool:
    """Не объявлять необнаруженный artifact безопасно проигнорированным."""
    if changed_id.startswith("ARCH@"):
        # Architecture refs являются произвольными paths/anchors. Их
        # существование уже проверяет canonical planning contract.
        return True
    kind, _, _ = changed_id.partition("-")
    if kind == "STEP":
        return (task_directory(root) / f"{changed_id}.md").is_file()
    directories = {
        "REQ": requirements_directory,
        "ADR": adr_directory,
        "OQ": open_questions_directory,
        "PRN": principles_directory,
    }
    directory = directories[kind](root)
    return any(directory.glob(changed_id + "-*.md"))


def selective_invalidation_preview(root: Path, changed: list[str]) -> dict[str, Any]:
    """Только read-only прогноз влияния с транзитивными STEP dependencies.

    Это объясняющая проекция поверх канонических связей, не новый freshness
    validator. Состояния PASS/DONE и внешние операции здесь не меняются.
    Результат "preserved" означает отсутствие влияния *этих* изменений,
    а не разрешение обойти существующие Review/Verification gates.
    """
    if not isinstance(changed, list) or not changed or any(
        not isinstance(item, str) or not item.strip() for item in changed
    ):
        raise ImpactAnalysisError("changed artifacts must be non-empty strings")
    names = sorted(set(value.strip() for value in changed))
    changed_keys = {_changed_component_key(name) for name in names}
    changed_ids = set(names)
    # Источник изменения должен существовать как canonical artifact. Если
    # его не удалось прочитать, нельзя объявлять несвязанные STEP безопасными.
    unresolved = sorted(name for name in names if not _canonical_change_exists(root, name))

    tasks: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[str]] = {}
    direct: dict[str, list[str]] = {}
    problems: dict[str, list[str]] = {}

    # Один проход по STEP — основание графа; ни один artifact не переписывается.
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        step_id = path.stem
        try:
            task = read_task(root, step_id)
            tasks[step_id] = task
            dependencies[step_id] = sorted(set(dependency_ids(task)))
            # Включаем explicit current и stored component IDs: если ссылка
            # удалена, старый plan всё равно остаётся участником impact.
            linked = _linked_component_keys(root, step_id)
            reasons = [
                _reason_for_component(key)
                for key in sorted(changed_keys & linked)
            ]
            reasons.extend(_replacement_reasons(root, task, changed_ids))
            if reasons:
                direct[step_id] = sorted(set(reasons))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.setdefault(step_id, []).append(
                f"cannot prove STEP/dependency context: {exc}"
            )
            # Даже повреждённая запись самой изменённой STEP не исчезает
            # из отчёта: такой узел остаётся ambiguous, не preserved.
            if f"STEP@{step_id}" in changed_keys:
                direct[step_id] = ["changed STEP cannot be parsed"]

    downstream: dict[str, set[str]] = {step_id: set() for step_id in tasks}
    for step_id, refs in dependencies.items():
        for ref in refs:
            if ref not in tasks:
                problems.setdefault(step_id, []).append(
                    f"missing dependency: {step_id} -> {ref}"
                )
            else:
                downstream[ref].add(step_id)

    # Kahn: все не удалённые узлы содержат цикл или зависят от него.
    # Консервативно помечаем их ambiguous вместо ложного preserved.
    degree = {
        step_id: sum(parent in tasks for parent in refs)
        for step_id, refs in dependencies.items()
    }
    queue = deque(sorted(step for step, count in degree.items() if count == 0))
    removed: set[str] = set()
    while queue:
        parent = queue.popleft()
        removed.add(parent)
        for child in sorted(downstream[parent]):
            degree[child] -= 1
            if degree[child] == 0:
                queue.append(child)
    for step_id in sorted(set(tasks) - removed):
        problems.setdefault(step_id, []).append(
            "cyclic dependency or descendant of dependency cycle"
        )

    # Если upstream STEP нельзя проверить (битый/отсутствующий contract),
    # то downstream также не может получить решение preserved по умолчанию.
    unverified = deque(sorted(problems))
    visited_unverified = set(problems)
    while unverified:
        parent = unverified.popleft()
        for child in sorted(downstream.get(parent, set())):
            if child not in visited_unverified:
                visited_unverified.add(child)
                problems.setdefault(child, []).append(
                    f"unverified dependency upstream: {parent}"
                )
                unverified.append(child)

    if unresolved:
        for step_id in tasks:
            problems.setdefault(step_id, []).append(
                "changed artifact could not be resolved: " + ", ".join(unresolved)
            )

    # Обратные связи нужны, чтобы изменение STEP-001 было видно в STEP-006,
    # даже если собственный planning fingerprint STEP-006 пока остался fresh.
    paths: dict[str, list[str]] = {}
    for origin in sorted(direct):
        seen = {origin}
        pending = deque([(origin, [origin])])
        while pending:
            parent, chain = pending.popleft()
            old = paths.get(parent)
            if old is None or (len(chain), chain) < (len(old), old):
                paths[parent] = chain
            for child in sorted(downstream.get(parent, set())):
                if child not in seen:
                    seen.add(child)
                    pending.append((child, [*chain, child]))

    steps: list[dict[str, Any]] = []
    for step_id in sorted(set(tasks) | set(problems)):
        issues = list(problems.get(step_id, []))
        try:
            plan = plan_staleness(root, step_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            plan = {"status": "invalid", "causes": [], "action": f"STEP PLAN {step_id}"}
            issues.append(f"cannot prove plan freshness: {exc}")

        impacted = step_id in paths
        explicit = step_id in direct
        plan_status = plan.get("status")
        if issues or plan_status == "invalid":
            state = "ambiguous"
            if plan_status == "invalid" and not issues:
                issues.append("plan state cannot be proven")
        elif plan_status == "stale":
            state = "invalidated"
        elif impacted:
            # Даже fresh direct plan не доказывает, что downstream review и
            # side effects корректны после upstream change.
            state = "revalidate"
        else:
            state = "preserved"

        source = paths.get(step_id, [])
        reasons = list(direct.get(step_id, []))
        if len(source) > 1:
            reasons.append("transitive dependency: " + " -> ".join(source))
        if state == "invalidated" and not reasons:
            reasons.append("existing plan freshness mismatch")
        if issues:
            reasons.extend(issues)

        # Никакого отдельного proof-store: результаты Review/Verification
        # не трогаем, а отмечаем, нужна ли их повторная проверка.
        evidence_decision = (
            "preserved" if state == "preserved" else
            "ambiguous" if state == "ambiguous" else
            "revalidate" if state == "revalidate" else "invalidated"
        )
        steps.append({
            "step": step_id,
            "decision": state,
            "direct": explicit,
            "dependencyPath": source,
            "reasons": sorted(set(reasons)),
            "plan": {
                **plan,
                # A plan_staleness() diagnostic may contain STEP PLAN, but a
                # repository-wide impact preview cannot recommend executing
                # it for every invalidated STEP in advance.
                "action": None,
                "deferredAction": plan.get("action"),
                "refreshPolicy": "when-selected-by-STEP-NEXT",
            },
            "evidence": {
                "review": evidence_decision,
                "verification": evidence_decision,
                "completion": evidence_decision,
            },
            # This preview is about blast radius, not a backlog of PLAN
            # commands. Invalidated plans are a deferred remediation until
            # STEP NEXT ranks their step as the next executable one.
            "action": (
                "investigate dependency/contract" if state == "ambiguous"
                else "revalidate current evidence and prerequisites" if state == "revalidate"
                else None
            ),
            "deferredPlanAction": (
                f"STEP PLAN {step_id}" if state == "invalidated" else None
            ),
            "planRefreshPolicy": "when-selected-by-STEP-NEXT",
        })

    states = ("preserved", "revalidate", "invalidated", "ambiguous")
    # Проблема в несвязанном STEP не должна блокировать целевой dry-run.
    # Для затронутых узлов, напротив, ambiguity остаётся fail-closed.
    affected = [item for item in steps if item["dependencyPath"]]
    existing = [
        item for item in steps
        if not item["dependencyPath"] and item["decision"] != "preserved"
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": (
            "BLOCKED" if unresolved or any(
                item["decision"] == "ambiguous" for item in affected
            ) else "PASS"
        ),
        "mode": "dry-run",
        "changed": names,
        "unresolvedChanges": unresolved,
        "summary": {
            state: sum(item["decision"] == state for item in steps)
            for state in states
        },
        "steps": steps,
        # Только действительно связанные с входным --changed STEP.
        # Уже stale/повреждённые, но несвязанные узлы — отдельная диагностика.
        "affected": affected,
        "preExistingConcerns": existing,
        "externalSideEffectsExecuted": False,
        "notice": (
            "Read-only impact estimate; never authorizes reuse of stale evidence "
            "or retries side effects. Existing canonical freshness guards apply."
        ),
    }


__all__ = [
    "ImpactAnalysisError",
    "affected_steps",
    "compare_component_sets",
    "plan_staleness",
    "selective_invalidation_preview",
]
