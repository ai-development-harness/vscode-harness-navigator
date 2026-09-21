# Настройка моделей и reasoning effort

Цель — тратить дорогой reasoning там, где он действительно повышает качество, а не на механические изменения.

Harness отделяет **роль** от конкретного AI runtime. Канонические responsibilities задаются protocol/role instructions, а выбор model/effort хранится в adapter-конфигурации:

- Codex: `.codex/config.toml` и `.codex/agents/*.toml`;
- Claude Code: `.claude/settings.json` и `.claude/agents/*.md`.

Подробности Claude adapter: [`CLAUDE_CODE.md`](CLAUDE_CODE.md).

## Базовый профиль

### Codex

| Роль | Модель | Effort | Когда |
|---|---|---|---|
| initializer | GPT-5.6 Sol | high | только bootstrap/re-bootstrap analysis |
| architect | GPT-5.6 Sol | high | архитектурные решения |
| planner | GPT-5.6 Sol | high | сложный анализ перед реализацией |
| implementer | GPT-5.6 Terra | medium | основной coding volume |
| reviewer | GPT-5.6 Sol | high | независимый поиск дефектов |
| security-reviewer | GPT-5.6 Sol | high | условно, security-sensitive changes |
| test-reviewer | GPT-5.6 Terra | low | условно, сложная test surface |
| docs | GPT-5.6 Terra | low | синхронизация документации |
| mechanic | GPT-5.6 Terra | low | локальная механическая работа |
| skill-curator | GPT-5.6 Sol | medium | внешние skills требуют careful inspection/provenance |
| git-operator | GPT-5.6 Terra | medium | diff classification, commit/branch/PR safety |
| harness-updater | GPT-5.6 Sol | high | BASE/OURS/THEIRS reconciliation и ownership conflicts |

### Claude Code

| Роль | Модель | Effort | Permission |
|---|---|---|---|
| initializer | opus | high | default |
| architect | opus | high | plan |
| planner | opus | high | plan |
| implementer | sonnet | medium | default |
| reviewer | opus | high | plan |
| security-reviewer | opus | high | plan |
| test-reviewer | sonnet | low | plan |
| docs | sonnet | low | default |
| mechanic | sonnet | low | default |
| skill-curator | opus | medium | default |
| git-operator | sonnet | medium | default |
| harness-updater | opus | high | default |

Family aliases в Claude Code выбраны намеренно: они позволяют runtime использовать актуальную разрешённую модель семейства. Проект при необходимости может закрепить конкретный model ID.

## Главный принцип экономии

Сначала сокращай **лишние агентные проходы и контекст**, а уже затем снижай effort.

Не запускай security/test reviewer для задачи, которой они не касаются. Planner можно пропустить внутри `RUN`, если task уже имеет свежий и достаточный Implementation plan. Механические изменения не должны уходить к самой дорогой reasoning-модели.

## Когда повышать implementer

Повышай роль на STEP, если присутствуют несколько факторов:

- cross-module/cross-service refactoring;
- concurrency/race conditions;
- сложные migrations/data transformations;
- security boundary;
- public API/protocol compatibility;
- сложная state machine;
- критичный performance path;
- много неочевидных side effects.

В остальных случаях balanced implementer profile является рекомендуемым default.

## Когда допустим Low

Low подходит для хорошо специфицированных, локальных задач:

- rename;
- boilerplate;
- простое поле/DTO/config;
- очевидные unit-test additions;
- документация;
- механический refactor без изменения поведения.

Если reviewer регулярно находит substantive findings после Low implementer, верни Medium. Используй фактическую статистику проекта, а не предположение.

## Почему reviewer обычно сильнее implementer

Implementer получает готовый task/plan и решает задачу в заданной рамке. Reviewer должен самостоятельно обнаружить то, что автор пропустил. Поэтому при ограниченном бюджете выгоднее экономить на механической реализации, а не на независимом контроле качества.

## Контекст и output

Агенты должны:

- читать только релевантные skills/docs;
- не пересказывать целиком task/ADR/REQ в финальном ответе;
- отдавать короткий structured handoff;
- не запускать параллельно несколько write-agents над одними файлами.

## Как изменить модель

### Codex

Редактируй конкретный `.codex/agents/<role>.toml`:

```toml
model = "gpt-5.6-terra"
model_reasoning_effort = "medium"
```

Root defaults и лимит параллелизма находятся в `.codex/config.toml`.

### Claude Code

Редактируй конкретный `.claude/agents/<role>.md`:

```yaml
---
model: sonnet
effort: medium
permissionMode: default
---
```

Root defaults находятся в `.claude/settings.json`:

```json
{
  "model": "sonnet",
  "effortLevel": "medium"
}
```

Tracked Codex и Claude role configs относятся к `shared`, поэтому пользовательские изменения сохраняются при Harness update через 3-way merge.

