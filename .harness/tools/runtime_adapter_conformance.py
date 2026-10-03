#!/usr/bin/env python3
"""Provider-neutral deterministic conformance checks Runtime Adapter Contract.

Suite проверяет adapter descriptors, capabilities и event envelope без запуска
реального Codex/Claude process. Runtime process/wire checks относятся к
отдельному optional integration layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_adapter_contract import (
    CAPABILITIES,
    EVENT_TYPES,
    RuntimeContractError,
    capability_snapshot,
    load_contract,
    normalize_event,
    require_capability,
    validate_contract,
)


def run_adapter_conformance(root: Path, runtime_id: str) -> dict[str, Any]:
    contract = load_contract(root)
    errors = validate_contract(contract)
    if errors:
        raise RuntimeContractError("; ".join(errors))
    snapshot = capability_snapshot(contract, runtime_id)

    capability_results: dict[str, str] = {}
    for name in sorted(CAPABILITIES):
        state = snapshot["capabilities"][name]
        if state == "unsupported":
            try:
                require_capability(snapshot, name)
            except RuntimeContractError:
                capability_results[name] = "unsupported-explicit"
            else:
                raise RuntimeContractError(
                    f"{runtime_id}.{name}: unsupported capability was accepted"
                )
        else:
            capability_results[name] = require_capability(snapshot, name)

    normalized_events: list[str] = []
    for event_type in sorted(EVENT_TYPES):
        event = normalize_event(
            {
                "type": event_type,
                "runtimeId": runtime_id,
                "sessionId": "conformance-session",
                "executionId": "conformance-execution",
                "data": {"conformance": True},
            }
        )
        if event["type"] != event_type or event["runtimeId"] != runtime_id:
            raise RuntimeContractError(
                f"{runtime_id}: normalized event identity mismatch for {event_type}"
            )
        normalized_events.append(event_type)

    return {
        "schemaVersion": 1,
        "runtimeId": runtime_id,
        "adapterVersion": snapshot["adapterVersion"],
        "capabilities": capability_results,
        "events": normalized_events,
        "status": "PASS",
    }


def run_all_declared_adapters(root: Path) -> list[dict[str, Any]]:
    contract = load_contract(root)
    adapters = contract.get("adapters")
    if not isinstance(adapters, dict):
        raise RuntimeContractError("runtime adapter contract adapters must be an object")
    return [
        run_adapter_conformance(root, runtime_id)
        for runtime_id in sorted(adapters)
    ]


__all__ = ["run_adapter_conformance", "run_all_declared_adapters"]
