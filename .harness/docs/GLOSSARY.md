# Глоссарий AI Development Harness

Этот документ определяет **каноническое значение терминов самого Harness**. Если термин используется в protocol, AGENTS, planning или отчётах агентов, его смысл должен соответствовать этому словарю.

Продуктовые термины конкретного проекта находятся отдельно в `docs/GLOSSARY.md` и заполняются при `PROJECT INIT`.


## Общие понятия Harness

### Harness

Набор repository-level правил, agents, skills, templates, policies и deterministic tools, который организует разработку проекта. Harness — это **прослойка процесса**, а не product framework и не runtime dependency будущего приложения.

### Protocol Layer

Стабильная часть репозитория, задающая способ работы агентов: `AGENTS.md`, `.harness/docs/EXECUTION_PROTOCOL.md`, core skills, agent configs, policies и `.harness/docs/*`.

### Command Transition System (CTS)

**Command Transition System** — детерминированная protocol-система, которая определяет:

- какие canonical commands существуют;
- какие команды могут участвовать в chain;
- какие переходы `A → B` структурно разрешены;
- при каком `onPreviousResult` edge активируется;
- какие runtime/repository preconditions должны быть выполнены;
- как наследуются DOMAIN и target.

Machine-readable source of truth: `.harness/command-transitions.json`.

Command Transition System **не считает сами команды состояниями**. Команда — это action/transition request. Фактическое состояние берётся из repository/runtime facts, например:

```text
STEP planned / implemented / review failed / review passed
Git branch clean / ahead / published / PR exists
Harness update check valid / blocked
```

Упрощённое выражение **Command State Machine** допустимо только как объяснение для человека, но не является каноническим термином Harness. Канонический термин — **Command Transition System**.

Structural validation CTS выполняется до command-specific interpretation и skill routing.

### Execution Status

Локальный crash-safe operational state всех canonical Harness-команд.

Хранится в одном фиксированном файле:

```text
.harness/local/execution/execution-status.json
```

Schema v2 хранит full records только для active/recoverable executions, отдельный `stepRecovery` для STEP proof и bounded `recentTerminals` для короткой terminal history. Новая пользовательская команда не затирает interrupted execution другой команды.

Execution Status не является product evidence и не задаёт допустимые переходы — это делает CTS.

### Execution Record

Одна фактическая root invocation пользователя.

Внутренний `mode` определяется автоматически:

- `single` — одна command;
- `chain` — explicit chain;
- `orchestration` — `STEP RUN STEP-NNN`.

Mode не является пользовательской командой или дополнительным workflow layer.

### Execution Resolver

Детерминированный механизм `.harness/tools/resolve-next-command.py`, который читает Execution Status и возвращает interrupted/current/next command внутри конкретной root execution.

Resolver не создаёт новые transitions: для chain/orchestration он использует CTS; для single execution после completion автоматически ничего не продолжает.

### Plan context basis

SHA-256 fingerprint relevant planning context, сохранённый в `plan.context_basis`.

Schema-v4 fingerprint включает semantic STEP/dependency contracts, semantic linked canonical REQ/ADR, explicit `architecture_refs` и relevant canonical OQ. Reverse traceability, scheduling metadata (`priority`/`phase`) и completion state dependency не должны инвалидировать plan; completion proof проверяется перед IMPLEMENT.

### Plan content hash

Отдельный SHA-256 fingerprint нормализованного текста `Implementation plan`. Он нужен потому, что изменение самого плана должно делать Ready stale даже при неизменном product contract.

### Project Knowledge Base

Нормализованная проектная база знаний после INIT: `PROJECT.md`, REQ, architecture, ADR, glossary, planning и связанные документы. Она должна позволять новой сессии восстановить контекст без chat history.

### Source of Truth

Авторитетный источник конкретного вида информации. Harness использует не один глобальный файл, а иерархию источников истины для factual state, architecture contract, requirements и task scope.

### Artifact

