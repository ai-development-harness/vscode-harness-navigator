#!/usr/bin/env python3
"""#301: отрицательные проверки безопасного portable adoption.

Это unit-boundary проверки. Реальные два Git clone и все race scenarios
остаются отдельным обязательным этапом #302.
"""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
from unittest.mock import patch

from execution_status import (
    ExecutionCheckpointError, empty_status, load_status, start_execution,
    validate_status,
)
from planning_contract import planning_context_basis, plan_content_hash, latest_matching_planning_review
from semantic_artifacts import write_plan_draft, write_planning_review
from portable_handoff import write_handoff
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts
from portable_resume import portable_resume_candidate
from harness_ux import harness_resume


ROOT = Path("/unused/repository")


def _preview(*, count: int = 1, fresh: bool = True) -> dict:
    return {
        "status": "PASS",
        "candidates": [
            {"stepId": f"STEP-{i:03d}", "planFreshness": "fresh" if fresh else "stale",
             "reasonCode": "PLAN_BASIS_STALE"}
            for i in range(1, count + 1)
        ],
    }


def _proof() -> dict:
    return {
        "status": "PASS",
        "path": "planning/handoffs/STEP-001.json",
        "publicationHead": "a" * 40,
    }


def test_portable_gate() -> None:
    empty = {"executions": [], "recentTerminals": [], "stepRecovery": {}}
    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview()),
        patch("portable_resume.check_handoff", return_value=_proof()),
    ):
        result = portable_resume_candidate(ROOT)
        assert result["status"] == "PASS"
        assert result["portable"] is True
        assert result["command"] == "STEP PLAN STEP-001"
        assert "executionId" not in result

    for field, occupied in (
        ("executions", [{"executionId": "old"}]),
        ("recentTerminals", [{"executionId": "old"}]),
        ("stepRecovery", {"STEP-001": {"old": True}}),
    ):
        state = {**empty, field: occupied}
        with patch("portable_resume.load_status", return_value=state):
            assert portable_resume_candidate(ROOT)["reasonCode"] == "PORTABLE_LOCAL_HISTORY_PRESENT"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview(count=2)),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "PORTABLE_CANDIDATES_AMBIGUOUS"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview(fresh=False)),
        patch("portable_resume.check_handoff", return_value=_proof()),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "PLAN_BASIS_STALE"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview()),
        patch("portable_resume.check_handoff", return_value={"status": "BLOCKED", "reasonCode": "HANDOFF_STEP_CHANGED"}),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "HANDOFF_STEP_CHANGED"

    with patch("portable_resume.load_status", side_effect=ExecutionCheckpointError("UNAVAILABLE", "lost marker")):
        try:
            portable_resume_candidate(ROOT)
        except ExecutionCheckpointError:
            pass
        else:
            raise AssertionError("Lost local checkpoint must not fall back to portable")


def test_local_precedence() -> None:
    local = {
        "status": "RESUME",
        "rootCommand": "STEP RUN STEP-009",
        "command": "STEP IMPLEMENT STEP-009",
        "executionId": "exec-local",
    }
    with (
        patch("harness_ux.unresolved_executions", return_value=[local]),
        patch("harness_ux.portable_resume_candidate", side_effect=AssertionError("portable must not run")),
    ):
        decision = harness_resume(ROOT)
        assert decision["executionId"] == "exec-local"
        assert decision["instruction"] == "resume-existing-execution-without-starting-new-root"

    # Уже завершённые локальные executions не actionable, но являются
    # частью истории. Старый API возвращает NO_RESUMABLE_EXECUTION с executions=[].
    for reason in ("PORTABLE_LOCAL_HISTORY_PRESENT", "NO_RESUMABLE_EXECUTION"):
        with (
            patch("harness_ux.unresolved_executions", return_value=[]),
            patch("harness_ux.portable_resume_candidate", return_value={
                "status": "BLOCKED", "reasonCode": reason,
            }),
        ):
            assert harness_resume(ROOT) == {
                "status": "BLOCKED",
                "reasonCode": "NO_RESUMABLE_EXECUTION",
                "executions": [],
            }

    # Локальный blocker не должен превращаться в portable fallback.
    with (
        patch("harness_ux.unresolved_executions", return_value=[
            {"status": "BLOCKED", "reasonCode": "COMMAND_BLOCKED"}
        ]),
        patch("harness_ux.portable_resume_candidate",
              side_effect=AssertionError("blocked local history must not use portable")),
    ):
        assert harness_resume(ROOT)["reasonCode"] == "NO_RESUMABLE_EXECUTION"

    with (
        patch("harness_ux.unresolved_executions", return_value=[]),
        patch("harness_ux.portable_resume_candidate", return_value={
            "status": "PASS", "portable": True, "command": "STEP PLAN STEP-001",
        }),
    ):
        assert harness_resume(ROOT)["portable"] is True



