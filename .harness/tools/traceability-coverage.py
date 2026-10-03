#!/usr/bin/env python3
"""CLI for deterministic REQ → STEP → Evidence coverage."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from traceability_coverage import build_coverage

def main() -> int:
    parser=argparse.ArgumentParser(description="Build deterministic traceability coverage.")
    parser.add_argument("--root",type=Path,default=None)
    parser.add_argument("--json",action="store_true",dest="as_json")
    args=parser.parse_args()
    root=(args.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        result=build_coverage(root)
    except Exception as exc:
        result={"schemaVersion":1,"status":"BLOCKED","error":str(exc)}
        print(json.dumps(result,ensure_ascii=False,separators=(",",":")))
        return 2
    if args.as_json:
        print(json.dumps(result,ensure_ascii=False,separators=(",",":")))
    else:
        m=result["metrics"]
        print(f"TRACEABILITY COVERAGE: {result['status']}")
        print(f"requirements: {m['requirements']}")
        print(f"coveredByStep: {m['coveredByStep']}")
        print(f"verified: {m['verified']}")
        print(f"uncovered: {m['uncovered']}")
        print(f"staleEvidence: {m['staleEvidence']}")
        print(f"orphanSteps: {m['orphanSteps']}")
        print(f"invalidReferences: {m['invalidReferences']}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
