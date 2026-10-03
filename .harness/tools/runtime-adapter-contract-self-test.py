#!/usr/bin/env python3
"""Synthetic tests provider-neutral Runtime Adapter Contract."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".harness/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from runtime_adapter_contract import (
    RuntimeContractError,
    capability_snapshot,
    load_contract,
    normalize_event,
    require_capability,
    validate_contract,
)


def main() -> int:
    contract = load_contract(ROOT)
    assert not validate_contract(contract), validate_contract(contract)

    codex = capability_snapshot(contract, "codex")
    claude = capability_snapshot(contract, "claude")
    assert codex["runtimeId"] == "codex"
    assert claude["runtimeId"] == "claude"
    assert require_capability(codex, "streaming") == "native"
    assert require_capability(claude, "structuredOutput") == "synthesized"

    event = normalize_event(
        {
            "type": "model.message.delta",
            "runtimeId": "codex",
            "sessionId": "session-1",
            "executionId": "execution-1",
            "data": {"text": "hello"},
            "providerMetadata": {"providerEvent": "opaque"},
        }
    )
    assert event["schemaVersion"] == 1
    assert event["type"] == "model.message.delta"
    assert event["providerMetadata"]["providerEvent"] == "opaque"

    broken = deepcopy(contract)
    broken["adapters"]["codex"]["capabilities"].pop("resume")
    errors = validate_contract(broken)
    assert any("capabilities missing: resume" in item for item in errors), errors

    unsupported = deepcopy(codex)
    unsupported["capabilities"]["cancel"] = "unsupported"
    try:
        require_capability(unsupported, "cancel")
    except RuntimeContractError as exc:
        assert "does not support cancel" in str(exc)
    else:
        raise AssertionError("unsupported capability did not fail explicitly")

    try:
        normalize_event({"type": "provider.private.event", "runtimeId": "codex"})
    except RuntimeContractError as exc:
        assert "event type" in str(exc)
    else:
        raise AssertionError("unknown provider event leaked into normalized contract")

    try:
        normalize_event(
            {
                "type": "run.started",
                "runtimeId": "claude",
                "secret": "must-not-exist",
            }
        )
    except RuntimeContractError as exc:
        assert "unsupported keys" in str(exc)
    else:
        raise AssertionError("unknown event field was accepted")

    print("RUNTIME ADAPTER CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
