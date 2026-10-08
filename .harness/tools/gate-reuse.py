#!/usr/bin/env python3
"""Canonical read-only integrity preflight with bounded exact-result reuse."""
from __future__ import annotations
import json
from pathlib import Path
from gate_reuse import validate_once


def main() -> int:
    try:
        outcome = validate_once(Path(__file__).resolve().parents[2])
    except (OSError, ValueError, TimeoutError) as exc:
        outcome = {"status": "BLOCKED", "reasonCode": "VALIDATION_PREFLIGHT_ERROR", "message": str(exc)}
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
