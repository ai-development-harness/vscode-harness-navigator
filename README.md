<!-- PROJECT:START -->
# AI Development Harness — новый проект

Проект ещё не инициализирован.

1. Создай локальный brief:

   ```bash
   cp PROJECT_BRIEF.example.md PROJECT_BRIEF.local.md
   ```

2. Опиши проект своими словами в `PROJECT_BRIEF.local.md`: цель, пользователей, сценарии, ограничения, предпочтительный стек, референсы и любые важные заметки.
3. При необходимости скопируй `AGENTS.local.example.md` в `AGENTS.local.md` и добавь локальные команды/предпочтения.
4. Открой репозиторий в Codex или Claude Code.
5. Выполни:

   ```text
   PROJECT INIT
   ```

После успешной инициализации агент заменит **только этот блок** описанием конкретного проекта, ключевыми ссылками и текущей точкой входа в разработку.
<!-- PROJECT:END -->

## Runtime adapters

Harness protocol не привязан к одной модели или одному coding agent:

- Codex: `.codex/config.toml` + `.codex/agents/*.toml`;
- Claude Code: `CLAUDE.md` + `.claude/settings.json` + `.claude/agents/*.md`.

`AGENTS.md`, execution protocol, REQ/ADR/STEP и `.agents/skills/` остаются общими источниками истины.

## Документация Harness

- [Начало работы](.harness/docs/GETTING_STARTED.md)
- [Как устроена документация и связи REQ / ADR / STEP / PLAN / STATUS](.harness/docs/DOCUMENT_MODEL.md)
- [Глоссарий терминов Harness](.harness/docs/GLOSSARY.md)
- [Структура репозитория](.harness/docs/REPOSITORY_LAYOUT.md)
- [Команды](.harness/docs/COMMANDS.md)
- [Execution Protocol](.harness/docs/EXECUTION_PROTOCOL.md)
- [Обновление Harness в существующем проекте](.harness/docs/UPDATES.md)
- [Агенты, модели и reasoning effort](.harness/docs/AGENT_CONFIGURATION.md)
- [Claude Code adapter](.harness/docs/CLAUDE_CODE.md)
- [Git workflow: GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT SYNC](.harness/docs/GIT_WORKFLOW.md)
- [CI и Harness Integrity](.harness/docs/CI.md)
- [Skills: SKILL FIND / SKILL INSTALL / SKILL CREATE](.harness/docs/SKILL_MANAGEMENT.md)
- [Синтаксис команд и цепочек](.harness/docs/COMMAND_SYNTAX.md)
- [Таблица допустимых переходов команд](.harness/docs/COMMAND_TRANSITIONS.md)
- [Полное оглавление документации Harness](.harness/docs/README.md)
