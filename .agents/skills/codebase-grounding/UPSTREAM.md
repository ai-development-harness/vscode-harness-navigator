# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/codebase-grounding/`
Provenance recorded: `2026-10-06`
External upstream: none

## References

- GitHub issue #219 — Read-only Codebase Grounding capability.
- pstack `how` skill used only as a design reference:
  https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills/how
- `.harness/docs/CONTEXT_CONTRACTS.md`
- `.harness/docs/CODEBASE_GROUNDING.md`

## Rationale

Harness already owns deterministic artifact selection, repository revision and explicit context expansion. This capability adds only the semantic layer needed to reconstruct flow, ownership and boundaries without turning repository traversal or model inference into authority.
