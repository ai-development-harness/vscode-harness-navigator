#!/usr/bin/env python3
"""Resolve interrupted or continuing Harness executions without LLM reasoning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_status import resolve_root, unresolved_executions



# Получить repository root независимо от cwd вызывающего агента.
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]



# Разобрать --root/--json и вывести результат resolver-а без command-specific интерпретации.
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve exact next/resume command from execution-status.json."
    )
    parser.add_argument("--root")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = repo_root()

    # С --root работаем с одной конкретной invocation. Без --root показываем
    # все unresolved records, чтобы новая session не потеряла параллельный контекст.
    if args.root:
        value = resolve_root(root, args.root)
    else:
        value = {
            "status": "UNRESOLVED_EXECUTIONS",
            "executions": unresolved_executions(root),
        }

    if args.as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif args.root:
        print(value["status"])
        if value.get("command"):
            print(value["command"])
        print(value["reasonCode"])
    else:
        for item in value["executions"]:
            command = item.get("command") or "—"
            print(
                f"{item['executionId']}: {item['status']} -> "
                f"{command} ({item['reasonCode']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
