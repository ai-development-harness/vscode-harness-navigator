#!/usr/bin/env python3
"""Regressions for optional STEP execution-group DAG."""
from execution_groups import ExecutionGroupError,dependency_layers,implementation_plan_step_count,normalize_execution_groups,topological_group_order

def group(gid,steps,*,depends=None,paths=None,parallel=False):
    return {"id":gid,"title":f"Purpose {gid}","steps":steps,"dependsOn":depends or [],"mutationPaths":paths or [f"src/{gid}"],"verificationResponsibilities":[f"Verify {gid}"],"parallel":parallel}
def err(value,count,needle):
    try: normalize_execution_groups(value,count)
    except ExecutionGroupError as exc: assert needle in str(exc),str(exc)
    else: raise AssertionError("expected ExecutionGroupError")
def main()->int:
    assert implementation_plan_step_count("### 1. Foundation\n\n### 2. UI\n") == 2
    assert implementation_plan_step_count("1. Legacy prose list\n") == 0
    assert normalize_execution_groups(None,4)==[]
    groups=normalize_execution_groups([
      group("foundation",[1]),
      group("api",[2],depends=["foundation"],paths=["src/api"],parallel=True),
      group("ui",[3],depends=["foundation"],paths=["src/ui"],parallel=True),
      group("integration",[4],depends=["api","ui"],paths=["tests/integration"]),
    ],4)
    assert topological_group_order(groups)==["foundation","api","ui","integration"]
    assert dependency_layers(groups)==[["foundation"],["api","ui"],["integration"]]
    err([group("a",[1],depends=["b"]),group("b",[2],depends=["a"])],2,"cycle")
    err([group("a",[1],depends=["missing"])],1,"unknown group")
    err([group("a",[1],depends=["a"])],1,"cannot depend on itself")
    err([group("a",[1]),group("b",[1])],2,"multiple execution groups")
    err([group("a",[2])],1,"invalid implementation step")
    err([group("a",[1])],2,"missing steps: 2")
    err([group("a",[1],paths=["src/shared"],parallel=True),group("b",[2],paths=["src/shared/model"],parallel=True)],2,"overlapping mutation surfaces")
    ordered=normalize_execution_groups([group("a",[1],paths=["src/shared"],parallel=True),group("b",[2],depends=["a"],paths=["src/shared/model"],parallel=True)],2)
    assert topological_group_order(ordered)==["a","b"]
    err([group("a",[1],paths=["src/**"])],1,"glob syntax is not supported")
    err([group("a",[1],paths=["src/./shared"])],1,"'.' or '..' segments")
    print("execution-groups self-test: PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
