---
schema: 1
namespace: CRP
id: CRP-007
slug: subtract-before-adding
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - refactor
---

# CRP-007 — Subtract before adding

## Trigger / applicability

Use for refactor STEP where new abstraction, wrapper, compatibility layer, or replacement structure is being considered.

## Rationale

Adding structure on top of obsolete structure compounds maintenance cost and makes the intended design harder to see.

## Actionable pattern

Remove dead/redundant paths and obsolete indirection before adding the replacement. Prefer the smallest surface that satisfies the contract. Do not add speculative validators, wrappers, or extension points without an observed requirement.
