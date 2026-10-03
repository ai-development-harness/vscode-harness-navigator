#!/usr/bin/env python3
"""Детерминированный regression suite orchestration/runtime/fault injection."""
from __future__ import annotations

from pathlib import Path
import sys

from command_transitions import load_transition_table, parse_canonical_command
from runtime_adapter_conformance import run_all_declared_adapters
from scripted_runtime import FAULT_POINTS, ScriptedFault, ScriptedRuntime, ScriptedRuntimeError


def _edge_allows(root: Path, source: str, target: str, result: str) -> bool:
    table = load_transition_table(root)
    left = parse_canonical_command(source, table)
    right = parse_canonical_command(target, table)
    if not left.get("valid") or not right.get("valid"):
        return False
    if left.get("domain") != right.get("domain"):
        return False
    domain = table["domains"][left["domain"]]
    return any(
        edge.get("from") == left.get("operation")
        and edge.get("to") == right.get("operation")
        and result in edge.get("onPreviousResult", [])
        for edge in domain.get("transitions", [])
    )


def main() -> int:
    root = Path(__file__).resolve().parents[2]

    # Одна deterministic conformance suite для каждого declared production adapter.
    conformance = run_all_declared_adapters(root)
    assert [item["runtimeId"] for item in conformance] == ["claude", "codex"], conformance
    assert all(item["status"] == "PASS" for item in conformance), conformance

    # Canonical STEP RUN repair path проверяется по реальному CTS, а не по
    # второй transition table, спрятанной внутри test double.
    flow = [
        ("STEP PLAN STEP-001", "SUCCESS"),
        ("STEP IMPLEMENT STEP-001", "SUCCESS"),
        ("STEP REVIEW STEP-001", "FAIL"),
        ("STEP FIX STEP-001", "SUCCESS"),
        ("STEP REVIEW STEP-001", "PASS"),
    ]
    for (source, result), (target, _) in zip(flow, flow[1:]):
        assert _edge_allows(root, source, target, result), (source, result, target)

    runtime = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP PLAN STEP-001",
                    "result": "SUCCESS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"phase": "plan"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP IMPLEMENT STEP-001",
                    "result": "SUCCESS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"phase": "implement"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP REVIEW STEP-001",
                    "result": "FAIL",
                    "events": [
                        {"type": "run.started"},
                        {
                            "type": "model.message.completed",
                            "data": {"findings": ["F-001"]},
                        },
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP FIX STEP-001",
                    "result": "SUCCESS",
                    "sideEffectIdentity": "fix:STEP-001:F-001",
                    "events": [
                        {"type": "run.started"},
                        {"type": "tool.started", "data": {"tool": "edit"}},
                        {"type": "tool.completed", "data": {"tool": "edit"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP REVIEW STEP-001",
                    "result": "PASS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"findings": []}},
                        {"type": "run.completed"},
                    ],
                },
            ]
        }
    )

    results = [runtime.start(command) for command, _result in flow]
    assert [item["result"] for item in results] == [item[1] for item in flow], results
    runtime.assert_complete()

    event_types = [item["type"] for item in runtime.events()]
    assert event_types == [
        "run.started", "model.message.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
        "run.started", "tool.started", "tool.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
    ], event_types

    # После fault за external side effect resume повторяет interaction, но
    # ScriptedRuntime фиксирует side-effect identity только один раз.
    recover = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP FIX STEP-002",
                    "expectResume": "STEP FIX STEP-002",
                    "result": "SUCCESS",
                    "sideEffectIdentity": "fix:STEP-002:F-001",
                    "faultOnce": "after_side_effect_before_observation",
                    "events": [
                        {"type": "run.started"},
                        {"type": "tool.completed", "data": {"tool": "write"}},
                    ],
                }
            ]
        }
    )
    try:
        recover.start("STEP FIX STEP-002")
    except ScriptedFault as exc:
        assert exc.checkpoint == "after_side_effect_before_observation", exc
    else:
        raise AssertionError("fault injection did not interrupt the scripted step")
    resumed = recover.resume("STEP FIX STEP-002")
    assert resumed["result"] == "SUCCESS", resumed
    assert recover.applied_side_effects() == ["fix:STEP-002:F-001"], recover.applied_side_effects()
    assert recover.side_effect_applications() == [
        "fix:STEP-002:F-001"
    ], recover.side_effect_applications()
    assert [event["type"] for event in recover.events()] == [
        "run.started",
        "tool.completed",
    ], recover.events()
    recover.assert_complete()

    # Crash до side effect не должен потерять mutation: resume пересекает boundary
    # ровно один раз после восстановления.
    retry_before_effect = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP FIX STEP-006",
                    "expectResume": "STEP FIX STEP-006",
                    "result": "SUCCESS",
                    "sideEffectIdentity": "fix:STEP-006:F-001",
                    "faultOnce": "before_side_effect",
                }
            ]
        }
    )
    try:
        retry_before_effect.start("STEP FIX STEP-006")
    except ScriptedFault as exc:
        assert exc.checkpoint == "before_side_effect", exc
    else:
        raise AssertionError("before_side_effect did not interrupt")
    retry_before_effect.resume("STEP FIX STEP-006")
    assert retry_before_effect.side_effect_applications() == [
        "fix:STEP-006:F-001"
    ], retry_before_effect.side_effect_applications()
    retry_before_effect.assert_complete()

    # Named checkpoints обязаны находиться на правильной logical boundary,
    # а не только выбрасывать exception с правильным именем.
    before_handoff = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP REVIEW STEP-007",
                    "faultOnce": "before_semantic_handoff",
                    "sideEffectIdentity": "review:STEP-007",
                    "events": [{"type": "run.started"}],
                }
            ]
        }
    )
    try:
        before_handoff.start("STEP REVIEW STEP-007")
    except ScriptedFault:
        pass
    else:
        raise AssertionError("before_semantic_handoff did not interrupt")
    assert before_handoff.events() == [], before_handoff.events()
    assert before_handoff.side_effect_applications() == []

    before_effect = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP FIX STEP-008",
                    "faultOnce": "before_side_effect",
                    "sideEffectIdentity": "fix:STEP-008:F-001",
                    "events": [{"type": "run.started"}],
                }
            ]
        }
    )
    try:
        before_effect.start("STEP FIX STEP-008")
    except ScriptedFault:
        pass
    else:
        raise AssertionError("before_side_effect did not interrupt")
    assert [event["type"] for event in before_effect.events()] == ["run.started"]
    assert before_effect.side_effect_applications() == []

    after_effect = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP FIX STEP-009",
                    "faultOnce": "after_side_effect_before_observation",
                    "sideEffectIdentity": "fix:STEP-009:F-001",
                    "events": [{"type": "run.started"}],
                }
            ]
        }
    )
    try:
        after_effect.start("STEP FIX STEP-009")
    except ScriptedFault:
        pass
    else:
        raise AssertionError("after_side_effect_before_observation did not interrupt")
    assert after_effect.side_effect_applications() == ["fix:STEP-009:F-001"]

    # Каждый declared named fault checkpoint реально исполняется, а не только числится в schema enum.
    for checkpoint in sorted(
        FAULT_POINTS - {"runtime_disconnect", "input_required"}
    ):
        injected = ScriptedRuntime(
            {
                "steps": [
                    {
                        "expect": "STEP IMPLEMENT STEP-099",
                        "faultOnce": checkpoint,
                        **(
                            {"sideEffectIdentity": "fault-side-effect"}
                            if checkpoint in {
                                "after_side_effect_before_observation",
                                "after_observation_before_completion_checkpoint",
                            }
                            else {}
                        ),
                    }
                ]
            }
        )
        try:
            injected.start("STEP IMPLEMENT STEP-099")
        except ScriptedFault as exc:
            assert exc.checkpoint == checkpoint, (checkpoint, exc)
        else:
            raise AssertionError(f"{checkpoint} did not interrupt")

    # Runtime disconnect и input-required — полноценные named interruptions.
    for checkpoint, expected_event in (
        ("runtime_disconnect", "run.interrupted"),
        ("input_required", "input.required"),
    ):
        interrupted = ScriptedRuntime(
            {
                "steps": [
                    {
                        "expect": "STEP IMPLEMENT STEP-003",
                        "faultOnce": checkpoint,
                        "events": [{"type": "run.started"}],
                    }
                ]
            }
        )
        try:
            interrupted.start("STEP IMPLEMENT STEP-003")
        except ScriptedFault as exc:
            assert exc.checkpoint == checkpoint, exc
        else:
            raise AssertionError(f"{checkpoint} did not interrupt")
        assert interrupted.events()[-1]["type"] == expected_event, interrupted.events()

    # Explicit unsupported capability должен падать на точном scenario step.
    unsupported = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP IMPLEMENT STEP-004",
                    "requiresCapability": "interactiveInput",
                }
            ]
        },
        capability_overrides={"interactiveInput": "unsupported"},
    )
    try:
        unsupported.start("STEP IMPLEMENT STEP-004")
    except ScriptedRuntimeError as exc:
        assert "does not support interactiveInput" in str(exc), exc
    else:
        raise AssertionError("unsupported capability was accepted")

    # Failure output содержит exact step, expected и actual interaction.
    mismatch = ScriptedRuntime({"steps": [{"expect": "STEP PLAN STEP-005"}]})
    try:
        mismatch.start("STEP REVIEW STEP-005")
    except ScriptedRuntimeError as exc:
        message = str(exc)
        assert "step 0" in message and "STEP PLAN STEP-005" in message and "STEP REVIEW STEP-005" in message
    else:
        raise AssertionError("scenario mismatch was accepted")

    print("orchestration-harness-self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
