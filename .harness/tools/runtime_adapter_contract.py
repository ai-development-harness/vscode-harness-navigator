#!/usr/bin/env python3
"""Provider-neutral Runtime Adapter Contract for AI Development Harness.

This module validates the tracked machine-readable runtime contract and offers
small deterministic helpers for adapter implementations/clients:
- capability negotiation;
- normalized runtime events;
- explicit unsupported capability handling.

The control plane remains the owner of canonical Harness command semantics.
Adapters only translate runtime lifecycle/auth/streaming details.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CONTRACT_PATH = ".harness/runtime-adapter-contract.json"
CONTRACT_ID = "harness.runtime-adapter"
SCHEMA_VERSION = 1

METHODS = {
    "getIdentity",
    "getCapabilities",
    "getAccount",
    "start",
    "resume",
    "cancel",
    "status",
}
CAPABILITIES = {
    "runtimeIdentity",
    "authenticatedAccount",
    "modelEffort",
    "interactiveInput",
    "streaming",
    "resume",
    "cancel",
    "subagents",
    "structuredOutput",
    "toolMcp",
    "sessionExecutionIds",
}
EVENT_TYPES = {
    "run.started",
    "model.message.delta",
    "model.message.completed",
    "tool.started",
    "tool.completed",
    "input.required",
    "auth.required",
    "run.interrupted",
    "run.completed",
    "run.failed",
}
SUPPORT_STATES = {"native", "synthesized", "unsupported"}


class RuntimeContractError(ValueError):
    """Malformed runtime adapter contract or normalized event."""


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeContractError(f"cannot read {CONTRACT_PATH}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeContractError(f"invalid JSON in {CONTRACT_PATH}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeContractError("runtime adapter contract root must be an object")
    return value


def _string_set(value: Any, label: str) -> set[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeContractError(f"{label} must be a string array")
    if len(value) != len(set(value)):
        raise RuntimeContractError(f"{label} must not contain duplicates")
    return set(value)


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")
    if contract.get("contractId") != CONTRACT_ID:
        errors.append(f"contractId must be {CONTRACT_ID}")

    for field, expected in (
        ("methods", METHODS),
        ("capabilities", CAPABILITIES),
        ("events", EVENT_TYPES),
        ("supportStates", SUPPORT_STATES),
    ):
        try:
            actual = _string_set(contract.get(field), field)
        except RuntimeContractError as exc:
            errors.append(str(exc))
            continue
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing:
            errors.append(f"{field} missing: {', '.join(missing)}")
        if unknown:
            errors.append(f"{field} unknown: {', '.join(unknown)}")

    invariants = contract.get("invariants")
    if not isinstance(invariants, dict):
        errors.append("invariants must be an object")
    else:
        if invariants.get("commandSemanticsOwnedBy") != "harness-control-plane":
            errors.append(
                "invariants.commandSemanticsOwnedBy must be harness-control-plane"
            )
        if invariants.get("providerMetadataOptional") is not True:
            errors.append("invariants.providerMetadataOptional must be true")
        if invariants.get("secretsPersistence") != "forbidden":
            errors.append("invariants.secretsPersistence must be forbidden")
        if invariants.get("unsupportedCapabilities") != "explicit":
            errors.append("invariants.unsupportedCapabilities must be explicit")
        if invariants.get("versioning") != "required":
            errors.append("invariants.versioning must be required")
        if invariants.get("crossRuntimeCommands") != "seamless":
            errors.append("invariants.crossRuntimeCommands must be seamless")
        if invariants.get("nativeSessionReuse") != "best-effort":
            errors.append("invariants.nativeSessionReuse must be best-effort")
        if invariants.get("runtimeChangeInvalidatesIntent") is not False:
            errors.append("invariants.runtimeChangeInvalidatesIntent must be false")

    adapters = contract.get("adapters")
    if not isinstance(adapters, dict) or not adapters:
        errors.append("adapters must be a non-empty object")
        return errors

    for adapter_id, adapter in sorted(adapters.items()):
        prefix = f"adapters.{adapter_id}"
        if not isinstance(adapter, dict):
            errors.append(f"{prefix} must be an object")
            continue
        version = adapter.get("adapterVersion")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            errors.append(f"{prefix}.adapterVersion must be a positive integer")

        account = adapter.get("account")
        if not isinstance(account, dict):
            errors.append(f"{prefix}.account must be an object")
        else:
            if account.get("persistence") != "none":
                errors.append(f"{prefix}.account.persistence must be none")
            for key in ("source", "operation"):
                if not isinstance(account.get(key), str) or not account[key].strip():
                    errors.append(f"{prefix}.account.{key} must be a non-empty string")

        lifecycle = adapter.get("lifecycle")
        if not isinstance(lifecycle, dict):
            errors.append(f"{prefix}.lifecycle must be an object")
        else:
            for key in ("start", "resume", "cancel", "status"):
                if not isinstance(lifecycle.get(key), str) or not lifecycle[key].strip():
                    errors.append(f"{prefix}.lifecycle.{key} must be a non-empty string")

        capabilities = adapter.get("capabilities")
        if not isinstance(capabilities, dict):
            errors.append(f"{prefix}.capabilities must be an object")
            continue
        missing = sorted(CAPABILITIES - set(capabilities))
        unknown = sorted(set(capabilities) - CAPABILITIES)
        if missing:
            errors.append(f"{prefix}.capabilities missing: {', '.join(missing)}")
        if unknown:
            errors.append(f"{prefix}.capabilities unknown: {', '.join(unknown)}")
        for name, state in sorted(capabilities.items()):
            if state not in SUPPORT_STATES:
                errors.append(
                    f"{prefix}.capabilities.{name} must be one of "
                    + ", ".join(sorted(SUPPORT_STATES))
                )
    return errors


def capability_snapshot(
    contract: dict[str, Any],
    runtime_id: str,
) -> dict[str, Any]:
    adapters = contract.get("adapters")
    if not isinstance(adapters, dict) or runtime_id not in adapters:
        raise RuntimeContractError(f"unknown runtime adapter: {runtime_id}")
    adapter = adapters[runtime_id]
    errors = validate_contract(contract)
    if errors:
        raise RuntimeContractError("; ".join(errors))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runtimeId": runtime_id,
        "adapterVersion": adapter["adapterVersion"],
        "capabilities": adapter["capabilities"],
    }


def require_capability(
    snapshot: dict[str, Any],
    capability: str,
) -> str:
    if capability not in CAPABILITIES:
        raise RuntimeContractError(f"unknown capability: {capability}")
    values = snapshot.get("capabilities")
    if not isinstance(values, dict):
        raise RuntimeContractError("capability snapshot is malformed")
    state = values.get(capability)
    if state not in SUPPORT_STATES:
        raise RuntimeContractError(f"capability state is invalid: {capability}")
    if state == "unsupported":
        raise RuntimeContractError(
            f"runtime {snapshot.get('runtimeId')} does not support {capability}"
        )
    return state


def plan_session_entry(
    contract: dict[str, Any],
    runtime_id: str,
    *,
    entry_kind: str,
    previous_runtime_id: str | None = None,
    native_session_handle: str | None = None,
    native_session_compatible: bool | None = None,
    canonical_reentry_safe: bool | None = None,
    required_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Решить только вопрос *нативной сессии*, не право выполнить STEP.

    PLAN в Claude и IMPLEMENT в Codex — два независимых canonical commands.
    Они не требуют совместимости runtime-сессий. При recovery Harness сначала
    доказывает безопасность через CTS/intent/side-effect contracts; здесь
    используется уже готовый результат, а не provider-specific предположение.

    Не возвращаем native handle и не сохраняем account/provider credentials.
    """
    if entry_kind not in {"new-command", "recover-command"}:
        raise RuntimeContractError("entry_kind must be new-command or recover-command")
    snapshot = capability_snapshot(contract, runtime_id)
    requirements = required_capabilities or []
    if (
        not isinstance(requirements, list)
        or any(not isinstance(value, str) for value in requirements)
    ):
        raise RuntimeContractError("required_capabilities must be a string array")

    def decision(action: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "runtimeId": runtime_id,
            "action": action,
            "reasonCode": reason,
            **extra,
        }

    # Отсутствующий необязательный MCP/capability не является blocker.
    # Проверяем только то, что конкретная команда действительно потребовала.
    for capability in requirements:
        try:
            require_capability(snapshot, capability)
        except RuntimeContractError as exc:
            return decision(
                "blocked", "REQUIRED_CAPABILITY_UNAVAILABLE",
                capability=capability, message=str(exc),
            )

    if entry_kind == "new-command":
        return decision("start", "NEW_CANONICAL_COMMAND")

    # Внутреннюю сессию нельзя использовать как доказательство безопасного
    # восстановления команды: этот guard полностью принадлежит Harness.
    if canonical_reentry_safe is not True:
        return decision("blocked", "CANONICAL_REENTRY_UNPROVEN")

    same_runtime = previous_runtime_id == runtime_id
    has_handle = isinstance(native_session_handle, str) and bool(native_session_handle.strip())
    resume_support = snapshot["capabilities"]["resume"] != "unsupported"

    if same_runtime and has_handle and native_session_compatible is True and resume_support:
        return decision("resume", "NATIVE_SESSION_COMPATIBLE")

    # Другая модель, обновлённый CLI, потерянный handle или неизвестная
    # совместимость не должны запрещать восстановление STEP. Запускаем новую
    # сессию и восстанавливаем только authoritative Harness context.
    return decision(
        "start", "CANONICAL_FRESH_SESSION",
        contextSource="harness-authoritative-state",
    )


