#!/usr/bin/env python3
"""Canonical bounded runner for concurrency/process-sensitive Harness stress tests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "stress-tests.json"
MAX_DIAGNOSTIC_CHARS = 4000


class StressConfigError(RuntimeError):
    pass


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tail(text: str) -> str:
    return text[-MAX_DIAGNOSTIC_CHARS:]


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
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


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StressConfigError(f"cannot read stress manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise StressConfigError("stress manifest schemaVersion must be 1")
    default_iterations = data.get("defaultIterations")
    if not isinstance(default_iterations, int) or not 1 <= default_iterations <= 1000:
        raise StressConfigError("defaultIterations must be integer in range 1..1000")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise StressConfigError("scenarios must be non-empty list")
    ids: set[str] = set()
    for raw in scenarios:
        if not isinstance(raw, dict):
            raise StressConfigError("scenario must be object")
        scenario_id = raw.get("id")
        tool = raw.get("tool")
        args = raw.get("args")
        timeout = raw.get("timeoutSeconds")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise StressConfigError("scenario id must be non-empty string")
        if scenario_id in ids:
            raise StressConfigError(f"duplicate stress scenario id: {scenario_id}")
        ids.add(scenario_id)
        if (
            not isinstance(tool, str)
            or "/" in tool
            or "\\" in tool
            or not tool.endswith("-self-test.py")
        ):
            raise StressConfigError(
                f"{scenario_id}: tool must be local *-self-test.py basename"
            )
        if (
            not isinstance(args, list)
            or not all(isinstance(item, str) for item in args)
            or args.count("{iterations}") != 1
        ):
            raise StressConfigError(
                f"{scenario_id}: args must contain exactly one {{iterations}} placeholder"
            )
        if not isinstance(timeout, int) or timeout < 1:
            raise StressConfigError(f"{scenario_id}: timeoutSeconds must be >= 1")
    return data


def _command(
    scenario: dict[str, Any],
    *,
    tools_dir: Path,
    iterations: int,
) -> list[str]:
    tool = tools_dir / str(scenario["tool"])
    if not tool.is_file():
        raise StressConfigError(
            f"{scenario['id']}: stress tool does not exist: {tool.name}"
        )
    args = [
        str(iterations) if item == "{iterations}" else item
        for item in scenario["args"]
    ]
    return [sys.executable, str(tool), *args]


def _run_one(
    scenario: dict[str, Any],
    *,
    tools_dir: Path,
    repo_root: Path,
    iterations: int,
) -> tuple[dict[str, Any], str, str]:
    command = _command(scenario, tools_dir=tools_dir, iterations=iterations)
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        command,
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )
    timeout = int(scenario["timeoutSeconds"])
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        status = "PASS" if proc.returncode == 0 else "FAIL"
        exit_code: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        status = "TIMEOUT"
        exit_code = None

    result: dict[str, Any] = {
        "id": scenario["id"],
        "status": status,
        "iterations": iterations,
        "timeoutSeconds": timeout,
        "command": [str(scenario["tool"]), *command[2:]],
        "exitCode": exit_code,
        "stdoutSha256": _hash(stdout),
        "stderrSha256": _hash(stderr),
        "stdoutBytes": len(stdout.encode("utf-8")),
        "stderrBytes": len(stderr.encode("utf-8")),
    }
    if status != "PASS":
        result["stdoutTail"] = _tail(stdout)
        result["stderrTail"] = _tail(stderr)
    return result, stdout, stderr


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Harness stress suite without retry-on-failure."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()

    try:
        manifest = _load_manifest(args.manifest.resolve())
    except StressConfigError as exc:
        if args.as_json:
            print(json.dumps({
                "schemaVersion": 1,
                "kind": "harness_stress_suite",
                "status": "BLOCKED",
                "reason": str(exc),
                "results": [],
            }, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"HARNESS STRESS SUITE: BLOCKED: {exc}", file=sys.stderr)
        return 2

    iterations = (
        args.iterations
        if args.iterations is not None
        else int(manifest["defaultIterations"])
    )
    if iterations < 1 or iterations > 1000:
        parser.error("--iterations must be in range 1..1000")

    scenarios = list(manifest["scenarios"])
    if args.list_only:
        if args.as_json:
            print(json.dumps(
                [{"id": item["id"], "tool": item["tool"]} for item in scenarios],
                ensure_ascii=False,
                separators=(",", ":"),
            ))
        else:
            for item in scenarios:
                print(f"{item['id']}: {item['tool']}")
        return 0

    repo_root = Path(__file__).resolve().parents[2]
    tools_dir = Path(__file__).resolve().parent
    results: list[dict[str, Any]] = []
    failed = False

    for scenario in scenarios:
        try:
            item, stdout, stderr = _run_one(
                scenario,
                tools_dir=tools_dir,
                repo_root=repo_root,
                iterations=iterations,
            )
        except StressConfigError as exc:
            item = {
                "id": scenario.get("id"),
                "status": "BLOCKED",
                "iterations": iterations,
                "reason": str(exc),
            }
            stdout = ""
            stderr = ""
        results.append(item)
        if item["status"] != "PASS":
            failed = True
        if not args.as_json:
            print(f"[{item['status']}] {item.get('id')}")
            if stdout.strip():
                print(stdout.rstrip())
            if stderr.strip():
                print(stderr.rstrip(), file=sys.stderr)

    status = "FAIL" if failed else "PASS"
    payload = {
        "schemaVersion": 1,
        "kind": "harness_stress_suite",
        "status": status,
        "iterations": iterations,
        "results": results,
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"HARNESS STRESS SUITE: {status} ({len(results)} scenarios x {iterations})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
