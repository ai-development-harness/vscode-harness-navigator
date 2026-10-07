---
schema: 1
namespace: CRP
id: CRP-008
slug: minimize-reader-load
status: active
roles:
  - planner
  - reviewer
triggers:
  - refactor
  - architecture-risk
---

# CRP-008 — Minimize reader and context load

## Trigger / applicability

Use for refactor or architecture-sensitive work where layers, ownership, or mutable state shape how difficult the system is to understand.

## Rationale

Maintainability cost is the number of layers a reader must trace plus the hidden state they must hold mentally. More abstraction is not automatically simpler.

## Actionable pattern

Collapse pass-through layers that hide no decision. Prefer boundaries that compress meaningful complexity. Shrink mutable state scope and make ownership/invariants explicit at one boundary instead of repeating them across consumers.