## Локальные настройки runtime

AI Development Harness использует нативную модель конфигурации каждого runtime. Поэтому локальные файлы Codex и Claude Code намеренно не симметричны.

### Claude Code

Claude Code нативно поддерживает project-local настройки:

```text
.claude/settings.local.json
```

Используй этот файл для персональных настроек текущего проекта, которые не должны попадать в Git: например, для локального выбора root-модели, effort или permission overrides.

Shared project defaults остаются в:

```text
.claude/settings.json
```

`settings.local.json` является нативным механизмом Claude Code, поэтому Harness поддерживает его напрямую и исключает из Git.

### Codex

Codex сейчас не имеет отдельного project-local файла, эквивалентного `.claude/settings.local.json`.

Shared project settings Harness остаются в:

```text
.codex/config.toml
```

Не создавай `.codex/config.local.toml`: пока Codex не поддерживает такой файл как отдельный слой конфигурации, его наличие создаст ложное впечатление, что runtime читает его автоматически.

Для персональных настроек Codex доступны следующие нативные варианты.

**Пользовательские defaults для всех проектов:**

```text
~/.codex/config.toml
```

**Переиспользуемый пользовательский профиль:**

```text
~/.codex/<profile>.config.toml
```

```bash
codex --profile <profile>
```

Project `.codex/config.toml` имеет более высокий приоритет, чем profile. Поэтому profile полезен для набора пользовательских defaults, но не является полным аналогом Claude `settings.local.json` и не переопределит значение, уже заданное project-конфигурацией.

**Локальный override для конкретного запуска:**

```bash
codex \
  --model <model> \
  --config model_reasoning_effort='"high"'
```

CLI flags и `--config` имеют более высокий приоритет, чем `.codex/config.toml`, поэтому это нативный способ переопределить project setting без изменения tracked-файла.

Если для конкретного проекта нужен постоянный локальный launcher или другой вспомогательный механизм, его можно хранить под:

```text
.codex/local/
```

Этот каталог исключён из Git. Важно: `.codex/local/` является только зарезервированным Harness местом для пользовательских локальных файлов; Codex не читает его автоматически. Launcher или внешний инструмент должен сам передать необходимые значения через поддерживаемые CLI overrides.

### Почему Harness не создаёт `.codex/config.local.toml`

Harness не вводит искусственный `.codex/config.local.toml` только ради одинаковой структуры каталогов. Runtime adapters должны использовать нативные возможности соответствующего инструмента, а не имитировать несуществующую семантику.

У Codex уже есть открытый upstream feature request на нативный gitignored project-local override layer:

- [`openai/codex#24961 — Add explicit config scopes with a gitignored project-local override layer`](https://github.com/openai/codex/issues/24961)

Как только такой механизм появится в Codex, Harness добавит его поддержку в следующем совместимом релизе. До этого Harness использует только официально поддерживаемые способы конфигурации и явно обозначает `.codex/local/` как user-owned helper area, а не как автоматически загружаемый configuration layer.

## Профили

### Quality-first

- reasoning roles: сильная модель + high;
- implementer: сильная/balanced модель, Medium или High для critical STEP;
- test-reviewer: Medium при сложной test surface;
- harness-updater: High, потому что запускается редко и ошибка может повредить protocol layer.

### Balanced (default)

- reasoning roles: сильная модель + High;
- implementer: balanced model + Medium;
- mechanical roles: balanced/cheap model + Low;
- harness-updater: сильная модель + High.

### Budget-first

- planner: balanced model + High для обычных задач, сильная модель только для architecture-heavy;
- implementer: Low/Medium;
- reviewer: сильная модель + High только для major/risky STEP, balanced + Medium для малых corrective STEP;
- mechanic/docs: Low;
- harness-updater не понижать автоматически: update лучше запускать реже, но с сильным reconciliation profile.

Budget-first не отменяет security/release gates для high-risk изменений.

## Skill curator

`skill-curator` вызывается редко, поэтому здесь выгоднее умеренно сильный профиль, чем максимальная экономия: он читает недоверенные third-party instructions/scripts и принимает решение об installation risk.

Для skill со scripts/hooks/network/security tooling разумно повысить curator до максимального обычного reasoning profile или дополнительно привлечь `security_reviewer`.

## Git operator

Задача в основном механическая, но требует аккуратно классифицировать diff, отделять unrelated files и формировать commit/PR metadata. Low допустим для очень простого репозитория, но Medium является более безопасным default. Git operator не должен принимать архитектурные решения и не заменяет reviewer.

## Harness updater

Updater сравнивает immutable source BASE, local OURS и target THEIRS, определяет ownership boundary и должен предпочитать blocker потенциально разрушительному auto-merge. Он не выполняет product work, STEP или Git publication и не запускает target migration scripts.

Для этой роли сохраняй сильную модель и High независимо от выбранного runtime.
