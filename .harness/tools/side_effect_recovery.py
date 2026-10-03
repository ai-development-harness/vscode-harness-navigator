#!/usr/bin/env python3
"""Internal contract bounded checkpoints для recovery внешних side effects.

Модуль намеренно не является command state machine: допустимые переходы команд
по-прежнему определяет CTS. Здесь фиксируется только состояние одной попытки
необратимой/внешней mutation, чтобы после crash/restart можно было сначала
сверить repository/provider facts и только потом решать retry/complete/BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

CONTRACT_VERSION = 1
PHASES = (
    "prepared",
    "side_effect_started",
    "side_effect_observed",
    "postconditions_verified",
)
KINDS = {
    "git_commit",
    "git_push",
    "provider_pr",
    # Legacy read/recovery compatibility for checkpoints persisted before the
    # provider-neutral PR kind was introduced. New checkpoints must use provider_pr.
    "github_pr",
    "harness_update",
    "file_write",
}
MAX_PROOF_BYTES = 8 * 1024
_FORBIDDEN_KEY_PARTS = ("password", "passwd", "secret", "token", "credential", "authorization")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _secret_key_paths(value: Any, prefix: str = "proof") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                found.append(f"{prefix}.{key}")
            found.extend(_secret_key_paths(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_key_paths(child, f"{prefix}[{index}]"))
    return found


def validate_checkpoint(value: Any, *, prefix: str = "sideEffect") -> list[str]:
    """Проверить optional per-attempt checkpoint без provider-specific schema."""
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]

    errors: list[str] = []
    allowed = {
        "contractVersion",
        "kind",
        "phase",
        "attempt",
        "preparedAt",
        "updatedAt",
        "proof",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        errors.append(f"{prefix} contains unknown keys: {', '.join(unknown)}")
    if value.get("contractVersion") != CONTRACT_VERSION:
        errors.append(f"{prefix}.contractVersion must be {CONTRACT_VERSION}")
    if value.get("kind") not in KINDS:
        errors.append(f"{prefix}.kind must be one of {sorted(KINDS)}")
    if value.get("phase") not in PHASES:
        errors.append(f"{prefix}.phase must be one of {list(PHASES)}")
    attempt = value.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        errors.append(f"{prefix}.attempt must be >= 1")
    for key in ("preparedAt", "updatedAt"):
        if not isinstance(value.get(key), str) or not value.get(key):
            errors.append(f"{prefix}.{key} must be non-empty")

    proof = value.get("proof")
    if not isinstance(proof, dict):
        errors.append(f"{prefix}.proof must be an object")
    else:
        try:
            size = _json_size(proof)
        except (TypeError, ValueError) as exc:
            errors.append(f"{prefix}.proof must be JSON-serializable: {exc}")
        else:
            if size > MAX_PROOF_BYTES:
                errors.append(
                    f"{prefix}.proof exceeds {MAX_PROOF_BYTES} UTF-8 JSON bytes: {size}"
                )
        forbidden = _secret_key_paths(proof)
        if forbidden:
            errors.append(
                f"{prefix}.proof contains forbidden secret-like keys: {', '.join(forbidden)}"
            )
    return errors


def checkpoint(
    *,
    kind: str,
    phase: str,
    attempt: int,
    proof: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Создать/продвинуть checkpoint с monotonic phase внутри одной попытки."""
    now = utc_now()
    if previous is not None:
        errors = validate_checkpoint(previous)
        if errors:
            raise ValueError("; ".join(errors))
        if previous["kind"] != kind:
            raise ValueError("sideEffect.kind cannot change within active command")
        if int(previous["attempt"]) == attempt:
            if PHASES.index(phase) < PHASES.index(str(previous["phase"])):
                raise ValueError("sideEffect.phase cannot move backwards within one attempt")
            prepared_at = str(previous["preparedAt"])
        elif attempt > int(previous["attempt"]):
            if phase != "prepared":
                raise ValueError("new side-effect attempt must start at prepared")
            prepared_at = now
        else:
            raise ValueError("sideEffect.attempt cannot decrease")
    else:
        if phase != "prepared":
            raise ValueError("first side-effect checkpoint must be prepared")
        prepared_at = now

    value = {
        "contractVersion": CONTRACT_VERSION,
        "kind": kind,
        "phase": phase,
        "attempt": attempt,
        "preparedAt": prepared_at,
        "updatedAt": now,
        "proof": proof,
    }
    errors = validate_checkpoint(value)
    if errors:
        raise ValueError("; ".join(errors))
    return value


def recovery_decision(*, observed: str, expected: str | None, baseline: str | None) -> str:
    """Classify a single externally observed identity.

    Возвращает ALREADY_APPLIED, SAFE_RETRY или AMBIGUOUS. None кодируется
    пустой строкой caller-ом, когда provider ref/object отсутствует.
    """
    if expected is not None and observed == expected:
        return "ALREADY_APPLIED"
    if observed == (baseline or ""):
        return "SAFE_RETRY"
    return "AMBIGUOUS"


__all__ = [
    "CONTRACT_VERSION",
    "KINDS",
    "MAX_PROOF_BYTES",
    "PHASES",
    "checkpoint",
    "recovery_decision",
    "utc_now",
    "validate_checkpoint",
]
