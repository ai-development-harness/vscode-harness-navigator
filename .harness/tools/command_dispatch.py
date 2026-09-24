#!/usr/bin/env python3
"""Deterministic command dispatcher AI Development Harness.

Dispatcher объединяет уже существующие contracts в одну runtime boundary:

raw command
  -> CTS structural validation
  -> execution state
  -> deterministic command handler ИЛИ semantic handoff
  -> completion
  -> resolver следующего segment

Он не выполняет LLM reasoning и не читает product source. Для semantic command
возвращается только canonical skill + phase-specific STEP context, если он нужен.
Таким образом root-model больше не воспроизводит orchestration вручную.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from command_transitions import (
    dispatch_spec,
    load_transition_table,
    parse_canonical_command,
    validate_command_text,
    validate_transition_table,
)
from execution_status import (
    begin_command,
    block_execution,
    complete_command,
    git_commit_completion_proven,
    load_status,
    resolve_execution,
    normalize_single_command,
    resolve_root,
    running_command_for,
    stamp_review_expectation,
    start_execution,
)
from git_action import GitActionError, execute_pr_finish, execute_push, execute_sync
from git_preflight import GitPreflightError, check as git_check
from harness_help import help_catalog
from harness_update import UpdateError, apply_update, check_update
from harness_ux import (
    harness_config,
    harness_doctor,
    harness_resume,
    harness_status,
    project_status,
    step_list,
    step_show,
)
from planning_contract import step_completion_proof
from step_context import build_step_context
from step_next import resolve_step_action, resolve_step_next
from verification import run_step_verification


SCHEMA_VERSION = 1


class DispatchError(RuntimeError):
    """Fail-closed ошибка deterministic dispatcher."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _table(root: Path) -> dict[str, Any]:
    table = load_transition_table(root)
    errors = validate_transition_table(table)
    if errors:
        raise DispatchError(
            "INVALID_TRANSITION_TABLE",
            "; ".join(errors),
        )
    return table


def route_command(root: Path, command: str) -> dict[str, Any]:
    """Разрешить одну canonical command в exact dispatch contract."""
    table = _table(root)
    parsed = parse_canonical_command(command, table)
    if not parsed.get("valid"):
        raise DispatchError(
            str(parsed.get("code") or "INVALID_COMMAND"),
            str(parsed.get("message") or "cannot parse canonical command"),
        )
    spec = dispatch_spec(
        table,
        str(parsed["domain"]),
        str(parsed["operation"]),
    )
    return {
        "command": parsed["normalized"],
        "domain": parsed["domain"],
        "operation": parsed["operation"],
        "target": parsed.get("target"),
        "input": parsed.get("input"),
        "dispatch": spec,
    }


def _execution_identity(execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "executionId": execution.get("executionId"),
        "rootCommand": execution.get("rootCommand"),
    }


def _block_recording_error(
    root: Path,
    root_command: str,
    *,
    command: str | None,
) -> str | None:
    """Зафиксировать blocker; вернуть ошибку записи state вместо её сокрытия.

    Если blocker не удалось сохранить, execution остаётся running: caller
    обязан сообщить это в BLOCKED ответе (`stateWriteError`), а не молчать (#117).
    """
    try:
        block_execution(root, root_command, command=command)
    except (OSError, ValueError) as exc:
        return str(exc)
    return None


def _active_execution(root: Path, root_command: str) -> dict[str, Any] | None:
    """Найти active execution без изменения attempt/resolver state."""
    status = load_status(root)
    for execution in reversed(status.get("executions", [])):
        if (
            execution.get("rootCommand") == root_command
            and execution.get("status") == "running"
        ):
            return execution
    return None


def _step_run_completion_gate(
    root: Path,
    root_command: str,
    command: str,
    result: str,
) -> dict[str, Any] | None:
    """STEP RUN SUCCESS допустим только с type-specific completion proof.

    Non-coding types (research/adr/audit/…) завершаются semantic handoff-ом;
    без этой проверки их RUN закрывался бы одним словом модели (#113).
    """
    if result != "SUCCESS":
        return None
    route = route_command(root, command)
    if route.get("domain") != "STEP" or route.get("operation") != "RUN":
        return None
    step_id = route.get("target")
    if not isinstance(step_id, str) or not step_id:
        return None
    try:
        proof = step_completion_proof(root, step_id)
    except (OSError, ValueError) as exc:
        proof = {"complete": False, "reasons": [str(exc)]}
    if proof.get("complete") is True:
        return None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "BLOCKED",
        "rootCommand": root_command,
        "command": command,
        "reasonCode": "STEP_COMPLETION_PROOF_FAILED",
        "details": {"reasons": proof.get("reasons", [])},
    }