def test_dispatch_creates_new_local_plan() -> None:
    from command_dispatch import resume_dispatch
    decision = {
        "status": "PASS",
        "portable": True,
        "rootCommand": "STEP PLAN STEP-001",
        "command": "STEP PLAN STEP-001",
        "sourceHandoff": "planning/handoffs/STEP-001.json",
        "publicationHead": "a" * 40,
    }
    started = {
        "status": "SEMANTIC",
        "executionId": "exec-new-local",
        "command": "STEP PLAN STEP-001",
    }
    with (
        patch("command_dispatch.harness_resume", return_value=decision),
        patch("command_dispatch.start_dispatch", return_value=started) as start,
        patch("portable_resume.portable_resume_candidate", return_value=decision),
        patch("command_dispatch.resolve_root", side_effect=AssertionError("must not resume source execution")),
    ):
        result = resume_dispatch(ROOT)
        start.assert_called_once_with(
            ROOT, "STEP PLAN STEP-001",
            require_fresh_clone=True, expected_git_head="a" * 40,
        )
        assert result["executionId"] == "exec-new-local"
        assert result["portableAdoption"]["importedExecution"] is False
        assert result["portableAdoption"]["externalSideEffectsExecuted"] is False



def _git(root: Path, *args: str) -> str:
    """Запустить настоящий Git в isolated fixture, без доступа к сети."""
    done = subprocess.run(
        ("git", *args), cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False,
    )
    assert done.returncode == 0, (args, done.stdout, done.stderr)
    return done.stdout.strip()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _task() -> str:
    """Минимальный реальный STEP с draft-планом (без forged runtime proofs)."""
    return """---
schema: 1
id: STEP-017
status: in_progress
type: implementation
priority: high
phase: backend
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: draft
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-017 — Portable resume integration

## Goal

- Continue published work without copying local execution state.

## Context

- Two independent Git clones share one canonical STEP.

## Scope

- Inspect the published implementation before further mutation.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated files

## Out of scope

- Replay of Git side effects.

## Acceptance criteria

- New clone receives a new local planning execution only.

## Verification

- manual: verify published implementation

## Deliverables

- Git-backed STEP.

## Implementation plan

1. Inspect the published code and task.
2. Verify current acceptance against the repository.

## Evidence

—

## Blocker / Failure reason

—
"""


def _prepare_ready_step(root: Path) -> None:
    """Сформировать настоящий Ready plan и immutable independent PLAN-REVIEW."""
    path = root / "planning/tasks/STEP-017.md"
    draft = _task()
    _write(path, draft)
    basis = planning_context_basis(root, "STEP-017")
    content_hash = plan_content_hash(root, "STEP-017")
    review = "planning/plan-reviews/STEP-017/PLAN-REVIEW-20261011T000000Z.md"
    _write(root / review, f"""---
schema: 1
kind: planning_review
step_id: STEP-017
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: {basis}
plan_content_hash: {content_hash}
created_at: 2026-10-11T00:00:00Z
---

# Planning Review STEP-017 — integration fixture

## Scope checked

Published STEP and implementation plan.

## Findings

No material findings.

## Verdict rationale

Plan is consistent with canonical task.
""")
    ready = draft.replace("  status: draft", "  status: ready", 1)
    ready = ready.replace("  revision: 0", "  revision: 1", 1)
    ready = ready.replace("  context_basis: null", f"  context_basis: {basis}", 1)
    ready = ready.replace("  content_hash: null", f"  content_hash: {content_hash}", 1)
    ready = ready.replace("  reviewed_report: null", f"  reviewed_report: {review}", 1)
    ready = ready.replace("  planned_at: null", "  planned_at: 2026-10-11T00:00:00+00:00", 1)
    _write(path, ready)
    assert latest_matching_planning_review(root, "STEP-017") is not None


