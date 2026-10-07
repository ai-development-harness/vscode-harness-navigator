---
schema: 1
namespace: CRP
id: CRP-003
slug: prove-the-real-artifact
status: active
roles:
  - reviewer
triggers:
  - review-phase
---

# CRP-003 — Prove the real artifact

## Trigger / applicability

Use during semantic REVIEW before accepting a claim about implemented behavior, generated output, or completed verification.

## Rationale

Self-report, compile success, cached output, or a nearby proxy can look convincing while the actual artifact is wrong. Existing deterministic Harness gates remain authority; this principle only guides semantic evidence selection.

## Actionable pattern

For each material semantic claim, inspect the real artifact or canonical evidence that directly demonstrates it. Prefer rerunnable checks. If a deterministic gate already proves the fact, reuse that result instead of restating it as model judgement.
