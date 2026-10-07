# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/decision-archaeology/`
Provenance recorded: `2026-10-06`
External upstream: none

## References

- GitHub issue #221 — Decision Archaeology.
- pstack `why` skill used as a design reference:
  https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills/why
- `.harness/docs/DECISION_ARCHAEOLOGY.md`
- `.harness/docs/CONTEXT_CONTRACTS.md`

## Rationale

The pstack reference emphasizes broad multi-source investigation. Harness keeps
the useful epistemic boundary — documented evidence vs inference, conflicts and
coverage gaps — but adapts it to a provider-neutral bounded contract. Canonical
repository artifacts remain highest-priority evidence; external sources are
optional supplied evidence rather than mandatory MCP dependencies.
