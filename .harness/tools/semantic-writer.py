#!/usr/bin/env python3
"""Public CLI for deterministic semantic artifact writers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from harness_config import resolve_repo_path
from semantic_artifacts import (
    SemanticArtifactError,
    write_plan_draft,
    write_planning_review,
    write_step_review,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_payload(root: Path, value: str) -> dict:
    if value == "-":
        raw = sys.stdin.read()
    else:
        path = resolve_repo_path(root, value, label="semantic payload")
        try:
            rel = path.relative_to((root / ".harness" / "local").resolve())
        except ValueError as exc:
            raise SemanticArtifactError(
                "payload file must stay under .harness/local/**"
            ) from exc
        if not rel.parts or not path.is_file() or path.is_symlink():
            raise SemanticArtifactError(
                "payload file must be a regular file under .harness/local/**"
            )
        raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticArtifactError(f"invalid payload JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SemanticArtifactError("payload JSON must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write canonical PLAN/REVIEW artifacts from semantic JSON payloads."
    )
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan-draft", "planning-review", "step-review"):
        item = sub.add_parser(action)
        item.add_argument("step_id")
        item.add_argument("--payload-file", required=True)

    args = parser.parse_args()
    root = repo_root()
    try:
        payload = load_payload(root, args.payload_file)
        if args.action == "plan-draft":
            result = write_plan_draft(root, args.step_id, payload)
        elif args.action == "planning-review":
            result = write_planning_review(root, args.step_id, payload)
        else:
            result = write_step_review(root, args.step_id, payload)
    except (OSError, ValueError) as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": getattr(exc, "code", "SEMANTIC_ARTIFACT_BLOCKED"),
            "message": str(exc),
        }

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") in {"PASS", "FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
