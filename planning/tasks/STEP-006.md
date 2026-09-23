---
schema: 1
id: STEP-006
status: completed
type: implementation
priority: high
phase: commands-ui
depends_on:
  - STEP-002
requirements:
  - REQ-001
  - REQ-007
  - REQ-008
adrs:
  - ADR-003
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - docs/architecture.md#security-boundaries
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:322bf22b86803d825d8ac37db9f6bf570908382287b65a05bb5c21edb2456ca7
  content_hash: sha256:11d8de8c4b9326448fb13a86ae73d64721949fc688f6e8f07259b15ef8f7c230
  reviewed_report: planning/plan-reviews/STEP-006/PLAN-REVIEW-20260923T163502Z.md
  planned_at: 2026-09-23T16:35:02+00:00
---

# STEP-006 — Каталог и справка Harness-команд

## Goal

Реализовать read-only Command Catalog, Harness Commands View, Find Command и безопасное Copy Command.

## Context

Command graph является machine-readable source of truth, а UI должен оставаться справкой, которая не dispatches commands.

## Scope

- Parser supported command graph schema и typed Command Catalog.
- Producer categories `CommandGraphReadError` и `CommandGraphUnsupportedSchema` для общего diagnostics flow.
- Commands Tree View by domain, descriptions/fallback, tooltips and Find Command Quick Pick.
- Copy canonical command templates to clipboard, включая STEP context substitution.
- Watch command graph and tests supported/unsupported schema, unknown future command and copy behavior.

## Mutation policy

### Allowed

- Source, tests, extension contributions и localized strings command catalog UI.

### Conditional

- Минимальные project-state subscriptions, необходимые для isolated command graph refresh per workspace root.

### Forbidden

- Ручной canonical command list как source of truth, command dispatch to terminal/agent/runtime и parsing commands from Markdown as contract.

## Out of scope

- Artifact parsing, reference navigation и command-chain helper.
- Изменение command graph или Harness project files.

## Acceptance criteria

