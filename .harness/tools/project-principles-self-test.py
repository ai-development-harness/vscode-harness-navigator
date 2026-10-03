#!/usr/bin/env python3
"""Positive/negative regressions for Project Principles."""
from __future__ import annotations
from pathlib import Path
import tempfile
from principles import active_blocking_principles, validate_principles

MANIFEST="""sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  principles: docs/principles
"""
def w(root:Path,p:str,s:str)->None:
    x=root/p; x.parent.mkdir(parents=True,exist_ok=True); x.write_text(s,encoding="utf-8")
def req()->str:
    return """---
schema: 1
id: REQ-001
priority: high
source: brief
steps: []
adrs: []
---
# REQ-001 — R
## Requirement
Behavior.
## Rationale
Reason.
## Acceptance
- Observable.
"""
def adr()->str:
    return """---
schema: 1
id: ADR-001
status: accepted
date: 2026-01-01
deciders: []
supersedes: []
superseded_by: []
requirements: []
steps: []
---
# ADR-001 — A
## Context
C.
## Problem
P.
## Decision
D.
## Alternatives considered
A.
## Consequences
C.
## Security implications
None.
## Data / migration implications
None.
## Compatibility / operational implications
None.
"""
def prn(pid:str,status="active",severity="blocking",superseded_by="null",requirements:tuple[str,...]=(),adrs:tuple[str,...]=())->str:
    req_yaml = "[]" if not requirements else "\n" + "\n".join(f"  - {item}" for item in requirements)
    adr_yaml = "[]" if not adrs else "\n" + "\n".join(f"  - {item}" for item in adrs)
    return f"""---
schema: 1
id: {pid}
status: {status}
severity: {severity}
scope: project
superseded_by: {superseded_by}
requirements: {req_yaml}
adrs: {adr_yaml}
---
# {pid} — Compatibility
## Rule
Public contract changes preserve backward compatibility.
## Rationale
Future steps must not silently break consumers.
## Applies to
Project-wide public contracts.
## Exceptions / approved deviation
Only explicit reviewed deviation.
"""
def main()->int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); w(root,".harness/manifest.yaml",MANIFEST); w(root,"docs/requirements/REQ-001-r.md",req()); w(root,"docs/adr/ADR-001-a.md",adr())
        w(root,"docs/principles/PRN-001-compat.md",prn("PRN-001",requirements=("REQ-001",),adrs=("ADR-001",)))
        assert validate_principles(root)==[] and "PRN-001" in active_blocking_principles(root)
        w(root,"docs/principles/PRN-002-advisory.md",prn("PRN-002",severity="advisory")); assert "PRN-002" not in active_blocking_principles(root)
        w(root,"docs/principles/PRN-003-bad-ref.md",prn("PRN-003",requirements=("REQ-999",))); assert any("unknown requirements reference REQ-999" in e for e in validate_principles(root)); (root/"docs/principles/PRN-003-bad-ref.md").unlink()
        w(root,"docs/principles/PRN-004-old.md",prn("PRN-004",status="superseded",superseded_by="PRN-999")); assert any("superseding principle does not exist" in e for e in validate_principles(root)); (root/"docs/principles/PRN-004-old.md").unlink()
        w(root,"docs/principles/PRN-005-self.md",prn("PRN-005",status="superseded",superseded_by="PRN-005")); assert any("principle cannot supersede itself" in e for e in validate_principles(root)); (root/"docs/principles/PRN-005-self.md").unlink()
        w(root,"docs/principles/PRN-001-duplicate.md",prn("PRN-001")); assert any("duplicate canonical id PRN-001" in e for e in validate_principles(root))
    print("project-principles contract self-test: PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
