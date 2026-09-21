#!/usr/bin/env python3
"""Публичный CLI structural validator Command Transition System.

Назначение:
- проверяет raw Harness command/chain до skill routing и mutations;
- нормализует shorthand chain по repository-local CTS;
- доказывает только structural validity.

PASS здесь не означает, что выполнены runtime preconditions: Git divergence,
STEP readiness, update route и другие factual gates проверяются отдельно.

Exit codes:
- 0 — structurally valid command/chain;
- 2 — invalid syntax, target, input или transition.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from command_transitions import load_transition_table, validate_command_text



# ---------------------------------------------------------------------------
# Bootstrap repository-local CTS.
# Validator не читает global config и не кэширует graph: source of truth —
# .harness/command-transitions.json именно текущего checkout.
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]



# ---------------------------------------------------------------------------
# CLI flow:
# 1. собрать raw command tokens;
# 2. загрузить CTS table;
# 3. нормализовать и проверить command/chain;
# 4. вывести один и тот же result в text или JSON;
# 5. вернуть exit code только по structural validity.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Harness command syntax and structural transition graph."
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Canonical command string. Quote chains in the shell.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    raw = " ".join(args.command).strip()
    if raw.startswith("-- "):
        raw = raw[3:].strip()

    # Table читается заново на каждый запуск, чтобы правка graph немедленно
    # влияла на validation и stale cache не создавал ложный PASS.
    table = load_transition_table(repo_root())

    # Здесь заканчивается structural layer. Даже VALID_CHAIN ещё не означает,
    # что runtime preconditions (Git divergence, update route и т.п.) выполнены.
    result = validate_command_text(raw, table)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        print(result["code"])
        for value in result["normalized"]:
            print(f"  - {value}")
        for edge in result.get("transitions", []):
            print(
                "  -> "
                + edge["to"]
                + " [on="
                + "/".join(edge["onPreviousResult"])
                + "; pre="
                + (", ".join(edge["runtimePreconditions"]) or "none")
                + "]"
            )
    else:
        print(f"{result['code']}: {result['message']}", file=sys.stderr)

    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
