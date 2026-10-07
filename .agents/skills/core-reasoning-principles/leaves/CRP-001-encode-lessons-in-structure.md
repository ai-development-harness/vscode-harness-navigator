---
schema: 1
namespace: CRP
id: CRP-001
slug: encode-lessons-in-structure
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - bugfix
  - hardening
---

# CRP-001 — Encode lessons in structure

## Trigger / applicability

Use on bugfix/hardening work when a correction may represent a recurring class of failure. First decide whether the issue is one-off or structural; do not invent a new mechanism for a single isolated mistake.

## Rationale

Repeated prose reminders are weak enforcement. A recurring failure is better captured by the strongest reliable mechanism already available: type/schema constraint, validator, lint/CI rule, canonical helper, or runtime guard.

## Actionable pattern

If structured Harness evidence shows the same class recurring, invoke the internal `structural-enforcement` capability instead of adding another instruction. It deterministically proves recurrence and enforces the ladder architecture/ownership → schema/type → validator/lint → regression → durable instruction. Do not infer recurrence from memory or transcript. Prefer prose only where judgement is irreducible.
