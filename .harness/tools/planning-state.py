#!/usr/bin/env python3
"""Machine-readable planning/review fingerprints for agent workflows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from planning_contract import init_review_basis, plan_content_hash, planning_context_basis, output_declaration_issues, read_task
from review_contract import repository_revision


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)

    plan = sub.add_parser("plan-context")
    plan.add_argument("step_id")
    outputs = sub.add_parser("output-contract")
    outputs.add_argument("step_id")

    init = sub.add_parser("init-basis")
    init.add_argument("stage", choices=["requirements", "roadmap"])

    sub.add_parser("review-revision")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.action == "output-contract":
        try:
            issues = output_declaration_issues(root, read_task(root, args.step_id))
            result = {"schemaVersion": 1, "stepId": args.step_id,
                      "status": "BLOCKED" if issues else "PASS",
                      "reasonCode": "OUTPUT_DECLARATIONS_REQUIRED" if issues else "OUTPUT_CONTRACT_VALID",
                      "issues": issues}
        except (ValueError, OSError):
            result = {"schemaVersion": 1, "stepId": args.step_id, "status": "BLOCKED", "reasonCode": "OUTPUT_CONTRACT_INVALID"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "BLOCKED" else 0
    elif args.action == "plan-context":
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
