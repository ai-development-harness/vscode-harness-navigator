#!/usr/bin/env python3
"""Public CLI stateful deterministic command dispatcher."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from command_dispatch import (
    complete_dispatch,
    resume_dispatch,
    route_command,
    start_dispatch,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def emit(value: object, *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _dispatch(root: Path, args: argparse.Namespace) -> dict:
    if args.action == "start":
        return start_dispatch(root, args.command)
    if args.action == "complete":
        details = json.loads(args.details_json) if args.details_json else None
        if details is not None and not isinstance(details, dict):
            raise ValueError("--details-json must decode to a JSON object")
        return complete_dispatch(
            root,
            args.root_command,
            args.command,
            args.result,
            details=details,
        )
    return resume_dispatch(root, args.root_command)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch Harness commands through deterministic CTS/execution routing."
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of compact machine-readable output.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    start = sub.add_parser("start")
    start.add_argument("--command", required=True)

    complete = sub.add_parser("complete")
    complete.add_argument("--root", required=True, dest="root_command")
    complete.add_argument("--command", required=True)
    complete.add_argument(
        "--result",
        required=True,
        choices=["SUCCESS", "PASS", "FAIL", "BLOCKED"],
    )
    complete.add_argument("--details-json")

    resume = sub.add_parser("resume")
    resume.add_argument("--root", dest="root_command")

    route = sub.add_parser("route")
    route.add_argument("--command", required=True)

    args = parser.parse_args()
    root = repo_root()

    if args.action in {"start", "complete", "resume"}:
        # Единый fail-closed контракт: любой отказ — BLOCKED JSON, а не
        # traceback, который agent мог бы неверно интерпретировать (#117).
        try:
            value = _dispatch(root, args)
        except (OSError, RuntimeError, ValueError) as exc:
            value = {
                "schemaVersion": 1,
                "status": "BLOCKED",
                "reasonCode": getattr(exc, "code", "DISPATCH_BLOCKED"),
                "message": str(exc),
            }
    else:
        try:
            value = {
                "schemaVersion": 1,
                "status": "PASS",
                **route_command(root, args.command),
            }
        except (OSError, RuntimeError, ValueError) as exc:
            value = {
                "schemaVersion": 1,
                "status": "BLOCKED",
                "reasonCode": getattr(exc, "code", "ROUTE_BLOCKED"),
                "message": str(exc),
            }

    emit(value, pretty=args.pretty)
    return 0 if value.get("status") not in {"BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
