#!/usr/bin/env python3
"""Read deterministic execution-group projection for one STEP."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from execution_groups import dependency_layers,implementation_plan_step_count,normalize_execution_groups,topological_group_order
from planning_contract import read_task

def main()->int:
    parser=argparse.ArgumentParser(description="Project optional STEP execution groups.")
    parser.add_argument("step_id"); parser.add_argument("--root",type=Path,default=None); parser.add_argument("--json",action="store_true",dest="as_json")
    args=parser.parse_args(); root=(args.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        task=read_task(root,args.step_id); plan=task["frontmatter"].get("plan")
        if not isinstance(plan,dict): raise ValueError("STEP frontmatter.plan must be a mapping")
        count=implementation_plan_step_count(task["sections"].get("Implementation plan",""))
        groups=normalize_execution_groups(plan.get("execution_groups"),count)
        result={"schemaVersion":1,"status":"PASS","stepId":args.step_id,"groups":groups,"topologicalOrder":topological_group_order(groups),"dependencyLayers":dependency_layers(groups),"parallelCandidates":[g["id"] for g in groups if g["parallel"]]}
    except (OSError,KeyError,TypeError,ValueError) as exc:
        result={"schemaVersion":1,"status":"BLOCKED","stepId":args.step_id,"error":str(exc)}
    print(json.dumps(result,ensure_ascii=False,separators=(",",":")) if args.as_json else json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
