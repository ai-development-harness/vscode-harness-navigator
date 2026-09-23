#!/usr/bin/env python3
"""Regression self-test stateful deterministic command dispatcher."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import command_dispatch as command_dispatch_module
from command_dispatch import (
    complete_dispatch,
    route_command,
    start_dispatch,
)
from command_transitions import load_transition_table, validate_transition_table
from execution_status import load_status


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
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=SOURCE_ROOT,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = token.decode("utf-8")
        source = SOURCE_ROOT / rel
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    run(target, "git", "init", "-q", "-b", "main")
    run(target, "git", "config", "user.email", "dispatcher@example.invalid")
    run(target, "git", "config", "user.name", "Dispatcher Test")
    run(target, "git", "add", ".")
    run(target, "git", "commit", "-qm", "fixture")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-dispatcher-") as tmp:
        root = Path(tmp)
        copy_tracked(root)

        # CTS является единственным routing registry: semantic route и
        # phase-specific context metadata получаются без чтения skill prose.
        plan_route = route_command(root, "STEP PLAN STEP-123")
        assert plan_route["dispatch"] == {
            "kind": "semantic",
            "skill": "plan-step",
            "contextPhase": "plan",
        }, plan_route

        # Mechanical Git actions do not need an LLM handoff anymore.
        assert route_command(root, "GIT CHECK")["dispatch"] == {
            "kind": "deterministic",
            "handler": "git-check",
        }
        assert route_command(root, "GIT PR FINISH")["dispatch"] == {
            "kind": "deterministic",
            "handler": "git-pr-finish",
        }
        assert route_command(root, "GIT SYNC")["dispatch"] == {
            "kind": "deterministic",
            "handler": "git-sync",
        }


        # Status/update commands consume deterministic engines directly.
        assert route_command(root, "PROJECT STATUS")["dispatch"] == {
            "kind": "deterministic",
            "handler": "project-status",
        }
        assert route_command(root, "HARNESS UPDATE CHECK")["dispatch"] == {
            "kind": "deterministic",
            "handler": "harness-update-check",
        }
        assert route_command(root, "HARNESS UPDATE APPLY")["dispatch"] == {
            "kind": "deterministic",
            "handler": "harness-update-apply",
        }

        # Mutating deterministic handler may return SUCCESS rather than PASS.
        # Dispatcher must persist exact SUCCESS and finish without semantic handoff.
        original_sync = command_dispatch_module.execute_sync
        command_dispatch_module.execute_sync = lambda _root: {
            "status": "SUCCESS",
            "action": "sync",
            "mutated": False,
        }
        try:
            sync_result = start_dispatch(root, "GIT SYNC")
        finally:
            command_dispatch_module.execute_sync = original_sync
        assert sync_result["status"] == "DONE", sync_result
        assert sync_result["result"]["status"] == "SUCCESS", sync_result

        # Удалённый dispatch metadata должен ломать graph fail-closed.
        table = load_transition_table(root)
        del table["domains"]["STEP"]["commands"]["PLAN"]["dispatch"]
        errors = validate_transition_table(table)
        assert any(
            "STEP.PLAN.dispatch must be an object" in item
            for item in errors
        ), errors

        # Read-only deterministic command исполняется самим dispatcher и
        # завершает execution без semantic handoff.
        help_result = start_dispatch(root, "HARNESS HELP")
        assert help_result["status"] == "DONE", help_result
        assert help_result["result"]["status"] == "PASS", help_result
        assert any(
            item["domain"] == "STEP"
            for item in help_result["result"]["domains"]
        ), help_result


        project_snapshot = start_dispatch(root, "PROJECT STATUS")
        assert project_snapshot["status"] == "DONE", project_snapshot
        assert project_snapshot["result"]["status"] == "PASS", project_snapshot
        assert project_snapshot["result"]["validation"] == "PASS", project_snapshot

        # Structural FAIL ничего не записывает в execution state.
        before = len(load_status(root)["executions"])
        invalid = start_dispatch(root, "GIT PR > COMMIT")
        after = len(load_status(root)["executions"])
        assert invalid["status"] == "BLOCKED", invalid
        assert invalid["reasonCode"] == "INVALID_CHAIN", invalid
        assert before == after, (before, after)

        # Semantic command возвращает только exact skill handoff.
        quick = start_dispatch(root, "PROJECT QUICK FIX: исправить опечатку")
        assert quick["status"] == "SEMANTIC", quick
        assert quick["skill"] == "quick-fix", quick
        assert quick["skillPath"] == ".agents/skills/quick-fix/SKILL.md", quick
        assert quick["commandData"]["input"] == "исправить опечатку", quick
        done = complete_dispatch(
            root,
            quick["rootCommand"],
            quick["command"],
            "SUCCESS",
        )
        assert done["status"] == "DONE", done


        # Normal coding STEP RUN skips the root run-step model turn and hands
        # the exact child command directly to its semantic skill. Special types
        # keep the semantic run-step fallback.
        original_action = command_dispatch_module.resolve_step_action
        original_context = command_dispatch_module.build_step_context
        command_dispatch_module.resolve_step_action = lambda _root, step_id: {
            "status": "PASS",
            "stepId": step_id,
            "stepType": "implementation",
            "lifecycleStatus": "planned",
            "command": f"STEP PLAN {step_id}",
        }
        command_dispatch_module.build_step_context = lambda _root, _step, _phase: {
            "status": "PASS",
            "readPaths": [],
            "deterministic": {},
        }
        try:
            coding_run = start_dispatch(root, "STEP RUN STEP-123")
        finally:
            command_dispatch_module.resolve_step_action = original_action
            command_dispatch_module.build_step_context = original_context
        assert coding_run["status"] == "SEMANTIC", coding_run
        assert coding_run["command"] == "STEP PLAN STEP-123", coding_run
        assert coding_run["skill"] == "plan-step", coding_run
        command_dispatch_module.block_execution(
            root,
            coding_run["rootCommand"],
            command=coding_run["command"],
        )

        command_dispatch_module.resolve_step_action = lambda _root, step_id: {
            "status": "PASS",
            "stepId": step_id,
            "stepType": "research",
            "lifecycleStatus": "planned",
            "command": f"STEP PLAN {step_id}",
        }
        try:
            special_run = start_dispatch(root, "STEP RUN STEP-124")
        finally:
            command_dispatch_module.resolve_step_action = original_action
        assert special_run["status"] == "SEMANTIC", special_run
        assert special_run["command"] == "STEP RUN STEP-124", special_run
        assert special_run["skill"] == "run-step", special_run
        special_done = complete_dispatch(
            root,
            special_run["rootCommand"],
            special_run["command"],
            "SUCCESS",
        )
        assert special_done["status"] == "DONE", special_done

        # Deterministic CHECK должен автоматически пройти первый segment
        # и вернуть модели только следующий semantic COMMIT handoff.
        chain = start_dispatch(root, "GIT CHECK > COMMIT")
        assert chain["status"] == "SEMANTIC", chain
        assert chain["command"] == "GIT COMMIT", chain
        assert chain["skill"] == "git-workflow", chain

        chain_done = complete_dispatch(
            root,
            chain["rootCommand"],
            chain["command"],
            "SUCCESS",
        )
        assert chain_done["status"] == "DONE", chain_done


        # Standalone PUSH still requires semantic scope reasoning.
        standalone_push = start_dispatch(root, "GIT PUSH")
        assert standalone_push["status"] == "SEMANTIC", standalone_push
        assert standalone_push["command"] == "GIT PUSH", standalone_push
        complete_dispatch(
            root,
            standalone_push["rootCommand"],
            standalone_push["command"],
            "SUCCESS",
        )

        # After canonical COMMIT in the same chain PUSH is purely mechanical:
        # execute_push owns fetch/preflight/mutation/postcondition, so no second
        # git-operator model turn is required.
        original_push = command_dispatch_module.execute_push
        original_commit_proof = command_dispatch_module.git_commit_completion_proven
        command_dispatch_module.execute_push = lambda _root: {
            "status": "SUCCESS",
            "action": "push",
            "branch": "test",
            "head": "deadbeef",
            "afterPush": "never",
        }
        command_dispatch_module.git_commit_completion_proven = lambda _root, _execution: True
        try:
            git_chain = start_dispatch(root, "GIT CHECK > COMMIT > PUSH")
            assert git_chain["status"] == "SEMANTIC", git_chain
            assert git_chain["command"] == "GIT COMMIT", git_chain
            git_done = complete_dispatch(
                root,
                git_chain["rootCommand"],
                git_chain["command"],
                "SUCCESS",
            )
        finally:
            command_dispatch_module.execute_push = original_push
            command_dispatch_module.git_commit_completion_proven = original_commit_proof
        assert git_done["status"] == "DONE", git_done
        assert git_done["result"]["status"] == "SUCCESS", git_done
        assert git_done["result"]["fastPath"] == "after-canonical-commit", git_done

        # A semantic SUCCESS claim alone cannot unlock the no-model PUSH path:
        # repository HEAD advancement is a required deterministic proof.
        command_dispatch_module.git_commit_completion_proven = (
            lambda _root, _execution: False
        )
        try:
            unproven_chain = start_dispatch(root, "GIT CHECK > COMMIT > PUSH")
            unproven = complete_dispatch(
                root,
                unproven_chain["rootCommand"],
                unproven_chain["command"],
                "SUCCESS",
            )
        finally:
            command_dispatch_module.git_commit_completion_proven = original_commit_proof
        assert unproven["status"] == "BLOCKED", unproven
        assert unproven["reasonCode"] == "COMMIT_POSTCONDITION_FAILED", unproven

        # UPDATE CHECK > APPLY persists exact machine route/lock details, so the
        # existing matching-update-target-and-route precondition remains active
        # even though both segments now run without an LLM.
        lock_ref = json.loads(
            (root / ".harness/harness.lock.json").read_text(encoding="utf-8")
        )["source"]["ref"]
        original_check_update = command_dispatch_module.check_update
        original_apply_update = command_dispatch_module.apply_update
        command_dispatch_module.check_update = lambda _root, target=None: {
            "status": "PASS",
            "current": lock_ref,
            "resolvedTarget": target or lock_ref,
            "route": [lock_ref],
            "checkedThrough": lock_ref,
        }
        command_dispatch_module.apply_update = lambda _root, target=None: {
            "status": "NO_UPDATE",
            "current": lock_ref,
            "resolvedTarget": target or lock_ref,
            "route": [lock_ref],
        }
        try:
            update_done = start_dispatch(
                root,
                f"HARNESS UPDATE CHECK TO {lock_ref} > APPLY",
            )
        finally:
            command_dispatch_module.check_update = original_check_update
            command_dispatch_module.apply_update = original_apply_update
        assert update_done["status"] == "DONE", update_done
        assert update_done["result"]["status"] == "SUCCESS", update_done
        assert update_done["result"]["engineStatus"] == "NO_UPDATE", update_done
        assert update_done["result"]["nextAction"] is None, update_done

        # HARNESS RESUME не создаёт отдельную root execution и возвращает
        # semantic handoff существующей interrupted command.
        interrupted = start_dispatch(root, "PROJECT QUICK FIX: resume test")
        assert interrupted["status"] == "SEMANTIC", interrupted
        count_before_resume = len(load_status(root)["executions"])
        resumed = start_dispatch(root, "HARNESS RESUME")
        count_after_resume = len(load_status(root)["executions"])
        assert resumed["status"] == "SEMANTIC", resumed
        assert resumed["rootCommand"] == interrupted["rootCommand"], resumed
        assert resumed["command"] == interrupted["command"], resumed
        assert count_before_resume == count_after_resume
        complete_dispatch(
            root,
            resumed["rootCommand"],
            resumed["command"],
            "SUCCESS",
        )

    print("COMMAND DISPATCH SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