def _verification_before_completion(
    root: Path,
    root_command: str,
    command: str,
    result: str,
    details: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Enforce Verification before IMPLEMENT/FIX SUCCESS.

    Первый элемент tuple — early dispatcher response. None означает, что
    completion разрешён. Второй — compact details для durable execution state.
    """
    # PASS для IMPLEMENT/FIX не имеет CTS edge, но всё равно завершает команду;
    # он не должен становиться обходом Verification (#113).
    if result not in {"SUCCESS", "PASS"}:
        return None, details

    route = route_command(root, command)
    if route.get("domain") != "STEP" or route.get("operation") not in {
        "IMPLEMENT",
        "FIX",
    }:
        return None, details

    step_id = route.get("target")
    if not isinstance(step_id, str) or not step_id:
        return (
            {
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                "rootCommand": root_command,
                "command": command,
                "reasonCode": "VERIFICATION_STEP_TARGET_MISSING",
            },
            None,
        )

    manual_results = None
    if isinstance(details, dict):
        value = details.get("manualVerification")
        if value is not None:
            manual_results = value

    verification = run_step_verification(
        root,
        step_id,
        manual_results=manual_results,
        write_evidence=True,
    )
    verification_status = verification.get("status")

    if verification_status == "PASS":
        compact = {
            key: value
            for key, value in (details or {}).items()
            if key != "manualVerification"
        }
        compact["verification"] = {
            "status": "PASS",
            "runAt": verification.get("runAt"),
            "revision": verification.get("revision"),
        }
        return None, compact

    if verification_status in {"FAIL", "MANUAL_REQUIRED"}:
        execution = _active_execution(root, root_command)
        if execution is None:
            return (
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "BLOCKED",
                    "rootCommand": root_command,
                    "command": command,
                    "reasonCode": "ACTIVE_EXECUTION_NOT_FOUND",
                    "verification": verification,
                },
                None,
            )
        handoff = _semantic_handoff(root, execution, command)
        handoff["reasonCode"] = "VERIFICATION_" + str(verification_status)
        handoff["verification"] = verification
        return handoff, None

    state_error = _block_recording_error(root, root_command, command=command)
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            **({"stateWriteError": state_error} if state_error else {}),
            "reasonCode": verification.get(
                "reasonCode",
                "VERIFICATION_BLOCKED",
            ),
            "verification": verification,
        },
        None,
    )


def _semantic_handoff(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]
    if dispatch.get("kind") != "semantic":
        raise DispatchError(
            "NOT_SEMANTIC",
            f"{command} is not a semantic dispatch",
        )

    skill = str(dispatch["skill"])
    skill_path = root / ".agents" / "skills" / skill / "SKILL.md"
    if not skill_path.is_file():
        raise DispatchError(
            "SKILL_MISSING",
            f"dispatch skill does not exist: {skill}",
        )

    context: dict[str, Any] | None = None
    context_phase = dispatch.get("contextPhase")
    if context_phase is not None:
        target = route.get("target")
        if not isinstance(target, str) or not target:
            raise DispatchError(
                "CONTEXT_TARGET_MISSING",
                f"{command}: contextPhase requires STEP target",
            )
        baseline = execution.get("implementationBaseline")
        context = build_step_context(
            root,
            target,
            str(context_phase),
            implementation_baseline=(
                baseline if isinstance(baseline, dict) else None
            ),
        )
        if context.get("status") != "PASS":
            raise DispatchError(
                "STEP_CONTEXT_BLOCKED",
                f"{command}: deterministic STEP context is not PASS",
            )

        # STEP REVIEW semantic reasoning must be bound to the exact deterministic
        # revision/gate that was handed to the reviewer. Persist this proof in
        # execution state before returning the handoff; the model never supplies
        # or rewrites it in semantic payload.
        if str(context_phase) == "review":
            deterministic = context.get("deterministic")
            if not isinstance(deterministic, dict):
                raise DispatchError(
                    "REVIEW_EXPECTATION_INVALID",
                    f"{command}: deterministic review context is missing",
                )
            revision = deterministic.get("repositoryRevision")
            gate = deterministic.get("specializedReviewGate")
            gate_basis = gate.get("basis") if isinstance(gate, dict) else None
            try:
                stamp_review_expectation(
                    root,
                    str(execution.get("executionId") or ""),
                    target,
                    revision if isinstance(revision, dict) else {},
                    str(gate_basis or ""),
                )
            except ValueError as exc:
                raise DispatchError(
                    "REVIEW_EXPECTATION_INVALID",
                    f"{command}: {exc}",
                ) from exc

    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "SEMANTIC",
        **_execution_identity(execution),
        "command": route["command"],
        "skill": skill,
        "skillPath": skill_path.relative_to(root).as_posix(),
        "commandData": {
            "domain": route["domain"],
            "operation": route["operation"],
            "target": route.get("target"),
            "input": route.get("input"),
        },
    }
    if context is not None:
        result["context"] = context
    return result



CODING_STEP_TYPES = {"implementation", "bugfix", "refactor", "hardening"}


def _update_target(route: dict[str, Any]) -> str | None:
    target = route.get("target")
    return str(target) if isinstance(target, str) and target else None


def _machine_completion_details(
    *,
    handler: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Persist only exact machine facts needed by continuation/recovery."""

    details: dict[str, Any] = {
        "dispatch": {
            "kind": "deterministic",
            "handler": handler,
            "status": result.get("status"),
        }
    }
    extra = result.get("executionDetails")
    if isinstance(extra, dict):
        details.update(extra)
    return details


def _finish_machine_result(
    root: Path,
    execution: dict[str, Any],
    command: str,
    result: dict[str, Any],
    *,
    handler: str,
) -> dict[str, Any]:
    status = result.get("status")
    if status not in {"PASS", "SUCCESS", "FAIL", "BLOCKED"}:
        raise DispatchError(
            "DETERMINISTIC_RESULT_INVALID",
            f"{command}: unsupported deterministic status {status!r}",
        )

    completed = complete_command(
        root,
        str(execution["rootCommand"]),
        command,
        str(status),
        details=_machine_completion_details(handler=handler, result=result),
    )
    resolved = resolve_execution(root, completed)

    if resolved.get("status") == "NEXT" and resolved.get("command"):
        next_command = str(resolved["command"])
        next_execution = begin_command(
            root,
            str(execution["rootCommand"]),
            next_command,
        )
        return _dispatch_running(root, next_execution, next_command)

    # Coding STEP RUN should not wake a model just to ask the resolver what to
    # do after a child command. Once a semantic child is complete, re-enter the
    # deterministic root orchestrator and let it either close the STEP or choose
    # the next child. Special STEP types still fall back to the run-step skill.
    if (
        resolved.get("status") == "RESUME"
        and resolved.get("command") == execution.get("rootCommand")
        and str(execution.get("rootCommand", "")).startswith("STEP RUN ")
    ):
        root_command = str(execution["rootCommand"])
        root_execution = begin_command(root, root_command, root_command)
        return _dispatch_running(root, root_execution, root_command)

    return _terminal(completed, resolved, result=result)


def _git_push_after_commit_fast_path(
    root: Path,
    execution: dict[str, Any],
    route: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute PUSH without a model only after COMMIT in the same explicit chain."""

    if route.get("domain") != "GIT" or route.get("operation") != "PUSH":
        return None
    if execution.get("mode") != "chain":
        return None
    sequence = execution.get("sequence")
    index = execution.get("currentIndex")
    if (
        not isinstance(sequence, list)
        or not isinstance(index, int)
        or index <= 0
        or index >= len(sequence)
    ):
        return None
    try:
        previous = route_command(root, str(sequence[index - 1]))
    except DispatchError:
        return None
    if previous.get("domain") != "GIT" or previous.get("operation") != "COMMIT":
        return None

    try:
        result = execute_push(root)
    except (GitActionError, GitPreflightError) as exc:
        return {
            "status": "BLOCKED",
            "reasonCode": exc.code,
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
    result = dict(result)
    result["fastPath"] = "after-canonical-commit"
    return result


def _dispatch_step_run(
    root: Path,
    execution: dict[str, Any],
    route: dict[str, Any],
) -> dict[str, Any]:
    """Use deterministic orchestration for ordinary coding STEP types.

    Non-coding types deliberately keep the semantic run-step fallback because
    ADR/RESEARCH/AUDIT/DOCUMENTATION/RELEASE flows may require type-specific
    semantic work that is not represented by the coding CTS edges.
    """

    target = route.get("target")
    if not isinstance(target, str) or not target:
        raise DispatchError("STEP_TARGET_MISSING", "STEP RUN requires target")

    action = resolve_step_action(root, target)
    step_type = action.get("stepType")
    lifecycle = action.get("lifecycleStatus")

    if isinstance(step_type, str) and step_type not in CODING_STEP_TYPES:
        return _semantic_handoff(root, execution, route["command"])

    if not isinstance(step_type, str):
        result = {
            "status": "BLOCKED",
            "reasonCode": action.get("reasonCode", "STEP_RUN_STATE_INVALID"),
            "message": action.get("message", "cannot resolve STEP type"),
            "details": action,
        }
        return _finish_machine_result(
            root,
            execution,
            route["command"],
            result,
            handler="step-run-orchestrator",
        )

    if lifecycle == "completed":
        proof = step_completion_proof(root, target)
        if proof.get("complete") is True:
            result = {
                "status": "SUCCESS",
                "stepId": target,
                "stepType": step_type,
                "completionProof": proof.get("proof_hash"),
                "orchestration": "already-complete",
            }
        else:
            result = {
                "status": "BLOCKED",
                "reasonCode": "STEP_COMPLETION_PROOF_FAILED",
                "stepId": target,
                "stepType": step_type,
                "details": proof,
            }
        return _finish_machine_result(
            root,
            execution,
            route["command"],
            result,
            handler="step-run-orchestrator",
        )

    if action.get("status") != "PASS":
        result = {
            "status": "BLOCKED",
            "reasonCode": action.get("reasonCode", "STEP_RUN_ACTION_BLOCKED"),
            "stepId": target,
            "stepType": step_type,
            "details": action,
        }
        return _finish_machine_result(
            root,
            execution,
            route["command"],
            result,
            handler="step-run-orchestrator",
        )

    child = action.get("command")
    if not isinstance(child, str) or not child:
        raise DispatchError("STEP_RUN_CHILD_MISSING", f"{target}: no next child command")
    child_execution = begin_command(
        root,
        str(execution["rootCommand"]),
        child,
    )
    return _dispatch_running(root, child_execution, child)


def _deterministic_handler(
    root: Path,
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]
    handler = dispatch.get("handler")

    if handler == "harness-help":
        return {"status": "PASS", "domains": help_catalog(root)}
    if handler == "harness-status":
        return harness_status(root)
    if handler == "harness-doctor":
        return harness_doctor(root)
    if handler == "harness-config":
        return harness_config(root)
    if handler == "project-status":
        return project_status(root)
    if handler == "harness-update-check":
        try:
            result = check_update(root, target=_update_target(route))
        except (UpdateError, OSError, ValueError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": getattr(exc, "code", "CONFIG_OR_IO_ERROR"),
                "message": str(exc),
            }
        result = dict(result)
        result["executionDetails"] = {
            "resolvedTarget": result.get("resolvedTarget"),
            "route": result.get("route"),
            "lockRef": result.get("current"),
        }
        return result
    if handler == "harness-update-apply":
        try:
            raw = apply_update(root, target=_update_target(route))
        except (UpdateError, OSError, ValueError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": getattr(exc, "code", "CONFIG_OR_IO_ERROR"),
                "message": str(exc),
            }
        engine_status = raw.get("status")
        if engine_status not in {"UPDATED", "NO_UPDATE", "UPDATER_RELOAD_REQUIRED"}:
            return {
                "status": "BLOCKED",
                "reasonCode": "UPDATE_RESULT_INVALID",
                "details": raw,
            }
        result = dict(raw)
        result["engineStatus"] = engine_status
        result["status"] = "SUCCESS"
        if engine_status == "UPDATER_RELOAD_REQUIRED":
            result["nextAction"] = {
                "kind": "reload-and-repeat",
                "command": route["command"],
            }
        elif engine_status == "UPDATED" or bool(raw.get("repositoryMutated")):
            # NO_UPDATE может всё же завершить deferred pre-INIT project-owned
            # template alignment после обязательного reload. Release ref при
            # этом уже current, но repository diff требует обычный Git gate.
            result["nextAction"] = {
                "kind": "command",
                "command": "GIT CHECK",
            }
        else:
            result["nextAction"] = None
        return result
    if handler == "step-list":
        return step_list(root)
    if handler == "step-show":
        target = route.get("target")
        if not isinstance(target, str) or not target:
            raise DispatchError("STEP_TARGET_MISSING", "STEP SHOW requires target")
        return step_show(root, target)
    if handler == "step-next":
        return resolve_step_next(root)
    if handler == "git-check":
        try:
            return git_check(root)
        except GitPreflightError as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": exc.details,
            }
    if handler == "git-pr-finish":
        try:
            return execute_pr_finish(root)
        except (GitActionError, GitPreflightError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
    if handler == "git-sync":
        try:
            return execute_sync(root)
        except (GitActionError, GitPreflightError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
    if handler == "harness-resume":
        # HARNESS RESUME не создаёт собственную execution. Его special flow
        # обрабатывается start_dispatch()/resume_dispatch().
        return harness_resume(root)

    raise DispatchError(
        "UNSUPPORTED_DETERMINISTIC_HANDLER",
        f"unsupported deterministic handler: {handler}",
    )


def _terminal(
    execution: dict[str, Any],
    resolved: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": resolved.get("status"),
        **_execution_identity(execution),
        "command": resolved.get("command"),
        "reasonCode": resolved.get("reasonCode"),
    }
    if result is not None:
        value["result"] = result
    if resolved.get("notExecuted") is not None:
        value["notExecuted"] = resolved.get("notExecuted")
    return value


def _dispatch_running(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]

    if (
        route.get("domain") == "STEP"
        and route.get("operation") == "RUN"
        and execution.get("mode") == "orchestration"
    ):
        return _dispatch_step_run(root, execution, route)

    if dispatch.get("kind") == "semantic":
        fast = _git_push_after_commit_fast_path(root, execution, route)
        if fast is None:
            return _semantic_handoff(root, execution, route["command"])
        return _finish_machine_result(
            root,
            execution,
            route["command"],
            fast,
            handler="git-push-after-commit",
        )

    result = _deterministic_handler(root, route["command"])
    return _finish_machine_result(
        root,
        execution,
        route["command"],
        result,
        handler=str(dispatch.get("handler") or "unknown"),
    )


def start_dispatch(root: Path, raw_command: str) -> dict[str, Any]:
    """Начать explicit user command и вернуть result либо semantic handoff."""
    table = _table(root)
    structural = validate_command_text(raw_command, table)
    if not structural.get("valid"):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": structural.get("code"),
            "message": structural.get("message"),
        }

    normalized = list(structural.get("normalized") or [])
    if normalized == ["HARNESS RESUME"]:
        return resume_dispatch(root)

    try:
        execution = start_execution(root, raw_command)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": "EXECUTION_START_BLOCKED",
            "message": str(exc),
        }

    current = execution.get("current") or {}
    command = current.get("command")
    if not isinstance(command, str) or not command:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            **_execution_identity(execution),
            "reasonCode": "CURRENT_COMMAND_MISSING",
        }
    try:
        return _dispatch_running(root, execution, command)
    except (DispatchError, OSError, ValueError) as exc:
        state_error = _block_recording_error(
            root,
            str(execution["rootCommand"]),
            command=command,
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            **_execution_identity(execution),
            "command": command,
            **({"stateWriteError": state_error} if state_error else {}),
            "reasonCode": getattr(exc, "code", "DISPATCH_BLOCKED"),
            "message": str(exc),
        }


def complete_dispatch(
    root: Path,
    root_command: str,
    command: str,
    result: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Зафиксировать semantic result и сразу dispatch-нуть continuation."""

    # The PUSH fast-path is allowed only when the preceding COMMIT has a
    # deterministic repository postcondition. This prevents a semantic
    # SUCCESS claim from skipping the scope boundary without an actual commit.
    active = _active_execution(root, root_command)
    if active is not None and result == "SUCCESS":
        route = route_command(root, command)
        sequence = active.get("sequence")
        index = active.get("currentIndex")
        push_follows = (
            active.get("mode") == "chain"
            and isinstance(sequence, list)
            and isinstance(index, int)
            and index + 1 < len(sequence)
            and sequence[index + 1] == "GIT PUSH"
        )
        if (
            push_follows
            and route.get("domain") == "GIT"
            and route.get("operation") == "COMMIT"
            and not git_commit_completion_proven(root, active)
        ):
            try:
                blocked = block_execution(root, root_command, command=command)
            except (OSError, ValueError):
                blocked = active
            return {
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                **_execution_identity(blocked),
                "command": command,
                "reasonCode": "COMMIT_POSTCONDITION_FAILED",
                "message": "GIT COMMIT reported SUCCESS but repository HEAD did not advance",
            }

    try:
        # Completion принимается только для текущей running команды. Проверка
        # идёт до Verification: чужая команда не должна запускать commands и
        # переписывать Evidence другого STEP (#113).
        normalized_command = normalize_single_command(root, command)["normalized"]
        running = running_command_for(root, root_command)
        if running is None:
            # Нет running команды: complete_command гарантированно отклонит
            # completion с точной причиной (already complete/blocked/not found).
            complete_command(root, root_command, command, result, details=details)
            raise ValueError("execution has no running command")
        if running != normalized_command:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                "rootCommand": root_command,
                "command": command,
                "reasonCode": "COMMAND_NOT_CURRENT",
                "message": f"current running command is {running!r}, not {normalized_command!r}",
            }

        early = _step_run_completion_gate(root, root_command, command, result)
        if early is not None:
            return early

        early, completion_details = _verification_before_completion(
            root,
            root_command,
            command,
            result,
            details,
        )
        if early is not None:
            return early

        execution = complete_command(
            root,
            root_command,
            command,
            result,
            details=completion_details,
        )
        resolved = resolve_execution(root, execution)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            "reasonCode": "EXECUTION_COMPLETE_BLOCKED",
            "message": str(exc),
        }

    if resolved.get("status") == "NEXT" and resolved.get("command"):
        next_command = str(resolved["command"])
        try:
            execution = begin_command(root, root_command, next_command)
            return _dispatch_running(root, execution, next_command)
        except (DispatchError, OSError, ValueError) as exc:
            state_error = _block_recording_error(root, root_command, command=next_command)
            return {
                **({"stateWriteError": state_error} if state_error else {}),
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                **_execution_identity(execution),
                "command": next_command,
                "reasonCode": getattr(exc, "code", "NEXT_DISPATCH_BLOCKED"),
                "message": str(exc),
            }

    if (
        resolved.get("status") == "RESUME"
        and resolved.get("command") == root_command
        and root_command.startswith("STEP RUN ")
    ):
        try:
            execution = begin_command(root, root_command, root_command)
            return _dispatch_running(root, execution, root_command)
        except (DispatchError, OSError, ValueError) as exc:
            state_error = _block_recording_error(root, root_command, command=root_command)
            return {
                **({"stateWriteError": state_error} if state_error else {}),
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                **_execution_identity(execution),
                "command": root_command,
                "reasonCode": getattr(exc, "code", "ORCHESTRATION_DISPATCH_BLOCKED"),
                "message": str(exc),
            }

    return _terminal(execution, resolved)


def resume_dispatch(
    root: Path,
    root_command: str | None = None,
) -> dict[str, Any]:
    """Продолжить explicit root либо единственную resumable execution."""
    if root_command is None:
        selection = harness_resume(root)
        if selection.get("status") != "PASS":
            return {
                "schemaVersion": SCHEMA_VERSION,
                **selection,
            }
        root_command = str(selection["rootCommand"])

    resolved = resolve_root(root, root_command)
    if resolved.get("status") not in {"RESUME", "NEXT"} or not resolved.get("command"):
        return {
            "schemaVersion": SCHEMA_VERSION,
            **resolved,
        }

    command = str(resolved["command"])
    try:
        execution = begin_command(root, root_command, command)
        return _dispatch_running(root, execution, command)
    except (DispatchError, OSError, ValueError) as exc:
        state_error = _block_recording_error(root, root_command, command=command)
        return {
            **({"stateWriteError": state_error} if state_error else {}),
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            "reasonCode": getattr(exc, "code", "RESUME_DISPATCH_BLOCKED"),
            "message": str(exc),
        }


__all__ = [
    "DispatchError",
    "complete_dispatch",
    "resume_dispatch",
    "route_command",
    "start_dispatch",
]
