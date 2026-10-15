#!/usr/bin/env python3
"""Read-only диагностическая точка входа для Portable Resume (#299)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from repository_recovery import repository_recovery_preview


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect canonical Git/STEP recovery candidates without resuming execution",
    )
    parser.add_argument("--step", help="Optional exact STEP-NNN to inspect")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    # Как и остальные Harness tooling CLI, используем root установленного
    # repository, а не случайный cwd, в котором запустили Python.
    root = Path(__file__).resolve().parents[2]
    result = repository_recovery_preview(root, args.step)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {result['reasonCode']}")
        for item in result.get("candidates", []):
            print(
                f"- {item['stepId']}: {item['planFreshness']} "
                f"(auto-resume запрещён)"
            )
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
