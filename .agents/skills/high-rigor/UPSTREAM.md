# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/high-rigor/`
Provenance recorded: `2026-10-06`

## Design references

- pstack Arena:
  https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills/arena
- pstack Interrogate:
  https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills/interrogate

## Harness adaptation

Harness keeps independent fan-out, shared rubric, independent judging, agreement/
disagreement preservation and lead synthesis. It removes provider-specific model
tables from canonical semantics, adds deterministic activation policy, exact
byte-traceable local inputs/results, bounded char budgets, explicit DEGRADED
state and a hard rule that multi-agent consensus never replaces Harness gates.
