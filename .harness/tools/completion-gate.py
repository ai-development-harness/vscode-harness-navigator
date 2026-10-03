#!/usr/bin/env python3
"""CLI deterministic precheck for STEP Completion Gate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from completion_gate import deterministic_precheck

def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic STEP completion precheck.")
    parser.add_argument("step_id")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        result = deterministic_precheck(root, args.step_id)
    except Exception as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": args.step_id,
            "error": str(exc),
        }
    print(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if args.as_json
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