- Catalog derives canonical syntax, domain, input/target and chain metadata from `.harness/command-transitions.json`.
- Commands View и Find Command показывают known и future commands supported schema, short localized description/fallback и graph-based tooltip.
- Copy Command places correct template or STEP-specific command only in clipboard and never executes it.
- Command graph change refreshes catalog without Extension Host restart; unsupported graph schema isolates its error from Artifact Navigator.
- Command graph read/schema failures имеют stable diagnostics categories и доступны через общий diagnostics flow.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`

## Deliverables

- Command graph service, Command Catalog, commands view/actions, watcher subscription, localized descriptions and tests.

## Implementation plan

### 1. Command graph parser и typed Command Catalog (vscode-независимо)

- Создать src/commandCatalog/commandGraph.ts: константы COMMAND_GRAPH_RELATIVE_PATH = '.harness/command-transitions.json' (единственная точка; в manifest ConfiguredPaths этого пути нет — фиксированный protocol path по REQ-007/ADR-003, а не ручной список команд) и SUPPORTED_SCHEMA_VERSIONS = [1].
- parseCommandGraph(text): fail-safe разбор недоверенного JSON (JSON.parse в try/catch, без eval/exec, проверка типов на каждом уровне); неподдерживаемый или отсутствующий schemaVersion → результат 'unsupportedSchema' без эвристической интерпретации; malformed JSON/неверная форма верхнего уровня → 'readError'.
- Typed CommandCatalog: domains[] в порядке графа, commands[] с canonical, domain, operation (ключ команды в графе), target ('none'|'step'|'release-optional'|будущие значения сохраняются как строка), input ('none'|'required'|'optional'|будущие), chainAllowed, summary, documentation, dispatch.kind, входящие/исходящие transitions (from/to/onPreviousResult/runtimePreconditions) и chainEnabled/inheritTarget/continuationAliases домена — всё выводится из графа, ничего не дублируется вручную.
- Будущие команды поддерживаемой schema отображаются (неизвестные значения target/input/dispatch не отбрасывают команду); отдельная malformed-команда пропускается с записью в catalog.skipped, а не роняет каталог; поле reasoning в UI не используется.
- Чтение файла: переиспользовать существующий readContainedMarkdown(root, file) из artifactIndex.ts без изменения (он не проверяет расширение; даёт containment/symlink/размер ≤ MAXIMUM_MARKDOWN_SIZE_BYTES) — новую containment-логику не писать.
- Unit-тесты используют статический снимок графа tests/unit/fixtures/command-transitions.snapshot.json (копия текущего .harness/command-transitions.json), а не живой файл, чтобы Harness update не ломал жёсткие 7 доменов/32 команды. Отсутствующий файл графа в valid root даёт состояние CommandGraphReadError (локализованное сообщение, Commands View показывает изолированную ошибку); это проверяется в unit и integration тестах.

**Files:**
- src/commandCatalog/commandGraph.ts
- tests/unit/commandGraph.test.ts
- tests/unit/fixtures/command-transitions.snapshot.json

**Tests:**
- Unit: реальная копия графа (fixture из .harness/command-transitions.json) → 7 доменов/32 команды с корректными target/input/chain metadata; schemaVersion 2/отсутствует → unsupportedSchema; невалидный JSON, массив/примитив вместо объекта → readError; будущая команда и неизвестные target/input значения сохраняются; одна malformed команда пропускается; symlink на файл вне root и oversize → readError; порядок доменов сохраняется.

**Risks:**
- Форма графа может измениться в будущем без bump schemaVersion: парсер проверяет только используемые поля и игнорирует лишние, чтобы не ломать supported schema.

### 2. Diagnostics: stable categories и общий diagnostics flow

- В src/projectModel/projectState.ts добавить в ProjectDiagnosticCategory значения 'CommandGraphReadError' и 'CommandGraphUnsupportedSchema' (conditional: минимальное расширение общего типа; значения — технический контракт, не зависят от локали).
- Добавить локализуемые message-константы каталога (commandCatalogMessages.ts по паттерну MESSAGES/VIEW_MESSAGES + массив значений для проверки l10n bundle) и helper diagnostic(category, message, args) с безопасной detail без содержимого файла.
- В ProjectStateService добавить минимальный механизм подключения внешних источников diagnostics (например registerDiagnosticSource(fn: (folder) => ProjectDiagnostic[])), который showDiagnostics() включает в отчёт рядом с diagnostics ArtifactIndex; ошибка graph НЕ меняет ProjectState root и не блокирует ArtifactIndex.

**Files:**
- src/projectModel/projectState.ts
- src/projectModel/projectStateService.ts
- src/commandCatalog/commandCatalogMessages.ts
- tests/unit/commandGraph.test.ts

**Tests:**
- Unit: категории возвращаются стабильными строками для readError/unsupportedSchema; showDiagnostics-источник вызывается только для valid roots (проверяется через Extension Host в шаге 7).

**Risks:**
- Расширение ProjectStateService должно оставаться обратно совместимым: без зарегистрированных источников поведение showDiagnostics не меняется (существующие integration-тесты STEP-002/003).

### 3. CommandCatalogService: per-root загрузка, watcher и refresh

- Создать src/commandCatalog/commandCatalogService.ts: Map<folderUri, CatalogState> ({kind:'ready'|'readError'|'unsupportedSchema', catalog?, diagnostics}), доступ getCatalog(folder), событие onDidChangeCatalog; загрузка выполняется только для root с ProjectState.kind==='valid' (через projectStates.getState(folder)), путь резолвится относительно owning root.
- На каждый valid root — один FileSystemWatcher на '.harness/command-transitions.json' (create/change/delete → перечитывание только этого root, без полного scan workspace и без перезапуска Extension Host); подписка на projectStates.onDidChangeProjectModel создаёт/удаляет watcher при переходе root в valid/invalid, дедуплицируя существующие.
- Ошибки чтения/schema изолируются в CatalogState своего root и пишутся в Output Channel 'Harness Navigator'; исключения не выходят из watcher-обработчиков (try/catch); ArtifactIndex/Artifacts/Focus Views не зависят от состояния каталога.
- Зарегистрировать сервис как diagnostic source ProjectStateService (шаг 2) и как disposable в lifecycle registry (dispose watchers/emitter).
- CommandCatalogService перечитывает граф каждого valid root на каждом onDidChangeProjectModel (событие срабатывает в конце refreshRoot), поэтому Harness: Refresh восстанавливает каталог даже при недоставленном событии watcher; watcher даёт refresh без ручной команды.

**Files:**
- src/commandCatalog/commandCatalogService.ts
- src/projectModel/projectStateService.ts

**Tests:**
- Unit (без vscode): чистая функция loadCatalogForRoot(root) на temp-каталоге — ready/readError/unsupportedSchema/отсутствующий файл; Extension Host: refresh после изменения файла (шаг 7).

**Risks:**
- Гонка refreshRoot и создания watcher: watchers переиспользуются, пока root остаётся valid (паттерн F-013 существующего ProjectStateService).

### 4. Pure view-model: группировка по domain, template и copy-текст

- Создать src/commandCatalog/commandViewModel.ts (без vscode): группировка по domain в порядке графа; label = canonical syntax; описание = локализованное короткое description из presentation-слоя, при отсутствии — summary из графа (fallback для незнакомых команд); tooltip-текст (plain text, не Markdown) из graph metadata: domain, target, input, chain (chainAllowed/следующие команды по transitions), dispatch kind, documentation.
- renderCommandTemplate(command, {stepId?}) — явные правила: (a) canonical берётся из графа как есть; у команд с target 'step' placeholder уже входит в canonical (например 'STEP PLAN STEP-NNN'), поэтому шаблон не дописывает второй; (b) при заданном stepId для target 'step' подставляется заменой литерального токена STEP-NNN в canonical, а если токена нет (будущая команда) — ID дописывается в конец; (c) '<…>' (одна фиксированная нотация placeholder) добавляется только к canonical, оканчивающемуся на ':' (input required/optional); (d) input 'optional' без ':' (например 'GIT COMMIT') и target 'release-optional' ('HARNESS UPDATE CHECK/APPLY') копируются как canonical без изменений и без синтезирования ключевых слов, которых нет в графе; никогда не формируется shell-вызов.
- Локализованные short descriptions — только presentation layer: presentation-only map в коде (по паттерну VIEW_MESSAGES) canonical → английский текст, служащий ключом vscode.l10n.t, с переводами в l10n bundle EN/RU. Fallback на summary графа определяется наличием записи в этой map, а не результатом l10n.t (при отсутствии ключа l10n.t возвращает сам ключ); значения map проходят FORBIDDEN_CANONICAL_PATTERNS из localization.test.ts и не участвуют в построении каталога.

**Files:**
- src/commandCatalog/commandViewModel.ts
- tests/unit/commandViewModel.test.ts
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json

**Tests:**
- Unit: для всех 32 команд снимка графа template совпадает с явно зафиксированной ожидаемой формой (по правилам (a)-(d), одна нотация placeholder '<…>'); подстановка stepId только для target 'step' и без двойного STEP-NNN; неизвестная будущая команда получает fallback description и корректный template; тексты RU/EN покрыты в bundle (по паттерну tests/unit/localization.test.ts).

**Risks:**
- Дрейф ключей описаний относительно графа после Harness update допустим: fallback на summary — это требование ADR-003, а не дефект.

### 5. Harness Commands View

- Создать src/commandCatalog/commandsView.ts: TreeDataProvider (по паттерну ArtifactsTreeDataProvider) с уровнями root (только multi-root) → domain → command; подписка на onDidChangeCatalog; TreeItem с label=canonical, description=short description, tooltip (plain string) из view-model, contextValue 'harnessCommandItem', ThemeIcon; клик по узлу НЕ выполняет команду (без TreeItem.command либо только выделение).
- Пустые/ошибочные состояния через TreeView.message (локализованные): не Harness-проект, каталог недоступен (readError), неподдерживаемая schema — сообщение указывает на диагностику, без утечки содержимого файла.
- В package.json: view 'harnessNavigator.commands' в контейнере harnessNavigator (name через %view.commands.name%), package.nls.json/package.nls.ru.json.

**Files:**
- src/commandCatalog/commandsView.ts
- package.json
- package.nls.json
- package.nls.ru.json

**Tests:**
- Unit view-model для сообщений/состояний; Extension Host: Commands View snapshot по тестовому seam (шаг 7).

**Risks:**
- Дерево не должно вызывать I/O при getChildren: читает только готовый CatalogState из сервиса.

### 6. Find Command и Copy Command

- Команда harnessNavigator.findCommand (палитра): нативный QuickPick по всем valid roots (label=canonical, description=short description, detail=domain·target/input, matchOnDescription/matchOnDetail); выбор копирует template в clipboard и показывает локализованное информационное сообщение; при пустом каталоге — сообщение, а не исключение.
- harnessNavigator.copyCommand: из Commands View (контекстное меню/inline) копирует template узла в vscode.env.clipboard; из узла артефакта Artifacts/Focus View (view/item/context с существующим when `viewItem == harnessArtifactItem`, contextValue не менять — assertion STEP-004 остаётся) для kind STEP показывает QuickPick команд с target 'step' и копирует вариант с подстановкой фактического STEP ID (например 'STEP PLAN STEP-005'); проверка node.artifact.kind === 'STEP' выполняется внутри команды, для не-STEP узла показывается локализованное сообщение без копирования.
- Ни одна команда каталога не выполняется: без vscode.window.createTerminal/Terminal.sendText, tasks, child_process, вызова команд Harness/агентов; единственный побочный эффект — запись строки в clipboard (ADR-003 Security implications).
- Регистрация команд и menus в package.json (commandPalette, view/item/context, view/title при необходимости), заголовки в package.nls*.json, сообщения в l10n bundle.

**Files:**
- src/commandCatalog/findCommand.ts
- src/commandCatalog/copyCommand.ts
- package.json
- package.nls.json
- package.nls.ru.json
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json

**Tests:**
- Unit: выбор и rendering текста для копирования (через view-model); Extension Host: findCommand со stub showQuickPick и чтением vscode.env.clipboard; copyCommand для узла Commands View и для STEP-узла Artifacts View; проверка, что число terminals не изменилось. Integration также покрывает отказ для не-STEP узла (REQ/ADR/OQ).

**Risks:**
- Тесты clipboard в Extension Host зависят от окружения: восстанавливать исходное содержимое clipboard в finally; при недоступности clipboard — BLOCKED в Evidence, а не PASS.

### 7. Wiring, lifecycle, test seams и Extension Host integration tests

- В extension.ts зарегистрировать CommandCatalogService, Commands View, findCommand/copyCommand через lifecycle registry (порядок: сервис до view); добавить узкие read-only test seams в духе getArtifactsViewSnapshot (getCommandsViewSnapshot, getCommandCatalogState); деактивация освобождает watchers и не оставляет регистраций.
- Написать src/test/integration/commandCatalog.test.ts: runtime-fixture по паттерну STEP-003/004/005 — .harness/command-transitions.json записывается через vscode.workspace.fs в valid-project, вызывается harnessNavigator.refresh, в finally файл удаляется/восстанавливается побайтно; статические файлы в fixtures не добавлять, multi-root.code-workspace не менять.
- Сценарии: (1) Commands View показывает домены/команды из графа, включая добавленную в тесте будущую команду и fallback description; (2) Find Command и Copy Command (view node и STEP-узел) кладут в clipboard ожидаемый текст и не создают terminals; (3) изменение файла графа обновляет view без перезагрузки Extension Host: достаточное окно ожидания watcher и затем документированный fallback через harnessNavigator.refresh по образцу extension.test.ts (F-018); в Evidence фиксировать, какой путь сработал; (4) неподдерживаемая schema: Commands View показывает изолированную ошибку, а Artifacts View и ArtifactIndex продолжают работать, showDiagnostics содержит CommandGraphUnsupportedSchema; malformed JSON → CommandGraphReadError; (5) локализованные сообщения и descriptions проверяются по vscode.env.language (integration-en и integration-ru).
- Отдельные test() на сценарий (не один монолитный test), чтобы падение одного не скрывало остальные.

**Files:**
- src/extension.ts
- src/test/integration/commandCatalog.test.ts
- tests/unit/localization.test.ts

**Tests:**
- yarn test:integration запускает commandCatalog.test.ts в обеих конфигурациях (integration-en, integration-ru); unit localization покрывает новые ключи l10n и package.nls.

**Risks:**
- Существующие integration-тесты (ArtifactDirectoryMissing/watcher/views) не должны меняться: новый view и diagnostic source не добавляют артефактных каталогов и не влияют на assertions STEP-002/003/004/005; при регрессии — чинить реализацию, а не ослаблять чужие тесты.

## Evidence


<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-23T16:46:06Z
- Status: PASS
- Git head: a5368182147ebe04d2dedbed40e531fed8cd462c
- Worktree hash: sha256:0be6abb47fbf6efca6516dbe83d8a59c5a7db7fec22dda06602c0d159ef125bf

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 2573
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3373
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1078
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 861
  - stdout sha256: d9142f64dfea6dc1d5f9912542ec1ce18770f0fb510e023d7b03f3f880db6dbd
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 15053
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 16521
  - stdout sha256: 0e17140981a3327ad6cb4987529faeab27cedfa179240f760c06c4b4152cc2ce
  - stderr sha256: 7226da6849c7e0454add33f740b994c0744932deeeae3e66f9d9b348ca31708d
  - stdout bytes: 12068
  - stderr bytes: 16059

### Manual verification
- none
<!-- VERIFICATION-EVIDENCE:END -->


## Blocker / Failure reason

—
