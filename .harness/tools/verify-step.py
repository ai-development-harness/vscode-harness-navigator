#!/usr/bin/env python3
"""Public CLI deterministic STEP Verification runner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from verification import run_step_verification


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic STEP Verification contract.")
    parser.add_argument("step_id")
    parser.add_argument("--manual-json")
    parser.add_argument("--no-write-evidence", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    manual = json.loads(args.manual_json) if args.manual_json else None
    if manual is not None and not isinstance(manual, list):
        parser.error("--manual-json must decode to an array")

    result = run_step_verification(
        repo_root(),
        args.step_id,
        manual_results=manual,
        write_evidence=not args.no_write_evidence,
    )
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))

    status = result.get("status")
    if status == "PASS":
        return 0
    if status == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
