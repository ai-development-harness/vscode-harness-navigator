#!/usr/bin/env python3
"""Regressions for requirements/architecture evolution and impact propagation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

import harness_ux as harness_ux_module
from command_dispatch import start_dispatch
from document_contract import render_document
from impact_analysis import affected_steps, selective_invalidation_preview, plan_staleness
from planning_contract import (
    implementation_prerequisite_failures,
    planning_context_basis,
    planning_context_components,
    read_task,
)
from project_state import build_project_state
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts
from execution_status import complete_command, start_execution
from semantic_artifacts import write_plan_draft, write_planning_review
from step_next import resolve_step_action


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)

def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")


def requirement(req_id: str, step_id: str, *, adr_id: str | None = None) -> str:
    adrs = "adrs: []" if adr_id is None else f"adrs:\n  - {adr_id}"
    return f"""---
schema: 1
id: {req_id}
priority: high
source: self_test
steps:
  - {step_id}
{adrs}
---

# {req_id} — Evolution fixture

## Requirement

Behavior for {step_id}.

## Rationale

Evolution regression.

## Acceptance

- Behavior remains reviewable.
"""


def adr(
    adr_id: str,
    *,
    status: str,
    step_id: str,
    req_id: str,
    supersedes: list[str] | None = None,
    superseded_by: list[str] | None = None,
) -> str:
    supersedes = supersedes or []
    superseded_by = superseded_by or []

    def block(name: str, values: list[str]) -> str:
        return f"{name}: []\n" if not values else f"{name}:\n" + "".join(
            f"  - {item}\n" for item in values
        )

    return f"""---
schema: 1
id: {adr_id}
status: {status}
date: 2026-10-02
deciders:
  - test
{block("supersedes", supersedes)}{block("superseded_by", superseded_by)}requirements:
  - {req_id}
steps:
  - {step_id}
---

# {adr_id} — Evolution decision

## Context

Synthetic decision.

## Problem

Need stable architecture.

## Decision

Use architecture {adr_id}.

## Alternatives considered

- none.

## Consequences

Deterministic fixture.

## Security implications

Not applicable.

## Data / migration implications

Not applicable.

## Compatibility / operational implications

Not applicable.
"""


def step(step_id: str, req_id: str, *, adr_id: str | None = None) -> str:
    adrs = "adrs: []" if adr_id is None else f"adrs:\n  - {adr_id}"
    return f"""---
schema: 1
id: {step_id}
status: planned
type: implementation
priority: high
phase: evolution-test
depends_on: []
requirements:
  - {req_id}
{adrs}
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Evolution fixture

## Goal

Implement {req_id}.

## Context

Synthetic evolution scenario.

## Scope

- Scope item {step_id}.

## Mutation policy

### Allowed

- src/{step_id.lower()}.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- unrelated behavior.

## Acceptance criteria

- Behavior remains reviewable.

## Verification

- manual: verify behavior

## Deliverables

- implementation.

## Implementation plan

TBD.

## Evidence

—

## Blocker / Failure reason

