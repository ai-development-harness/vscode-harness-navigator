#!/usr/bin/env python3
"""Synthetic regression deterministic STEP NEXT recommendation."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import errno
import shutil
import subprocess
import tempfile
import time

import step_next as step_next_module
import planning_contract as planning_contract_module
import execution_status as execution_status_module
import command_dispatch as command_dispatch_module
import harness_ux as harness_ux_module
from command_dispatch import start_dispatch
from execution_status import begin_command, complete_command, load_status, start_execution, unresolved_executions
from planning_contract import dependency_completion_failures, implementation_prerequisite_failures
from step_next import resolve_step_action, resolve_step_next


from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)

def step_text(
    step_id: str,
    *,
    priority: str = "medium",
    status: str = "planned",
    step_type: str = "implementation",
    depends: list[str] | None = None,
    adrs: list[str] | None = None,
    risks: list[str] | None = None,
) -> str:
    deps = depends or []
    linked_adrs = adrs or []
    flags = risks or ["none"]
    dep_yaml = "[]"
    if deps:
        dep_yaml = "\n" + "\n".join(f"  - {item}" for item in deps)
    adr_yaml = "[]"
    if linked_adrs:
        adr_yaml = "\n" + "\n".join(f"  - {item}" for item in linked_adrs)
    risk_yaml = "\n" + "\n".join(f"  - {item}" for item in flags)
    return f"""---
schema: 1
id: {step_id}
status: {status}
type: {step_type}
priority: {priority}
phase: test
depends_on: {dep_yaml}
requirements: []
adrs: {adr_yaml}
architecture_refs: []
risk_flags: {risk_yaml}
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Next fixture {step_id}

## Goal

Проверить STEP NEXT.

## Context

Synthetic.

## Scope

- Next selection.

## Mutation policy

### Allowed

- synthetic.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product.

## Acceptance criteria

- Deterministic recommendation.

## Verification

- command: `python3 -V`

## Deliverables

- Recommendation.

## Implementation plan

TBD.

## Evidence

—

## Blocker / Failure reason

—
"""


def write_step(root: Path, step_id: str, **kwargs) -> None:
    path = root / f"planning/tasks/{step_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step_text(step_id, **kwargs), encoding="utf-8", newline="\n")


def write_adr(root: Path, adr_id: str, *, status: str = "proposed") -> None:
    path = root / f"docs/adr/{adr_id}-synthetic.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema: 1
id: {adr_id}
status: {status}
date: 2026-10-04
deciders: []
supersedes: []
superseded_by: []
requirements: []
steps: []
---

# {adr_id} — Synthetic ADR

## Context

Synthetic STEP NEXT regression fixture.
""",
        encoding="utf-8",
        newline="\n",
    )


def reset_steps(root: Path) -> None:
    directory = root / "planning/tasks"
    for path in directory.glob("STEP-*.md"):
        path.unlink()


@contextmanager
def temporary_git_checkout():
    """Очистить временный Git checkout без случайного падения из-за race.

    На Python 3.11 rmtree иногда встречает временно непустую .git. Повторяем
    только этот конкретный сбой, не игнорируя постоянную ошибку очистки.
    """
    temporary = tempfile.TemporaryDirectory(prefix="harness-step-next-")
    try:
        yield temporary.name
    finally:
        for attempt in range(3):
            try:
                temporary.cleanup()
                break
            except OSError as exc:
                if exc.errno != errno.ENOTEMPTY or attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))


def tracked_operational_snapshot(root: Path) -> dict[str, bytes]:
    """Включая файлы проекций и lock: NEXT не должен ничего записывать."""
    snapshot: dict[str, bytes] = {}
    for rel in (".harness/local", "planning", "docs/requirements", "docs/adr"):
        directory = root / rel
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file():
                    snapshot[path.relative_to(root).as_posix()] = path.read_bytes()
    return snapshot


