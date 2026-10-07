# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/pr-maintenance/`
External upstream: none

## References

- GitHub issue #226 — PR-maintenance semantic workflows.
- pstack `fix-ci`, `get-pr-comments`, `make-pr-easy-to-review`, `babysit` used as design references only.
- `.harness/docs/GIT_WORKFLOW.md`
- `.harness/docs/PR_MAINTENANCE.md`

## Rationale

Harness already owns deterministic Git/PR mutation and provider selection. This capability adds only read-only provider fact normalization plus bounded semantic interpretation, while all mutations remain in the existing Git/STEP workflows.
