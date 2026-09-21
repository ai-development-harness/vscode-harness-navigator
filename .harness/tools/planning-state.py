#!/usr/bin/env python3
"""Machine-readable planning/review fingerprints for agent workflows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from planning_contract import init_review_basis, plan_content_hash, planning_context_basis
from review_contract import repository_revision


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)

    plan = sub.add_parser("plan-context")
    plan.add_argument("step_id")

    init = sub.add_parser("init-basis")
    init.add_argument("stage", choices=["requirements", "roadmap"])

    sub.add_parser("review-revision")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.action == "plan-context":
        result = {
            "stepId": args.step_id,
            "contextBasis": planning_context_basis(root, args.step_id),
            "planContentHash": plan_content_hash(root, args.step_id),
        }
    elif args.action == "init-basis":
        result = {
            "stage": args.stage,
            "basis": init_review_basis(root, args.stage),
        }
    else:
        result = repository_revision(root)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