def assert_deep_dependency_graph(root: Path) -> None:
    """Проверить длинную цепь и повторное использование proof cache без Git I/O."""
    first, last = 1000, 2200
    original_read = planning_contract_module.read_task
    original_proof = planning_contract_module.step_completion_proof
    proof_calls = 0

    def fake_read(_root: Path, step_id: str) -> dict:
        number = int(step_id.removeprefix("STEP-"))
        deps = [] if number == first else [f"STEP-{number - 1}"]
        return {"frontmatter": {"depends_on": deps}}

    def fake_proof(_root: Path, _step_id: str) -> dict:
        nonlocal proof_calls
        proof_calls += 1
        return {"complete": True, "reasons": []}

    planning_contract_module.read_task = fake_read
    planning_contract_module.step_completion_proof = fake_proof
    try:
        proofs: dict[str, dict] = {}
        dependencies: dict[str, list[str]] = {}
        failures = dependency_completion_failures(
            root, f"STEP-{last}",
            proof_cache=proofs, dependency_cache=dependencies,
        )
        assert failures == [], failures
        assert proof_calls == last - first, proof_calls
        # При повторном запросе того же графа общий cache не пересчитывает proof.
        failures = dependency_completion_failures(
            root, f"STEP-{last - 1}",
            proof_cache=proofs, dependency_cache=dependencies,
        )
        assert failures == [], failures
        assert proof_calls == last - first, proof_calls
    finally:
        planning_contract_module.read_task = original_read
        planning_contract_module.step_completion_proof = original_proof


def assert_readonly_review_recovery(root: Path) -> None:
    """Durable PASS review нельзя использовать как предлог записать STEP на NEXT."""
    original_review = execution_status_module.latest_review
    original_proof = execution_status_module.step_completion_proof
    original_finalize = execution_status_module.finalize_step_completion
    execution = {
        "current": {
            "command": "STEP REVIEW STEP-005",
            "status": "running",
            "context": {"reviewReportBefore": "old"},
        },
    }

    def forbid_finalize(*_args, **_kwargs):
        raise AssertionError("read-only recovery tried to finalize STEP")

    try:
        execution_status_module.latest_review = lambda *_args, **_kwargs: {
            "path": "new", "verdict": "PASS", "completionResult": "PASS",
        }
        execution_status_module.finalize_step_completion = forbid_finalize
        execution_status_module.step_completion_proof = lambda *_args, **_kwargs: {
            "complete": False,
        }
        pending = execution_status_module._durable_recovery_result(
            root, execution, allow_finalization=False,
        )
        assert pending is None, pending

        execution_status_module.step_completion_proof = lambda *_args, **_kwargs: {
            "complete": True,
        }
        proven = execution_status_module._durable_recovery_result(
            root, execution, allow_finalization=False,
        )
        assert proven == "PASS", proven
    finally:
        execution_status_module.latest_review = original_review
        execution_status_module.step_completion_proof = original_proof
        execution_status_module.finalize_step_completion = original_finalize


