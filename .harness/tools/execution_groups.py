#!/usr/bin/env python3
"""Deterministic contract for optional STEP execution groups."""
from __future__ import annotations
import re
from typing import Any

GROUP_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_GLOB_CHARS = set("*?[]{}")

class ExecutionGroupError(ValueError):
    """Execution-group graph is malformed or unsafe."""

def implementation_plan_step_count(text: str) -> int:
    return len(re.findall(r"(?m)^### [0-9]+\. ", text))

def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionGroupError(f"{label} must be a non-empty string")
    result=value.strip()
    if "\n" in result or "\r" in result:
        raise ExecutionGroupError(f"{label} must be a single line")
    return result

def _strings(value: Any, label: str, *, required: bool=False) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value,list):
        raise ExecutionGroupError(f"{label} must be an array")
    result=[_text(item,f"{label}[{index}]") for index,item in enumerate(value)]
    if required and not result:
        raise ExecutionGroupError(f"{label} must not be empty")
    return result

def _path(value: Any, label: str) -> str:
    path=_text(value,label)
    if "\\" in path:
        raise ExecutionGroupError(f"{label} must use repository-relative POSIX separators")
    if path.startswith("/") or re.match(r"^[A-Za-z]:",path):
        raise ExecutionGroupError(f"{label} must be repository-relative")
    if any(char in path for char in _GLOB_CHARS):
        raise ExecutionGroupError(f"{label} must be an explicit path/prefix; glob syntax is not supported")
    while path.startswith("./"):
        path=path[2:]
    path=path.rstrip("/") or "."
    parts=path.split("/")
    if any(part in {"",".."} for part in parts) or (path!="." and "." in parts):
        raise ExecutionGroupError(
            f"{label} must not contain empty, '.' or '..' segments"
        )
    return path

def mutation_paths_overlap(left: str, right: str) -> bool:
    # Conservative across case-sensitive and case-insensitive worktrees.
    left_key=left.casefold(); right_key=right.casefold()
    return left_key=="." or right_key=="." or left_key==right_key or left_key.startswith(right_key+"/") or right_key.startswith(left_key+"/")

def _depends_transitively(by_id: dict[str,dict[str,Any]], group_id: str, dependency_id: str) -> bool:
    stack=list(by_id[group_id]["dependsOn"])
    seen:set[str]=set()
    while stack:
        current=stack.pop()
        if current==dependency_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(by_id[current]["dependsOn"])
    return False

