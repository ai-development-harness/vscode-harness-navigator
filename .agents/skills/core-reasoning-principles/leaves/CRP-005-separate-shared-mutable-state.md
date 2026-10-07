---
schema: 1
namespace: CRP
id: CRP-005
slug: separate-shared-mutable-state
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - concurrency-risk
---

# CRP-005 — Separate shared mutable state before serialization

## Trigger / applicability

Use when STEP risk includes concurrency and multiple actors/components may write the same file, key, branch, queue state, or mutable object.

## Rationale

Concurrency bugs often come from unnecessary shared mutation. Locking every shared object preserves contention and complexity when ownership could instead be separated.

## Actionable pattern

Identify shared write targets. First ask whether each actor can own separate state and merge only at a read/report boundary. If one shared writer is truly invariant, enforce serialization structurally with single-writer ownership, lock/CAS/transaction, or ordered phases—not instructions.
