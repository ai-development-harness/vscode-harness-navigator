# AI Development Harness — документация

Эта папка описывает **сам Harness**, а не конкретный продукт. После `PROJECT INIT` продуктовая документация остаётся в repository-level `docs/` и `planning/`, а документация ядра Harness — здесь.

## С чего начать

- [`GETTING_STARTED.md`](GETTING_STARTED.md) — создание проекта из template и `PROJECT INIT`.
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — обязательные core dependencies, runtime adapters и optional GitHub PR capability.
- [`DOCUMENT_MODEL.md`](DOCUMENT_MODEL.md) — какие артефакты существуют, что является источником истины и как связаны REQ / ADR / STEP / PLAN / STATUS / Evidence / Review.
- [`GLOSSARY.md`](GLOSSARY.md) — полный словарь терминов и сокращений Harness.
- [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md) — файловая архитектура и разделение protocol / knowledge / implementation.
- [`COMMANDS.md`](COMMANDS.md) — пользовательский командный интерфейс.
- [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md) — namespaces, targets и chain operator `>`.
- [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md) — полная transition matrix, validation order и runtime conditions.
- [`EXECUTION_STATUS.md`](EXECUTION_STATUS.md) — единый local execution-status.json, resume semantics и independent single/chain/orchestration executions.
- [`LANGUAGE_POLICY.md`](LANGUAGE_POLICY.md) — единая настройка языка для docs/commits/comments/tests/fixtures/templates.
- [`QUICK_CHANGES.md`](QUICK_CHANGES.md) — когда мелкая правка не требует STEP.
- [`UPDATES.md`](UPDATES.md) — безопасное обновление Harness в уже идущем проекте.
- [`EXECUTION_PROTOCOL.md`](EXECUTION_PROTOCOL.md) — формальная семантика state transitions и выполнения STEP.

## Агенты и автоматизация

- [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md) — runtime-neutral роли субагентов, модели, reasoning effort, локальные runtime overrides и стратегии экономии.
- [`CLAUDE_CODE.md`](CLAUDE_CODE.md) — project settings, subagents и ownership Claude Code adapter.
- [`WORKFLOW.md`](WORKFLOW.md) — устройство orchestration и durable handoff между стадиями.
- [`REPORTING.md`](REPORTING.md) — требования к итоговым отчётам.
- [`SKILL_MANAGEMENT.md`](SKILL_MANAGEMENT.md) — поиск, inspection, установка и создание skills.
- [`GITHUB_TEMPLATES.md`](GITHUB_TEMPLATES.md) — регенерация Issue Forms и PR template по текущему стеку проекта.

## Repository operations

- [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) — `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT SYNC`.
- [`CI.md`](CI.md) — Harness Integrity CI и граница между Harness CI и product CI.
- [`VALIDATORS.md`](VALIDATORS.md) — единый справочник Python-валидаторов, validation gates, CLI-ключей, exit codes и примеров запуска.
- [`MAINTENANCE.md`](MAINTENANCE.md) — как изменять Harness, не смешивая protocol layer с product knowledge.
- [`UPDATES.md`](UPDATES.md) — release/lock/ownership/legacy-adoption lifecycle self-update.

## Project-specific документация

После `PROJECT INIT` основными продуктовыми источниками становятся:

- [`docs/PROJECT.md`](../../docs/PROJECT.md) — что это за проект и его границы;
- [`docs/requirements/`](../../docs/requirements/) — canonical `REQ-NNN-*.md`;
- [`docs/requirements/SPEC.md`](../../docs/requirements/SPEC.md) — index projection требований;
- [`docs/requirements/STATUS.md`](../../docs/requirements/STATUS.md) — lifecycle projection REQ;
- [`docs/architecture.md`](../../docs/architecture.md) — текущий архитектурный baseline;
- [`docs/adr/`](../../docs/adr/) — история устойчивых архитектурных решений;
- [`planning/PLAN.md`](../../planning/PLAN.md) — roadmap projection;
- [`planning/tasks/`](../../planning/tasks/) — канонические task contracts;
- [`docs/GLOSSARY.md`](../../docs/GLOSSARY.md) — **продуктовый** глоссарий конкретного проекта.

Не смешивай продуктовый глоссарий с [`GLOSSARY.md`](GLOSSARY.md): последний определяет язык и сущности самого Harness.