def normalize_execution_groups(value: Any, step_count: int) -> list[dict[str,Any]]:
    if value is None or value==[] or value=={}:
        return []
    if isinstance(value,dict):
        expanded=[]
        for group_id, raw_group in value.items():
            if not isinstance(raw_group,dict):
                raise ExecutionGroupError(f"execution_groups.{group_id} must be a mapping")
            if "id" in raw_group:
                raise ExecutionGroupError(f"execution_groups.{group_id} must not repeat id")
            expanded.append({"id":group_id, **raw_group})
        value=expanded
    if not isinstance(value,list):
        raise ExecutionGroupError("executionGroups must be an array or canonical mapping")
    if isinstance(step_count,bool) or not isinstance(step_count,int) or step_count<1:
        raise ExecutionGroupError("executionGroups require at least one canonical Implementation plan step")
    groups:list[dict[str,Any]]=[]
    ids:set[str]=set()
    covered:set[int]=set()
    for index,raw in enumerate(value):
        label=f"executionGroups[{index}]"
        if not isinstance(raw,dict):
            raise ExecutionGroupError(f"{label} must be an object")
        allowed={"id","title","steps","dependsOn","mutationPaths","verificationResponsibilities","parallel"}
        extra=sorted(set(raw)-allowed)
        if extra:
            raise ExecutionGroupError(f"{label} has unsupported keys: "+", ".join(extra))
        gid=_text(raw.get("id"),f"{label}.id")
        if GROUP_ID_RE.fullmatch(gid) is None:
            raise ExecutionGroupError(f"{label}.id must match [a-z][a-z0-9-]{{0,63}}")
        if gid in ids:
            raise ExecutionGroupError(f"duplicate execution group id: {gid}")
        ids.add(gid)
        title=_text(raw.get("title"),f"{label}.title")
        raw_steps=raw.get("steps")
        if not isinstance(raw_steps,list) or not raw_steps:
            raise ExecutionGroupError(f"{gid}.steps must be a non-empty array")
        steps:list[int]=[]
        for item in raw_steps:
            if isinstance(item,bool) or not isinstance(item,int) or item<1 or item>step_count:
                raise ExecutionGroupError(f"{gid}.steps contains invalid implementation step: {item}")
            if item in steps:
                raise ExecutionGroupError(f"{gid}.steps contains duplicate step: {item}")
            if item in covered:
                raise ExecutionGroupError(f"implementation step {item} belongs to multiple execution groups")
            steps.append(item); covered.add(item)
        depends=_strings(raw.get("dependsOn",[]),f"{gid}.dependsOn")
        if len(set(depends))!=len(depends):
            raise ExecutionGroupError(f"{gid}.dependsOn contains duplicates")
        raw_paths=raw.get("mutationPaths")
        if not isinstance(raw_paths,list) or not raw_paths:
            raise ExecutionGroupError(f"{gid}.mutationPaths must be a non-empty array")
        paths=[_path(item,f"{gid}.mutationPaths[{i}]") for i,item in enumerate(raw_paths)]
        if len(set(paths))!=len(paths):
            raise ExecutionGroupError(f"{gid}.mutationPaths contains duplicate path/prefix")
        verification=_strings(raw.get("verificationResponsibilities"),f"{gid}.verificationResponsibilities",required=True)
        parallel=raw.get("parallel",False)
        if not isinstance(parallel,bool):
            raise ExecutionGroupError(f"{gid}.parallel must be boolean")
        groups.append({"id":gid,"title":title,"steps":steps,"dependsOn":depends,"mutationPaths":paths,"verificationResponsibilities":verification,"parallel":parallel})
    missing=sorted(set(range(1,step_count+1))-covered)
    if missing:
        raise ExecutionGroupError("executionGroups must cover every Implementation plan step exactly once; missing steps: "+", ".join(str(x) for x in missing))
    by_id={g["id"]:g for g in groups}
    for group in groups:
        for dep in group["dependsOn"]:
            if dep==group["id"]:
                raise ExecutionGroupError(f"{group['id']} cannot depend on itself")
            if dep not in by_id:
                raise ExecutionGroupError(f"{group['id']} depends on unknown group {dep}")
    color={gid:0 for gid in by_id}
    def visit(gid:str)->None:
        if color[gid]==1:
            raise ExecutionGroupError(f"execution group dependency cycle at {gid}")
        if color[gid]==2:
            return
        color[gid]=1
        for dep in by_id[gid]["dependsOn"]:
            visit(dep)
        color[gid]=2
    for gid in sorted(by_id):
        visit(gid)
    candidates=[g for g in groups if g["parallel"]]
    for i,left in enumerate(candidates):
        for right in candidates[i+1:]:
            if _depends_transitively(by_id,left["id"],right["id"]) or _depends_transitively(by_id,right["id"],left["id"]):
                continue
            for lp in left["mutationPaths"]:
                for rp in right["mutationPaths"]:
                    if mutation_paths_overlap(lp,rp):
                        raise ExecutionGroupError(f"parallel execution groups have overlapping mutation surfaces: {left['id']}:{lp} <-> {right['id']}:{rp}")
    return groups

def execution_groups_to_storage(groups: list[dict[str,Any]]) -> dict[str,dict[str,Any]]:
    """Encode normalized groups into restricted-YAML-compatible frontmatter."""
    return {
        group["id"]: {
            "title": group["title"],
            "steps": list(group["steps"]),
            "dependsOn": list(group["dependsOn"]),
            "mutationPaths": list(group["mutationPaths"]),
            "verificationResponsibilities": list(group["verificationResponsibilities"]),
            "parallel": group["parallel"],
        }
        for group in groups
    }

def topological_group_order(groups: list[dict[str,Any]]) -> list[str]:
    by_id={g["id"]:g for g in groups}; seen:set[str]=set(); order:list[str]=[]
    def visit(gid:str)->None:
        if gid in seen: return
        for dep in sorted(by_id[gid]["dependsOn"]): visit(dep)
        seen.add(gid); order.append(gid)
    for gid in sorted(by_id): visit(gid)
    return order

def dependency_layers(groups: list[dict[str,Any]]) -> list[list[str]]:
    remaining={g["id"]:set(g["dependsOn"]) for g in groups}; completed:set[str]=set(); layers:list[list[str]]=[]
    while remaining:
        ready=sorted(gid for gid,deps in remaining.items() if deps<=completed)
        if not ready:
            raise ExecutionGroupError("execution group dependency graph is not acyclic")
        layers.append(ready); completed.update(ready)
        for gid in ready: del remaining[gid]
    return layers

__all__=["ExecutionGroupError","dependency_layers","execution_groups_to_storage","implementation_plan_step_count","mutation_paths_overlap","normalize_execution_groups","topological_group_order"]
