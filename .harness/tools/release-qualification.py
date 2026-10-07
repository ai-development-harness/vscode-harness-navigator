#!/usr/bin/env python3
"""Canonical deterministic entrypoint для release-level qualification Harness.

Один executable используется всеми platform/runtime lanes. Внешний orchestrator
выбирает lane, но не дублирует набор команд qualification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time
from typing import Sequence


SCHEMA_VERSION = 1
MINIMUM_PYTHON = (3, 11)
PREFLIGHT_TIMEOUT_SECONDS = 60
DEFAULT_GATE_TIMEOUT_SECONDS = 300
STRESS_GATE_TIMEOUT_SECONDS = 330
MAX_GATE_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class _RunResult:
    """Нормализованный результат bounded subprocess invocation."""

    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _elapsed_ms(start_ns: int) -> int:
    return max(0, (time.monotonic_ns() - start_ns) // 1_000_000)


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Остановить timeout process вместе с descendants без retry execution."""

    if proc.poll() is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=1)
            return
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    elif os.name == "nt":
        # taskkill /T нужен, потому что self-test может породить git/python descendants.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int = PREFLIGHT_TIMEOUT_SECONDS,
) -> _RunResult:
    """Выполнить command с monotonic timing и bounded process-tree lifetime."""

    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    start_ns = time.monotonic_ns()
    proc = subprocess.Popen(
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        returncode: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        returncode = None

    return _RunResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_ms=_elapsed_ms(start_ns),
        timed_out=timed_out,
    )


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> _RunResult:
    return _run(
        ["git", *args],
        cwd=root,
        timeout_seconds=PREFLIGHT_TIMEOUT_SECONDS,
    )


def _current_revision(root: Path) -> tuple[str | None, str | None]:
    proc = _git(root, "rev-parse", "HEAD")
    if proc.timed_out:
        return None, "GIT_HEAD_TIMEOUT"
    if proc.returncode != 0:
        return None, "GIT_HEAD_UNAVAILABLE"
    value = proc.stdout.strip()
    if not value:
        return None, "GIT_HEAD_UNAVAILABLE"
    return value, None


def _worktree_status(root: Path) -> _RunResult:
    return _git(root, "status", "--porcelain=v1", "--untracked-files=all")


