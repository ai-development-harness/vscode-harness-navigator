#!/usr/bin/env python3
"""CLI для versioned project-owned Git handoff (#300)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from portable_handoff import check_handoff, write_handoff


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or inspect a Git-tracked portable STEP handoff",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Write handoff file, never git add/commit/push")
    group.add_argument("--check", action="store_true", help="Read-only check of committed handoff")
    parser.add_argument("--step", required=True, help="Canonical STEP-NNN")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = (
        write_handoff(root, args.step)
        if args.write
        else check_handoff(root, args.step)
    )
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.as_json
        else f"{result['status']}: {result['reasonCode']}"
    )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
