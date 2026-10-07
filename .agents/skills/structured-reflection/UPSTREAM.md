# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/structured-reflection/`
External upstream: none

## References

- GitHub issue #227 — Structured Reflection.
- pstack `reflect` used as a design reference only.
- `.harness/docs/STRUCTURAL_ENFORCEMENT.md`
- `.harness/docs/STRUCTURED_REFLECTION.md`

## Rationale

Harness already has durable review/fix/progress/evidence contracts. Reflection consumes those artifacts instead of chat transcripts and can only propose one durable routing target per lesson.
