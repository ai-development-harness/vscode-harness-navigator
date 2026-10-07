#!/usr/bin/env python3
"""CLI wrapper for deterministic Codebase Grounding payload validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from codebase_grounding import GroundingContractError, validate_grounding_payload


def _load_json(path: str) -> dict[str, object]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise GroundingContractError(f"{path}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a bounded read-only Codebase Grounding payload."
    )
    parser.add_argument("--context-file", required=True)
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        context = _load_json(args.context_file)
        payload = _load_json(args.payload_file)
        result = validate_grounding_payload(root, context, payload)
    except (
        GroundingContractError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        blocked = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "error": str(exc),
        }
        print(
            json.dumps(
                blocked,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
