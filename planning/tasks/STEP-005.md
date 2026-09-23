---
schema: 1
id: STEP-005
status: completed
type: implementation
priority: high
phase: ide-navigation
depends_on:
  - STEP-003
requirements:
  - REQ-001
  - REQ-005
  - REQ-006
  - REQ-008
adrs:
  - ADR-002
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - docs/architecture.md#data-state-model
  - docs/architecture.md#reliability-observability
risk_flags:
  - performance-critical
plan:
  status: ready
  revision: 1
  context_basis: sha256:f9caac14d774be1e053a4a5665082c6a741fb658fe09337bc763f3978fd2c40d
  content_hash: sha256:fb7abd3b60a0b3d299f543e8a2b00218dbeab0e3f325875c8497bf76eb1a043e
  reviewed_report: planning/plan-reviews/STEP-005/PLAN-REVIEW-20260923T151559Z.md
  planned_at: 2026-09-23T15:15:59+00:00
---

# STEP-005 — Навигация, references и relations Harness ID

## Goal

Реализовать standard VS Code navigation и relations flows для Harness ID на основе общих Artifact и Reference indexes.

## Context

Navigator должен дать ID поведение IDE symbol, но не обходить workspace повторно и не применять semantic behavior за пределами Harness-aware files.

## Scope

- Definition, document link, hover, completion, reference и semantic highlighting providers.
- Relations service, backlinks, Show Relations и Find All References entry points.
- Theme-compatible rendering and diagnostics unknown IDs в области classifier.
- Unit/integration tests navigation, completion, references, relations, hover and highlighting.

## Mutation policy

### Allowed

- Source, tests, command contributions и localized strings navigation/relations providers.

### Conditional

- Минимальные extensions shared index interfaces для required range and metadata lookups.

### Forbidden

- Повторный scan workspace при hover/completion/references, fixed RGB styles и semantic processing outside Harness-aware files.
- Автоматическое изменение Markdown или Harness configuration.

## Out of scope

- Artifact/focus tree UI and command catalog UI.
- Command execution, graph visualisation and WebView details panel.

## Acceptance criteria