def main() -> int:
    with temporary_git_checkout() as tmp:
        root = Path(tmp)
        copy_tracked(root)
        isolate_project_artifacts(root)
        reset_steps(root)

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "next@example.invalid")
        run(root, "git", "config", "user.name", "Next Test")
        # Во временной фикстуре не нужен фоновый Git maintenance / auto-gc.
        run(root, "git", "config", "gc.auto", "0")
        run(root, "git", "config", "maintenance.auto", "false")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # Dependency completion is a hard gate before ranking, even when the
        # blocked downstream task has critical priority.
        write_step(
            root,
            "STEP-001",
            priority="critical",
            depends=["STEP-010"],
        )
        write_step(root, "STEP-010", priority="low")
        first = resolve_step_next(root)
        assert first["status"] == "PASS", first
        assert first["command"] == "STEP RUN STEP-010", first
        assert first["selected"]["ranking"]["priority"] == "low", first
        assert any(x["stepId"] == "STEP-001" for x in first["blockers"]), first

        exact = resolve_step_action(root, "STEP-001")
        assert exact["status"] == "PASS", exact
        assert exact["stepType"] == "implementation", exact
        assert exact["command"] == "STEP PLAN STEP-001", exact

        # A five-STEP DAG: unfinished prerequisites never compete on priority.
        reset_steps(root)
        write_step(root, "STEP-001", priority="low")
        write_step(root, "STEP-002", priority="critical", depends=["STEP-001"])
        write_step(root, "STEP-003", priority="medium")
        write_step(
            root, "STEP-004", priority="high",
            depends=["STEP-002", "STEP-003"],
        )
        write_step(
            root, "STEP-005", priority="critical",
            depends=["STEP-001", "STEP-002", "STEP-003", "STEP-004"],
        )
        dag = resolve_step_next(root)
        assert dag["command"] == "STEP RUN STEP-003", dag
        assert dag["eligibleCount"] == 2, dag
        assert dag["alternatives"][0]["command"] == "STEP RUN STEP-001", dag
        assert {item["stepId"] for item in dag["blockers"]} == {
            "STEP-002", "STEP-004", "STEP-005",
        }, dag
        assert "dependency-incomplete:STEP-001" in " ".join(
            next(item["reasons"] for item in dag["blockers"]
                 if item["stepId"] == "STEP-002")
        ), dag
        # Manually requested PLAN retains the old permissive prerequisite rule.
        manual = resolve_step_action(root, "STEP-005")
        assert manual["status"] == "PASS", manual
        assert manual["command"] == "STEP PLAN STEP-005", manual

        # Completed metadata alone is not enough: a research dependency needs
        # durable evidence before it can unlock an implementation STEP.
        reset_steps(root)
        write_step(root, "STEP-020", priority="critical", depends=["STEP-021"])
        write_step(
            root, "STEP-021", status="completed", step_type="research",
        )
        no_proof = resolve_step_next(root)
        assert no_proof["status"] == "BLOCKED", no_proof
        assert no_proof["reasonCode"] == "NO_EXECUTABLE_STEP", no_proof
        assert any(
            reason.startswith("dependency-incomplete:STEP-021")
            for item in no_proof["blockers"] for reason in item["reasons"]
        ), no_proof

        completed_research = root / "planning/tasks/STEP-021.md"
        research_text = completed_research.read_text(encoding="utf-8")
        assert "## Evidence\n\n—" in research_text
        completed_research.write_text(
            research_text.replace(
                "## Evidence\n\n—", "## Evidence\n\n- Synthetic research proof."
            ),
            encoding="utf-8",
            newline="\n",
        )
        ready_after_proof = resolve_step_next(root)
        assert ready_after_proof["status"] == "PASS", ready_after_proof
        assert ready_after_proof["command"] == "STEP RUN STEP-020", ready_after_proof

        # Missing dependencies and dependency cycles are never executable.
        reset_steps(root)
        write_step(root, "STEP-030", depends=["STEP-031"])
        missing = resolve_step_next(root)
        assert missing["status"] == "BLOCKED", missing
        assert any(
            reason.startswith("dependency-unprovable:STEP-031")
            for item in missing["blockers"] for reason in item["reasons"]
        ), missing
        write_step(root, "STEP-031", depends=["STEP-030"])
        cycle = resolve_step_next(root)
        assert cycle["status"] == "BLOCKED", cycle
        assert any(
            reason.startswith("dependency-cycle:")
            for item in cycle["blockers"] for reason in item["reasons"]
        ), cycle

        # Неправильный тип depends_on нельзя тихо считать отсутствием связей.
        reset_steps(root)
        write_step(root, "STEP-050", priority="low")
        write_step(root, "STEP-051", priority="critical")
        malformed_path = root / "planning/tasks/STEP-051.md"
        original_text = malformed_path.read_text(encoding="utf-8")
        assert "depends_on: []" in original_text
        for invalid_yaml in (
            "depends_on: STEP-050",
            "depends_on:\n  - STEP-050\n  - 42",
            "depends_on:\n  - STEP-050\n  - STEP-050",
        ):
            malformed_path.write_text(
                original_text.replace("depends_on: []", invalid_yaml),
                encoding="utf-8", newline="\n",
            )
            rejected = resolve_step_next(root)
            assert rejected["command"] == "STEP RUN STEP-050", rejected
            assert any(
                item["stepId"] == "STEP-051"
                and any(reason.startswith("dependency-unprovable:STEP-051")
                        for reason in item["reasons"])
                for item in rejected["blockers"]
            ), rejected
            shared_gate = implementation_prerequisite_failures(root, "STEP-051")
            assert any(reason.startswith("dependency-unprovable:STEP-051")
                       for reason in shared_gate), shared_gate
        malformed_path.write_text(original_text, encoding="utf-8", newline="\n")

        # Missing trusted implementation review never unlocks descendants.
        reset_steps(root)
        write_step(root, "STEP-060", priority="critical", depends=["STEP-061"])
        write_step(root, "STEP-061", status="completed")
        invalid_implementation = resolve_step_next(root)
        assert invalid_implementation["status"] == "BLOCKED", invalid_implementation
        assert any(
            "trusted PASS review is missing" in reason
            for item in invalid_implementation["blockers"]
            for reason in item["reasons"]
        ), invalid_implementation

        # Plan Ready metadata без matching basis/review не является runnable.
        reset_steps(root)
        write_step(root, "STEP-065", priority="critical")
        stale_path = root / "planning/tasks/STEP-065.md"
        stale_text = stale_path.read_text(encoding="utf-8")
        stale_path.write_text(
            stale_text.replace("  status: not_planned", "  status: ready", 1),
            encoding="utf-8", newline="\n",
        )
        stale_next = resolve_step_next(root)
        assert stale_next["status"] == "BLOCKED", stale_next
        assert any(
            "plan-fingerprints-are-invalid" in reason
            for item in stale_next["blockers"]
            for reason in item["reasons"]
        ), stale_next

        # #331: Just-in-time planning after REQ/ADR/architecture drift.
        # A valid old Ready fingerprint cannot authorize IMPLEMENT, but STEP
        # NEXT may recommend STEP RUN to refresh PLAN when dependency gates
        # are clear. Other STEP plans must NOT be regenerated in bulk.
        reset_steps(root)
        write_step(root, "STEP-080", priority="low")
        write_step(root, "STEP-081", priority="critical", depends=["STEP-080"])
        write_step(root, "STEP-082", priority="medium")
        task_path = root / "planning/tasks/STEP-080.md"
        old_basis = planning_contract_module.planning_context_basis(root, "STEP-080")
        old_content = planning_contract_module.plan_content_hash(root, "STEP-080")
        plan_text = task_path.read_text(encoding="utf-8")
        plan_text = plan_text.replace("  status: not_planned", "  status: ready", 1)
        plan_text = plan_text.replace("  context_basis: null", f"  context_basis: {old_basis}", 1)
        plan_text = plan_text.replace("  content_hash: null", f"  content_hash: {old_content}", 1)
        # Goal is part of the semantic STEP contract; priority/phase are
        # scheduling metadata and must NOT stale a Ready plan.
        plan_text = plan_text.replace(
            "## Goal\n\nПроверить STEP NEXT.",
            "## Goal\n\nПроверить изменённый contract STEP NEXT.", 1,
        )
        task_path.write_text(plan_text, encoding="utf-8", newline="\n")
        failures = implementation_prerequisite_failures(root, "STEP-080")
        assert "plan-context-basis-is-stale" in failures, failures
        assert resolve_step_action(root, "STEP-080")["command"] == "STEP PLAN STEP-080"
        assert resolve_step_action(root, "STEP-080")["planningAdvisory"]["staleReadyPlan"]
        future_plan = resolve_step_action(root, "STEP-081")
        assert future_plan["command"] == "STEP PLAN STEP-081", future_plan
        assert future_plan["planningAdvisory"]["deferIfNotNext"] is True

        before_selection = resolve_step_next(root)
        assert before_selection["command"] == "STEP RUN STEP-082", before_selection
        assert before_selection["alternatives"][0]["command"] == "STEP RUN STEP-080"
        assert before_selection["alternatives"][0]["planTiming"]["deferUntilSelected"] is True
        assert any(x["stepId"] == "STEP-081" for x in before_selection["blockers"])
        stale_list = harness_ux_module.step_list(root)
        stale_row = next(x for x in stale_list["steps"] if x["id"] == "STEP-080")
        assert stale_row["planFreshness"] == "stale", stale_row
        assert stale_row["planRemediation"] is None, stale_row
        assert stale_row["deferredPlanRemediation"] == "STEP PLAN STEP-080", stale_row
        assert stale_row["planRefreshPolicy"] == "when-selected-by-STEP-NEXT", stale_row

        # As soon as stale Ready STEP becomes the highest-priority actionable
        # one, NEXT recommends one RUN; the child PLAN is selected inside RUN.
        task_path.write_text(
            task_path.read_text(encoding="utf-8").replace(
                "priority: low", "priority: high", 1,
            ),
            encoding="utf-8", newline="\n",
        )
        selected_stale = resolve_step_next(root)
        assert selected_stale["command"] == "STEP RUN STEP-080", selected_stale
        assert selected_stale["selected"]["planTiming"]["refreshStaleReady"] is True
        assert selected_stale["selected"]["planTiming"]["deferUntilSelected"] is False
        still_blocked = implementation_prerequisite_failures(root, "STEP-080")
        assert "plan-context-basis-is-stale" in still_blocked, still_blocked
        # A standalone IMPLEMENT must remain BLOCKED, even though RUN can
        # safely execute a fresh independent PLAN before attempting it.
        step_implement = start_dispatch(root, "STEP IMPLEMENT STEP-080")
        assert step_implement["status"] == "BLOCKED", step_implement

        # Planning blockers such as TBD phase stay relevant even without deps.
        reset_steps(root)
        write_step(root, "STEP-066", priority="critical")
        write_step(root, "STEP-067", priority="low")
        tbd_path = root / "planning/tasks/STEP-066.md"
        tbd_path.write_text(
            tbd_path.read_text(encoding="utf-8").replace(
                "phase: test", "phase: TBD", 1,
            ),
            encoding="utf-8", newline="\n",
        )
        phase_next = resolve_step_next(root)
        assert phase_next["command"] == "STEP RUN STEP-067", phase_next
        assert any(item["stepId"] == "STEP-066" for item in phase_next["blockers"]), phase_next

        # PROJECT STATUS должен брать тот же результат, без второго ranking.
        reset_steps(root)
        write_step(root, "STEP-068", priority="low")
        write_step(root, "STEP-069", priority="critical", depends=["STEP-068"])
        canonical_next = resolve_step_next(root)
        original_write_projections = harness_ux_module.write_projections
        original_run = harness_ux_module._run
        try:
            harness_ux_module.write_projections = lambda _root: []
            harness_ux_module._run = lambda *_args, **_kwargs: {
                "ok": True, "code": 0, "stdout": "PASS", "stderr": "",
            }
            status = harness_ux_module.project_status(root)
        finally:
            harness_ux_module.write_projections = original_write_projections
            harness_ux_module._run = original_run
        assert status["status"] == "PASS", status
        assert status["nextWork"]["command"] == canonical_next["command"], status
        assert status["nextWork"]["command"] == "STEP RUN STEP-068", status

        # Даже отрицательная read-only рекомендация не создаёт execution.
        reset_steps(root)
        before_empty = tracked_operational_snapshot(root)
        empty_dispatch = start_dispatch(root, "STEP NEXT")
        assert empty_dispatch["status"] == "BLOCKED", empty_dispatch
        assert empty_dispatch["result"]["reasonCode"] == "NO_EXECUTABLE_STEP", empty_dispatch
        assert tracked_operational_snapshot(root) == before_empty

        assert_deep_dependency_graph(root)
        assert_readonly_review_recovery(root)

        # ADR STEP owns its linked proposed ADR: requiring accepted before PLAN
        # would create a cyclic prerequisite. Ordinary implementation STEPs
        # remain blocked by the same proposed ADR status.
        reset_steps(root)
        write_adr(root, "ADR-1000", status="proposed")
        write_adr(root, "ADR-1001", status="proposed")
        write_step(
            root,
            "STEP-011",
            priority="critical",
            step_type="adr",
            adrs=["ADR-1000"],
        )
        write_step(
            root,
            "STEP-012",
            priority="high",
            adrs=["ADR-1001"],
        )

        adr_action = resolve_step_action(root, "STEP-011")
        assert adr_action["status"] == "PASS", adr_action
        assert adr_action["stepType"] == "adr", adr_action
        assert adr_action["command"] == "STEP PLAN STEP-011", adr_action

        implementation_action = resolve_step_action(root, "STEP-012")
        assert implementation_action["status"] == "BLOCKED", implementation_action
        assert (
            "adr-not-accepted:ADR-1001" in implementation_action["reasons"]
        ), implementation_action

        adr_next = resolve_step_next(root)
        assert adr_next["status"] == "PASS", adr_next
        assert adr_next["command"] == "STEP RUN STEP-011", adr_next

        # Same priority: a STEP that unlocks more downstream active work wins.
        reset_steps(root)
        write_step(root, "STEP-002", priority="high")
        write_step(root, "STEP-003", priority="high")
        write_step(
            root,
            "STEP-004",
            priority="low",
            status="blocked",
            depends=["STEP-002"],
        )
        downstream = resolve_step_next(root)
        assert downstream["command"] == "STEP RUN STEP-002", downstream
        assert downstream["selected"]["ranking"]["downstreamImpact"] == 1, downstream

        # Risk is only a deterministic visibility tie-breaker, not a severity
        # model. With all earlier ranking dimensions equal, explicit risk wins.
        reset_steps(root)
        write_step(root, "STEP-005", priority="medium")
        write_step(
            root,
            "STEP-006",
            priority="medium",
            risks=["security-sensitive", "public-api"],
        )
        risk = resolve_step_next(root)
        assert risk["command"] == "STEP RUN STEP-006", risk
        assert risk["selected"]["ranking"]["riskFlagCount"] == 2, risk

        # Existing interrupted STEP execution always wins over higher-priority
        # fresh work. This preserves user continuity without LLM arbitration.
        write_step(root, "STEP-007", priority="critical")
        active = start_execution(root, "STEP PLAN STEP-005")
        assert active["status"] == "running", active
        continuity = resolve_step_next(root)
        assert continuity["command"] == "STEP PLAN STEP-005", continuity
        assert continuity["reasonCode"] == "RESUME_STEP_EXECUTION", continuity
        assert continuity["selected"]["source"] == "execution", continuity
        assert continuity["alternatives"][0]["command"] == "STEP RUN STEP-007", continuity

        # REVIEW PASS and completion are different durable facts. A PASS review
        # with in-scope completion FAIL still requires canonical FIX; a semantic
        # completion blocker must not be converted into new implementation work.
        original_latest_review = step_next_module.latest_review
        try:
            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "FAIL",
            }
            completion_fix = resolve_step_action(root, "STEP-005")
            assert completion_fix["status"] == "PASS", completion_fix
            assert completion_fix["command"] == "STEP FIX STEP-005", completion_fix

            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "BLOCKED",
            }
            completion_blocked = resolve_step_action(root, "STEP-005")
            assert completion_blocked["status"] == "BLOCKED", completion_blocked
            assert (
                "current-review-completion-blocked"
                in completion_blocked["reasons"]
            ), completion_blocked
        finally:
            step_next_module.latest_review = original_latest_review

        # Dispatcher executes STEP NEXT itself; no next-step semantic skill is
        # needed to choose the recommendation.
        prior_files = tracked_operational_snapshot(root)
        dispatched = start_dispatch(root, "STEP NEXT")
        assert dispatched["status"] == "DONE", dispatched
        result = dispatched["result"]
        assert result["status"] == "PASS", result
        assert result["command"] == "STEP PLAN STEP-005", result
        assert tracked_operational_snapshot(root) == prior_files, (
            "STEP NEXT dispatcher changed project or local operational files"
        )

        # Durable PLAN success is a read-only virtual completion; NEXT must
        # not recommend repeating already completed semantic planning.
        original_plan_info = execution_status_module.plan_info
        try:
            execution_status_module.plan_info = (
                lambda _root, _step: {"ready": True}
            )
            before_recovery = tracked_operational_snapshot(root)
            recoverable = unresolved_executions(root, mutate=False)
            assert tracked_operational_snapshot(root) == before_recovery
            assert not any(
                item.get("command") == "STEP PLAN STEP-005"
                and item.get("status") == "RESUME"
                for item in recoverable
            ), recoverable
        finally:
            execution_status_module.plan_info = original_plan_info

        # Clean up the synthetic interrupted command to leave no hidden state.
        complete_command(
            root,
            active["rootCommand"],
            active["current"]["command"],
            "BLOCKED",
        )

        # Interrupted PLAN is not an exception to dependency gating.
        # Reading STEP NEXT must not rewrite durable execution state.
        reset_steps(root)
        write_step(root, "STEP-040", priority="critical", depends=["STEP-041"])
        write_step(root, "STEP-041", priority="low")
        unsafe = start_execution(root, "STEP PLAN STEP-040")
        state_file = root / ".harness/local/execution/execution-status.json"
        before = state_file.read_bytes()
        guarded = resolve_step_next(root)
        after = state_file.read_bytes()
        assert before == after, "STEP NEXT mutated execution state"
        assert guarded["command"] == "STEP RUN STEP-041", guarded
        assert guarded["selected"]["source"] == "fresh", guarded
        assert any(
            item["stepId"] == "STEP-040" for item in guarded["blockers"]
        ), guarded
        complete_command(
            root,
            unsafe["rootCommand"],
            unsafe["current"]["command"],
            "BLOCKED",
        )

        # Cross-version v0.11.4-style v2 state: existing STEP RUN with a
        # running PLAN child must keep its executionId. A durable Ready plan
        # may have been written before the local completion checkpoint.
        reset_steps(root)
        write_step(root, "STEP-070", priority="critical")
        old_root = "STEP RUN STEP-070"
        old_exec = start_execution(root, old_root)
        begin_command(root, old_root, "STEP PLAN STEP-070")
        state_file = root / ".harness/local/execution/execution-status.json"
        assert load_status(root)["schemaVersion"] == 2
        old_state = state_file.read_bytes()
        previous_plan_info = execution_status_module.plan_info
        previous_prerequisites = execution_status_module.implementation_prerequisite_failures
        previous_dispatch = command_dispatch_module._dispatch_running
        try:
            # Simulate a durable approved Ready plan / passing preflight.
            execution_status_module.plan_info = (
                lambda _root, _step: {"ready": True}
            )
            execution_status_module.implementation_prerequisite_failures = (
                lambda _root, _step: []
            )
            # Keep this test at the dispatcher boundary; do not invoke an AI
            # provider or mutate the product during the synthetic check.
            command_dispatch_module._dispatch_running = (
                lambda _root, execution, command: {
                    "status": "RUNNING",
                    "rootCommand": execution["rootCommand"],
                    "executionId": execution["executionId"],
                    "command": command,
                }
            )

            preview = resolve_step_next(root)
            assert preview["status"] == "PASS", preview
            assert preview["command"] == old_root, preview
            assert preview["selected"]["executionId"] == old_exec["executionId"], preview
            assert preview["selected"]["nextChildCommand"] == "STEP IMPLEMENT STEP-070", preview
            assert state_file.read_bytes() == old_state, "NEXT committed virtual recovery"

            # Running the exact recommended command must reconcile the
            # original root first, not create an orphaned IMPLEMENT invocation.
            continued = start_dispatch(root, preview["command"])
            assert continued["executionId"] == old_exec["executionId"], continued
            assert continued["rootCommand"] == old_root, continued
            assert continued["command"] == "STEP IMPLEMENT STEP-070", continued
            owned = [
                item for item in load_status(root)["executions"]
                if item["executionId"] == old_exec["executionId"]
            ]
            assert len(owned) == 1 and owned[0]["current"]["command"] == "STEP IMPLEMENT STEP-070", owned
            assert not any(
                item["rootCommand"] == "STEP IMPLEMENT STEP-070"
                for item in load_status(root)["executions"]
            ), "orphaned standalone IMPLEMENT was created"
            assert owned[0]["current"]["status"] == "running", owned
        finally:
            execution_status_module.plan_info = previous_plan_info
            execution_status_module.implementation_prerequisite_failures = previous_prerequisites
            command_dispatch_module._dispatch_running = previous_dispatch

        # An uninterrupted (not-yet-proven) PLAN also resumes its original
        # STEP RUN root, rather than starting a standalone PLAN.
        reset_steps(root)
        write_step(root, "STEP-071")
        plain_root = "STEP RUN STEP-071"
        plain = start_execution(root, plain_root)
        begin_command(root, plain_root, "STEP PLAN STEP-071")
        plain_next = resolve_step_next(root)
        assert plain_next["command"] == plain_root, plain_next
        assert plain_next["selected"]["nextChildCommand"] == "STEP PLAN STEP-071", plain_next
        previous_dispatch = command_dispatch_module._dispatch_running
        try:
            command_dispatch_module._dispatch_running = (
                lambda _root, execution, command: {
                    "status": "RUNNING",
                    "rootCommand": execution["rootCommand"],
                    "executionId": execution["executionId"],
                    "command": command,
                }
            )
            plain_resume = start_dispatch(root, plain_root)
        finally:
            command_dispatch_module._dispatch_running = previous_dispatch
        assert plain_resume["executionId"] == plain["executionId"], plain_resume
        assert plain_resume["command"] == "STEP PLAN STEP-071", plain_resume

        # Manual STEP chains also have one durable root. NEXT must return
        # that root, not the child command, even with multiple commands.
        reset_steps(root)
        write_step(root, "STEP-072")
        chain_root = "STEP PLAN STEP-072 > STEP IMPLEMENT STEP-072"
        chain = start_execution(root, chain_root)
        chain_next = resolve_step_next(root)
        assert chain_next["command"] == chain_root, chain_next
        previous_dispatch = command_dispatch_module._dispatch_running
        try:
            command_dispatch_module._dispatch_running = (
                lambda _root, execution, command: {
                    "status": "RUNNING",
                    "rootCommand": execution["rootCommand"],
                    "executionId": execution["executionId"],
                    "command": command,
                }
            )
            chain_resume = start_dispatch(root, chain_root)
        finally:
            command_dispatch_module._dispatch_running = previous_dispatch
        assert chain_resume["executionId"] == chain["executionId"], chain_resume
        assert chain_resume["command"] == "STEP PLAN STEP-072", chain_resume

        # The old dispatcher envelope offered an executionId field.
        # Read-only NEXT cannot allocate an ID, but the field remains stable.
        envelope = start_dispatch(root, "STEP NEXT")
        assert "executionId" in envelope and envelope["executionId"] is None, envelope

    print("STEP NEXT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