Любой долговечный результат, сохранённый в репозитории: requirement, ADR, STEP, review report, code, migration, test, config, audit report и т. п.

### Generated Block

Ограниченный участок файла между специальными markers, который агенту разрешено переписывать автоматически.

Пример:

```text
<!-- PROJECT:START -->
...
<!-- PROJECT:END -->
```

Статический текст вне generated block не должен переписываться initializer без отдельной причины.

### ID / Stable ID

Устойчивый идентификатор артефакта, который не переиспользуется и не меняется после появления в истории проекта.

Примеры: `REQ-014`, `ADR-007`, `STEP-042`.

### TBD — To Be Determined

Явная отметка, что значение ещё не определено. `TBD` лучше выдуманного ответа, но не должно бесконечно оставаться в обязательном контракте: blocking TBD превращается в Open Question / RESEARCH / ADR STEP.

## Planning metadata

### Status

Текущее lifecycle-состояние артефакта.

For canonical STEP machine status Harness использует protocol-English enum: `planned | in_progress | blocked | completed | deferred | cancelled`. Человекочитаемый UI/projection может локализовать эти значения, но frontmatter не локализуется.

REQ lifecycle-state не является canonical field. Он детерминированно выводится из canonical REQ + STEP completion proofs и отражается только в requirements STATUS projection.

### Priority

Относительная важность STEP для порядка работы. Priority не отменяет dependencies: критичный, но заблокированный STEP не становится executable только из-за высокого приоритета.

Canonical machine priority использует closed enum `critical | high | medium | low`. Проекции/UI могут локализовать отображение.

### Phase

Логическая стадия roadmap, объединяющая несколько STEP по продуктовой/архитектурной цели. Phase помогает навигации, но не заменяет dependency graph.

### Severity

Серьёзность finding в review/audit/security report. Обычно используется шкала `critical / high / medium / low` или эквивалент проекта. Severity описывает impact/risk, а не приоритет разработчика «по ощущениям».

### Type

Canonical machine `type` определяет семантику выполнения: `implementation | bugfix | refactor | research | adr | audit | review | hardening | documentation | release`. `STEP RUN STEP-NNN` обязан учитывать type-specific flow/completion proof.

## Часто встречающиеся технические сокращения

### PR — Pull Request

Запрос на интеграцию изменений одной Git branch в другую с review/CI history. Каноническая Harness-команда для создания/поиска такого запроса — `GIT PR`.

### CI — Continuous Integration

Автоматическое выполнение проверок при push/PR. В Harness различаются baseline Harness Integrity CI и product-specific CI.

### CD — Continuous Delivery / Continuous Deployment

Автоматизация подготовки или фактического развёртывания release. Harness не включает универсальный product CD заранее: он проектируется после выбора реального deployment stack.

### CLI — Command-Line Interface

Интерфейс программы через терминал. Например GitHub CLI `gh` может использоваться Git workflow для PR.

### API — Application Programming Interface

Формализованный программный интерфейс между компонентами/системами. В requirements/ADR термин должен сопровождаться конкретным контрактом, если он влияет на compatibility.

### URL — Uniform Resource Locator

Адрес ресурса. В brief может использоваться для референсов; в security-sensitive implementation URL input может потребовать отдельной проверки (например SSRF controls).

### AuthN / Authentication

Проверка **кто** является пользователем/клиентом.

### AuthZ / Authorization

Проверка **что** аутентифицированному субъекту разрешено делать.

### IDOR — Insecure Direct Object Reference

Класс authorization defect, когда пользователь может получить доступ к чужому объекту, подставив его идентификатор без корректной серверной проверки прав.

### SSRF — Server-Side Request Forgery

Уязвимость, при которой атакующий заставляет сервер выполнять нежелательные сетевые запросы, например к internal/private endpoints.

### XSS — Cross-Site Scripting

Инъекция исполняемого browser-side script/content в страницу другого пользователя из-за небезопасной обработки untrusted input/output.

