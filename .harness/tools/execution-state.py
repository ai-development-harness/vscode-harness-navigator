#!/usr/bin/env python3
"""Manage the universal local Harness execution-status.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_status import (
    begin_command,
    block_execution,
    complete_command,
    find_completed,
    load_status,
    stamp_plan,
    start_execution,
)



# Определить корень repository относительно расположения самого tooling. Скрипт не зависит от текущего shell directory.
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]



# Печатать machine-readable JSON одинаковым форматом для агента, клиента и ручной диагностики.
def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))



# Описать публичные subcommands execution-state.py и делегировать каждую операцию execution_status.py.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage crash-safe Harness command execution status."
    )
    # Каждая subcommand отражает простую mutation/query общего status file.
    # Новых Harness-команд здесь нет: это внутренний tooling protocol layer.
    sub = parser.add_subparsers(dest="action", required=True)

    start = sub.add_parser("start")
    start.add_argument("--command", required=True)

    begin = sub.add_parser("begin")
    begin.add_argument("--root", required=True)
    begin.add_argument("--command", required=True)

    complete = sub.add_parser("complete")
    complete.add_argument("--root", required=True)
    complete.add_argument("--command", required=True)
    complete.add_argument(
        "--result",
        required=True,
        choices=["SUCCESS", "PASS", "FAIL", "BLOCKED"],
    )
    complete.add_argument(
        "--details-json",
        help="Optional JSON object with command-specific durable handoff metadata.",
    )

    block = sub.add_parser("block")
    block.add_argument("--root", required=True)
    block.add_argument("--command")

    sub.add_parser("status")

    find = sub.add_parser("find")
    find.add_argument("--command", required=True)
    find.add_argument("--result", choices=["SUCCESS", "PASS", "FAIL", "BLOCKED"])
    find.add_argument(
        "--latest",
        action="store_true",
        help="Match only the latest completed execution.",
    )

    stamp = sub.add_parser("stamp-plan")
    stamp.add_argument("step_id")

    args = parser.parse_args()
    root = repo_root()

    if args.action == "start":
        emit(start_execution(root, args.command))
    elif args.action == "begin":
        emit(begin_command(root, args.root, args.command))
    elif args.action == "complete":
        # details — редкая command-specific metadata внутри той же execution
        # (например resolved update target/route). Это не отдельный state file.
        details = json.loads(args.details_json) if args.details_json else None
        if details is not None and not isinstance(details, dict):
            raise ValueError("--details-json must decode to a JSON object")
        emit(
            complete_command(
                root,
                args.root,
                args.command,
                args.result,
                details=details,
            )
        )
    elif args.action == "block":
        emit(block_execution(root, args.root, command=args.command))
    elif args.action == "status":
        emit(load_status(root))
    elif args.action == "find":
        emit(
            find_completed(
                root,
                args.command,
                result=args.result,
                latest_only=args.latest,
            )
        )
    elif args.action == "stamp-plan":
        emit(stamp_plan(root, args.step_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
