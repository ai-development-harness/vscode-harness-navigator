#!/usr/bin/env python3
"""Public CLI deterministic STEP NEXT resolver."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from step_next import resolve_step_next


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve deterministic STEP NEXT recommendation.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    result = resolve_step_next(repo_root())
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
