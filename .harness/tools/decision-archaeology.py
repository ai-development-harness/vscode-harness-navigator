#!/usr/bin/env python3
"""CLI for Decision Archaeology preflight and payload validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from decision_archaeology import (
    DecisionArchaeologyError,
    decision_archaeology_preflight,
    validate_decision_archaeology_payload,
)


def _load_object(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DecisionArchaeologyError(f"{path}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build/validate bounded evidence for historical rationale."
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--scope", choices=["simple", "complex"], default="simple")
    parser.add_argument("--context-file")
    parser.add_argument("--payload-file")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        context = (
            _load_object(args.context_file)
            if args.context_file
            else None
        )
        if args.payload_file:
            result = validate_decision_archaeology_payload(
                root,
                args.target,
                args.scope,
                _load_object(args.payload_file),
                context,
            )
        else:
            result = decision_archaeology_preflight(
                root,
                args.target,
                args.scope,
                context,
            )
    except (
        DecisionArchaeologyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "target": args.target,
            "scope": args.scope,
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1

    print(
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if args.as_json
        else json.dumps(result, ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
