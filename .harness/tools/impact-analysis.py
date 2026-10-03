#!/usr/bin/env python3
"""CLI for deterministic planning impact analysis."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from impact_analysis import affected_steps, plan_staleness


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explain stale plans and affected STEP surface."
    )
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--step")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        if args.step and args.changed:
            parser.error("--step and --changed are mutually exclusive")
        if args.step:
            result = {
                "schemaVersion": 1,
                "status": "PASS",
                "stepId": args.step,
                "plan": plan_staleness(root, args.step),
            }
        elif args.changed:
            result = affected_steps(root, args.changed)
        else:
            parser.error("use --step STEP-NNN or one/more --changed ARTIFACT-ID")
    except (OSError, UnicodeError, ValueError) as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
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
