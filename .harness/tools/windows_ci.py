"""Три изолированные группы Windows CI и общий обязательный результат (#339).

Группы владеют непересекающимися наборами self-tests, включая проверку очистки (#334).
Итоговый check принимает только успех всех трёх jobs; пропуск или отмена
не становятся успехом даже при успешных оставшихся группах.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

GROUPS = {
    "update": ("harness-config", "document-contract", "update-engine"),
    "resume": ("step-next", "portable-handoff", "portable-resume", "portable-resume-matrix"),
    "execution": ("execution", "verification", "reliable-orchestration-fault",
                  "operational-reports", "operational-completion", "operational-integration", "local-cleanup"),
}


def validate_groups() -> None:
    names = [name for group in GROUPS.values() for name in group]
    if len(names) != 14 or len(set(names)) != len(names):
        raise ValueError("Windows-набор должен содержать 14 различных self-tests")


def finalize(needs: dict) -> bool:
    """GitHub needs привязан к текущему запуску/SHA, а не к чужому прошлому PASS."""
    expected = {"windows-" + group for group in GROUPS}
    return (isinstance(needs, dict) and set(needs) == expected
            and all(isinstance(value, dict) and value.get("result") == "success"
                    for value in needs.values()))


def run_group(group: str, timeout: float) -> dict:
    tools = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("harness_self_test_runner", tools / "run-self-tests.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    results = []
    for name in GROUPS[group]:
        path = tools / (name + "-self-test.py")
        started = time.monotonic()
        try:
            item, stdout, stderr = runner.run_one(path, repo_root=tools.parents[1], timeout_seconds=timeout)
        except OSError:
            item, stdout, stderr = {"test": path.name, "status": "ERROR", "exitCode": None}, "", "Ошибка запуска процесса"
        item["durationMs"] = round((time.monotonic() - started) * 1000)
        results.append(item)
        print(f"[{item['status']}] {path.name}: durationMs={item['durationMs']} exitCode={item['exitCode']}", flush=True)
        if stdout.strip():
            print(stdout.rstrip(), flush=True)
        if stderr.strip():
            print(stderr.rstrip(), file=sys.stderr, flush=True)
    return {"group": group, "status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "finalize"))
    parser.add_argument("--group", choices=tuple(GROUPS))
    parser.add_argument("--timeout-seconds", type=float, default=900)
    args = parser.parse_args()
    validate_groups()
    if args.action == "finalize":
        try:
            passed = finalize(json.loads(os.environ.get("WINDOWS_NEEDS_JSON", "null")))
        except (ValueError, TypeError):
            passed = False
        print("WINDOWS BOUNDARIES: " + ("PASS" if passed else "FAIL"))
        return 0 if passed else 1
    if args.group is None or not 0 < args.timeout_seconds <= 900:
        parser.error("run требует --group и timeout в диапазоне (0, 900]")
    result = run_group(args.group, args.timeout_seconds)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
