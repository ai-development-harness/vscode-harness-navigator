#!/usr/bin/env python3
"""CLI проверки и синхронизации tracked projections.

Режимы:
- --check: строго read-only, сравнивает tracked projections с deterministic
  representation canonical REQ/STEP/OQ state;
- без --check: mutation mode, переписывает только drifted projections.

Fail-closed: если canonical state нельзя доказуемо превратить в projection,
ProjectionDerivationError возвращает BLOCKED вместо частичной сводки.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from projection_contract import ProjectionDerivationError, validate_projections, write_projections


# ---------------------------------------------------------------------------
# CLI boundary projection engine.
# Read-only check и mutation используют один projection_contract, чтобы expected
# content не расходился между CI и repair path.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.check:
        # Read-only режим намеренно ничего не исправляет: DRIFT должен оставаться
        # наблюдаемым фактом для caller/CI.
        errors = validate_projections(root)
        result = {"status": "PASS" if not errors else "DRIFT", "errors": errors}
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["status"])
            for item in errors:
                print(f"- {item}")
        return 0 if not errors else 1

    # Mutation разрешена только после успешного derivation всех targets.
    # Engine не записывает частичный набор projections при первой же ошибке.
    try:
        changed = write_projections(root)
    except ProjectionDerivationError as exc:
        result = {"status": "BLOCKED", "errors": [str(exc)]}
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("BLOCKED")
            print(f"- {exc}")
        return 2
    result = {"status": "UPDATED", "changed": changed}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("UPDATED")
        for item in changed:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