### CSRF — Cross-Site Request Forgery

Атака, при которой браузер аутентифицированного пользователя принуждают отправить нежелательный state-changing request без должной защиты.

## Идентификаторы и артефакты

### REQ — Requirement

**REQ** — устойчивое проверяемое требование к продукту или системе: что должно быть истинно с точки зрения поведения, качества, безопасности, совместимости или другого продукта-контракта.

REQ отвечает на вопрос:

> **Что система обязана обеспечивать?**

Пример ID:

```text
REQ-014
REQ-1000
```

Protocol ID pattern — `REQ-NNN+`: минимум три цифры, без искусственного верхнего предела.

REQ не должен описывать конкретный файл или implementation technique без необходимости. Один REQ может реализовываться несколькими STEP.

Canonical REQ находится в configured `sources.requirements`. `SPEC.md`/`STATUS.md` внутри configured requirements directory — deterministic projections, а не competing truth.

### ADR — Architecture Decision Record

**ADR** — неизменяемая историческая запись устойчивого архитектурного решения, его контекста, альтернатив и последствий.

ADR отвечает на вопрос:

> **Какое архитектурное решение принято и почему?**

Пример:

```text
ADR-007 — Использовать PostgreSQL как основной transactional storage
```

Accepted ADR не переписывается задним числом при смене решения. Создаётся новый ADR с `Supersedes`.

ADR не создаётся для каждой мелкой реализации. Он нужен, когда решение формирует долгоживущий контракт, границу подсистем, security/data model, integration strategy или другой значимый trade-off.

Canonical ADR находится в configured `sources.adrDirectory`.

### ASR

**ASR не является термином AI Development Harness.** В текущем protocol и шаблонах такой сущности нет.

Если `ASR` встречается в контексте Harness, это следует считать ошибкой/неоднозначностью и проверить, не имелся ли в виду **ADR**. Агент не должен самостоятельно придумывать расшифровку `ASR` или создавать новый тип артефакта без явного изменения protocol.

В конкретном продукте `ASR` может иметь собственное доменное значение — тогда оно определяется в `docs/GLOSSARY.md`, а не здесь.

### STEP

**STEP** — ограниченная единица планируемой работы с устойчивым идентификатором `STEP-NNN`.

STEP отвечает на вопрос:

> **Какую конкретную работу нужно выполнить, чтобы приблизить проект к требуемому состоянию?**

Task-файл определяет status, type, priority, dependencies, связанные REQ/ADR, goal, context, scope, mutation policy, out of scope, acceptance criteria, verification, deliverables, implementation plan и evidence.

Canonical STEP находится в configured `protocol.taskDirectory`.

### PLAN

Термин используется в двух смыслах:

1. **configured `sources.roadmap`** — deterministic roadmap projection всех STEP и их порядка/зависимостей.
2. **`STEP PLAN STEP-NNN`** — команда, которая проводит pre-implementation analysis и сохраняет `Implementation plan` в task-файл.

`PLAN.md` не заменяет task-файлы и не является вторым каноническим описанием STEP.

### STATUS

Configured `sources.status` — deterministic projection текущего состояния STEP.

Requirements `STATUS.md` внутри configured `sources.requirements` — deterministic projection lifecycle REQ.

STATUS-файлы — **projection**, а не самостоятельный источник контрактов.

### PROJECT_BRIEF

Configured `sources.localBrief` — локальный сырой ввод пользователя для bootstrap. Default template использует `PROJECT_BRIEF.local.md`.

Brief не является permanent source of truth после `PROJECT INIT`. Нормализованный контекст переносится в project documentation.

### PROJECT.md

Configured `sources.projectOverview` — нормализованное описание продукта: назначение, пользователи, цели, границы, constraints и high-level scenarios.

### Architecture baseline

Configured `sources.architecture` — актуальный architecture baseline. STEP включает в planning basis только explicit `architecture_refs` на relevant document/anchor, а не весь baseline автоматически.