—
"""


def make_ready(root: Path, step_id: str) -> dict:
    execution = start_execution(root, f"STEP PLAN {step_id}")
    draft = write_plan_draft(
        root,
        step_id,
        {
            "implementationPlan": [
                {
                    "title": "Implement contract",
                    "actions": [f"Implement {step_id} exactly as approved."],
                }
            ],
            "verification": [
                {"kind": "manual", "value": f"Verify {step_id} behavior"}
            ],
        },
    )
    assert draft["status"] == "PASS", draft
    review = write_planning_review(
        root,
        step_id,
        {
            "verdict": "pass",
            "findings": [],
            "rationale": "Plan matches current canonical contract.",
        },
    )
    assert review["status"] == "PASS", review
    task = read_task(root, step_id)
    assert task["frontmatter"]["plan"]["status"] == "ready", task
    assert task["frontmatter"]["plan"]["context_components"], task
    complete_command(
        root,
        execution["rootCommand"],
        f"STEP PLAN {step_id}",
        "SUCCESS",
        expected_execution_id=execution["executionId"],
    )
    return review


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-impact-evolution-") as tmp:
        root = Path(tmp)
        copy_tracked(root)
        isolate_project_artifacts(root)
        inherited_req = root / "docs/requirements/REQ-001-template.md"
        inherited_req.unlink(missing_ok=True)

        manifest_path = root / ".harness/manifest.yaml"
        manifest = manifest_path.read_text(encoding="utf-8")
        manifest = manifest.replace("initialized: false", "initialized: true", 1)
        manifest = manifest.replace("name: null", "name: evolution-self-test", 1)
        manifest = manifest.replace(
            "initializedAt: null",
            "initializedAt: 2026-10-02T00:00:00+00:00",
            1,
        )
        write(manifest_path, manifest)

        for number in range(1, 8):
            req_id = f"REQ-{number:03d}"
            step_id = f"STEP-{number:03d}"
            adr_id = "ADR-001" if number == 3 else None
            write(
                root / f"docs/requirements/{req_id}-evolution.md",
                requirement(req_id, step_id, adr_id=adr_id),
            )
            write(
                root / f"planning/tasks/{step_id}.md",
                step(step_id, req_id, adr_id=adr_id),
            )

        # STEP-006/007 — цепочка зависимостей с собственной REQ у каждого.
        # Изменение REQ-001 напрямую затрагивает STEP-001, косвенно — 006/007.
        for step_id, parent in (("STEP-006", "STEP-001"), ("STEP-007", "STEP-006")):
            path = root / f"planning/tasks/{step_id}.md"
            write(
                path,
                path.read_text(encoding="utf-8").replace(
                    "depends_on: []",
                    f"depends_on:\n  - {parent}",
                    1,
                ),
            )

        write(
            root / "docs/adr/ADR-001-evolution.md",
            adr(
                "ADR-001",
                status="accepted",
                step_id="STEP-003",
                req_id="REQ-003",
            ),
        )

        reviews = {step_id: make_ready(root, step_id) for step_id in (
            "STEP-001",
            "STEP-002",
            "STEP-003",
            "STEP-004",
            "STEP-005",
            "STEP-006",
            "STEP-007",
        )}

        first_task = read_task(root, "STEP-001")
        first_report = root / first_task["frontmatter"]["plan"]["reviewed_report"]
        first_report_bytes = first_report.read_bytes()

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "evolution@example.invalid")
        run(root, "git", "config", "user.name", "Evolution Test")
        run(root, "git", "config", "gc.auto", "0")
        run(root, "git", "config", "maintenance.auto", "false")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # DoD / REQ change: only the linked Ready STEP becomes stale.
        req1 = root / "docs/requirements/REQ-001-evolution.md"
        req1.write_text(
            req1.read_text(encoding="utf-8").replace(
                "Behavior for STEP-001.",
                "Changed behavior for STEP-001.",
            ),
            encoding="utf-8",
            newline="\n",
        )
        stale = plan_staleness(root, "STEP-001")
        assert stale["status"] == "stale", stale
        assert {
            "component": "REQ@REQ-001",
            "change": "changed",
        } in stale["causes"], stale
        assert stale["action"] == "STEP PLAN STEP-001", stale
        assert plan_staleness(root, "STEP-002")["status"] == "fresh"

        affected = affected_steps(root, ["REQ-001"])
        assert [item["step"] for item in affected["affected"]] == ["STEP-001"], affected

        # #287: имеющийся affected_steps сохраняет прямую семантику (#174).
        # Новый dry-run дополнительно учитывает транзитивные depends_on,
        # не объявляя существующий план ребёнка stale без фактического proof.
        preview = selective_invalidation_preview(root, ["REQ-001"])
        decisions = {item["step"]: item for item in preview["steps"]}
        assert preview["mode"] == "dry-run", preview
        assert {item["step"] for item in preview["affected"]} == {
            "STEP-001", "STEP-006", "STEP-007",
        }, preview
        assert decisions["STEP-001"]["decision"] == "invalidated", preview
        assert decisions["STEP-006"]["decision"] == "revalidate", preview
        assert decisions["STEP-007"]["decision"] == "revalidate", preview
        assert decisions["STEP-007"]["dependencyPath"] == [
            "STEP-001", "STEP-006", "STEP-007",
        ], preview
        assert decisions["STEP-002"]["decision"] == "preserved", preview
        # Oracle для synthetic graph: нет false negative и false positive.
        assert preview["summary"] == {
            "preserved": 4, "revalidate": 2, "invalidated": 1, "ambiguous": 0
        }, preview

        # Повторный анализ не меняет tracked STEP/REQ и immutable REVIEW.
        before_preview = first_report.read_bytes()
        again = selective_invalidation_preview(root, ["REQ-001"])
        assert again == preview
        assert first_report.read_bytes() == before_preview

        # PROJECT STATE and PROJECT STATUS surfaces explain cause + remediation.
        project_state = build_project_state(root)
        step1_node = next(
            node for node in project_state["graph"]["nodes"]
            if node["id"] == "STEP-001"
        )
        assert step1_node["metadata"]["planFreshness"] == "stale", step1_node
        assert step1_node["metadata"]["planRemediation"] is None, step1_node
        assert step1_node["metadata"]["deferredPlanRemediation"] == "STEP PLAN STEP-001", step1_node
        assert {
            "component": "REQ@REQ-001",
            "change": "changed",
        } in step1_node["metadata"]["planStaleCauses"], step1_node

        listed = harness_ux_module.step_list(root)
        step1_row = next(item for item in listed["steps"] if item["id"] == "STEP-001")
        assert step1_row["planFreshness"] == "stale", step1_row
        assert step1_row["planRemediation"] is None, step1_row
        assert step1_row["deferredPlanRemediation"] == "STEP PLAN STEP-001", step1_row
        assert decisions["STEP-001"]["action"] is None, preview
        assert decisions["STEP-001"]["deferredPlanAction"] == "STEP PLAN STEP-001", preview
        assert decisions["STEP-001"]["plan"]["action"] is None, preview
        assert decisions["STEP-001"]["plan"]["deferredAction"] == "STEP PLAN STEP-001", preview

        original_write = harness_ux_module.write_projections
        original_run = harness_ux_module._run
        original_next = harness_ux_module.resolve_step_next
        try:
            harness_ux_module.write_projections = lambda _root: []
            harness_ux_module._run = lambda *_args, **_kwargs: {
                "ok": True,
                "code": 0,
                "stdout": "PASS",
                "stderr": "",
            }
            harness_ux_module.resolve_step_next = lambda _root: {
                "status": "BLOCKED",
                "reasonCode": "fixture",
            }
            status_payload = harness_ux_module.project_status(root)
        finally:
            harness_ux_module.write_projections = original_write
            harness_ux_module._run = original_run
            harness_ux_module.resolve_step_next = original_next
        assert status_payload["status"] == "PASS", status_payload
        assert status_payload["summary"]["stalePlans"] == 1, status_payload
        assert status_payload["stalePlans"][0]["id"] == "STEP-001", status_payload
        assert status_payload["stalePlans"][0]["planStaleCauses"] == stale["causes"], status_payload

        # A stale Ready plan cannot reach IMPLEMENT; however an eligible
        # STEP RUN must refresh PLAN just in time, not leave it blocked forever.
        impacted_action = resolve_step_action(root, "STEP-001")
        assert impacted_action["status"] == "PASS", impacted_action
        assert impacted_action["command"] == "STEP PLAN STEP-001", impacted_action
        assert impacted_action["planningAdvisory"]["staleReadyPlan"] is True
        assert "plan-context-basis-is-stale" in implementation_prerequisite_failures(
            root, "STEP-001",
        )
        unrelated_action = resolve_step_action(root, "STEP-002")
        assert unrelated_action["status"] == "PASS", unrelated_action
        assert unrelated_action["command"] == "STEP IMPLEMENT STEP-002", unrelated_action

        refreshed_run = start_dispatch(root, "STEP RUN STEP-001")
        assert refreshed_run["status"] == "SEMANTIC", refreshed_run
        assert refreshed_run["command"] == "STEP PLAN STEP-001", refreshed_run
        assert "STEP IMPLEMENT STEP-001" not in str(refreshed_run), refreshed_run
        # Stop the unfinished test invocation before the next independent
        # blast-radius scenario; no implementation/review mutation occurs.
        complete_command(
            root, refreshed_run["rootCommand"],
            "STEP PLAN STEP-001", "BLOCKED",
            expected_execution_id=refreshed_run["executionId"],
        )

        # ADR replacement: linked historical ADR changes status/superseded_by,
        # new ADR ID still maps to the affected STEP.
        adr1 = root / "docs/adr/ADR-001-evolution.md"
        write(
            root / "docs/adr/ADR-002-evolution.md",
            adr(
                "ADR-002",
                status="accepted",
                step_id="STEP-003",
                req_id="REQ-003",
                supersedes=["ADR-001"],
            ),
        )
        write(
            adr1,
            adr(
                "ADR-001",
                status="superseded",
                step_id="STEP-003",
                req_id="REQ-003",
                superseded_by=["ADR-002"],
            ),
        )
        adr_stale = plan_staleness(root, "STEP-003")
        assert adr_stale["status"] == "stale", adr_stale
        assert {
            "component": "ADR@ADR-001",
            "change": "changed",
        } in adr_stale["causes"], adr_stale
        replacement = affected_steps(root, ["ADR-002"])
        assert any(item["step"] == "STEP-003" for item in replacement["affected"]), replacement
        adr_preview = selective_invalidation_preview(root, ["ADR-002"])
        adr_decision = {item["step"]: item for item in adr_preview["steps"]}
        assert adr_decision["STEP-003"]["decision"] == "invalidated", adr_preview
        assert adr_decision["STEP-002"]["decision"] == "preserved", adr_preview

        # Task-local contract edit invalidates only its own STEP component.
        step4 = root / "planning/tasks/STEP-004.md"
        write(
            step4,
            step4.read_text(encoding="utf-8").replace(
                "- Scope item STEP-004.",
                "- Changed scope STEP-004.",
            ),
        )
        local_stale = plan_staleness(root, "STEP-004")
        assert local_stale["status"] == "stale", local_stale
        assert {
            "component": "STEP@STEP-004",
            "change": "changed",
        } in local_stale["causes"], local_stale

        # Existing Ready plans from before component fingerprints stay safe:
        # authoritative basis mismatch remains stale, but cause is generic.
        step5 = root / "planning/tasks/STEP-005.md"
        step5_doc = read_task(root, "STEP-005")
        step5_meta = step5_doc["frontmatter"]
        step5_meta["plan"]["context_components"] = []
        write(step5, render_document(step5_meta, step5_doc["body"]))
        req5 = root / "docs/requirements/REQ-005-evolution.md"
        write(
            req5,
            req5.read_text(encoding="utf-8").replace(
                "Behavior for STEP-005.",
                "Changed behavior for STEP-005.",
            ),
        )
        legacy = plan_staleness(root, "STEP-005")
        assert legacy["status"] == "stale", legacy
        assert legacy["causes"] == [
            {"component": "PLANNING_CONTEXT", "change": "changed"}
        ], legacy

        # Другой stale STEP не должен искусственно расширять площадь
        # влияния изменённого REQ-001, но ошибка видна отдельным разделом.
        scoped = selective_invalidation_preview(root, ["REQ-001"])
        assert "STEP-005" not in {
            item["step"] for item in scoped["affected"]
        }, scoped
        assert "STEP-005" in {
            item["step"] for item in scoped["preExistingConcerns"]
        }, scoped

        # Error cases: cycles and missing dependencies must not be silently
        # called preserved, even when no upstream semantic hash changed.
        six = root / "planning/tasks/STEP-006.md"
        six.write_text(
            six.read_text(encoding="utf-8").replace("- STEP-001", "- STEP-007", 1),
            encoding="utf-8", newline="\n",
        )
        cyclic = selective_invalidation_preview(root, ["STEP-006"])
        cycle_decisions = {item["step"]: item for item in cyclic["steps"]}
        assert cycle_decisions["STEP-006"]["decision"] == "ambiguous", cyclic
        assert cycle_decisions["STEP-007"]["decision"] == "ambiguous", cyclic
        assert any("cyclic" in reason for reason in cycle_decisions["STEP-006"]["reasons"])

        seven = root / "planning/tasks/STEP-007.md"
        seven.write_text(
            seven.read_text(encoding="utf-8").replace("- STEP-006", "- STEP-999", 1),
            encoding="utf-8", newline="\n",
        )
        missing = selective_invalidation_preview(root, ["STEP-999"])
        missing_decisions = {item["step"]: item for item in missing["steps"]}
        assert missing_decisions["STEP-007"]["decision"] == "ambiguous", missing
        assert any("missing dependency" in reason
                   for reason in missing_decisions["STEP-007"]["reasons"]), missing

        # Не связанный с REQ-002 повреждённый STEP-007 остаётся
        # диагностикой, но не превращает корректный scoped preview в BLOCKED.
        scoped_clean = selective_invalidation_preview(root, ["REQ-002"])
        assert scoped_clean["status"] == "PASS", scoped_clean
        assert {item["step"] for item in scoped_clean["affected"]} == {"STEP-002"}, scoped_clean
        assert any(
            item["step"] == "STEP-007" and item["decision"] == "ambiguous"
            for item in scoped_clean["preExistingConcerns"]
        ), scoped_clean

        # Analysis never rewrites immutable historical planning review.
        assert first_report.read_bytes() == first_report_bytes

        # Semantic-only workflows have deterministic policy regressions too.
        implement_skill = (
            SOURCE_ROOT / ".agents/skills/implement-step/SKILL.md"
        ).read_text(encoding="utf-8")
        assert "верни `BLOCKED`" in implement_skill, implement_skill
        assert "предполагаемого owner: REQ / ADR / OQ / STEP" in implement_skill, implement_skill

        quick_fix_skill = (
            SOURCE_ROOT / ".agents/skills/quick-fix/SKILL.md"
        ).read_text(encoding="utf-8")
        assert "не является QUICK FIX" in quick_fix_skill, quick_fix_skill
        assert "Примеры: typo" in quick_fix_skill, quick_fix_skill

        reconcile_skill = (
            SOURCE_ROOT / ".agents/skills/reconcile-project/SKILL.md"
        ).read_text(encoding="utf-8")
        assert "impact-analysis.py --step STEP-NNN" in reconcile_skill, reconcile_skill
        assert "canonical owner" in reconcile_skill, reconcile_skill

        # Fingerprints still come from the same planning snapshot machinery.
        assert planning_context_basis(root, "STEP-002")
        assert planning_context_components(root, "STEP-002")

    print("impact-analysis self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