def normalize_event(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeContractError("runtime event must be an object")
    allowed = {
        "type",
        "runtimeId",
        "sessionId",
        "executionId",
        "timestamp",
        "data",
        "providerMetadata",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RuntimeContractError(
            "runtime event has unsupported keys: " + ", ".join(unknown)
        )

    event_type = value.get("type")
    if event_type not in EVENT_TYPES:
        raise RuntimeContractError(
            "runtime event type must be one of: " + ", ".join(sorted(EVENT_TYPES))
        )
    runtime_id = value.get("runtimeId")
    if not isinstance(runtime_id, str) or not runtime_id.strip():
        raise RuntimeContractError("runtime event runtimeId must be a non-empty string")

    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "type": event_type,
        "runtimeId": runtime_id,
    }
    for field in ("sessionId", "executionId", "timestamp"):
        raw = value.get(field)
        if raw is not None:
            if not isinstance(raw, str) or not raw.strip():
                raise RuntimeContractError(
                    f"runtime event {field} must be null or a non-empty string"
                )
            result[field] = raw
    data = value.get("data")
    if data is not None:
        if not isinstance(data, dict):
            raise RuntimeContractError("runtime event data must be null or an object")
        result["data"] = data
    metadata = value.get("providerMetadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise RuntimeContractError(
                "runtime event providerMetadata must be null or an object"
            )
        # Provider-specific metadata is opaque and optional. It must never be
        # required by canonical orchestration decisions.
        result["providerMetadata"] = metadata
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        contract = load_contract(root)
        errors = validate_contract(contract)
        if errors:
            payload: dict[str, Any] = {"status": "FAIL", "errors": errors}
            code = 1
        elif args.runtime:
            payload = {
                "status": "PASS",
                "contract": capability_snapshot(contract, args.runtime),
            }
            code = 0
        else:
            payload = {
                "status": "PASS",
                "schemaVersion": SCHEMA_VERSION,
                "adapters": sorted(contract["adapters"]),
            }
            code = 0
    except RuntimeContractError as exc:
        payload = {"status": "BLOCKED", "errors": [str(exc)]}
        code = 2

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["status"])
        for error in payload.get("errors", []):
            print(f"- {error}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