### Open Question

Нерешённый вопрос, на который нельзя безопасно ответить на основании имеющихся источников.

Canonical Open Question хранится отдельным schema-v1 `OQ-NNN-*.md` в configured `sources.openQuestions`; configured `sources.openQuestionsIndex` — deterministic projection. Blocking OQ может потребовать `RESEARCH`/`ADR` STEP.

## Содержимое STEP

### Goal

Краткое целевое состояние STEP — что должно измениться после его успешного выполнения.

### Context

Факты, причины и окружение, необходимые для понимания задачи. Context не должен раздуваться в полный пересказ проекта.

### Scope

Явно разрешённый объём работы текущего STEP.

### Out of scope

То, что сознательно **не входит** в STEP, даже если находится рядом по смыслу. Это основной механизм против scope creep.

### Mutation policy

Ограничение на категории файлов/подсистем, которые STEP разрешает изменять, изменять условно или запрещает менять.

### Acceptance Criteria

Набор проверяемых условий, которые должны быть истинны, чтобы считать STEP выполненным.

Acceptance criteria описывают результат, а не просто действия разработчика.

### Verification

Конкретные проверки, команды, тесты или наблюдения, которыми доказываются acceptance criteria.

Verification должен ссылаться на реальные tools/scripts проекта; агенту запрещено выдумывать команды.

### Evidence

Конкретные доказательства выполненной работы: изменённые артефакты, tests, commands и результаты, migrations, screenshots/measurements при необходимости, commit/PR reference и т. п.

Evidence обязано различать **буквально захваченный output** и **нормализованное резюме наблюдения**. Нельзя оформлять реконструированный/пересказанный terminal output как буквальную цитату. Если точный output не сохраняется, фиксируй как минимум command, exit code и краткое `Observed` с проверяемыми фактами.

Фраза `проверено, работает` evidence не является.

### Deliverable

Артефакт, который STEP обязан создать или изменить: код, документ, migration, workflow, package, configuration и т. п.

### Dependency

Другой STEP или обязательное внешнее условие, без которого текущий STEP нельзя корректно выполнить или закрыть.

### Blocker

Факт, препятствующий продолжению работы. Blocker должен содержать причину и required next action, а не только статус.

### Risk Flag

Классификация риска, влияющая на orchestration. Canonical `risk_flags` используют closed enum: `none`, `security-sensitive`, `data-migration`, `destructive`, `public-api`, `architecture`, `concurrency`, `external-integration`, `performance-critical`, `release-critical`. `none` взаимоисключающий. Flags участвуют в deterministic specialized-review preselector.

### Implementation Plan

Durable технический handoff, создаваемый `STEP PLAN STEP-NNN` и сохраняемый внутри task-файла. Должен быть достаточно конкретным, чтобы implementer мог работать в новой сессии без chat history.

## Типы STEP

### IMPLEMENTATION

Добавление или изменение product behavior/code/configuration/tests.

### BUGFIX

Исправление подтверждённого дефекта с воспроизводимым ожидаемым поведением.

### ADR

STEP, целью которого является принятие или reconciliation архитектурного решения, а не реализация production code.

### RESEARCH

Исследование неизвестного, сравнение вариантов, spike или получение evidence перед решением. Не должен выдавать догадку за Accepted ADR.

### AUDIT

Формальная проверка состояния без скрытого исправления production code. Найденные дефекты становятся findings/corrective work.

### REVIEW

Проверка уже существующего результата относительно task/REQ/ADR/acceptance/evidence.

### DOCUMENTATION

Документационная работа, где production behavior не должен изменяться.

### HARDENING

Усиление reliability/security/performance/operability существующей capability.

### RELEASE

Release-oriented gate: готовность версии/развёртывания/миграций/документации и других release constraints.

## Review и качество

### Review

Независимая проверка реализации. Reviewer не должен быть автором проверяемого изменения.

Review report хранится отдельно и не переписывает task contract.