def test_two_clone_real_dispatch() -> None:
    """Positive path: Git publish -> clone -> real HARNESS RESUME dispatcher."""
    from command_dispatch import start_dispatch, complete_dispatch

    with tempfile.TemporaryDirectory(prefix="portable-resume-integration-") as temp:
        root = Path(temp)
        desktop, laptop, origin = root / "desktop", root / "laptop", root / "origin.git"
        desktop.mkdir()
        copy_effective_harness_checkout(Path(__file__).resolve().parents[2], desktop)
        isolate_project_artifacts(desktop)
        manifest = desktop / ".harness/manifest.yaml"
        original = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in original
        _write(manifest, original.replace("initialized: false", "initialized: true", 1))
        _prepare_ready_step(desktop)

        _git(root, "init", "--bare", "-q", "-b", "main", str(origin))
        _git(desktop, "init", "-q", "-b", "main")
        _git(desktop, "config", "user.email", "portable@example.invalid")
        _git(desktop, "config", "user.name", "Portable Integration")
        _git(desktop, "remote", "add", "origin", str(origin))
        _git(desktop, "add", ".")
        _git(desktop, "commit", "-qm", "published implementation")
        _git(desktop, "push", "-q", "-u", "origin", "main")

        # Producer имеет собственную незавершённую invocation. Она не переносится.
        source_local = start_execution(desktop, "STEP IMPLEMENT STEP-017")
        exported = write_handoff(desktop, "STEP-017")
        assert exported["status"] == "PASS", exported
        _git(desktop, "add", exported["path"])
        _git(desktop, "commit", "-qm", "publish portable handoff")
        _git(desktop, "push", "-q", "origin", "main")
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(laptop))

        assert not (laptop / ".harness/local/execution/execution-status.json").exists()
        assert not (laptop / ".harness/.execution-checkpoint-known").exists()
        selection = harness_resume(laptop)
        assert selection["status"] == "PASS" and selection["portable"] is True, selection
        assert selection["command"] == "STEP PLAN STEP-017", selection
        assert not (laptop / ".harness/local/execution/execution-status.json").exists()

        # Проверяем именно public dispatcher, а не mock его ответа.
        output = subprocess.run(
            (sys.executable, ".harness/tools/harness-dispatch.py", "start",
             "--command", "HARNESS RESUME"),
            cwd=laptop, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False,
        )
        assert output.returncode == 0, (output.stdout, output.stderr)
        response = json.loads(output.stdout)
        assert response["status"] == "SEMANTIC", response
        assert response["command"] == "STEP PLAN STEP-017", response
        assert response["skill"] == "plan-step", response
        assert response["portableAdoption"]["importedExecution"] is False, response
        assert response["portableAdoption"]["externalSideEffectsExecuted"] is False, response
        assert response["executionId"] != source_local["executionId"], response
        local = load_status(laptop)
        assert len(local["executions"]) == 1, local
        assert local["executions"][0]["rootCommand"] == "STEP PLAN STEP-017", local
        assert local["executions"][0]["current"]["context"]["intentBasis"], local
        assert local["executions"][0]["current"]["context"]["portablePlanProofBefore"], local
        corrupted = json.loads(json.dumps(local))
        corrupted["executions"][0]["current"]["context"]["portablePlanProofBefore"]["revision"] = "invalid"
        assert any(
            "portablePlanProofBefore" in issue
            for issue in validate_status(corrupted)
        ), corrupted
        assert _git(laptop, "status", "--porcelain") == ""

        # Старый Ready plan НЕ может подтвердить эту только что созданную
        # локальную PLAN: ни при crash recovery, ни через semantic SUCCESS.
        local_choice = harness_resume(laptop)
        assert local_choice["status"] == "PASS", local_choice
        assert local_choice["executionId"] == response["executionId"], local_choice
        assert local_choice["command"] == "STEP PLAN STEP-017", local_choice
        assert len(load_status(laptop)["executions"]) == 1
        premature = complete_dispatch(
            laptop, "STEP PLAN STEP-017", "STEP PLAN STEP-017",
            "SUCCESS", execution_id=response["executionId"],
        )
        assert premature["status"] == "BLOCKED", premature
        assert premature["reasonCode"] == "PORTABLE_PLAN_RECHECK_REQUIRED", premature
        assert load_status(laptop)["executions"][0]["status"] == "running"

        # Обязательная новая semantic PLAN: канонический writer создаёт новый
        # draft + независимый immutable planning review, после чего stamp Ready.
        draft = write_plan_draft(laptop, "STEP-017", {
            "implementationPlan": [{
                "title": "Inspect existing implementation",
                "actions": ["Inspect the published implementation against acceptance."],
                "files": [],
                "tests": [],
                "risks": [],
            }],
            "verification": [{"kind": "manual", "value": "Inspect published implementation"}],
        })
        assert draft["status"] == "PASS", draft
        reviewed = write_planning_review(laptop, "STEP-017", {
            "verdict": "pass",
            "findings": [],
            "rationale": "The portable STEP remains semantically consistent.",
        })
        assert reviewed["status"] == "PASS", reviewed
        assert reviewed["executionId"] == response["executionId"], reviewed
        completed = complete_dispatch(
            laptop, "STEP PLAN STEP-017", "STEP PLAN STEP-017",
            "SUCCESS", execution_id=response["executionId"],
        )
        assert completed["status"] == "DONE", completed
        assert completed["executionId"] == response["executionId"], completed
        assert harness_resume(laptop)["reasonCode"] == "NO_RESUMABLE_EXECUTION"

        # Новый Ready plan НЕ должен сам по себе запускать IMPLEMENT/REVIEW.
        # Обычный STEP resolver лишь предлагает следующий этап после PLAN.
        from step_next import resolve_step_action
        next_step = resolve_step_action(laptop, "STEP-017")
        assert next_step["status"] == "PASS", next_step
        assert next_step["command"] == "STEP IMPLEMENT STEP-017", next_step
        assert not any(
            item["rootCommand"].startswith(("STEP IMPLEMENT", "STEP REVIEW"))
            for item in load_status(laptop)["executions"]
        )

        # Явный IMPLEMENT после нового PLAN использует штатный local recovery,
        # а отсутствие на ноутбуке manual Verification НЕ становится PASS.
        implement = start_dispatch(laptop, "STEP IMPLEMENT STEP-017")
        assert implement["status"] == "SEMANTIC", implement
        local_implement = harness_resume(laptop)
        assert local_implement["status"] == "PASS", local_implement
        assert local_implement["executionId"] == implement["executionId"]
        assert local_implement.get("portable") is not True
        missing_verification = complete_dispatch(
            laptop, "STEP IMPLEMENT STEP-017", "STEP IMPLEMENT STEP-017",
            "SUCCESS", execution_id=implement["executionId"],
        )
        assert missing_verification["status"] != "DONE", missing_verification
        assert missing_verification["reasonCode"].startswith("VERIFICATION_"), missing_verification
        assert load_status(laptop)["executions"][-1]["status"] == "running"

        # Новый clone с сохранённым пустым local state НЕ является fresh clone.
        prior = root / "prior-local"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(prior))
        _write(
            prior / ".harness/local/execution/execution-status.json",
            json.dumps(empty_status()) + "\n",
        )
        assert harness_resume(prior)["reasonCode"] == "NO_RESUMABLE_EXECUTION"
        with patch("command_dispatch.harness_resume", return_value=selection):
            rejected = start_dispatch(prior, "HARNESS RESUME")
            # The patched selection still must hit the atomic fresh state guard.
            assert rejected["status"] == "BLOCKED", rejected
            assert rejected["reasonCode"] == "PORTABLE_LOCAL_HISTORY_PRESENT", rejected
        # Проверяем и сам атомарный guard, если local state появился
        # уже ПОСЛЕ read-only проверки handoff, перед start_execution.
        atomic = start_dispatch(
            prior, "STEP PLAN STEP-017", require_fresh_clone=True,
            expected_git_head=_git(prior, "rev-parse", "HEAD"),
        )
        assert atomic["status"] == "BLOCKED", atomic
        assert atomic["reasonCode"] == "EXECUTION_STATE_INCOMPATIBLE", atomic
        assert load_status(prior)["executions"] == []

        # HEAD может сдвинуться между read-only preview и записью state.
        # Подменяем только Git observation внутри atomic boundary и
        # проверяем, что ни один новый execution не зарегистрирован.
        moving = root / "moving-head"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(moving))
        with (
            patch("execution_status._git_head", return_value="f" * 40),
            patch("command_dispatch.harness_resume", return_value=selection),
        ):
            blocked = start_dispatch(moving, "HARNESS RESUME")
        assert blocked["status"] == "BLOCKED", blocked
        assert blocked["reasonCode"] == "HANDOFF_HEAD_CHANGED", blocked
        assert load_status(moving)["executions"] == []

        # Uncommitted files and diverged branch cannot provide adoption proof.
        dirty = root / "dirty"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(dirty))
        _write(dirty / "unpublished.txt", "not in Git\n")
        assert harness_resume(dirty)["reasonCode"] == "WORKTREE_DIRTY"
        assert not (dirty / ".harness/local/execution/execution-status.json").exists()

        wrong_branch = root / "wrong-branch"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(wrong_branch))
        _git(wrong_branch, "switch", "-q", "-c", "unrelated")
        assert harness_resume(wrong_branch)["reasonCode"] == "HANDOFF_BRANCH_CHANGED"

        # Multiple in_progress STEP candidates remain ambiguous.
        ambiguous = root / "ambiguous"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(ambiguous))
        second = _task().replace("STEP-017", "STEP-018").replace("  status: draft", "  status: not_planned")
        _write(ambiguous / "planning/tasks/STEP-018.md", second)
        _git(ambiguous, "config", "user.email", "portable@example.invalid")
        _git(ambiguous, "config", "user.name", "Portable Integration")
        _git(ambiguous, "add", "planning/tasks/STEP-018.md")
        _git(ambiguous, "commit", "-qm", "second STEP candidate")
        assert harness_resume(ambiguous)["reasonCode"] == "PORTABLE_CANDIDATES_AMBIGUOUS"

        # Local execution start between read-only selection and dispatch
        # must not be overwritten/reused by portable PLAN.
        race = root / "local-race"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(race))
        selected = harness_resume(race)
        assert selected["status"] == "PASS", selected
        competing = start_execution(race, "PROJECT QUICK FIX: started concurrently")
        with patch("command_dispatch.harness_resume", return_value=selected):
            blocked = start_dispatch(race, "HARNESS RESUME")
        assert blocked["status"] == "BLOCKED", blocked
        assert blocked["reasonCode"] == "PORTABLE_LOCAL_HISTORY_PRESENT", blocked
        state = load_status(race)
        assert len(state["executions"]) == 1, state
        assert state["executions"][0]["executionId"] == competing["executionId"]

        # Тот же root STEP PLAN: portable adoption не имеет права подхватить
        # чужой running PLAN через обычный shortcut в start_dispatch.
        same = root / "local-race-same-root"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(same))
        published = harness_resume(same)
        assert published["status"] == "PASS", published
        existing_plan = start_execution(same, "STEP PLAN STEP-017")
        blocked_same = start_dispatch(
            same, "STEP PLAN STEP-017",
            require_fresh_clone=True,
            expected_git_head=_git(same, "rev-parse", "HEAD"),
        )
        assert blocked_same["status"] == "BLOCKED", blocked_same
        assert blocked_same["reasonCode"] == "EXECUTION_STATE_INCOMPATIBLE", blocked_same
        current_state = load_status(same)
        assert len(current_state["executions"]) == 1, current_state
        assert current_state["executions"][0]["executionId"] == existing_plan["executionId"]



