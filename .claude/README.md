# Claude Code adapter

`.claude/settings.json` задаёт project-scoped defaults root-сессии Claude Code: модель и effort.

`.claude/agents/*.md` содержит специализированные роли Harness. Для каждой роли можно независимо выбрать `model`, `effort` и `permissionMode`.

`CLAUDE.md` импортирует канонический `AGENTS.md`, поэтому Claude Code и Codex получают один protocol contract без дублирования repository instructions.

## Skills

Core Harness skills остаются в `.agents/skills/`. Это vendor-neutral source of truth, который используют все runtime adapters. Claude Code должен читать выбранный protocol skill напрямую из `.agents/skills/<name>/SKILL.md`.

Не копируй core skills в `.claude/skills/`: две tracked копии одного workflow быстро расходятся. Project-specific Claude-native skills при необходимости можно добавлять в `.claude/skills/`; неизвестные updater path по умолчанию считаются project-owned.

## Локальные настройки

Для персонального выбора root-модели/effort используй `.claude/settings.local.json`. Для локальных инструкций Claude Code используй `CLAUDE.local.md`.

Оба файла игнорируются Git. Tracked `.claude/settings.json` и `.claude/agents/*.md` считаются shared Harness files и при `HARNESS UPDATE APPLY` проходят 3-way merge, поэтому проектные настройки модели не должны молча затираться.

Почему у Claude Code есть нативный project-local settings layer, а у Codex пока нет его аналога, описано в [`.harness/docs/AGENT_CONFIGURATION.md`](../.harness/docs/AGENT_CONFIGURATION.md#локальные-настройки-runtime).
