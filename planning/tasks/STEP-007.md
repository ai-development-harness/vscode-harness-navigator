---
schema: 1
id: STEP-007
status: completed
type: implementation
priority: high
phase: integration-quality
depends_on:
  - STEP-004
  - STEP-005
  - STEP-006
requirements:
  - REQ-001
  - REQ-002
  - REQ-003
  - REQ-004
  - REQ-005
  - REQ-006
  - REQ-007
  - REQ-008
  - REQ-009
  - REQ-010
adrs:
  - ADR-001
  - ADR-002
  - ADR-003
  - ADR-004
  - ADR-007
architecture_refs:
  - "docs/architecture.md#основные-потоки"
  - docs/architecture.md#reliability-observability
  - docs/architecture.md#deployment-runtime-assumptions
  - docs/architecture.md#security-boundaries
risk_flags:
  - release-critical
  - security-sensitive
plan:
  status: ready
  revision: 1
  context_basis: sha256:2fd0b5a0911df7d543e70f19fd58a9c760bb684a67b2eb3b20cc60c34d4f7e3a
  content_hash: sha256:a5e3dd4c64d32697d40409f8b1e3d044f2f860d26ce6950ddd890d2adba3ba2b
  reviewed_report: planning/plan-reviews/STEP-007/PLAN-REVIEW-20260923T193904Z.md
  planned_at: 2026-09-23T19:39:04+00:00
---

# STEP-007 — Интеграция MVP и release proof

## Goal

Свести реализованные подсистемы в проверяемый локальный MVP, закрыть cross-cutting integration gaps и подготовить фактические package/release evidence.

## Context

Функции в независимых STEP требуют целостной проверки multi-root lifecycle, watcher refresh, localization, performance boundary and packaged extension behavior.

## Scope

- Интеграционные tests всех обязательных MVP flows, cross-root isolation, `Harness: Refresh` и `Harness: Show Diagnostics`.
- Проверка watch-driven refresh artifact/projection/manifest/command graph, summary/status bar и diagnostics resilience.
- Проверка offline/no-shell/no-mutation boundary на фактическом extension path.
- End-to-end проверка containment configured paths и complete stable diagnostics taxonomy.
- Production bundling/package inspection and documentation of real developer/release commands.

## Mutation policy

### Allowed

- Интеграционный source/wiring, tests, test fixtures, package configuration и development/release documentation, необходимые для MVP proof.

### Conditional

- Узкие corrective changes ownership ранее реализованных components только при подтверждённом integration defect.

### Forbidden

- Новые post-MVP product capabilities, WebView, AI/network integrations или расширение mutation boundary.

## Out of scope

- Новые REQ/architectural contracts и product features после утверждённого MVP.
- Автоматический publication, Git commit, push или release.

## Acceptance criteria