def _gate(
    gate_id: str,
    command: Sequence[str],
    *,
    root: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    proc = _run(command, cwd=root, timeout_seconds=timeout_seconds)
    if proc.timed_out:
        status = "TIMEOUT"
        exit_code: int | None = None
    else:
        status = "PASS" if proc.returncode == 0 else "FAIL"
        exit_code = proc.returncode
    return {
        "id": gate_id,
        "status": status,
        "exitCode": exit_code,
        "timeoutSeconds": timeout_seconds,
        "durationMs": proc.duration_ms,
        "stdoutSha256": _sha256(proc.stdout),
        "stderrSha256": _sha256(proc.stderr),
        "stdoutBytes": len(proc.stdout.encode("utf-8")),
        "stderrBytes": len(proc.stderr.encode("utf-8")),
    }


def _lane_commands(
    lane: str,
    *,
    gate_timeout_seconds: int,
) -> list[tuple[str, list[str], int]]:
    py = sys.executable
    if lane in {"current", "minimum"}:
        commands = [
            (
                "validate-ci",
                [py, ".harness/tools/validate.py", "--mode", "ci"],
                gate_timeout_seconds,
            ),
            (
                "synthetic-self-tests",
                [py, ".harness/tools/run-self-tests.py"],
                gate_timeout_seconds,
            ),
        ]
        if lane == "current":
            # Stress runner имеет собственный 300s scenario timeout. Внешний cap
            # оставляет 30s на process-tree cleanup и формирование evidence.
            commands.append(
                (
                    "bounded-stress-suite",
                    [
                        py,
                        ".harness/tools/run-stress-tests.py",
                        "--iterations",
                        "20",
                    ],
                    max(gate_timeout_seconds, STRESS_GATE_TIMEOUT_SECONDS),
                )
            )
        return commands
    if lane == "windows":
        targeted = [
            "harness-config-self-test.py",
            "document-contract-self-test.py",
            "execution-self-test.py",
            "verification-self-test.py",
            "reliable-orchestration-fault-self-test.py",
            "update-engine-self-test.py",
        ]
        commands: list[tuple[str, list[str], int]] = [
            (
                "validate-ci",
                [py, ".harness/tools/validate.py", "--mode", "ci"],
                gate_timeout_seconds,
            )
        ]
        commands.extend(
            (
                f"windows-{name.removesuffix('.py')}",
                [py, f".harness/tools/{name}"],
                gate_timeout_seconds,
            )
            for name in targeted
        )
        return commands
    raise ValueError(f"unsupported lane: {lane}")


def _blocked_result(
    *,
    lane: str,
    expected_revision: str,
    repository_revision: str | None,
    reason: str,
    duration_ms: int,
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "harness_release_qualification",
        "status": "BLOCKED",
        "lane": lane,
        "expectedRevision": expected_revision,
        "repositoryRevision": repository_revision,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "durationMs": duration_ms,
        "reason": reason,
        "gates": [],
    }


def qualify(
    *,
    lane: str,
    expected_revision: str,
    expected_python: str | None = None,
    gate_timeout_seconds: int = DEFAULT_GATE_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, object]]:
    started_ns = time.monotonic_ns()
    root = _repo_root()
    revision, revision_error = _current_revision(root)
    if revision is None:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=None,
            reason=revision_error or "GIT_HEAD_UNAVAILABLE",
            duration_ms=_elapsed_ms(started_ns),
        )
    if revision != expected_revision:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="REVISION_MISMATCH",
            duration_ms=_elapsed_ms(started_ns),
        )

    if sys.version_info[:2] < MINIMUM_PYTHON:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="UNSUPPORTED_PYTHON",
            duration_ms=_elapsed_ms(started_ns),
        )
    if expected_python is not None:
        actual = f"{sys.version_info.major}.{sys.version_info.minor}"
        if actual != expected_python:
            return 2, _blocked_result(
                lane=lane,
                expected_revision=expected_revision,
                repository_revision=revision,
                reason=f"PYTHON_VERSION_MISMATCH:{actual}",
                duration_ms=_elapsed_ms(started_ns),
            )
    if lane == "minimum" and sys.version_info[:2] != MINIMUM_PYTHON:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="MINIMUM_LANE_REQUIRES_PYTHON_3_11",
            duration_ms=_elapsed_ms(started_ns),
        )
    if lane == "windows" and os.name != "nt":
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="WINDOWS_LANE_REQUIRES_WINDOWS",
            duration_ms=_elapsed_ms(started_ns),
        )

    before = _worktree_status(root)
    if before.timed_out:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="GIT_STATUS_TIMEOUT",
            duration_ms=_elapsed_ms(started_ns),
        )
    if before.returncode != 0:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason=f"GIT_STATUS_FAILED:{_sha256(before.stderr)}",
            duration_ms=_elapsed_ms(started_ns),
        )
    if before.stdout:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="CHECKOUT_NOT_CLEAN",
            duration_ms=_elapsed_ms(started_ns),
        )

    gates: list[dict[str, object]] = []
    failed = False
    for gate_id, command, timeout_seconds in _lane_commands(
        lane,
        gate_timeout_seconds=gate_timeout_seconds,
    ):
        item = _gate(
            gate_id,
            command,
            root=root,
            timeout_seconds=timeout_seconds,
        )
        gates.append(item)
        if item["status"] != "PASS":
            failed = True

    after = _worktree_status(root)
    if after.timed_out:
        gates.append(
            {
                "id": "checkout-clean-after",
                "status": "TIMEOUT",
                "exitCode": None,
                "timeoutSeconds": PREFLIGHT_TIMEOUT_SECONDS,
                "durationMs": after.duration_ms,
                "stdoutSha256": _sha256(after.stdout),
                "stderrSha256": _sha256(after.stderr),
                "stdoutBytes": len(after.stdout.encode("utf-8")),
                "stderrBytes": len(after.stderr.encode("utf-8")),
            }
        )
        failed = True
    elif after.returncode != 0:
        gates.append(
            {
                "id": "checkout-clean-after",
                "status": "FAIL",
                "exitCode": after.returncode,
                "timeoutSeconds": PREFLIGHT_TIMEOUT_SECONDS,
                "durationMs": after.duration_ms,
                "stdoutSha256": _sha256(after.stdout),
                "stderrSha256": _sha256(after.stderr),
                "stdoutBytes": len(after.stdout.encode("utf-8")),
                "stderrBytes": len(after.stderr.encode("utf-8")),
            }
        )
        failed = True
    else:
        clean = not after.stdout
        gates.append(
            {
                "id": "checkout-clean-after",
                "status": "PASS" if clean else "FAIL",
                "exitCode": 0 if clean else 1,
                "timeoutSeconds": PREFLIGHT_TIMEOUT_SECONDS,
                "durationMs": after.duration_ms,
                "stdoutSha256": _sha256(after.stdout),
                "stderrSha256": _sha256(after.stderr),
                "stdoutBytes": len(after.stdout.encode("utf-8")),
                "stderrBytes": len(after.stderr.encode("utf-8")),
            }
        )
        if not clean:
            failed = True

    payload: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "harness_release_qualification",
        "status": "FAIL" if failed else "PASS",
        "lane": lane,
        "expectedRevision": expected_revision,
        "repositoryRevision": revision,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "durationMs": _elapsed_ms(started_ns),
        "gates": gates,
    }
    return (1 if failed else 0), payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify an exact Harness release-candidate checkout."
    )
    parser.add_argument(
        "--lane",
        choices=("current", "minimum", "windows"),
        required=True,
        help="Qualification lane selected by the release orchestrator.",
    )
    parser.add_argument(
        "--expect-sha",
        required=True,
        help="Exact candidate commit SHA that this checkout must contain.",
    )
    parser.add_argument(
        "--expected-python",
        help="Optional exact major.minor runtime required by the caller, e.g. 3.13.",
    )
    parser.add_argument(
        "--gate-timeout-seconds",
        type=int,
        default=DEFAULT_GATE_TIMEOUT_SECONDS,
        help="Maximum runtime for an ordinary qualification gate (default: 300).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if not 1 <= args.gate_timeout_seconds <= MAX_GATE_TIMEOUT_SECONDS:
        parser.error(
            f"--gate-timeout-seconds must be in range 1..{MAX_GATE_TIMEOUT_SECONDS}"
        )

    code, payload = qualify(
        lane=args.lane,
        expected_revision=args.expect_sha,
        expected_python=args.expected_python,
        gate_timeout_seconds=args.gate_timeout_seconds,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(
            f"HARNESS RELEASE QUALIFICATION: {payload['status']} "
            f"(lane={payload['lane']}, sha={payload.get('repositoryRevision')}, "
            f"durationMs={payload.get('durationMs')})"
        )
        if payload.get("reason"):
            print(f"Reason: {payload['reason']}", file=sys.stderr)
        for gate in payload.get("gates", []):
            print(
                f"[{gate['status']}] {gate['id']} "
                f"durationMs={gate.get('durationMs')} "
                f"timeoutSeconds={gate.get('timeoutSeconds')}"
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
