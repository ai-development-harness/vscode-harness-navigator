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
    plan_session_entry,
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

    # Основное правило #286: Claude PLAN → Codex IMPLEMENT не является
    # восстановлением Claude-сессии и не требует никакого handshake.
    claude_to_codex = plan_session_entry(
        contract, "codex",
        entry_kind="new-command",
        previous_runtime_id="claude",
    )
    assert claude_to_codex["action"] == "start", claude_to_codex
    assert claude_to_codex["reasonCode"] == "NEW_CANONICAL_COMMAND", claude_to_codex
    assert "contextSource" not in claude_to_codex

    codex_to_claude = plan_session_entry(
        contract, "claude",
        entry_kind="new-command",
        previous_runtime_id="codex",
    )
    assert codex_to_claude["action"] == "start", codex_to_claude

    # При прерванном IMPLEMENT другой runtime начинает fresh native session,
    # но контекст восстанавливается из authoritative state Harness.
    for source, target in (("claude", "codex"), ("codex", "claude")):
        recovery = plan_session_entry(
            contract, target, entry_kind="recover-command",
            previous_runtime_id=source,
            native_session_handle="other-provider-session",
            native_session_compatible=True,
            canonical_reentry_safe=True,
        )
        assert recovery["action"] == "start", recovery
        assert recovery["contextSource"] == "harness-authoritative-state", recovery
        assert "native_session_handle" not in recovery

    # Сессия того же provider используется, только если сам provider
    # доказал совместимость. Неизвестная/просроченная сессия не блокирует STEP.
    native = plan_session_entry(
        contract, "codex", entry_kind="recover-command",
        previous_runtime_id="codex", native_session_handle="session-1",
        native_session_compatible=True, canonical_reentry_safe=True,
    )
    assert native["action"] == "resume", native
    expired = plan_session_entry(
        contract, "codex", entry_kind="recover-command",
        previous_runtime_id="codex", native_session_handle="session-1",
        native_session_compatible=False, canonical_reentry_safe=True,
    )
    assert expired["action"] == "start", expired
    unknown = plan_session_entry(
        contract, "codex", entry_kind="recover-command",
        previous_runtime_id="codex", native_session_handle="session-1",
        canonical_reentry_safe=True,
    )
    assert unknown["action"] == "start", unknown

    # Необязательный MCP не блокирует workflow, а действительно необходимый
    # capability проверяется только при явном запросе со стороны команды.
    no_mcp = deepcopy(contract)
    no_mcp["adapters"]["claude"]["capabilities"]["toolMcp"] = "unsupported"
    optional = plan_session_entry(no_mcp, "claude", entry_kind="new-command")
    assert optional["action"] == "start", optional
    required = plan_session_entry(
        no_mcp, "claude", entry_kind="new-command",
        required_capabilities=["toolMcp"],
    )
    assert required["action"] == "blocked", required
    assert required["reasonCode"] == "REQUIRED_CAPABILITY_UNAVAILABLE"

    # Unsafe canonical recovery блокируется НЕ из-за смены провайдера.
    unsafe = plan_session_entry(
        contract, "codex", entry_kind="recover-command",
        previous_runtime_id="claude", canonical_reentry_safe=False,
    )
    assert unsafe["action"] == "blocked", unsafe
    assert unsafe["reasonCode"] == "CANONICAL_REENTRY_UNPROVEN"
    unknown_proof = plan_session_entry(
        contract, "codex", entry_kind="recover-command",
        previous_runtime_id="claude",
    )
    assert unknown_proof["action"] == "blocked", unknown_proof

    # Runtime invariants выражены в machine contract, а не только в docs.
    changed = deepcopy(contract)
    changed["invariants"]["crossRuntimeCommands"] = "requires-migration"
    assert any(
        "crossRuntimeCommands" in error for error in validate_contract(changed)
    )

    print("RUNTIME ADAPTER CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