def test_new_review_must_belong_to_new_execution() -> None:
    """Новый immutable review чужой invocation не может доказать portable PLAN."""
    from execution_status import portable_plan_recheck_proven

    report = "planning/plan-reviews/STEP-017/PLAN-REVIEW-new.md"
    execution = {
        "executionId": "exec-portable",
        "current": {
            "command": "STEP PLAN STEP-017",
            "context": {
                "portablePlanProofBefore": {
                    "reviewedReport": "planning/plan-reviews/STEP-017/PLAN-REVIEW-old.md",
                    "revision": 1,
                }
            },
        },
    }
    current_plan = {
        "frontmatter": {
            "plan": {"status": "ready", "revision": 2, "reviewed_report": report}
        }
    }
    with (
        patch("execution_status.normalize_single_command", return_value={
            "domain": "STEP", "operation": "PLAN", "target": "STEP-017",
        }),
        patch("execution_status.read_planning_task", return_value=current_plan),
        patch("execution_status.latest_matching_planning_review", return_value={
            "path": ROOT / report,
            "document": {"frontmatter": {"execution_id": "exec-other"}},
        }),
    ):
        assert portable_plan_recheck_proven(ROOT, execution) is False

    with (
        patch("execution_status.normalize_single_command", return_value={
            "domain": "STEP", "operation": "PLAN", "target": "STEP-017",
        }),
        patch("execution_status.read_planning_task", return_value=current_plan),
        patch("execution_status.latest_matching_planning_review", return_value={
            "path": ROOT / report,
            "document": {"frontmatter": {"execution_id": "exec-portable"}},
        }),
    ):
        assert portable_plan_recheck_proven(ROOT, execution) is True


