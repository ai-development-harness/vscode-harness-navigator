#!/usr/bin/env python3
"""Discoverable runner всех Harness synthetic self-tests.

Любой новый `*-self-test.py` автоматически становится частью regression suite.
Это исключает drift между каталогом tools и вручную перечисленными CI steps.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def discover() -> list[Path]:
    root = Path(__file__).resolve().parent
    return sorted(root.glob("*-self-test.py"), key=lambda path: path.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all Harness synthetic self-tests.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()

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
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        item = {
            "test": path.name,
            "exitCode": proc.returncode,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
        }
        results.append(item)
        if proc.returncode != 0:
            failed = True
        if not args.as_json:
            print(f"[{item['status']}] {path.name}")
            if proc.stdout.strip():
                print(proc.stdout.rstrip())
            if proc.stderr.strip():
                print(proc.stderr.rstrip(), file=sys.stderr)

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
