#!/usr/bin/env python3
"""Workflow regression for Project Principles PLAN/REVIEW enforcement."""
from __future__ import annotations
from pathlib import Path
import tempfile
from planning_contract import planning_context_basis, planning_context_snapshot
from principles import active_blocking_principles, validate_principles

MANIFEST="""sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  principles: docs/principles
protocol:
  taskDirectory: planning/tasks
"""
REQ="""---
schema: 1
id: REQ-001
priority: high
source: brief
steps:
  - STEP-001
adrs: []
---
# REQ-001 — Public API
## Requirement
Public API remains usable by supported clients.
## Rationale
Existing integrations must continue to work.
## Acceptance
- Supported clients continue working during migration.
"""
STEP="""---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: high
phase: P1
depends_on: []
requirements:
  - REQ-001
adrs: []
architecture_refs: []
risk_flags:
  - public-api
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---
# STEP-001 — Change public API
## Goal
Change public API safely.
## Context
REQ-001.
## Scope
- API migration.
## Mutation policy
### Allowed
- src/api
### Conditional
- compatibility adapter
### Forbidden
- unrelated behavior
## Out of scope
- unrelated modules
## Acceptance criteria
- Existing supported clients continue to work.
## Verification
- manual: inspect compatibility behavior
## Deliverables
- implementation
## Implementation plan
Not planned.
## Evidence
Pending.
## Blocker / Failure reason
—
"""
PRN="""---
schema: 1
id: PRN-001
status: active
severity: blocking
scope: project
superseded_by: null
requirements:
  - REQ-001
adrs: []
---
# PRN-001 — Backward-compatible public API changes
## Rule
Public API changes must preserve backward compatibility.
## Rationale
Consumers migrate independently from server releases.
## Applies to
All public API schema and endpoint changes.
## Exceptions / approved deviation
Only an explicit reviewed deviation recorded in the owning STEP or ADR.
"""
def w(root:Path,p:str,s:str)->None:
    x=root/p; x.parent.mkdir(parents=True,exist_ok=True); x.write_text(s,encoding="utf-8")
def rule(root:Path)->str: return active_blocking_principles(root)["PRN-001"]["sections"]["Rule"]
def plan_check(root:Path,text:str)->str: return "BLOCKED" if "backward compatibility" in rule(root) and "backward-compatible" not in text else "PASS"
def review_check(root:Path,text:str)->str: return "BLOCKED" if "backward compatibility" in rule(root) and "backward-compatible" not in text else "PASS"
def main()->int:
    repo=Path(__file__).resolve().parents[2]
    assert "Project Principles" in (repo/".agents/skills/plan-step/SKILL.md").read_text(encoding="utf-8")
    assert "sources.principles" in (repo/".agents/skills/review-step/SKILL.md").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); w(root,".harness/manifest.yaml",MANIFEST); w(root,"docs/requirements/REQ-001-api.md",REQ); w(root,"planning/tasks/STEP-001.md",STEP); w(root,"docs/architecture.md","# Architecture\n"); (root/"docs/adr").mkdir(parents=True); (root/"docs/open-questions").mkdir(parents=True); w(root,"docs/principles/PRN-001-api.md",PRN)
        assert validate_principles(root)==[]; assert "PRN-001" in planning_context_snapshot(root,"STEP-001")["principles"]
        before=planning_context_basis(root,"STEP-001")
        assert plan_check(root,"Replace endpoint and remove old response.")=="BLOCKED"
        assert plan_check(root,"Introduce backward-compatible endpoint evolution.")=="PASS"
        assert review_check(root,"Tests prove backward-compatible behavior.")=="PASS"
        assert review_check(root,"Old clients fail after deployment.")=="BLOCKED"
        p=root/"docs/principles/PRN-001-api.md"; p.write_text(PRN.replace("must preserve backward compatibility.","must preserve backward compatibility for one release window."),encoding="utf-8")
        assert planning_context_basis(root,"STEP-001")!=before
    print("project-principles workflow self-test: PASS"); return 0
if __name__=="__main__": raise SystemExit(main())
