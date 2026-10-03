#!/usr/bin/env python3
"""Discoverable runner всех Harness synthetic self-tests.

Любой новый `*-self-test.py` автоматически становится частью regression suite.
Это исключает drift между каталогом tools и вручную перечисленными CI steps.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


DEFAULT_TEST_TIMEOUT_SECONDS = 120


def discover() -> list[Path]:
    root = Path(__file__).resolve().parent
    return sorted(root.glob("*-self-test.py"), key=lambda path: path.name)


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Остановить зависший self-test вместе с его дочерними процессами."""
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


def run_one(
    path: Path,
    *,
    repo_root: Path,
    timeout_seconds: float,
) -> tuple[dict[str, object], str, str]:
    """Запустить один self-test с bounded runtime и диагностикой timeout."""
    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [sys.executable, str(path)],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        return (
            {
                "test": path.name,
                "exitCode": None,
                "status": "TIMEOUT",
                "timeoutSeconds": timeout_seconds,
            },
            stdout,
            stderr,
        )
    return (
        {
            "test": path.name,
            "exitCode": proc.returncode,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        },
        stdout,
        stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all Harness synthetic self-tests.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", dest="list_only")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        help="Maximum runtime of one self-test before TIMEOUT.",
    )
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be >= 1")

    tests = discover()
    if args.list_only:
        if args.as_json:
            print(json.dumps([path.name for path in tests], ensure_ascii=False))
        else:
            for path in tests:
                print(path.name)
        return 0

    results: list[dict[str, object]] = []
    failed = False
    repo_root = Path(__file__).resolve().parents[2]
    for path in tests:
        item, stdout, stderr = run_one(
            path,
            repo_root=repo_root,
            timeout_seconds=args.timeout_seconds,
        )
        results.append(item)
        if item["status"] != "PASS":
            failed = True
        if not args.as_json:
            print(f"[{item['status']}] {path.name}")
            if stdout.strip():
                print(stdout.rstrip())
            if stderr.strip():
                print(stderr.rstrip(), file=sys.stderr)

    if args.as_json:
        print(
            json.dumps(
                {
                    "status": "FAIL" if failed else "PASS",
                    "count": len(results),
                    "results": results,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    else:
        print(f"HARNESS SELF-TESTS: {'FAIL' if failed else 'PASS'} ({len(results)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
