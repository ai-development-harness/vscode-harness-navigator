---
schema: 1
namespace: CRP
id: CRP-006
slug: attack-repeated-assumptions
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - bugfix
---

# CRP-006 — Attack repeated assumptions

## Trigger / applicability

Use for bugfix work before another fix is built on the same unverified premise that could explain the failure.

## Rationale

Repeated fixes that share a false premise converge slowly because each patch treats the symptom while preserving the wrong model of the system.

## Actionable pattern

State the premise behind the proposed fix and choose an observation that could falsify it. Match the experiment to the hypothesis. If evidence weakens the premise, change the model before changing more code.
