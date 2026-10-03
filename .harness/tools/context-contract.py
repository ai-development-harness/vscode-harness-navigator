#!/usr/bin/env python3
"""CLI for runtime-neutral STEP Context Contracts."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from context_contracts import ContextContractError, build_context_contract, validate_expansion

def main()->int:
    parser=argparse.ArgumentParser(description="Resolve role-specific task-local context.")
    parser.add_argument("step_id", nargs="?")
    parser.add_argument("--role", choices=["planner","implementer","reviewer"])
    parser.add_argument("--expand")
    parser.add_argument("--reason")
    parser.add_argument("--root",type=Path,default=None)
    parser.add_argument("--json",action="store_true",dest="as_json")
    args=parser.parse_args()
    root=(args.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        if args.expand:
            result=validate_expansion(root,args.expand,args.reason or "")
        else:
            if not args.step_id or not args.role:
                parser.error("step_id and --role are required unless --expand is used")
            result=build_context_contract(root,args.step_id,args.role)
    except (OSError,UnicodeError,ValueError,ContextContractError) as exc:
        result={"schemaVersion":1,"status":"BLOCKED","error":str(exc)}
        print(json.dumps(result,ensure_ascii=False,separators=(",",":")))
        return 1
    print(json.dumps(result,ensure_ascii=False,separators=(",",":")) if args.as_json else json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
