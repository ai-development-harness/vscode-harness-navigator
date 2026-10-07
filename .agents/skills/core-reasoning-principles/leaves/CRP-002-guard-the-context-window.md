---
schema: 1
namespace: CRP
id: CRP-002
slug: guard-the-context-window
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - context-heavy
---

# CRP-002 — Guard the context window

## Trigger / applicability

Use when the resolved Context Contract is structurally large: many linked artifacts/sections already consume the semantic budget.

## Rationale

Large raw context degrades reasoning and makes accidental full-repository preload more likely. Harness already resolves section-level context, so the reasoning layer should preserve that advantage.

## Actionable pattern

Read the selected sections first. Pull extra files only through explicit material expansion. Summarize bulky evidence instead of copying it into the main reasoning thread. Do not reread the same large file when a stable compact result already exists.
