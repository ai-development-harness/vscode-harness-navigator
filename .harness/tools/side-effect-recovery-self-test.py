#!/usr/bin/env python3
"""Fault-injection tests SideEffectProof contract без real provider/runtime."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

from execution_status import empty_status, load_status, save_status
from side_effect_recovery import (
    MAX_PROOF_BYTES,
    checkpoint,
    recovery_decision,
    validate_checkpoint,
)


def _push_proof() -> dict[str, object]:
    return {
        "localHead": "a" * 40,
        "remote": "origin",
        "branch": "feature/x",
        "remoteHeadBefore": "b" * 40,
    }


def main() -> int:
    # Fault 1: crash before side effect. prepared не запрещает новую attempt.
    prepared = checkpoint(
        kind="git_push",
        phase="prepared",
        attempt=1,
        proof=_push_proof(),
    )
    retry = checkpoint(
        kind="git_push",
        phase="prepared",
        attempt=2,
        proof=_push_proof(),
        previous=prepared,
    )
    assert retry["attempt"] == 2
    assert retry["phase"] == "prepared"

    # Fault 2: crash during unknown outcome. Третье внешнее состояние ambiguous.
    started = checkpoint(
        kind="git_push",
        phase="side_effect_started",
        attempt=2,
        proof=retry["proof"],
        previous=retry,
    )
    assert recovery_decision(
        observed="c" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "AMBIGUOUS"

    # Fault 3: crash after side effect. Exact intended external identity means
    # ALREADY_APPLIED и mutation нельзя повторять.
    assert recovery_decision(
        observed="a" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "ALREADY_APPLIED"

    # Fault 4: crash after observation but before completion checkpoint.
    observed = checkpoint(
        kind="git_push",
        phase="side_effect_observed",
        attempt=2,
        proof={**started["proof"], "observedRemoteHead": "a" * 40},
        previous=started,
    )
    verified = checkpoint(
        kind="git_push",
        phase="postconditions_verified",
        attempt=2,
        proof=observed["proof"],
        previous=observed,
    )
    assert validate_checkpoint(verified) == []

    # SAFE_RETRY допускается только пока внешний факт равен baseline.
    assert recovery_decision(
        observed="b" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "SAFE_RETRY"

    # Durable restart: checkpoint проходит execution-status schema, записывается
    # atomic writer-ом и после нового read восстанавливается byte-semantically.
    with tempfile.TemporaryDirectory(prefix="harness-side-effect-") as tmp:
        root = Path(tmp)
        status = empty_status()
        status["executions"].append(
            {
                "executionId": "exec-test",
                "ordinal": 1,
                "mode": "single",
                "requestedCommand": "GIT PUSH",
                "rootCommand": "GIT PUSH",
                "sequence": ["GIT PUSH"],
                "currentIndex": 0,
                "status": "running",
                "current": {
                    "command": "GIT PUSH",
                    "status": "running",
                    "result": None,
                    "attempt": 2,
                    "startedAt": "2026-01-01T00:00:00+00:00",
                    "completedAt": None,
                    "context": {"sideEffect": observed},
                },
                "notExecuted": [],
                "fixReviewCycles": 0,
                "startedAt": "2026-01-01T00:00:00+00:00",
                "completedAt": None,
                "updatedAt": "2026-01-01T00:00:00+00:00",
            }
        )
        status["nextOrdinal"] = 2
        save_status(root, status)
        restored = load_status(root)
        restored_checkpoint = restored["executions"][0]["current"]["context"]["sideEffect"]
        assert restored_checkpoint == observed

    # Provider PR kind не зависит от конкретного Git provider.
    provider_pr = checkpoint(
        kind="provider_pr",
        phase="prepared",
        attempt=1,
        proof={"headBranch": "feature/x", "baseBranch": "main", "headSha": "a" * 40},
    )
    assert validate_checkpoint(provider_pr) == []

    # Legacy github_pr остаётся валидным для durable recovery уже сохранённого
    # checkpoint, но kind нельзя переименовывать посреди active lifecycle.
    legacy_pr = checkpoint(
        kind="github_pr",
        phase="prepared",
        attempt=1,
        proof={"headBranch": "feature/x", "baseBranch": "main", "headSha": "a" * 40},
    )
    assert validate_checkpoint(legacy_pr) == []
    try:
        checkpoint(
            kind="provider_pr",
            phase="side_effect_started",
            attempt=1,
            proof=legacy_pr["proof"],
            previous=legacy_pr,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("legacy PR checkpoint kind changed within active lifecycle")

    # Secret-like metadata и oversized proof fail-closed.
    try:
        checkpoint(
            kind="git_push",
            phase="prepared",
            attempt=1,
            proof={"authToken": "should-never-persist"},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("secret-like proof key was accepted")

    too_large = {
        "contractVersion": 1,
        "kind": "file_write",
        "phase": "prepared",
        "attempt": 1,
        "preparedAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "proof": {"payload": "x" * (MAX_PROOF_BYTES + 1)},
    }
    assert validate_checkpoint(too_large)

    # Внутри одной attempt фаза не может откатиться назад.
    try:
        checkpoint(
            kind="git_push",
            phase="prepared",
            attempt=2,
            proof=_push_proof(),
            previous=started,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("phase rollback was accepted")

    print("side-effect-recovery-self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