- Known Harness ID в Harness-aware file поддерживает definition, peek, Ctrl/Cmd+Click, document links, localized hover и completion, вставляющий только canonical ID.
- Theme-compatible highlighting не ухудшает Markdown syntax highlighting; unknown IDs не приводят к exception.
- Relations и backlinks показывают кликабельные outgoing/incoming artifacts из общих indexes.
- Standard Find All References и UI entry points возвращают shared Reference Index results без erroneous inclusion canonical definition.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`
- manual: Открыть fixture Harness workspace в Extension Development Host в RU и EN локали и визуально проверить, что подсветка ID не ломает Markdown highlighting в светлой и тёмной темах.

## Deliverables

- Navigation/highlighting providers, relations service, reference commands, localized UX and tests.

## Implementation plan

### 1. Shared index: индексированные range/metadata lookups (conditional mutation)

- В ArtifactIndex добавить приватные Map referencesByFile (offset-sorted) и referencesByTargetId; поддерживать их в rebuild() и updatePath() вместе с существующим массивом references, не меняя контракт snapshot().
- Добавить read-only API: referencesInFile(file), referencesTo(id), getByFile(file), definitionRangesOf(id) — диапазоны frontmatter `id:` и H1 в canonical файле artifact (вычисляются при parseArtifact/materialize, а не при запросе).
- Запросы hover/completion/references/relations не вызывают rebuild, markdownFiles и snapshot() (последний копирует весь массив) — только Map lookup.
- Хранить в ArtifactReference (и в definition ranges) не только offset/length, но и готовые line/character start/end (вычисляются в referencesForFile/parseArtifact, пока исходный текст в памяти; учесть CRLF), чтобы Location/Range строились из индекса без openTextDocument и чтения файлов.
- Добавить read-only итератор/список известных ID для completion без копирования и сортировки snapshot() (например artifactIds() поверх существующей Map).

**Files:**
- src/projectModel/artifactIndex.ts
- tests/unit/artifactIndex.test.ts

**Tests:**
- Unit: lookups после rebuild и после updatePath (изменение/удаление файла), definition ranges, отсутствие definition в referencesTo при includeDeclaration=false, стабильность старого snapshot(). Позиции line/character совпадают с offset после rebuild и updatePath, включая CRLF; artifactIds() не копирует snapshot().

**Risks:**
- performance-critical: два индекса должны обновляться атомарно с references, иначе возможен рассинхрон; покрыть тестом на инкрементальный updatePath.

### 2. Pure core: распознавание ID и Harness-aware scope

- Создать vscode-независимый src/navigation/idMatcher.ts: единый regex STEP|REQ|ADR|OQ-\d+, idAtOffset(text, offset), completionPrefixAt(linePrefix) для префиксов STEP-/REQ-/ADR-/OQ-, canonical ID из индекса.
- Создать src/navigation/harnessScope.ts: resolveScope(document) → {folder, index} только для scheme=file, language=markdown, valid root (projectStates.getIndex) и isHarnessAwareMarkdown; иначе undefined — все providers/diagnostics/tokens возвращают пусто вне области (REQ-001, REQ-005).
- Для активного документа матчинг ID выполнять по тексту документа в пределах строки/слова (актуально для несохранённых правок), а cross-file данные брать из индекса.

**Files:**
- src/navigation/idMatcher.ts
- src/navigation/harnessScope.ts
- tests/unit/idMatcher.test.ts

**Tests:**
- Unit idMatcher: границы слова, ID в тексте с пунктуацией, префиксы, неизвестные/некорректные ID (STEP-, STEP-abc, XSTEP-1).

**Risks:**
- Расхождение offset индекса (диск) и dirty-документа: для definition/hover/highlight использовать текст документа, для references индекс — зафиксировать в комментарии и в тестах.

### 3. Definition, document links, hover, completion

- Зарегистрировать DefinitionProvider (Peek и Ctrl/Cmd+Click работают штатно), DocumentLinkProvider (Uri на canonical file) и HoverProvider (локализованные title/kind/status/relations count; неизвестный ID — пустой hover без исключения) для селектора {language: 'markdown', scheme: 'file'}, но с проверкой resolveScope внутри.
- Зарегистрировать CompletionItemProvider (trigger '-') : фильтрация индекса по префиксу, label=ID, detail=kind/status, documentation=title, insertText только canonical ID, range заменяет набранный префикс.
- Обернуть handlers в try/catch с записью в Output Channel 'Harness Navigator' (reliability: исключение providers не должно ронять Extension Host).

**Files:**
- src/navigation/definitionProvider.ts
- src/navigation/documentLinkProvider.ts
- src/navigation/hoverProvider.ts
- src/navigation/completionProvider.ts
- src/navigation/navigationMessages.ts

**Tests:**
- Unit view-model для hover/completion (без vscode) и покрытие l10n ключей navigationMessages в bundle RU/EN.

**Risks:**
- DocumentLinkProvider на больших Markdown: ограничить обработку размером MAXIMUM_MARKDOWN_SIZE_BYTES и не читать диск.

### 4. Find All References и reference provider

- Реализовать ReferenceProvider на referencesTo(id) из общего индекса; при context.includeDeclaration=false исключать definition ranges (frontmatter id + H1 canonical файла), при true — добавлять canonical definition Location.
- Реализовать команду harnessNavigator.findAllReferences (палитра, editor context menu для markdown, view/item/context для artifact nodes STEP-004): берёт ID из курсора либо tree node и показывает результат через штатный editor.action.peekLocations по данным индекса, без открытия/скана файлов.

**Files:**
- src/navigation/referenceProvider.ts
- src/commands/findAllReferences.ts
- package.json

**Tests:**
- Unit: фильтрация definition; Integration: Find All References из редактора и из tree node возвращают те же Location, definition не включена.

**Risks:**
- Стандартный UX VS Code (includeDeclaration): не исключать definition принудительно, когда пользователь явно запросил declaration.

### 5. Relations service, backlinks и Show Relations

- Создать src/navigation/relationsService.ts (без vscode): buildRelations(index, id) → outgoing (requirements/adrs/dependencies/... из Artifact.outgoingRelations), incoming (incomingRelations) и backlinks-упоминания (referencesTo сгруппированные по файлу), все элементы содержат Uri/Range для клика.
- Реализовать команду harnessNavigator.showRelations на нативном QuickPick с separators (Outgoing/Incoming/Mentions), выбор открывает artifact или mention; entry points: палитра, editor context menu, tree item context menu.
- Unknown/dangling relation не бросает исключение: элемент помечается как unresolved без ссылки.
- Добавить в Show Relations QuickPick отдельный пункт «Find All References» (нативный item/button), который вызывает harnessNavigator.findAllReferences для текущего ID — relations flow как точка входа Find All References (REQ-006 Acceptance).

**Files:**
- src/navigation/relationsService.ts
- src/commands/showRelations.ts
- package.json

**Tests:**
- Unit relationsService: outgoing/incoming/backlinks, dangling, multi-root изоляция; Integration: Show Relations items кликабельны и открывают правильный файл. Integration: путь Find All References из Show Relations возвращает те же Location, что редактор и tree node.

**Risks:**
- Backlinks и Find All References обязаны использовать один и тот же referencesTo — покрыть тестом эквивалентности.

### 6. Theme-compatible semantic highlighting и diagnostics unknown IDs

- В package.json объявить contributes.semanticTokenTypes (harnessArtifactId, superType из стандартной иерархии) и semanticTokenScopes с маппингом на стандартный TextMate scope — без фиксированных RGB и без semanticTokenColorCustomizations по умолчанию.
- Реализовать DocumentSemanticTokensProvider: токены только для известных ID в Harness-aware markdown; onDidChangeSemanticTokens по onDidChangeProjectModel.
- Реализовать DiagnosticCollection 'Harness Navigator' для открытых Harness-aware документов: warning на неизвестный ID (локализованное сообщение); очищать при выходе документа из области, закрытии и dispose.

**Files:**
- src/navigation/semanticTokensProvider.ts
- src/navigation/unknownIdDiagnostics.ts
- package.json

**Tests:**
- Unit: токенизация только известных ID, unknown → diagnostic; Integration: DiagnosticCollection в RU/EN, отсутствие diagnostics вне Harness-aware файла.

**Risks:**
- Не ухудшить Markdown highlighting: токены точечные (один ID = один токен), без перекрытия и без захвата всей строки.

### 7. Wiring, локализация и test seams

- В extension.ts зарегистрировать все providers/commands/diagnostics через lifecycle registry; подписать refresh на projectStates.onDidChangeProjectModel; добавить узкие read-only test seams в духе существующих getActive*.
- Добавить строки в package.nls.json/package.nls.ru.json (titles команд) и l10n/bundle.l10n*.json (hover/completion/relations/diagnostics); расширить tests/unit/localization.test.ts покрытием новых message-констант.
- README/docs не менять кроме случая, когда user-facing команды требуют упоминания (решение принять на STEP REVIEW; canonical REQ/ADR не трогать).

**Files:**
- src/extension.ts
- package.json
- package.nls.json
- package.nls.ru.json
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json
- tests/unit/localization.test.ts

**Tests:**
- Unit: ключи l10n покрыты в EN и RU; Integration: activate → deactivate → activate не оставляет регистраций.

**Risks:**
- Регистрация providers на каждый root vs один глобальный: использовать один provider на язык и резолвить root по документу (multi-root).

### 8. Extension Host integration tests и финальная верификация

- Navigation-артефакты и Markdown с известными/неизвестными ID создавать во время выполнения теста через vscode.workspace.fs (по принятому паттерну STEP-003/004 тестов), вызывать harnessNavigator.refresh, а в finally побайтно восстанавливать fixture и не оставлять configured-каталоги. Статические docs/requirements, docs/adr, planning/tasks в fixtures/valid-project НЕ добавлять; multi-root.code-workspace не менять. Негативный кейс «Markdown вне Harness workspace» создавать в ordinary-folder также во время выполнения.
- Написать src/test/integration/navigation.test.ts: definition, document links, hover, completion (вставка только canonical ID), references, relations, unknown-ID diagnostics, отсутствие semantic функциональности вне области; сообщения проверять по vscode.env.language (RU/EN) по существующему паттерну.
- Прогнать typecheck, lint, format, unit и integration; зафиксировать фактические команды/exit code в Evidence при IMPLEMENT.

**Files:**
- src/test/integration/navigation.test.ts

**Tests:**
- yarn test:integration запускает navigation.test.ts в обеих конфигурациях (integration-en и integration-ru из .vscode-test.mjs); локализованные hover/diagnostics/relations проверяются по vscode.env.language по существующему паттерну.

**Risks:**
- Integration-тесты зависят от запуска Electron: если среда недоступна — BLOCKED в Evidence, а не заявление о PASS.

## Evidence









<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-23T16:11:34Z
- Status: PASS
- Git head: 9dd03427541d13c53808ab423b200e76944c8fb4
- Worktree hash: sha256:e971b9db3efc881c85c3ef0aeb9d360bf37c098c5a07b2f7b2c5e0dec0b10c9a

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 2538
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3119
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1047
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 904
  - stdout sha256: e5ef4528e95fddf35da028da29e86981341a098cf31a73c34a43701b127a1aae
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 12833
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 14298
  - stdout sha256: eb2118d08c8382527896e359da165f54689a90a674eec976bbe20523494deb26
  - stderr sha256: 2d976d9396cd3edbb38b095f91f262143820c6ce2749bd65578e85773311d359
  - stdout bytes: 9130
  - stderr bytes: 11990

### Manual verification
- Check: Открыть fixture Harness workspace в Extension Development Host в RU и EN локали и визуально проверить, что подсветка ID не ломает Markdown highlighting в светлой и тёмной темах.
  - Status: PASS
  - Observed: "Подтверждено пользователем без повторного просмотра на этой ревизии: ручная проверка (светлая и тёмная темы, RU и EN) прошла успешно на более ранней ревизии; второй FIX менял только внутреннюю индексацию ArtifactIndex (замена spread на циклы в retainDiagnostics/appendAll) и unit-тесты и на подсветку не влияет. Пользователь явно подтвердил."
<!-- VERIFICATION-EVIDENCE:END -->









## Blocker / Failure reason

—