### Finding

Конкретная проблема, найденная review/audit. Хороший finding содержит severity, location, scenario/preconditions, impact и fix direction.

### Verdict

Итог независимого review:

- `PASS` — material closing problems не обнаружено, acceptance/evidence достаточны;
- `FAIL` — подтверждены implementation/evidence defects, которые можно исправить внутри существующего STEP contract;
- `BLOCKED` — review/planning не может безопасно продолжаться из-за contract contradiction, missing decision/prerequisite, stale planning context или другого препятствия, которое нельзя честно превратить в обычный FIX.

`BLOCKED` терминален для текущей execution и не должен автоматически превращаться в `FAIL → FIX`.

### FIX

Отдельный проход исправления подтверждённых findings последнего применимого FAIL review. FIX не должен превращаться в новую бесконтрольную реализацию.

### Corrective STEP

Новый STEP, создаваемый для дефекта/drift/prerequisite, который не должен скрыто исправляться в scope текущей работы.

### Gate / Deterministic Gate

Проверяемое машиной или воспроизводимой процедурой условие: tests, typecheck, lint, build, migration check, schema validation и т. п.

AI verdict не заменяет deterministic gate.

### Release Check

Проверка проекта перед выпуском: unresolved findings, requirements, tests/build, security, migrations, docs, compatibility/deploy concerns.

## Согласованность документации

### Canonical Source

Файл/артефакт, являющийся основным источником конкретного контракта. Например task-файл — canonical source STEP, а `PLAN.md` — его projection.

### Projection

Производное представление канонических данных, удобное для навигации или отчётности. Projection обязана синхронизироваться с canonical sources.

### Traceability

Возможность пройти связь в обе стороны между requirement, decision, task, implementation и evidence.

Базовая цепочка:

```text
REQ ↔ STEP ↔ Evidence
       ↑
      ADR
```

### Drift

Расхождение между слоями проекта.

#### Architecture Drift

Фактическая реализация расходится с Accepted ADR или устойчивым архитектурным контрактом.

#### Documentation Drift

Документация описывает не то, что реально существует или принято.

#### Status Drift

PLAN/STATUS/REQ status не соответствует canonical task/evidence/factual state.

### RECONCILE

Процесс обнаружения и документированного разрешения drift через `PROJECT RECONCILE`. Он не должен молча переписывать production code.

## Агенты и execution

### Root Agent

Основной агент текущей сессии, который принимает пользовательскую команду, читает protocol и оркестрирует специализированные роли.

### Subagent

Отдельный agent thread со своей ролью, model/effort/configuration и ограниченным контекстом.

### Role

Специализация субагента: `planner`, `implementer`, `reviewer`, `architect`, `git_operator` и т. п.

### Model

Конкретная модель, используемая ролью. Настраивается в `.codex/agents/*.toml` и может отличаться между ролями.

### Reasoning Effort

Объём reasoning budget модели (`low`, `medium`, `high` и другие поддерживаемые конкретной моделью значения). Больше effort обычно дороже и медленнее, поэтому выбирается по сложности роли.

### Sandbox Mode

Ограничение filesystem/tool mutation агента. Например `read-only` для reviewer/planner и `workspace-write` для implementer.

### Approval Policy

Правило, когда Codex должен запросить человеческое подтверждение перед потенциально чувствительным действием.

### Orchestration

Координация стадий/ролей, например:

```text
PLAN → IMPLEMENT → REVIEW → FIX → REVIEW
```

### Durable Handoff

Сохранённый в репозитории результат стадии, позволяющий следующему агенту/сессии продолжить работу без chat history.

## Skills

### Skill / Repository Skill

Версионируемый playbook в `.agents/skills/<name>/`, основной инструкцией которого является `SKILL.md`. Может включать references/scripts/assets.

### Skill Routing

Короткое правило в generated-block `AGENTS.md`, указывающее, для какого класса задач применять установленный skill.

### Skill Registry

