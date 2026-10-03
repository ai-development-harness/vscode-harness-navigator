#!/usr/bin/env python3
"""CLI validator for semantic requirements-quality payloads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from requirements_quality import RequirementsQualityError, normalize_result


def _read_payload(path: str) -> object:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Requirements Quality Gate semantic payload."
    )
    parser.add_argument("--payload-file", required=True)
    args = parser.parse_args()
    try:
        result = normalize_result(_read_payload(args.payload_file))
    except (OSError, json.JSONDecodeError, RequirementsQualityError) as exc:
        print(
            json.dumps(
                {"schemaVersion": 1, "status": "ERROR", "message": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
