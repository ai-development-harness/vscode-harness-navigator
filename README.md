<!-- PROJECT:START -->
# VSCode Harness Navigator

Локальное read-only расширение Visual Studio Code для навигации по STEP, REQ, ADR, OQ и справке по canonical-командам AI Development Harness 0.6.0+.

Ключевые документы:

- [Описание проекта](docs/PROJECT.md)
- [Требования](docs/requirements/SPEC.md)
- [Архитектура](docs/architecture.md)
- [Roadmap](planning/PLAN.md)

Текущая точка входа в разработку: `STEP PLAN STEP-001`.
<!-- PROJECT:END -->

## Зависимости

- Python 3.11+ — обязателен для deterministic tools/validators.
- Git — обязателен для repository workflow.
- Codex **или** Claude Code — runtime выбирается пользователем; оба одновременно не требуются.
- GitHub CLI `gh` — optional capability dependency: нужен только для `GIT PR` / `GIT PR FINISH` при текущей GitHub PR integration.

Подробно: [`.harness/docs/DEPENDENCIES.md`](.harness/docs/DEPENDENCIES.md).

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
