#!/usr/bin/env python3
"""Run selected configured Verification commands for feedback, not completion."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from verification_selective import run_selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step")
    parser.add_argument("--command", action="append", required=True, dest="commands")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        result = run_selected(args.root.resolve(), args.step, args.commands)
    except (OSError, ValueError) as exc:
        result = {"status": "BLOCKED", "reasonCode": "SELECTED_VERIFICATION_ERROR", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