`docs/skills/REGISTRY.md` — реестр дополнительных skills, их происхождения и локальных адаптаций.

### Provenance

Информация о происхождении стороннего skill: repository, path, URL, commit/ref, license, дата установки и local modifications.

### Upstream

В контексте skills — исходный внешний источник, из которого skill установлен.

## Git и CI

### GIT COMMIT

Harness-команда для безопасной подготовки локального Git commit: preflight, staging policy, hygiene checks, commit message и traceability. Не выполняет GIT PUSH.

### Conventional Commit

Формат subject вида:

```text
feat(scope): краткое описание
```

Harness дополняет его body с Context / Changes / Verification / Traceability согласно policy.

### GIT PUSH

Публикация уже существующих commit текущей ветки в configured remote после fetch/divergence/safety checks.

### PR — Pull Request

Запрос на интеграцию опубликованной ветки в base branch. Harness может создавать или переиспользовать PR согласно `.harness/git-policy.toml`.

### GIT PR FINISH

Standalone post-merge cleanup-команда. Подтверждает merged PR через provider, возвращается на сохранённую return/base branch, допускает только safe ff-only update и удаляет локальную PR-ветку без force.

### GIT SYNC

Проверка состояния local/remote branch. По умолчанию read-only report; policy может разрешать только безопасный fast-forward.

### Protected Branch

Ветка (`main`, `master` и т. п.), для которой Harness применяет повышенные ограничения на commit/push.

### Remote

Именованный Git remote, обычно `origin`.

### Upstream Branch

В Git-контексте — remote branch, с которой связана локальная ветка. Не путать с upstream источником стороннего skill.

### CI — Continuous Integration

Автоматические проверки репозитория при push/PR.

### Harness Integrity CI

Минимальный CI самого Harness: обязательные файлы, configs, agent bindings, forbidden tracked files, repository hygiene и форматные invariants.

### Product CI

Проверки конкретного продукта после INIT: tests, lint, typecheck, build, migrations, deploy checks и другие реальные gates выбранного стека.

### Local-only file

Файл, намеренно не отслеживаемый Git, например `PROJECT_BRIEF.local.md`, `.env` или локальные overrides.

## Команды Harness

Канонический список пользовательских команд и их семантика находится в [`COMMANDS.md`](COMMANDS.md). State transitions — в `.harness/docs/EXECUTION_PROTOCOL.md`.

## PROJECT QUICK FIX

Команда/режим для micro-change, которому не нужна отдельная STEP/REQ/ADR traceability. Не является способом обойти процесс для маленькой фичи или скрытого behavior change.

## Micro-change

Маленькое низкорисковое изменение без изменения product/API/data/security/architecture/dependency contract. Пример: опечатка, пунктуация, безопасный комментарий, локальное formatting.

## Language Policy

Централизованные языковые настройки `.harness/manifest.yaml` → `language`, определяющие язык documentation, commits, comments, test names, fixtures, GitHub templates и release notes. Не меняют identifiers/API keys и не отменяют multilingual domain requirements.

## GitHub Issue Form

Structured YAML template из `.github/ISSUE_TEMPLATE/*.yml`, который GitHub использует для создания типизированного issue с обязательными/необязательными полями. Harness генерирует формы по фактическому tooling проекта через `GITHUB GENERATE TEMPLATES`.

## Pull Request Template

`.github/pull_request_template.md` — форма описания PR. В Harness она может регенерироваться по текущим verification gates и traceability conventions проекта.

## `GITHUB GENERATE TEMPLATES`

Idempotent-команда, которая инспектирует актуальный repository stack/tooling/CI и заменяет managed Issue/PR templates. Не создаёт commit автоматически.

## `AGENTS.local.md`

Локальный, исключённый из Git файл пользовательских alias-команд и предпочтений. `AGENTS.md` требует читать его последним, если он существует. Локальные инструкции расширяют workflow, но не должны скрыто обходить safety/ADR/STEP/security gates.