def test_legacy_empty_project_without_published_handoff() -> None:
    """Не менять прежний ответ HARNESS RESUME для ещё пустого проекта.

    Проверяем не mock, а два публичных пути в реальной копии шаблона:
    pre-INIT и initialized project без Git repository. В обоих случаях
    переносимый handoff невозможен и возвращается старый reasonCode.
    """
    from command_dispatch import start_dispatch

    with tempfile.TemporaryDirectory(prefix="harness-resume-empty-project-") as tmp:
        root = Path(tmp)
        copy_effective_harness_checkout(Path(__file__).resolve().parents[2], root)
        # Reproduce an initialized downstream host even when CI itself runs
        # on the pristine Harness template. This specifically regresses the
        # canary failure where the copied manifest had initialized: true.
        manifest = root / ".harness/manifest.yaml"
        copied = manifest.read_text(encoding="utf-8")
        if "initialized: false" in copied:
            manifest.write_text(
                copied.replace("initialized: false", "initialized: true", 1),
                encoding="utf-8",
            )
        # This is a *pre-INIT* regression regardless of whether the installed
        # host is the pristine template or an initialized downstream project.
        # Keep Harness-managed files, reset only project-owned fixture state.
        isolate_project_artifacts(root)
        manifest = root / ".harness/manifest.yaml"
        original = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in original
        assert not (root / ".git").exists()

        expected = {
            "status": "BLOCKED",
            "reasonCode": "NO_RESUMABLE_EXECUTION",
            "executions": [],
        }
        assert harness_resume(root) == expected
        dispatched = start_dispatch(root, "HARNESS RESUME")
        assert dispatched["status"] == "BLOCKED", dispatched
        assert dispatched["reasonCode"] == "NO_RESUMABLE_EXECUTION", dispatched
        assert dispatched["executions"] == [], dispatched

        # Проект может быть помечен initialized, но не являться Git worktree.
        # Это тоже не разрешение для portable recovery.
        manifest.write_text(
            original.replace("initialized: false", "initialized: true", 1),
            encoding="utf-8",
        )
        assert harness_resume(root) == expected
        assert not (root / ".harness/local/execution/execution-status.json").exists()


if __name__ == "__main__":
    test_legacy_empty_project_without_published_handoff()
    test_new_review_must_belong_to_new_execution()
    test_portable_gate()
    test_local_precedence()
    test_dispatch_creates_new_local_plan()
    test_two_clone_real_dispatch()
    print("portable-resume-self-test: PASS")
