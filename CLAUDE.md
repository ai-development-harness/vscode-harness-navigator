@AGENTS.md

# Claude Code adapter

Этот файл связывает Claude Code с каноническим protocol contract AI Development Harness в `AGENTS.md`.

- Общие project defaults Claude Code находятся в `.claude/settings.json`.
- Role-specific model / effort / permission profile находятся в `.claude/agents/*.md`.
- `.agents/skills/` остаётся runtime-neutral source of truth для Harness skills. Когда protocol выбирает skill, читай соответствующий `.agents/skills/<name>/SKILL.md` напрямую; не создавай дублирующую копию только ради Claude Code.
- Локальные/private overrides храни в `AGENTS.local.md`, `CLAUDE.local.md` и `.claude/settings.local.json`; эти файлы не должны попадать в Git.
- Claude-specific adapter settings не изменяют семантику команд Harness, ownership rules, REQ/ADR/STEP contracts или Git policy.
