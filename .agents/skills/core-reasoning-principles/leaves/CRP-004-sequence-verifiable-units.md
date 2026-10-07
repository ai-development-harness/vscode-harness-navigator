---
schema: 1
namespace: CRP
id: CRP-004
slug: sequence-verifiable-units
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - multi-unit
---

# CRP-004 — Sequence verifiable units

## Trigger / applicability

Use when work has multiple declared execution groups/dependencies or migration/release risk that makes partial ordering material.

## Rationale

A failure localized to one small verified unit is cheaper to diagnose than a failure discovered after a large batch. Ordered units also make review evidence easier to replay.

## Actionable pattern

Break the change into ordered units with an observable check at each boundary. Do not advance past a failed unit. Prefer a delivery order where each commit/group is independently understandable and the verification story remains monotonic.
