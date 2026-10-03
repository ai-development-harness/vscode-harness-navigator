#!/usr/bin/env python3
"""Детерминированный provider-neutral test double RuntimeAdapter.

ScriptedRuntime используется только в тестах и не владеет семантикой Harness
commands: caller передаёт canonical interaction, а double проверяет порядок,
capabilities, normalized events и injected fault checkpoints.

Scenario — обычная Python/JSON-compatible структура. API key, runtime process
и сеть не требуются.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime_adapter_contract import (
    CAPABILITIES,
    RuntimeContractError,
    normalize_event,
    require_capability,
)

FAULT_POINTS = {
    "before_semantic_handoff",
    "after_model_return_before_state_checkpoint",
    "before_side_effect",
    "after_side_effect_before_observation",
    "after_observation_before_completion_checkpoint",
    "during_report_write",
    "during_execution_state_write",
    "runtime_disconnect",
    "input_required",
}


class ScriptedRuntimeError(AssertionError):
    """Несовпадение scenario с точной диагностикой interaction/event."""


@dataclass(frozen=True)
class ScriptedFault(RuntimeError):
    checkpoint: str
    interaction: str
    step_index: int

    def __str__(self) -> str:
        return (
            f"scripted fault at step {self.step_index}: "
            f"{self.interaction} @ {self.checkpoint}"
        )


def _support_map(overrides: dict[str, str] | None = None) -> dict[str, str]:
    values = {name: "native" for name in CAPABILITIES}
    for name, state in (overrides or {}).items():
        if name not in CAPABILITIES:
            raise ScriptedRuntimeError(f"unknown scripted capability: {name}")
        if state not in {"native", "synthesized", "unsupported"}:
            raise ScriptedRuntimeError(
                f"invalid scripted capability state for {name}: {state}"
            )
        values[name] = state
    return values


class ScriptedRuntime:
    """Versioned deterministic test double для Runtime Adapter Contract."""

    schema_version = 1
    runtime_id = "scripted"
    adapter_version = 1

    def __init__(
        self,
        scenario: dict[str, Any],
        *,
        capability_overrides: dict[str, str] | None = None,
    ):
        if not isinstance(scenario, dict):
            raise ScriptedRuntimeError("scenario must be an object")
        steps = scenario.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ScriptedRuntimeError("scenario.steps must be a non-empty array")
        self._steps = deepcopy(steps)
        self._index = 0
        self._events: list[dict[str, Any]] = []
        self._faulted_once: set[int] = set()
        self._side_effect_crossed_steps: set[int] = set()
        self._side_effect_applications: list[str] = []
        self._events_emitted_steps: set[int] = set()
        self._cancelled = False
        self._capabilities = _support_map(capability_overrides)
        self._validate_steps()

    def _validate_steps(self) -> None:
        for index, raw in enumerate(self._steps):
            if not isinstance(raw, dict):
                raise ScriptedRuntimeError(f"scenario.steps[{index}] must be an object")
            allowed = {
                "expect",
                "expectResume",
                "result",
                "events",
                "faultOnce",
                "sideEffectIdentity",
                "requiresCapability",
                "details",
            }
            unknown = sorted(set(raw) - allowed)
            if unknown:
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}] unsupported keys: {', '.join(unknown)}"
                )
            expect = raw.get("expect")
            expect_resume = raw.get("expectResume")
            if not isinstance(expect, str) or not expect.strip():
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].expect must be non-empty"
                )
            if expect_resume is not None and (
                not isinstance(expect_resume, str) or not expect_resume.strip()
            ):
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].expectResume must be null or non-empty"
                )
            events = raw.get("events", [])
            if not isinstance(events, list):
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].events must be an array"
                )
            fault = raw.get("faultOnce")
            if fault is not None and fault not in FAULT_POINTS:
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].faultOnce unknown checkpoint: {fault}"
                )
            identity = raw.get("sideEffectIdentity")
            if identity is not None and (
                not isinstance(identity, str) or not identity.strip()
            ):
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].sideEffectIdentity must be non-empty"
                )
            required = raw.get("requiresCapability")
            if required is not None and required not in CAPABILITIES:
                raise ScriptedRuntimeError(
                    f"scenario.steps[{index}].requiresCapability unknown: {required}"
                )

    def get_identity(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "runtimeId": self.runtime_id,
            "adapterVersion": self.adapter_version,
            "testDouble": True,
        }

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "runtimeId": self.runtime_id,
            "adapterVersion": self.adapter_version,
            "capabilities": deepcopy(self._capabilities),
        }

    def require_capability(self, name: str) -> str:
        try:
            return require_capability(self.get_capabilities(), name)
        except RuntimeContractError as exc:
            raise ScriptedRuntimeError(str(exc)) from exc

    def get_account(self) -> dict[str, Any]:
        return {
            "runtimeId": self.runtime_id,
            "authenticated": True,
            "account": {"kind": "scripted", "displayName": "Deterministic Test Runtime"},
        }

    def _event(
        self,
        raw: dict[str, Any],
        *,
        execution_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        value = dict(raw)
        value.setdefault("runtimeId", self.runtime_id)
        value.setdefault("executionId", execution_id)
        value.setdefault("sessionId", session_id)
        return normalize_event(value)

    def _apply_side_effect_once(
        self,
        raw: dict[str, Any],
        *,
        step_index: int,
    ) -> None:
        """Пересечь synthetic side-effect boundary максимум один раз на logical step."""
        identity = raw.get("sideEffectIdentity")
        if not isinstance(identity, str) or not identity:
            return
        if step_index in self._side_effect_crossed_steps:
            return
        self._side_effect_crossed_steps.add(step_index)
        self._side_effect_applications.append(identity)

    def _maybe_fault_at(
        self,
        raw: dict[str, Any],
        *,
        checkpoint: str,
        interaction: str,
        step_index: int,
    ) -> None:
        """Inject fault только в заявленной logical boundary scenario step."""
        fault = raw.get("faultOnce")
        if (
            fault != checkpoint
            or step_index in self._faulted_once
        ):
            return

        self._faulted_once.add(step_index)
        if checkpoint == "runtime_disconnect":
            self._events.append(
                normalize_event(
                    {
                        "type": "run.interrupted",
                        "runtimeId": self.runtime_id,
                        "data": {"reason": "runtime_disconnect"},
                    }
                )
            )
        elif checkpoint == "input_required":
            self._events.append(
                normalize_event(
                    {
                        "type": "input.required",
                        "runtimeId": self.runtime_id,
                        "data": {"prompt": "scripted input required"},
                    }
                )
            )
        raise ScriptedFault(checkpoint, interaction, step_index)

    def invoke(
        self,
        interaction: str,
        *,
        execution_id: str = "exec-scripted",
        session_id: str = "session-scripted",
        resume: bool = False,
    ) -> dict[str, Any]:
        if self._cancelled:
            raise ScriptedRuntimeError("scripted runtime is cancelled")
        if self._index >= len(self._steps):
            raise ScriptedRuntimeError(
                f"unexpected interaction after scenario end: {interaction}"
            )

        raw = self._steps[self._index]
        expected = (
            raw.get("expectResume")
            if resume and raw.get("expectResume") is not None
            else raw.get("expect")
        )
        if interaction != expected:
            raise ScriptedRuntimeError(
                f"step {self._index} interaction mismatch: "
                f"expected {expected!r}, got {interaction!r}"
            )

        required = raw.get("requiresCapability")
        if isinstance(required, str):
            self.require_capability(required)

        start_index = len(self._events)
        current_index = self._index

        self._maybe_fault_at(
            raw,
            checkpoint="before_semantic_handoff",
            interaction=interaction,
            step_index=current_index,
        )

        if current_index not in self._events_emitted_steps:
            for event_raw in raw.get("events", []):
                if not isinstance(event_raw, dict):
                    raise ScriptedRuntimeError(
                        f"step {self._index} event must be an object"
                    )
                try:
                    self._events.append(
                        self._event(
                            event_raw,
                            execution_id=execution_id,
                            session_id=session_id,
                        )
                    )
                except RuntimeContractError as exc:
                    raise ScriptedRuntimeError(
                        f"step {self._index} invalid normalized event: {exc}"
                    ) from exc
            self._events_emitted_steps.add(current_index)

        for checkpoint in (
            "after_model_return_before_state_checkpoint",
            "runtime_disconnect",
            "input_required",
            "before_side_effect",
        ):
            self._maybe_fault_at(
                raw,
                checkpoint=checkpoint,
                interaction=interaction,
                step_index=current_index,
            )

        self._apply_side_effect_once(raw, step_index=current_index)

        for checkpoint in (
            "after_side_effect_before_observation",
            "after_observation_before_completion_checkpoint",
            "during_report_write",
            "during_execution_state_write",
        ):
            self._maybe_fault_at(
                raw,
                checkpoint=checkpoint,
                interaction=interaction,
                step_index=current_index,
            )
        result = {
            "schemaVersion": 1,
            "runtimeId": self.runtime_id,
            "interaction": interaction,
            "result": raw.get("result", "SUCCESS"),
            "details": deepcopy(raw.get("details") or {}),
            "events": deepcopy(self._events[start_index:]),
            "resumed": resume,
        }
        self._index += 1
        return result

    def start(self, interaction: str, **kwargs: Any) -> dict[str, Any]:
        return self.invoke(interaction, resume=False, **kwargs)

    def resume(self, interaction: str, **kwargs: Any) -> dict[str, Any]:
        return self.invoke(interaction, resume=True, **kwargs)

    def cancel(self) -> dict[str, Any]:
        self._cancelled = True
        return {"status": "CANCELLED", "runtimeId": self.runtime_id}

    def status(self) -> dict[str, Any]:
        return {
            "status": "CANCELLED" if self._cancelled else "READY",
            "runtimeId": self.runtime_id,
            "stepIndex": self._index,
            "remaining": len(self._steps) - self._index,
        }

    def events(self) -> list[dict[str, Any]]:
        return deepcopy(self._events)

    def applied_side_effects(self) -> list[str]:
        """Compatibility projection уникальных identities."""
        return sorted(set(self._side_effect_applications))

    def side_effect_applications(self) -> list[str]:
        """Exact ordered journal фактического пересечения side-effect boundary."""
        return list(self._side_effect_applications)

    def assert_complete(self) -> None:
        if self._index != len(self._steps):
            next_expected = self._steps[self._index].get("expect")
            raise ScriptedRuntimeError(
                f"scenario incomplete at step {self._index}; next expected {next_expected!r}"
            )


__all__ = [
    "FAULT_POINTS",
    "ScriptedFault",
    "ScriptedRuntime",
    "ScriptedRuntimeError",
]