- Integration tests покрывают all required detection states, views, providers, command catalog/copy, diagnostics, watchers, multi-root and RU/EN behavior.
- Реальный packaged extension работает offline, не запускает shell/Harness tools, не требует GitHub auth и не изменяет Harness artifacts.
- Status Bar/summary reflect derived counts, watcher refresh works without Extension Host restart, and `node_modules` is not scanned.
- `Harness: Refresh` восстанавливает current workspace derived state, а `Harness: Show Diagnostics` показывает stable taxonomy для detection, artifacts, projections и command graph; configured path за границей root не читается.
- All real project quality gates, bundling and package inspection pass; final MVP gaps are either fixed in scope or recorded as blocker.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`
- command: `yarn build`
- command: `yarn package`
- command: `yarn inspect:package`
- command: `yarn test:packaged`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Открыть mvp fixture workspace в Extension Development Host в RU и EN локали, светлой и тёмной теме: Status Bar item читаем, использует theme colors, по click открывает Harness View; Summary view отображает release и counts без WebView.

## Deliverables

- Интеграционные tests/fixtures, minimum integration fixes, package evidence and updated development/release documentation.

## Implementation plan

### 1. Изолированный test workspace: integration tests не изменяют tracked fixtures

- Факт: существующие Extension Host tests (extension.test.ts, navigation.test.ts, commandCatalog.test.ts) создают и удаляют planning/, docs/, command graph и меняют manifest прямо в tracked src/test/fixtures/**, а sort/filter пишут ConfigurationTarget.Workspace в tracked src/test/fixtures/multi-root.code-workspace; при падении теста до finally tracked файлы остаются изменёнными. Устранить это до добавления новых tests.
- Создать scripts/prepare-test-workspace.ts (TypeScript, запуск через node --import tsx, только node:fs/node:path): удаляет и заново копирует src/test/fixtures → out/test-workspace/ (out/ уже в .gitignore) с fs.cpSync({ recursive: true, verbatimSymlinks: true }); никогда не пишет за пределы out/test-workspace (проверка resolved target до записи).
- Скрипт дополнительно генерирует в копии то, что нельзя хранить в Git: каталоги node_modules/** MVP-фикстуры (node_modules/ в .gitignore — хранить их в src под нейтральным именем, например _node_modules, и переименовывать при копировании), static symlink-фикстуры шага 2 (configured каталог, .harness/manifest.yaml и файл внутри configured каталога, указывающие за пределы root), manifest с абсолютным configured path, построенным из фактического path.resolve внешнего каталога текущей platform, и (только на POSIX и не под root) каталог .harness без права поиска для UnexpectedInternalError. Если OS отказывает в создании symlink (например EPERM на Windows без Developer Mode) или в chmod, соответствующая фикстура не создаётся, скрипт пишет маркер-файл с причиной, а test явно пропускается с этой причиной; traversal и absolute фикстуры создаются на всех platform без исключений.
- Перевести .vscode-test.mjs на workspaceFolder внутри out/test-workspace/...; обновить package.json → test:integration: yarn build:dev && yarn compile:tests && node --import tsx scripts/prepare-test-workspace.ts && vscode-test с выбором integration-профилей по label (если @vscode/test-cli не поддерживает несколько --label — отдельный --config файл).
- Добавить во все suites guard-assert: каждый vscode.workspace.workspaceFolders[i].uri.fsPath лежит внутри out/test-workspace, а не внутри src/test/fixtures — регрессия конфигурации сразу проваливает suite.

**Files:**
- scripts/prepare-test-workspace.ts
- .vscode-test.mjs
- package.json
- src/test/integration/extension.test.ts
- src/test/integration/navigation.test.ts
- src/test/integration/commandCatalog.test.ts

**Tests:**
- Существующие EN/RU integration suites проходят без изменения поведения против копии в out/test-workspace.
- После yarn test:integration git status не показывает изменений в src/test/fixtures (фиксируется в Evidence).

**Risks:**
- Порядок scripts: yarn build/build:dev выполняют clean (rm -rf dist out), поэтому prepare-test-workspace обязан запускаться после compile:tests и перед vscode-test.
- cpSync с verbatimSymlinks нужен, чтобы относительные symlink-фикстуры не превратились в копии содержимого.

### 2. MVP fixture workspace для cross-cutting сценариев и platform-scoped containment (ADR-007)

- Создать src/test/fixtures/mvp/mvp.code-workspace и отдельные roots, не трогая существующий multi-root.code-workspace (его test проверяет ровно 4 roots): mvp-valid (release 0.6.0+, planning/tasks с STEP in_progress, blocked и planned c depends_on/requirements/adrs; docs/requirements с REQ и generated requirements STATUS.md projection; docs/adr с ADR; docs/open-questions с open OQ; docs/guides/*.md с упоминаниями ID; .harness/command-transitions.json supported schema на базе tests/unit/fixtures/command-transitions.snapshot.json; _node_modules/pkg/README.md и _node_modules/pkg/planning/tasks/STEP-7xx.md с известным и неизвестным ID). Все configured каталоги mvp-valid существуют в fixture до activation, чтобы artifact watchers создавались при activation (F-013).
- mvp-degraded (valid manifest): malformed artifact (ArtifactParseError), duplicate ID (DuplicateArtifactId), ссылка на несуществующий ID в frontmatter (InvalidArtifactReference), malformed STATUS.md (ProjectionReadError), отсутствующий configured каталог (ArtifactDirectoryMissing), command graph с неподдерживаемой schema (CommandGraphUnsupportedSchema); CommandGraphReadError получается runtime-переходом (malformed JSON) в out-копии и восстанавливается.
- Detection roots: mvp-ordinary (NotHarnessProject), mvp-invalid-manifest (InvalidManifest; используется и для hard manifest-watcher assert шага 5), mvp-old-release (release ниже 0.6.0 → UnsupportedHarnessVersion с detected/minimum версиями), mvp-unsupported-schema (UnsupportedSchema), mvp-unreadable (EACCES на .harness) → UnexpectedInternalError там, где среда это допускает.
- Containment roots, выровненные с ADR-007 §1 и docs/architecture.md#security-boundaries (portable защита действует на всех platform): mvp-traversal (sources.* = ../mvp-external/...), mvp-absolute (абсолютный configured path, генерируется prepare-test-workspace), mvp-symlink (configured каталог — static symlink на внешний каталог), mvp-manifest-symlink (.harness/manifest.yaml — static symlink на внешний валидный manifest). Ожидание для всех четырёх — ConfigurationBlocked на КАЖДОЙ platform, без platform-условия в assert; единственный допустимый skip — отказ OS создать symlink на этапе подготовки (маркер шага 1), не platform capability.
- Static symlink внутри valid root: в mvp-valid/planning/tasks генерируется symlink-файл STEP-991.md на внешний STEP; ожидание на всех platform — root остаётся valid, STEP-991 не индексируется (markdownFiles пропускает symlink entries), остальные artifacts читаются.
- Внешние цели лежат в отдельном каталоге mvp-external, который НЕ является workspace root, и содержат уникальные ID (STEP-990, STEP-991 и т.п.), чтобы tests доказывали, что configured path за границей root не прочитан (ID отсутствует во всех indexes, views и diagnostics).
- Non-Linux гарантия ADR-007 §3: mvp-valid (и остальные корректные roots) обязаны достигать kind valid на любой platform; assert valid безусловный — без skip/ветки по process.platform, фактический process.platform прогона фиксируется в Evidence. Ancestor-race (Linux-only защита ADR-007 §2) в integration не воспроизводится — это adversarial race, покрытый unit tests capability injection (manifestService.test.ts, artifactIndex.test.ts).

**Files:**
- src/test/fixtures/mvp/**

**Tests:**
- Фикстуры используются только suites шагов 4-6 через отдельные mvp профили .vscode-test.mjs.

**Risks:**
- Фикстуры должны оставаться Harness 0.6.0+ совместимыми по форме frontmatter/projection, иначе tests проверят parser-ошибки вместо flows; брать форму из существующих unit fixtures artifactIndex.test.ts.
- Уровень containment-проверок — обычные ошибки конфигурации (traversal, absolute, статический symlink), без adversarial race-сценариев (AGENTS.local.md); race-защита уже покрыта unit tests STEP-002/003/008.
- Абсолютный путь различается по platform (POSIX / drive-letter на Windows), поэтому он не хранится в Git, а генерируется из path.resolve на целевой машине.

### 3. Status Bar и Project Summary из общих derived indexes (закрытие MVP gap REQ-009)

- Факт: Status Bar item и summary в коде отсутствуют (нет createStatusBarItem, нет summary в Harness View), хотя REQ-009 и Acceptance STEP-007 их требуют, а ни один из STEP-001..006 их не владел. Реализовать как интеграционную wiring поверх существующих ProjectStateService/ArtifactIndex/CommandCatalogService без нового parsing и без WebView.
- src/views/summaryModel.ts (vscode-независимо): чистая функция из ProjectState[] и ArtifactSnapshot per root → per-root summary (release, количество STEP/REQ/ADR, open OQ, in_progress и blocked STEP через существующий selectFocusArtifacts, число diagnostics) и aggregate counts; статусы и kinds берутся только из snapshot, locale-независимо.
- src/views/statusBar.ts: один StatusBarItem (ThemeIcon, без фиксированных цветов) с локализованным компактным текстом вида «Harness · N active · M blocked · K OQ» и tooltip-сводкой по roots; command открывает Harness View container (workbench.view.extension.harnessNavigator) — это навигация UI, не dispatch Harness-команды; item скрыт, когда ни один root не является Harness-проектом; обновляется на onDidChangeProjectModel и изменения каталога.
- Project Summary в Harness View: отдельный нативный Tree View harnessNavigator.summary (contributes.views + package.nls*.json), read-only items без TreeItem.command: Harness release, STEP/REQ/ADR/OQ open counts, In progress, Blocked; в multi-root — группа на root, non-valid root показывает свою diagnostic category и локализованное объяснение.
- Регистрировать все disposable через lifecycle registry; добавить узкие read-only test seams в src/extension.ts (getStatusBarSnapshot: text/tooltip/command/visible; getSummaryViewSnapshot) в стиле существующих getArtifactsViewSnapshot.
- Добавить новые строки в l10n/bundle.l10n.json и l10n/bundle.l10n.ru.json и package.nls*.json; canonical ID/enums/категории не локализуются.

**Files:**
- src/views/summaryModel.ts
- src/views/statusBar.ts
- src/views/summaryView.ts
- src/views/viewMessages.ts
- src/extension.ts
- package.json
- package.nls.json
- package.nls.ru.json
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json
- tests/unit/summaryModel.test.ts
- tests/unit/localization.test.ts

**Tests:**
- Unit: summaryModel считает counts для пустого проекта, смешанных статусов, нескольких roots и non-valid root; результат не зависит от locale.
- Unit: ключи Status Bar/Summary присутствуют в обоих runtime bundle и в package.nls*.json.
- Integration (шаг 5): counts Status Bar/Summary равны counts из getActiveArtifactSnapshot и меняются после watcher/refresh.

**Risks:**
- Не превращать summary в dashboard/WebView и не добавлять выбор «следующего STEP» (Forbidden STEP-004/REQ-004).
- Добавление четвёртого view не должно менять существующие snapshots Artifacts/Focus/Commands views.

### 4. Multi-root lifecycle: добавление и удаление workspace root без restart (test-first, conditional)

- Факт: ProjectStateService и CommandCatalogService инициализируют roots только в constructor, подписки на vscode.workspace.onDidChangeWorkspaceFolders нет; architecture «Основные потоки» п.1 требует detection «при открытии или изменении workspace root».
- Сначала написать integration test в mvp suite: vscode.workspace.updateWorkspaceFolders добавляет в конец out-копию Harness root → state/index/views/status bar появляются без restart; удаление root убирает его state, watchers, catalog и diagnostics; другие roots не затронуты. Если test подтверждает defect — минимальный corrective change.
- Corrective: ProjectStateService получает addRoot/removeRoot (refreshRoot + manifest watcher; dispose manifest/artifact watchers, state, index) и одну подписку onDidChangeWorkspaceFolders в extension.ts через lifecycle registry; CommandCatalogService при sync освобождает watcher и state удалённого root; firing onDidChangeProjectModel обновляет views/status bar.
- Lifecycle corrective не затрагивает containment readers (manifestService.resolveContainedPath/readBoundedManifest, artifactIndex.readContainedMarkdown/markdownFiles) и parser: новый root проходит тот же detectProject, что и при activation.

**Files:**
- src/projectModel/projectStateService.ts
- src/commandCatalog/commandCatalogService.ts
- src/extension.ts
- src/test/integration/mvp/lifecycle.test.ts

**Tests:**
- Integration EN/RU: add/remove root обновляет derived state без restart; watchers удалённого root больше не меняют state.
- Integration: добавленный в runtime containment root (mvp-symlink) сразу получает ConfigurationBlocked, а не valid.
- Integration: activate → deactivate → повторный activate сохраняет корректный registeredDisposableCount с новыми подписками.

**Risks:**
- updateWorkspaceFolders в multi-root пишет .code-workspace — допустимо только потому, что workspace находится в out/test-workspace (шаг 1).
- Изменение первого folder перезапускает Extension Host — добавлять и удалять только последний root.

### 5. MVP integration suite: все обязательные flows, taxonomy, watchers, refresh, containment, node_modules, RU/EN

- src/test/integration/mvp/mvpFlows.test.ts против mvp.code-workspace, в EN и RU профилях; вынести общие helpers (pollFor, converge с возвратом фактического пути 'watcher' | 'refresh fallback', locale helper, require test seams) в src/test/integration/support/*.ts и переиспользовать без изменения семантики существующих tests.
- Detection states: showDiagnostics возвращает для каждого mvp root ожидаемые kind и category (NotHarnessProject, InvalidManifest, UnsupportedHarnessVersion с detected/minimum, UnsupportedSchema, UnexpectedInternalError там, где среда позволяет, valid) и локализованные строки активной locale; mvp-valid → valid безусловно на любой platform (ADR-007 §3).
- Containment e2e (ADR-007 §1 / docs/architecture.md#security-boundaries): mvp-traversal, mvp-absolute, mvp-symlink, mvp-manifest-symlink → kind configurationBlocked и category ConfigurationBlocked на каждой platform (assert без ветки по process.platform); ни один ID из mvp-external (STEP-990, STEP-991 и т.п.) не появляется в getActiveArtifactSnapshot любого root, Artifacts/Focus/Summary views, Go to Artifact candidates, definition/references, Status Bar counts и diagnostics; symlink-файл STEP-991.md внутри mvp-valid не индексируется, а mvp-valid остаётся valid; остальные roots продолжают работать.
- Complete taxonomy: единая проверка, что через Harness: Show Diagnostics (report.lines и Output Channel flow) наблюдаются все 12 категорий REQ-008 для detection, artifacts, projections и command graph; для недостижимой в конкретной среде категории test помечается skipped с явной причиной, а unit-покрытие этой категории указывается в Evidence.
- Views/providers/catalog smoke на mvp-valid: Artifacts View группы STEP/REQ/ADR/OQ с ID/title/status, Focus View active/blocked/open OQ, Go to Artifact (stub showQuickPick) открывает canonical файл, definition/hover/completion/document links/references/Show Relations для ID из docs/guides, Commands View домены и Copy Command/Find Command → только clipboard; REQ lifecycle берётся из STATUS.md projection.
- Watchers без restart, уровень 1 — hard watcher-only asserts (как manifest-сценарий существующего extension.test.ts): тест НЕ вызывает harnessNavigator.refresh и не содержит fallback-ветки; фиксированное достаточное окно poll (порядка 15 s, шаг 100 ms), таймаут = FAIL. (a) artifact watcher: новый STEP-файл в существующем с activation каталоге mvp-valid/planning/tasks появляется в getActiveArtifactSnapshot, затем изменение status существующего STEP отражается в Focus View и Status Bar counts; (b) manifest watcher: исправление manifest mvp-invalid-manifest переводит root invalidManifest→valid, возврат исходного текста → снова invalidManifest, наблюдаемо через showDiagnostics. Тесты не зависят от порядка файлов mocha: измеряемые каталоги существуют с activation, изменения конфигурации mvp-valid/mvp-invalid-manifest другими suites запрещены (их configured paths неизменны, поэтому refresh переиспользует watchers — F-013), а перед измерением тест дожидается завершения любого предыдущего refresh и сам его не вызывает.
- Watchers без restart, уровень 2 — requirements STATUS.md projection (lifecycle REQ меняется), Harness-aware guide (references обновляются) и command graph (каталог меняется; CommandGraphReadError→восстановление) через converge(): watcher-only окно, затем документированный refresh fallback REQ-009; каждый сценарий логирует фактический путь для Evidence. Aggregate assert в финальном тесте suite: среди сценариев уровня 2 не более одного 'refresh fallback' — fallback компенсирует только изолированный flake; если все (или больше одного) сошлись только через fallback — FAIL. После каждого сценария уровней 1 и 2 Status Bar/Summary counts совпадают со snapshot.
- Refresh: изменить artifact и сразу выполнить harnessNavigator.refresh — snapshot обновлён сразу после завершения команды независимо от watcher; hash всех Harness файлов root до/после refresh и showDiagnostics одинаков.
- Cross-root isolation: одинаковый ID в двух valid roots резолвится в файл своего root; diagnostics mvp-degraded не попадают в mvp-valid; blocked root не блокирует соседние.
- node_modules: ни одно упоминание из node_modules/** не входит в references/backlinks, STEP из node_modules/**/planning/tasks не индексируется, запись нового .md в node_modules во время теста не меняет snapshot и не создаёт diagnostics.

**Files:**
- src/test/integration/mvp/mvpFlows.test.ts
- src/test/integration/mvp/watchers.test.ts
- src/test/integration/support/*.ts
- .vscode-test.mjs

**Tests:**
- mvp-en и mvp-ru профили .vscode-test.mjs (files: out/test/integration/mvp/**/*.test.js, workspaceFolder: out/test-workspace/mvp/mvp.code-workspace); существующие профили переводятся на out/test/integration/*.test.js, чтобы suites не пересекались.
- Hard watcher-only asserts artifact и manifest проходят в dev и packaged профилях EN/RU; Evidence фиксирует фактический путь каждого сценария уровня 2.

**Risks:**
- Watcher delivery в sandbox исторически нестабилен (F-018): hard asserts уровня 1 при провале дают FAIL/BLOCKED среды с зафиксированной причиной, а не PASS через refresh; ослаблять их до fallback запрещено. Снижение flake допускается только легитимными средствами: каталоги существуют до activation, отсутствие refresh перед измерением, достаточное окно.
- Проверки должны наблюдать providers/views/commands через VS Code API и узкие test seams, а не mocks helpers (REQ-010).

### 6. Boundary suite: offline, no-shell, no-auth, no-mutation и in-memory lookups на фактическом extension path

- src/test/integration/support/stackAttribution.ts (vscode-независимый, чистая функция): bundleFile = path.join(extensionPath, 'dist', 'extension.js'); вызов extension-originated тогда и только тогда, когда хотя бы один кадр захваченного stack имеет файл, РАВНЫЙ bundleFile после нормализации (разбор форм 'at fn (file:line:col)' и 'at file:line:col', снятие :line:col, file:// → path, path.normalize, case-insensitive сравнение только на win32). Никакого prefix/startsWith по extensionPath: в dev-профиле extensionPath — корень репозитория и префикс для out/test, .vscode-test/ и node_modules/mocha. На время spies Error.stackTraceLimit поднимается (например до 100) и восстанавливается в teardown.
- src/test/integration/support/boundarySpies.ts: runtime spies (восстанавливаются в teardown) двух видов. Forbidden (spy определяет источник вызова через stackAttribution: вызов, атрибутированный bundle, записывается и завершается sentinel без call-through, чтобы даже при нарушении не исполнялись shell/network; вызов НЕ из bundle — тест, mocha, built-in расширения и сам VS Code — записывается как extension-originated=false и проходит call-through в оригинал без sentinel): node:child_process (spawn, spawnSync, exec, execSync, execFile, execFileSync, fork), node:http/https (request, get), node:net (connect, createConnection), node:tls.connect, node:dns.lookup, globalThis.fetch, vscode.window.createTerminal, vscode.tasks.executeTask, vscode.authentication.getSession, fs write API (writeFile*, appendFile*, rename*, unlink*, rm*, mkdir*, fs.promises.*), vscode.workspace.fs write/delete/rename/createDirectory, vscode.workspace.applyEdit. Observed (record + call-through): node:fs read/open/stat/readdir, vscode.window.showQuickPick. Каждая запись хранит api и результат stackAttribution; нарушение = forbidden-запись с extension-originated=true.
- Controls атрибуции (F-002), выполняются в каждом прогоне boundary suite до основной части и валят suite при несоответствии: (1) negative — вызов forbidden API из test-кода (и, отдельно, классификация инжектированного stack без bundle-кадра) проходит call-through БЕЗ sentinel: запись есть, extension-originated=false, violations = 0; аргументы безвредные и без shell (execFileSync(process.execPath, ['-e','0'])); терминал, созданный control через vscode.window.createTerminal, закрывается сразу, а baseline vscode.window.terminals для основной части снимается ПОСЛЕ control-фазы; (2) positive — во время harnessNavigator.refresh observed spy node:fs.openSync/readFileSync и во время Go to Artifact observed spy vscode.window.showQuickPick получают ≥1 запись с extension-originated=true; (3) violation-path — в control-фазе observed read API (fs.readFileSync/openSync) временно классифицируется как forbidden, refresh выполняется, и recorder обязан зафиксировать ≥1 нарушение из bundle (sentinel получает только bundle-вызов); после этого классификация возвращается и выполняется восстанавливающий harnessNavigator.refresh ДО основной части, чтобы derived state не остался испорченным. Провал positive/violation-path означает, что spies не видят bundle, и boundary suite не может дать PASS.
- Собственные изменения файлов теста (watcher-сценарии шага 5, подготовка/восстановление fixtures) выполняются оригинальными функциями fs/vscode.workspace.fs, сохранёнными в support/originalApis.ts до установки spies; они не проходят через recorder и не считаются нарушением. Built-in расширения того же Extension Host (git, markdown language server) не влияют на результат: их вызовы не атрибутированы bundle и проходят call-through; отключение built-in расширений не требуется, а тест 'нет нарушений' не зависит от их активности.
- Под spies выполнить полный набор flows (refresh всех roots, showDiagnostics, views/summary/status bar snapshots, Go to Artifact, Find Command/Copy Command, definition/hover/completion/references/Show Relations, watcher-изменения) и утверждать ноль нарушений; vscode.window.terminals не увеличивается.
- No-mutation: SHA-256 дерево всех Harness файлов каждого root (manifest, configured каталоги и projections, .harness/command-transitions.json) до и после flows совпадает, кроме файлов, которые меняет сам test; forbidden write spies выше дополняют hash-проверку. Разрешённая запись sort/filter в workspace settings выполняется через WorkspaceConfiguration и не является Harness artifact.
- In-memory lookups: observed fs read spies во время hover/completion/definition/references показывают ноль extension-originated обращений (REQ-009: без повторного scanning).
- Если какое-то свойство vscode namespace или built-in окажется non-writable/getter-only, использовать Object.defineProperty на владельце; если перехват невозможен в принципе — явный skip этого API с причиной, запись в Evidence и покрытие только static bundle scan шага 7 (без ложного PASS).
- Зафиксировать ограничение: activation происходит до установки spies, поэтому для activation-пути доказательство даёт static bundle scan шага 7, а runtime spies покрывают re-detection/re-index через Harness: Refresh.

**Files:**
- src/test/integration/mvp/boundary.test.ts
- src/test/integration/support/stackAttribution.ts
- src/test/integration/support/boundarySpies.ts
- src/test/integration/support/treeHash.ts
- tests/unit/stackAttribution.test.ts
- src/test/integration/support/originalApis.ts

**Tests:**
- Unit stackAttribution: кадр bundleFile в dev-пути (<repo>/dist/extension.js) и packaged-пути (out/packaged/extension/dist/extension.js), включая минифицированный column и Windows drive-letter/регистр → true; кадры <repo>/out/test/**, <repo>/.vscode-test/**, <repo>/node_modules/mocha/**, <extensionPath>/__packaged_tests__/**, dist/extension.js.map, dist/extension.jsx, соседний extension с тем же префиксом пути → false; stack без кадров → false.
- Integration controls negative (call-through без sentinel)/positive/violation-path проходят в dev (mvp-en/ru) и packaged (packaged-en/ru) профилях; их результаты (число записей, профиль) фиксируются в Evidence.
- Boundary suite выполняется и в dev (mvp-en/ru), и в packaged (packaged-en/ru) профилях.
- Integration control (F-002): вызов forbidden API из test-кода и из имитированного не-bundle кадра проходит call-through без sentinel и без нарушения; собственная запись теста через сохранённый оригинал не попадает в recorder.

**Risks:**
- Esbuild CJS вызывает built-ins через property access (import_node_fs.readFileSync), поэтому spies видят вызовы bundle; positive control это проверяет, а не предполагает.
- Если Extension Host применяет source maps к Error.stack в dev-профиле, кадры bundle превратятся в src/*.ts и positive control упадёт; исправление — отключить sourcemap только для test-сборки через существующий флаг esbuild.js, а не ослаблять равенство файла в классификаторе.

### 7. Package tooling: чтение VSIX, inspection, извлечение и .vscodeignore

- scripts/packageArchive.ts: zero-dependency чтение ZIP central directory (EOCD, stored/deflate через node:zlib.inflateRawSync), без исполнения содержимого; отказ на ZIP64/шифровании/entry с абсолютным путём, '..' или backslash (zip-slip).
- scripts/packageInspection.ts: чистая функция правил (entries + extension/package.json + extension/dist/extension.js → violations): точный allowlist entries (extension.vsixmanifest, [Content_Types].xml, extension/package.json, extension/package.nls.json, extension/package.nls.ru.json, extension/l10n/bundle.l10n.json, extension/l10n/bundle.l10n.ru.json, extension/dist/extension.js, extension/readme.md, extension/LICENSE.txt); запрет src/, tests/, out/, node_modules/, .harness/, planning/, docs/, .vscode*, .env*, *.map, *.ts, *.vsix, AGENTS*/CLAUDE*/PROJECT_BRIEF*, ключей и сертификатов.
- Правила bundle: разрешённые require только vscode, node:fs, node:path; запрещены child_process, http, https, http2, net, tls, dgram, dns, worker_threads, cluster, inspector и tokens createTerminal, executeTask, createWebviewPanel, registerWebviewViewProvider, fetch(, XMLHttpRequest, WebSocket, authentication.getSession, applyEdit, telemetry logger, fs write API; нет sourceMappingURL/sourcesContent. Правила manifest: main ./dist/extension.js, l10n ./l10n, нет enabledApiProposals, extensionDependencies/extensionPack, authentication/taskDefinitions/terminal contributions. Secret heuristics по всем текстовым entries (PRIVATE KEY блоки, ghp_/github_pat_/AKIA префиксы). Разумный лимит размера архива.
- scripts/inspect-package.ts: CLI читает <name>-<version>.vsix из package.json, печатает отсортированный список entries с SHA-256 и violations, exit 1 при любом нарушении или отсутствии архива; только чтение, без сети и без записи.
- scripts/prepare-packaged-extension.ts: очищает out/packaged/, извлекает только extension/** из того же VSIX в out/packaged/extension (zip-slip guard) и пишет out/packaged/extracted-entries.json (entry → SHA-256) вне каталога расширения; затем копирует скомпилированное дерево out/test в out/packaged/extension/__packaged_tests__/ (шаг 8, F-003). Каталог __packaged_tests__ — единственное дополнение к содержимому VSIX, bundle на него не ссылается (подтверждает static scan).
- tsconfig.scripts.json и расширение scripts typecheck/lint/format на scripts/**/*.ts; package.json scripts inspect:package; удалить из .vscodeignore строку !dist/extension.js.map, чтобы dev sourcemap с sourcesContent не мог попасть в пакет.
- Не добавлять runtime dependencies; при необходимости devDependency только после явного обоснования (предпочтение — zero-dependency reader).

**Files:**
- scripts/packageArchive.ts
- scripts/packageInspection.ts
- scripts/inspect-package.ts
- scripts/prepare-packaged-extension.ts
- tsconfig.scripts.json
- package.json
- eslint.config.mjs
- .vscodeignore
- tests/unit/packageInspection.test.ts

**Tests:**
- Unit: правила inspection на синтетических входах — лишний src/*.ts, .map, node_modules entry, require('child_process'), fetch(, extensionDependencies, PRIVATE KEY блок → violation; эталонный allowlist → PASS.
- Unit: archive reader отвергает entry с '..' и абсолютным путём (синтетический минимальный ZIP, сформированный в test через node:zlib).

**Risks:**
- Allowlist зависит от поведения vsce (readme.md в нижнем регистре, LICENSE → LICENSE.txt); при изменении версии vsce обновлять allowlist осознанно, а не ослаблять правило.
- Static token scan может дать false positive на строки внутри bundled js-yaml; разрешать только точечными, прокомментированными исключениями.

### 8. Packaged smoke: MVP и boundary suites против извлечённого VSIX с тестами внутри packaged extension

- Факт (F-003): Extension Host выдаёт отдельный экземпляр vscode API на расширение по пути модуля; test-модули вне каталога packaged extension получили бы другой instance, и их патчи vscode.window/tasks/authentication/workspace не были бы видны bundle. Поэтому packaged-профили запускают копию скомпилированных suites из out/packaged/extension/__packaged_tests__/ — модули принадлежат тому же расширению, что и bundle, и получают тот же API instance (в dev-профиле это уже так: out/test лежит под extensionPath = корень репозитория).
- Добавить профили packaged-en и packaged-ru в .vscode-test.mjs: extensionDevelopmentPath = out/packaged/extension, files = out/packaged/extension/__packaged_tests__/integration/mvp/**/*.test.js, workspaceFolder = out/test-workspace/mvp/mvp.code-workspace, launchArgs с --locale и --disable-extensions.
- package.json → test:packaged: yarn compile:tests && node --import tsx scripts/prepare-packaged-extension.ts && node --import tsx scripts/prepare-test-workspace.ts && vscode-test с packaged labels; скрипт использует уже собранный yarn package VSIX, не пересобирает bundle и ничего не публикует.
- В packaged-профиле suites утверждают: extension.extensionPath === resolved out/packaged/extension; __filename каждого suite лежит внутри extension.extensionPath (иначе API instance другой); SHA-256 extensionPath/dist/extension.js равен записи extension/dist/extension.js из out/packaged/extracted-entries.json — доказательство, что проверяется именно production-minified bundle из архива.
- Positive control шага 6 (spy vscode.window.showQuickPick получает вызов из bundleFile во время Go to Artifact) является обязательным доказательством видимости патчей vscode API в packaged-профиле; при его провале packaged boundary suite FAIL. Static bundle scan шага 7 остаётся дополнительным слоем (activation path и API, которые невозможно перехватить), а не заменой runtime-доказательства.

**Files:**
- .vscode-test.mjs
- package.json
- scripts/prepare-packaged-extension.ts
- src/test/integration/mvp/*.test.ts
- src/test/integration/support/*.ts

**Tests:**
- yarn test:packaged: MVP flows + watcher hard asserts + boundary suite (включая controls) PASS в EN и RU на распакованном production VSIX.

**Risks:**
- @vscode/test-electron скачивает VS Code при отсутствии кэша в .vscode-test/ — это сеть test tooling, а не runtime расширения; offline-прогон возможен только с заполненным кэшем, фиксировать в Evidence.
- Production bundle минифицирован: test seams должны оставаться именованными CJS exports (esbuild сохраняет имена exports).
- Compiled suites внутри packaged extension могут require только собственные относительные модули, vscode и node built-ins; зависимость от файлов вне __packaged_tests__ (кроме dist/extension.js через extensionPath) запрещена, иначе копия будет неполной.

### 9. Development/release документация с реальными командами

- Создать docs/development.md: требования (Node >=20, Yarn 4 через packageManager, Python 3.11+ для Harness tools), yarn install --immutable, typecheck/lint/format/format:fix, test:unit, test:integration (headless Linux: xvfb-run -a), build/build:dev, package, inspect:package, test:packaged, запуск Extension Development Host (.vscode/launch.json), назначение out/test-workspace, out/packaged и __packaged_tests__.
- Раздел release: ручной checklist (все quality gates → yarn package → yarn inspect:package → yarn test:packaged → проверка entries), явно: автоматическая публикация, vsce publish, Git tag/push не выполняются этим проектом и остаются out of scope.
- Раздел security/containment: кратко и со ссылкой на ADR-007 — static symlink/traversal/absolute блокируются на всех platform, ancestor-race защита Linux-only, корректный проект valid на macOS/Windows.
- Добавить ссылку на docs/development.md в README.md вне блока PROJECT:START/PROJECT:END; не менять Harness-managed часть README.

**Files:**
- docs/development.md
- README.md

**Tests:**
- Каждая команда в docs/development.md существует в package.json scripts и выполнена в Verification этого STEP.

**Risks:**
- Упакованный readme.md сейчас содержит Harness repository README; product-facing marketplace README — вопрос публикации (out of scope), фиксируется в Evidence как известное ограничение, а не скрытый gap.

### 10. Финальный прогон gates, evidence и учёт оставшихся MVP gaps

- Выполнить Verification в указанном порядке; зафиксировать в Evidence команды, exit codes, process.platform прогона, отсортированный список VSIX entries, размер архива, результаты controls boundary suite по профилям, фактический путь каждого watcher-сценария уровня 2 и skipped-категории/фикстуры с причинами — без реконструкции terminal output.
- Любой найденный integration defect в чужом ownership исправлять только минимально и только если он подтверждён failing test.
- Containment readers (manifestService.resolveContainedPath/readBoundedManifest, artifactIndex.readContainedMarkdown/markdownFiles/walkAnchoredDirectory) не менять, кроме conditional corrective для подтверждённого failing e2e test дефекта, противоречащего ADR-007 (static symlink/traversal/absolute не блокируется либо корректный project не достигает valid на non-Linux); corrective минимален, сопровождается unit regression test и не вводит native addon, Linux-only valid или блокировку non-Linux (ADR-007 §3-4). Если дефект требует изменения threat model — не исправлять здесь, записать blocker.
- Оставшиеся MVP gaps, которые нельзя закрыть в Scope, записать в Blocker / Failure reason, а не расширять contract.

**Files:**
- planning/tasks/STEP-007.md

**Tests:**
- Полный набор Verification ниже.

**Risks:**
- Integration и packaged suites требуют display (xvfb) и выполняются вне sandbox; в sandbox фиксировать BLOCKED среды, а не PASS.
- Integration-прогон на macOS/Windows в этом STEP может быть недоступен; non-Linux гарантия тогда подтверждается unit tests capability injection, что явно фиксируется в Evidence, а не подразумевается.

## Evidence






<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-23T20:53:25Z
- Status: PASS
- Git head: f0c02b7f93b8c18c84e35ff6d95de5a6db62fc8b
- Worktree hash: sha256:5aa6027e00552f8b3e5c2812b8eadfc47eb2806c0ebb9f14ae6154c634189461

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3296
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4184
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1290
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 871
  - stdout sha256: ea9582daf37fbe7289fa17efa9392e6a0cdc5c629f94792b9412952e58f11690
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 17718
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 46059
  - stdout sha256: 94074ed40261d7561d974f2274348ddbcdae242e5c4e9c97fe80b9eef52fbb43
  - stderr sha256: 63727427aa8d9ef35eb8bf170ef3916599894217d509ca8d9e73a94b8ca538c6
  - stdout bytes: 36263
  - stderr bytes: 30256
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 520
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3440
  - stdout sha256: 694b91857dc8547be98d2168d72a504461c4140cf10c58b9ff0bd23ec8dbb9e1
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 799
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 332
  - stdout sha256: 2f5b1c8d60f7603d574a89654d51f71bad5396e7dd2bf16b54bfb309e718944f
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1119
  - stderr bytes: 0
- Command: yarn test:packaged
  - Status: PASS
  - Exit code: 0
  - Duration ms: 31288
  - stdout sha256: 99455603ebf4c17fc75a062868270b6fc7fe3af3509fab51eb2c54891d02eb37
  - stderr sha256: 627151b0bc493ec06f3adc20f98aa72076e56dac62cecff9b49969707d63c3a3
  - stdout bytes: 24684
  - stderr bytes: 15128
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 8
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1054
  - stdout sha256: e406cad96ad51589843c1c5019b7ba698f7c1f7db4aa84ba39d223dc530542d1
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Открыть mvp fixture workspace в Extension Development Host в RU и EN локали, светлой и тёмной теме: Status Bar item читаем, использует theme colors, по click открывает Harness View; Summary view отображает release и counts без WebView.
  - Status: PASS
  - Observed: "Пользователь сообщил в чате, что повторная ручная проверка после второго FIX прошла успешно; детали по локалям/темам не приводились."
<!-- VERIFICATION-EVIDENCE:END -->

Implementer run (не финальный Verification gate; dispatcher выполняет его отдельно). Только command, exit code и observed facts; terminal output не цитируется. Platform прогона: `process.platform` = linux (Node v24.21.0, VS Code 1.139.0 test build из кэша `.vscode-test/`, DISPLAY=:1, xvfb-run отсутствует, display доступен).

- `yarn typecheck`, `yarn lint`, `yarn format`: exit 0.
- `yarn test:unit`: exit 0, 141 pass / 0 fail (новые: summaryModel, stackAttribution, packageInspection, localization Summary view).
- `yarn test:integration`: exit 0; профили integration-en/ru — 16 passing каждый; mvp-en/ru — 23 passing + 1 pending (packagedIdentity, skip в dev-профиле по дизайну). После прогона `git status src/test/fixtures` не показывает изменений tracked fixtures.
- `yarn build`, `yarn package`: exit 0, VSIX 10 files, 48145 bytes, размер `extension/dist/extension.js` 113481 bytes (состояние после второго STEP FIX).
- `yarn inspect:package`: exit 0, `0 violations`; entries (отсортированы): `[Content_Types].xml`, `extension.vsixmanifest`, `extension/LICENSE.txt`, `extension/dist/extension.js`, `extension/l10n/bundle.l10n.json`, `extension/l10n/bundle.l10n.ru.json`, `extension/package.json`, `extension/package.nls.json`, `extension/package.nls.ru.json`, `extension/readme.md`. SHA-256 `extension/dist/extension.js` = aea3eeb9592e4c664962235bd13f60dbee6512744de98b752ac117c2836bd248 (после STEP FIX).
- `yarn test:packaged`: exit 0; packaged-en/ru — 24 passing каждый (включая packaged identity: extensionPath = out/packaged/extension, suites внутри extensionPath, SHA-256 bundle равен записи extracted-entries.json).
- Watcher hard asserts уровня 1 (artifact и manifest, без refresh) — PASS в dev (mvp-en/ru) и packaged (en/ru).
- Watcher уровень 2, фактический путь (во всех прогонах EN/RU, dev и packaged): STATUS.md projection = watcher; guide references = watcher; command graph (readError и recovery) = watcher; refresh fallback не использовался. Известный допуск: aggregate assert уровня 2 допускает не более одного refresh fallback из трёх сценариев (компенсация изолированного flake); уровень 1 остаётся hard watcher-only assert без fallback.
- Boundary controls (dev и packaged, en/ru): negative — forbidden API из test-кода записан с extension-originated=false, sentinel нет, violations=0 (11-13 записей); positive — fs.openSync/readFileSync из bundle = 259 записей, showQuickPick из bundle = 1; violation-path — 9 sentinel-нарушений из bundle, восстановление refresh прошло. Основной прогон под spies: 0 нарушений, terminals не выросли, SHA-256 деревьев всех roots до/после совпали, in-memory lookups (definition/hover/completion/references) без extension-originated fs reads.
- Пропуски и ограничения: `vscode.workspace.fs.{writeFile,delete,rename,createDirectory,copy}` не перехватываются (non-configurable свойства Extension Host: `Cannot redefine property`) — explicit skip этих API, runtime-покрытия нет; они закрыты только статической проверкой bundle (`inspect:package`, best-effort denylist: запрет токенов workspace.fs, деструктуризации из workspace, createDirectory/.copy(, write-флагов openSync/O_*, конкатенации require, process.binding, executeCommand вне allowlist литеральных id, sync/async fs write API, fs promises, applyEdit, openExternal, saveAll, .save(/.edit(, нелитеральный require и т.д., 0 совпадений в актуальном bundle); это статическая проверка текста bundle (best-effort denylist, не runtime-гарантия и не доказательство отсутствия любых обходов); activation-path не под runtime spies (spies ставятся после activation). Fixtures symlink/chmod созданы (skipped-fixtures.json пуст), UnexpectedInternalError достижим (не root) — skip не потребовался. Ancestor-race (Linux-only ADR-007 §2) в integration не воспроизводится; non-Linux гарантия ADR-007 §3 подтверждена unit tests capability injection, integration на macOS/Windows в этом прогоне не выполнялся.
- Lifecycle (шаг 4): тест написан первым и падал (defect подтверждён: root, добавленный через `updateWorkspaceFolders`, не получал state/index); corrective — `ProjectStateService.addRoot/removeRoot` + подписка `onDidChangeWorkspaceFolders` в `src/extension.ts`; после исправления lifecycle-набор проходит (4 теста, включая два root с одинаковым basename). Containment readers (`manifestService`, `artifactIndex`) не изменялись.
- MVP gap REQ-009 закрыт в scope: Status Bar (`src/views/statusBar.ts`) и Project Summary view (`harnessNavigator.summary`) из общих derived indexes; ручная проверка Extension Development Host в RU/EN, светлой/тёмной теме этим прогоном не выполнялась.
- Известное ограничение: `extension/readme.md` в VSIX — README репозитория, а не product-facing marketplace README (вопрос публикации, out of scope).
- `git diff --check`: exit 0. `python3 .harness/tools/validate.py --mode manual`: PASS (warnings о stale plan context_basis у STEP-003/004/008/009 существовали до этого STEP).






## Blocker / Failure reason

—
