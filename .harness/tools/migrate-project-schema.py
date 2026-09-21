#!/usr/bin/env python3
"""CLI идемпотентной migration active project documents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_migration import legacy_schema_pending, migrate_project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.check:
        result = {
            "status": "MIGRATION_REQUIRED" if legacy_schema_pending(root) else "CURRENT",
            "legacyPending": legacy_schema_pending(root),
        }
        code = 1 if result["legacyPending"] else 0
    else:
        result = migrate_project(root)
        code = 0

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        if result.get("report"):
            print(result["report"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
