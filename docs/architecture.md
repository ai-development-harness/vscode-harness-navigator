# Architecture

## System context

Расширение VS Code локально читает файл `.harness/manifest.yaml`, configured Markdown-artifacts, requirements projections и `.harness/command-transitions.json` в каждом workspace root. Оно отображает derived read-only состояние через VS Code Extension API и не является частью runtime Harness. Любой configured path перед доступом должен быть доказуемо contained в owning workspace root после resolution; путь, traversal или symlink, выходящие за эту границу, являются project-level configuration blocker.

## Основные компоненты / границы

- Detection и Manifest Service определяют Harness-проект, release, configured paths и область Harness-aware Markdown внутри каждого workspace root.
- Artifact Parser формирует типизированные STEP, REQ, ADR и OQ; Artifact Index хранит единственную модель известных артефактов.
- Reference Index хранит упоминания canonical ID в Harness-aware файлах и обслуживает backlinks, navigation, diagnostics и references.
- Command Catalog строится из command graph и отделён от локализованных descriptions.
- Views, providers, commands, highlighting, diagnostics и status bar потребляют индексы, но не парсят документы независимо. Dependency Graph получает отдельную typed presentation model только из Project State API.
- Watcher обновляет только затронутый workspace root и зависимые derived views.

## Data / state model

Состояние только производное и находится в памяти Extension Host. Canonical metadata, статусы REQ и связи читаются из Harness; workspace settings хранят лишь пользовательские параметры сортировки и фильтрации. Расширение не создаёт альтернативную persistent-модель проекта.

## Основные потоки

1. При открытии или изменении workspace root detection читает manifest и создаёт project state либо диагностируемое состояние incompatibility.
2. Валидный project state загружает configured artifacts и projections, строит Artifact Index и Reference Index; для trusted Harness 0.10.3+ Graph provider получает отдельный cached snapshot Project State API.
3. Views и language providers выполняют lookup в общих индексах; command UI использует Command Catalog.
4. FileSystemWatcher инкрементально обновляет соответствующие индексы и уведомляет UI.

## External dependencies / integrations

Нужны официальный VS Code Extension API и YAML parser. Dependency Graph использует изолированный VS Code WebView и один fixed local Project State API entry point; runtime не выполняет shell, Harness commands, произвольные Python tools, сетевые запросы, telemetry, AI API и GitHub integration.

## Security boundaries

Входными данными являются файлы workspace и JSON fixed local API, поэтому parsing должен быть fail-safe. Manifest-configured paths разрешаются относительно owning workspace root и проходят containment check после resolution; абсолютный, traversal или symlink путь за его пределы не читается и диагностируется как configuration blocker. Только в trusted workspace Extension Host может без shell выполнить `.harness/tools/project-state.py --json` с fixed argv, bounded output, timeout и cancellation; это не разрешает другие tools/commands. WebView является presentation-only и не получает filesystem/process access. Копирование canonical command в clipboard — локальное пользовательское действие и не является dispatch в terminal, agent или runtime.

## Reliability / observability

Ошибки отдельного артефакта изолируются и отражаются через diagnostics; manifest/schema/path blockers не допускают построения индекса из предположений. Необработанные исключения не должны завершать Extension Host; технические детали направляются в Output Channel `Harness Navigator`.

## Deployment / runtime assumptions

Расширение распространяется как bundled VS Code extension на поддерживаемом VS Code Node.js runtime. Код TypeScript работает в strict mode; форматирование, lint и тесты становятся частью toolchain в STEP-001.

## Accepted ADR

- [ADR-001](adr/ADR-001-read-only-source-of-truth.md) — read-only граница и Harness как источник истины.
- [ADR-002](adr/ADR-002-shared-project-indexes.md) — единые Artifact и Reference indexes.
- [ADR-003](adr/ADR-003-command-catalog-from-graph.md) — Command Catalog из command graph.
- [ADR-004](adr/ADR-004-native-vscode-ui-and-local-runtime.md) — нативный VS Code UI и локальный offline runtime.
- [ADR-006](adr/ADR-006-step-002-platform-containment-bridge.md) — прямой platform-scoped contract для STEP-002.
- [ADR-008](adr/ADR-008-project-state-graph-integration.md) — узкая интеграция Project State API и dependency Graph.

## Известный architecture debt / drift

На момент инициализации production code отсутствует. Drift будет проверяться отдельными STEP review и `PROJECT RECONCILE`.
