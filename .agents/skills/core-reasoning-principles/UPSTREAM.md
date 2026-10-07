# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/core-reasoning-principles/`
Provenance recorded: `2026-10-06`

Design references:
https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills

Adapted references:

- `principle-encode-lessons-in-structure`
- `principle-guard-the-context-window`
- `principle-prove-it-works`
- `principle-sequence-verifiable-units`
- `principle-separate-before-serializing-shared-state`
- `principle-attack-the-premise`
- `principle-subtract-before-you-add`
- `principle-minimize-reader-load`

## Harness adaptation

Harness does not load a principle catalog globally. It keeps eight short CRP
leaves behind a deterministic runtime-neutral applicability selector and keeps
the CRP namespace structurally separate from project-owned PRN-NNN artifacts.
Existing deterministic gates remain authoritative.
