#!/usr/bin/env python3
"""Public CLI for deterministic Harness UX commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness_ux import (
    harness_config,
    harness_doctor,
    harness_resume,
    harness_status,
    render_text,
    step_list,
    step_show,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Harness UX queries/control")
    parser.add_argument(
        "action",
        choices=["status", "resume", "doctor", "config", "step-list", "step-show"],
    )
    parser.add_argument("--step")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        if args.action == "status":
            value = harness_status(root)
        elif args.action == "resume":
            value = harness_resume(root)
        elif args.action == "doctor":
            value = harness_doctor(root)
        elif args.action == "config":
            value = harness_config(root)
        elif args.action == "step-list":
            value = step_list(root)
        else:
            if not args.step:
                parser.error("step-show requires --step STEP-NNN")
            value = step_show(root, args.step)
    except Exception as exc:
        value = {"status": "BLOCKED", "reasonCode": "UX_QUERY_FAILED", "message": str(exc)}

    print(
        json.dumps(value, ensure_ascii=False, indent=2)
        if args.as_json
        else render_text(value)
    )
    return 0 if value.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
