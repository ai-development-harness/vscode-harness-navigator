#!/usr/bin/env python3
"""CLI for deterministic Semantic Blast Radius preflight/validation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_blast_radius import (
    BlastRadiusError,
    blast_radius_preflight,
    validate_blast_radius_payload,
)


def _load_object(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BlastRadiusError(f"{path}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight or validate Semantic Blast Radius for a STEP."
    )
    parser.add_argument("step_id")
    parser.add_argument("--phase", required=True, choices=["plan", "review"])
    parser.add_argument("--context-file")
    parser.add_argument("--grounding-file")
    parser.add_argument("--payload-file")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()

    validation_args = [
        args.context_file,
        args.grounding_file,
        args.payload_file,
    ]
    if any(validation_args) and not all(validation_args):
        parser.error(
            "--context-file, --grounding-file and --payload-file "
            "must be supplied together"
        )

    try:
        if all(validation_args):
            result = validate_blast_radius_payload(
                root,
                args.step_id,
                args.phase,
                _load_object(args.context_file),
                _load_object(args.grounding_file),
                _load_object(args.payload_file),
            )
        else:
            result = blast_radius_preflight(root, args.step_id, args.phase)
    except (
        BlastRadiusError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "phase": args.phase,
            "stepId": args.step_id,
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
