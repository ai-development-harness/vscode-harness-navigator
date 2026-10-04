---
schema: 1
id: STEP-019
status: completed
type: implementation
priority: high
phase: project-graph-ui
depends_on:
  - STEP-018
requirements:
  - REQ-011
  - REQ-012
adrs:
  - ADR-008
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - docs/architecture.md#data-state-model
  - "docs/architecture.md#основные-потоки"
  - docs/architecture.md#security-boundaries
risk_flags:
  - security-sensitive
plan:
  status: ready
  revision: 2
  context_basis: sha256:5f762649cedaacedfd6b48938e465c9a6bbdfaf3f398c7febe2ae1365cb74762
  content_hash: sha256:a45857332ecd078dc578ef404b52e868e08233b86d3cf9f137b1b57441f96d6f
  reviewed_report: planning/plan-reviews/STEP-019/PLAN-REVIEW-20261004T105905Z.md
  planned_at: 2026-10-04T10:59:05+00:00
  execution_groups:
  context_components:
    - "ADR@ADR-008=sha256:720fcc4b69d7dce7db6c7a7c639866c05c890511a79ebffb86c469032c16abb1"
    - "ARCH@docs/architecture.md#data-state-model=sha256:13a099a565169edeea63faa425cd5ea2a49e0e1c1208705ed91c76de89748212"
    - "ARCH@docs/architecture.md#security-boundaries=sha256:f731111e192e740f7dde5bbf7de269691998d65e6396c912bb583bd2fde2a65a"
    - "ARCH@docs/architecture.md#основные-компоненты-границы=sha256:b20e31de215315620ffca4c01ff54ba3ac128dc2a6457d779d453e1f2020ac76"
    - "ARCH@docs/architecture.md#основные-потоки=sha256:5d196d05578bc8cb4a57bc55f0af9171526042b306bbe8c94784b4ae17a534b9"
    - "REQ@REQ-011=sha256:7e7dea655cfca317c560d0894c32948ce51775ed0facbe50e2529e77f717c33d"
    - "REQ@REQ-012=sha256:d97831dd878aefa5f9dac56cce69d2271cea4920cd45430c926a6eb4366f356d"
    - "STEP@STEP-018=sha256:3ec2fd1ea2d1736c15692b2d5cccc1324ec54085090102bb4316be1331dbdb44"
    - "STEP@STEP-019=sha256:87d81fe05037d9cb9ac0c888e7f76bd9f20b09f8488a5b7e6d93bf664b2df620"
---

# STEP-019 — Аналитический обзор и интерактивный Dependency Graph

## Goal

Переработать существующую страницу `Harness: Dependency Graph` в информативный аналитический обзор проекта с интерактивным SVG-графом, читаемыми metrics/diagnostics и структурированным inspector, сохранив Project State API как единственный источник graph facts.

## Context

STEP-018 завершён и поставляет существующую архитектуру `.harness/tools/project-state.py --json → ProjectGraphService → DependencyGraphPresentation → DependencyGraphPanel → isolated VS Code WebView` по REQ-011/ADR-008. Backend и cache/process boundaries уже реализованы; этот STEP развивает presentation, а не повторяет создание provider.

При добавлении задачи 2026-10-04 локальный и удалённый `main` совпадают на `de9ec3b3e77ef06eda7f5e554a58e35be04c93c3`. `src/projectGraph/dependencyGraphWebview.ts` содержит монолитный HTML/CSS/JS template, квадратный grid и raw `<pre>` для details/insights/diagnostics. Текущая presentation сохраняет summary/insights/metadata как records; задача допускает их безопасное типизированное извлечение, но не новые canonical вычисления.

Локальный Project State API Harness 0.10.3 проверен: summary разделяет canonical artifacts, reviews и skills; dependency insights содержит longestChain/cycles; STEP metadata содержит plan freshness и структурированные stale causes. Downstream impact не гарантируется для каждого STEP. Перед STEP PLAN сверить актуальный main и wire-форму API/fixtures без изменения Harness tool/schema.

Визуальный ориентир — согласованный пользователем вариант «аналитический обзор + интерактивный граф». Макет не приложен и не является pixel-perfect контрактом; достаточный обязательный layout и observable behavior описаны ниже. Отсутствие изображения не блокирует планирование.

## Scope

### Данные и границы

- Использовать только текущий API payload и prepared presentation model. WebView не читает workspace, не запускает процессы, не парсит Harness artifacts, не вычисляет lifecycle/project semantics и не получает filesystem/process/direct Extension Host access. ArtifactIndex не является graph source/fallback.
- Сохранить узкий message contract, преимущественно ID-based. Минимальное расширение возможно только для необходимого presentation flow; arbitrary path из WebView запрещён. UI events не запускают API, explicit refresh и существующая watcher/cache lifecycle сохраняются.
- Summary: `artifacts`, `reviews`, `skills`, `relationships`, `byType`, `byStatus`, `blockers`, `missingReferences`, `invalidReviews`, `relationshipCoveragePercent`, `traceabilityCoverage`. Insights: `blockers`, `uncoveredRequirements`, `isolatedArtifacts`, `dependency.longestChain`, `dependency.cycles`, `traceabilityCoverage`. Отсутствующие optional fields не заменяются вымышленными метриками.
- Узлы: PROJECT, REQ, ADR, STEP, OQ, REVIEW, SKILL, MISSING. Relations: только `implemented_by`, `addresses`, `governs`, `depends_on`, `affects`, `reviews`; `declaredBy` сохраняет provenance. SKILL без API edges остаётся отдельным узлом.

### Overview, Views/Filters и поиск

- Компактный верхний Project Overview: workspace folder name, project name, Harness release при наличии, integrity, canonical artifacts, relationships, blockers, missing references, relationship coverage и cycles count. Counts reviews/skills и invalid reviews доступны в читаемых компонентах overview/health; `summary.artifacts` не подменяется общим числом graph nodes.
- Обычные метрики нейтральны. Ненулевые blockers/missing/cycles/invalid reviews и degraded integrity получают warning/error accent; `ok` и нулевые проблемы не выглядят аварийными. Overview не вытесняет graph по высоте.
- Левая панель содержит presets: Full graph — все nodes/relations; STEP dependencies — STEP/`depends_on`; Blockers — IDs из `insights.blockers` и их непосредственные соседи; Dependency cycles — STEP из API cycles и соответствующие `depends_on`; Missing references — MISSING и непосредственные соседи; Uncovered requirements — REQ из API insight; Isolated artifacts — IDs из API insight. Это только presentation filters, без собственного blocker/cycle detection.
- Типы artifacts можно включать/выключать; counts берутся из summary либо текущего полного snapshot там, где summary не считает PROJECT/REVIEW/SKILL/MISSING. Relation filter/legend не показывает отсутствующие в snapshot types. Сохранить status filters.
- Поиск по ID/title работает внутри выбранных preset/type/status/relation filters полностью client-side. Exact ID match допустимо автоматически выбрать; связанный контекст можно приглушать либо скрывать. После очистки возвращается предыдущий graph view, в том числе текущий focus; изменение поиска не сбрасывает filters/preset.

### SVG canvas и размещение

- Сохранить select, double-click/open canonical artifact, zoom/pan/fit, focus, related nodes и keyboard activation.
- Заменить квадратный grid детерминированным layered algorithm. Для Full graph предпочтительны lanes/regions REQ/ADR/STEP/OQ/REVIEW/MISSING; PROJECT — сверху/root context, SKILL — отдельная вспомогательная группа. Стабильное упорядочивание и placement не используют случайные координаты, учитывают длинные titles, сохраняют isolated nodes и отдельную группу MISSING. Алгоритм должен уменьшать пересечения edges, но универсальный layout engine не требуется.
- Тип задаёт базовый accent/icon из VS Code theme variables; status задаётся badge/indicator/border decoration отдельно от типа. Представить имеющиеся `in_progress`, `blocked`, `completed`, `planned`, `open`, PASS/FAIL и missing states без переопределения API semantics.
- Selection, cycle membership, longest-chain membership и MISSING различимы; selection имеет высший визуальный приоритет. Разные relations различаются stroke style/label/marker, направление edge однозначно, цвета не чрезмерно яркие. Tooltip содержит source/target/relation/declaredBy.
- При selection прямые incoming/outgoing edges контрастнее, несвязанные nodes/edges приглушены. Подсветка цепочки использует только `insights.dependency.longestChain` и название `Longest dependency chain` / `Самая длинная цепочка зависимостей`; пустая цепочка скрывает/disables action. Циклы подсвечиваются только из API.

### Inspector

- Header: type/icon, ID, title, status badge, `Open canonical artifact` при canonical path. MISSING явно обозначается как проблема и не имеет open action; Extension Host повторно проверяет ID/path containment.
- STEP: только имеющиеся `completionState`, `latestReviewVerdict`, `latestCompletionResult`, `stepType`, `priority`, `phase`, `riskFlags`, `planStatus`, `planRevision`, `executionGroups`, `planFreshness`, `planStaleCauses`, `planRemediation` и status.
- REQ: priority/source/lifecycle status; ADR: status/date; OQ: status/createdAt/resolvedAt; REVIEW: status/verdict/stepId/createdAt/verificationStatus; SKILL: id/title/status/path; MISSING: expectedType и diagnostic context, если предоставлены. `undefined`/`null` и неприменимые строки не выводятся.
- Для stale/blocked/invalid plan отображать имеющиеся structured stale causes и remediation. Команду можно копировать как текст, без dispatch/terminal execution.
- Прямые canonical relations группировать по incoming/outgoing и type; показывать source/target/relation/declaredBy. Click на related artifact выбирает node.
- Downstream impact — только уже существующий deterministic per-node факт из metadata либо соответствующей записи insights; не вычислять транзитивную достижимость/новый impact. При отсутствии факта строка не выводится.
- Execution groups — компактный read-only summary group ID/steps count/parallel/dependsOn, без второго графа.

### Health, диагностика, адаптивность и организация кода

- Заменить raw JSON `summary`, `insights`, `sources`, `diagnostics` читаемыми компонентами. Health показывает integrity, API relationship/traceability coverage без переинтерпретации и counts blockers/missing/invalid reviews/uncovered requirements/isolated artifacts/cycles. Counts с соответствующим preset могут быть shortcuts.
- Diagnostics — компактный список. `MISSING_REFERENCE` показывает code/source/target/relation, `INVALID_REVIEW` — path/errors; отображаются реально имеющиеся поля wire-формы, без fake chronology/activity. Error/unavailable/empty graph/empty filter states остаются явными и локализованными; degraded snapshot не блокирует graph.
- Сохранить panel на конкретный root, один panel per root, существующий Quick Pick multi-root при открытии через Command Palette. В header достаточно workspace folder/project name, без второго root selector.
- VS Code theme variables вместо fixed light/dark palette; layout пригоден для широкого, среднего и split editor. На узкой ширине inspector можно перенести вниз, левую панель сделать compact/collapsible, canvas сохраняет usable minimum size.
- Все actions доступны с клавиатуры; nodes имеют keyboard selection/Enter activation, aria labels и читаемый focus; состояния не зависят только от цвета. Новые labels/actions/states покрыты RU/EN.
- На десятках и низких сотнях nodes/edges поиск/filters/selection/zoom/preset остаются отзывчивыми. Избегать полного DOM rebuild там, где локальное обновление не создаёт заметной сложности; selection/zoom не должны без необходимости пересоздавать canvas.
- Разделить монолит на тестируемые presentation/layout/rendering/inspector/filter-search/style-template concerns в обычном TypeScript/DOM/SVG и текущем build toolchain. Не добавлять frontend framework. Внешний layout package допускается только с обоснованным преимуществом и проверенным bundle impact в Implementation plan.
- Актуализировать описание UI в документации Navigator: dashboard metrics только из API, presets — client-side views, health score не вычисляется, graph read-only. Архитектурный контракт интеграции сохраняется.

## Mutation policy

### Allowed

- `src/projectGraph/dependencyGraphPresentation.ts`, `src/projectGraph/dependencyGraphWebview.ts` и новые presentation/UI/layout helpers/assets в `src/projectGraph/**`.
- `src/projectGraph/dependencyGraphPanel.ts` в части передачи prepared presentation, labels/root context и минимального ID-based UI message flow.
- `l10n/**`, graph-focused `tests/unit/**`, `src/test/integration/mvp/dependencyGraph.test.ts` и необходимые graph fixtures/test seams.
- `README.md`, `docs/marketplace/README.md`, `docs/README.md` для описания graph UI; owning REQ-011/REQ-012 и этот STEP/evidence; projections только через sync tool.

### Conditional

- `src/projectGraph/projectStatePayload.ts` — только tolerant типизация/извлечение уже существующих schema-v1 полей; новые поля API или semantic вычисления запрещены.
- `src/commands/showDependencyGraph.ts`, `src/extension.ts` и существующие view/command wiring — только доказанная необходимость сохранения navigation/focus/multi-root behavior.
- `esbuild.js`, `tsconfig*.json`, package contributions/localization и scripts/test configuration — только для небольшого WebView asset pipeline либо проверок существующих flows. CSP/resource roots меняются лишь минимально для approved локальных assets, без расширения trust boundary.
- `package.json`/`yarn.lock` для небольшого layout package — только после оценки bundle impact и обоснования в reviewed Implementation plan. Production frontend framework не допускается.

### Forbidden

- Изменение `.harness/**`, Project State API/schema, graph backend/process/cache/watch semantics и ArtifactIndex как graph source.
- Переписывание Accepted ADR decisions, unrelated production changes, выполнение Harness-команд/агентов/shell/terminal из UI и произвольные пути в WebView messages.
- WebView filesystem/process/network access, mutation artifacts, новые semantic analytics/relations и persistent graph layout.

## Out of scope

- Изменение Harness Project State schema, отдельный backend/server, новые relation types (`blocks`, `validates`, `requires skill`, `relates to`) и отсутствующие в API SKILL → STEP edges.
- Health/integrity score, fake missing-reference percentage, synthetic recommendations/AI, custom blockers, Critical Path, альтернативная longest chain, произвольные dependency paths или расчёт semantic downstream impact.
- Git branch/history, activity timeline, timestamps/history activity, artifact history, количество файлов артефакта.
- Редактирование artifacts, automatic command execution, drag-and-drop с сохранением coordinates, persistence layout, полноценный execution-group DAG, React/Vue/Svelte.

## Acceptance criteria

- Основной UI не показывает raw JSON `summary`, `insights`, `sources`, `diagnostics` и metadata.
- Верхний Project Overview отображает только реальные Project State metrics и корректно разделяет canonical artifacts/reviews/skills.
- Отсутствуют вымышленные percentages, health score, activity/history, Git branch и synthetic recommendations.
- Левая панель предоставляет Full graph, STEP dependencies, Blockers, Dependency cycles, Missing references, Uncovered requirements и Isolated artifacts по существующему payload.
- Поиск по ID/title работает client-side совместно с preset/filters; очистка возвращает предыдущий view.
- Artifact type, relation и status filters работают без Project State refresh; counts не хардкодятся, отсутствующие relation types не показаны.
- Grid заменён deterministic layered layout со стабильными координатами, readable длинными titles, isolated nodes и отдельными MISSING.
- Node type, lifecycle/status, selection и cycle/longest-chain highlighting имеют разные presentation dimensions; selection приоритетен.
- Все edges соответствуют canonical schema-v1 types; direction/tooltip содержат source/target/relation/declaredBy.
- Navigator не создаёт synthetic SKILL relations.
- Inspector структурирован, применим к выбранному type и не показывает `undefined`/`null`/raw JSON.
- STEP inspector отображает предоставленные priority/phase/plan/review/completion/freshness metadata.
- Причины stale/blocked/invalid plan и remediation показываются только при наличии в API; команда копируется как текст без исполнения.
- Relations inspector группирует прямые связи по direction/type, сохраняет provenance и позволяет выбрать related node; selection выделяет прямые edges и приглушает несвязанные элементы.
- MISSING показан как проблема без open action; попытка его открыть не открывает файл.
- `insights.dependency.longestChain` можно подсветить; пустая цепочка не предлагает активную подсветку, название соответствует контракту и не использует Critical Path.
- Cycle members отображаются из API без собственного cycle detection.
- Health использует canonical integrity/coverage и реальные counts; optional impact не вычисляется, execution groups имеют только компактный summary.
- Diagnostics читаемы, сохраняют available code/source/target/relation либо path/errors, без fake timeline.
- Zoom/pan/fit/select/double-click/open/focus/related/keyboard activation не регрессируют; open проходит existing containment validation по ID.
- Один panel per root и multi-root Quick Pick/root isolation сохраняются.
- WebView получает только presentation model без filesystem/process/direct workspace API.
- Search/filter/select/zoom/pan/preset не запускают Project State API; explicit refresh обновляет presentation, degraded graph отображается.
- UI использует VS Code theme variables без fixed palette и остаётся читаемым в custom/high contrast themes; состояния различаются не только цветом.
- Layout пригоден для широкого/среднего/split editor, canvas usable на узкой ширине; keyboard focus/actions/aria labels доступны.
- RU/EN localization покрывает все новые labels/actions/states.
- Unit и integration tests покрывают новые observable semantics и существующие navigation/security boundaries.
- Typecheck/lint/format, unit/integration tests и production build/package gates из Verification проходят.
- Документация graph UI актуальна и фиксирует API-derived metrics/client-side presets/отсутствие health score/read-only.
- Существующая архитектура и read-only presentation boundary ADR-008 сохранены, graph backend/API не перепроектированы.

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
- manual: В Extension Development Host либо браузерном preview того же shipped production renderer проверить light/dark/custom/high contrast themes, keyboard/Enter/focus/aria, читаемость titles и направление edges, реальные metrics/diagnostics, ширины 1200/800/480 CSS px и понятные empty/error/degraded/MISSING states. Host integration отдельно подтверждает navigation/root boundaries.
- manual: На representative fixture около 200 nodes/400 edges выполнить search, filters/presets, selection и zoom/pan/fit: интерфейс остаётся отзывчивым, UI operations не увеличивают API invocation count. Зафиксировать фактические наблюдения, включая исполнение shipped minified runtime.

## Deliverables

- Модульный TypeScript/DOM/SVG UI с overview, Views/Filters/Search, layered graph, inspector и health/diagnostics.
- Prepared typed presentation helpers и минимальная panel integration поверх текущего API.
- RU/EN labels и meaningful unit/Extension Host regression tests/fixtures.
- Актуальное описание graph UI и verification/review evidence по этому STEP.

## Implementation plan

### 1. Подготовить полный snapshot и типизированные presentation helpers

- Сохранить все API nodes/edges в DependencyGraphPresentation даже при focus; selectedId/focusId остаются hints. Project Overview и counts используют полный snapshot, focus/presets/filter/search применяются только к отображению. Сохранить доступность существующих panel seams.
- В новых dependencyGraphViewModel.ts/helpers создать self-contained pure factory с типами overview, семи presets, type/status/relation/search filters, direct relations, inspector fields, diagnostics и API chain/cycle facts. Поля брать только из текущей schema-v1 representation с tolerant guards; structured stale causes форматировать читаемо, null/undefined не выводить.
- Counts canonical artifacts брать из summary.artifacts; counts REVIEW/SKILL/MISSING/PROJECT при необходимости из полного graph. Impact извлекать только из existing metadata либо insights.blockers для совпадающего ID, без traversal; execution groups показать компактно. Missing diagnostics связывать по предоставленным IDs.
- Сохранить compatibility функции filterDependencyGraph и existing error/degraded state. Чистые helpers не используют fs/process/vscode или semantic detection.
- Создать graph fixtures из captured актуальной schema-v1 wire формы API: summary counts, blockers entries, structured stale causes, diagnostics code/source/target/relation и review path/errors. Partial старые fixtures не считать доказательством новых данных; missing optional fields также тестируются отдельно.

**Files:**
- src/projectGraph/dependencyGraphPresentation.ts
- src/projectGraph/dependencyGraphViewModel.ts
- tests/unit/dependencyGraphPresentation.test.ts
- tests/unit/dependencyGraphViewModel.test.ts
- tests/unit/fixtures/projectState.ts

**Tests:**
- Overview и реальные summary counts; все presets включая пустые insights
- Сочетание focus/preset/type/status/relation/search; ID/title exact match; очистка поиска
- Direct relations/provenance, STEP/other metadata, stale causes/remediation, impact absent/present, execution groups, diagnostics, MISSING
- Отсутствие новых metrics/relations и no ArtifactIndex fallback

**Risks:**
- Существующий focus скрывает snapshot; regressions предотвращаются тестом полного snapshot + focused view
- Blockers/diagnostics wire формы должны быть проверены по актуальному API и fixtures, не по вымышленным optional fields

### 2. Реализовать стабильное layered-размещение и графические признаки

- Создать self-contained deterministic layout factory в dependencyGraphLayout.ts без внешних package/runtime dependencies. Lanes по типам, стабильное ordering с соседями для уменьшения crossings, PROJECT root context, SKILL auxiliary lane, MISSING separate lane; isolated nodes сохраняются.
- Предусмотреть bounded wrapping/ellipsis длинных ID/title с полным tooltip; одинаковый snapshot даёт одинаковые geometry/bounds независимо от входного порядка там, где порядок не semantic.
- Edges сохраняют API direction/type/provenance, endpoints вне target rect, reciprocal/self edges различимы. Longest chain/cycles берутся только из API; selection, status и type используют разные attributes/classes.

**Files:**
- src/projectGraph/dependencyGraphLayout.ts
- tests/unit/dependencyGraphLayout.test.ts

**Tests:**
- Детерминизм, lanes/isolated/MISSING, empty result, long titles, отсутствие overlapping node rectangles
- Direction/markers, reciprocal/self edges и цепочка только по API

**Risks:**
- Universal optimum crossing minimization не требуется; стабильно bounded graph geometry важнее скрытых semantic вычислений

### 3. Собрать модульный адаптивный WebView и интеграцию panel

- Вынести styles/template, graph runtime/rendering и inspector/filter concerns из dependencyGraphWebview.ts в небольшие TypeScript модули. Использовать DOM/SVG и self-contained runtime factory без framework. При необходимости добавить DOM lib в tsconfig.json/tsconfig.unit.json; это типизация браузерного кода, не runtime dependency.
- Сохранить inline nonce CSP, localResourceRoots: [], безопасное JSON escaping и textContent для payload. В HTML встраивать скомпилированные self-contained factories/runtime без внешних lexical imports; исполнение shipped production/minified script обязательно проверяется.
- Создать компактный overview, левую Views/Filters/Search панель, основной SVG canvas, structured inspector и health/diagnostics. Filters relations только из snapshot, type counts не хардкодить; responsive sidebar/inspector и graph minimum size.
- Сохранить selection/double-click/open/keyboard/zoom/pan/fit/focus/related/reset и root isolation. Full snapshot позволяет локальные presets/focus/search; на model update сохранять view/search/highlight, если нет нового external focus. При исчезновении selected node очистить selection; обновить filters/options после initial loading.
- Selection обновляет классы/inspector без полного canvas rebuild, zoom/pan меняют только viewBox, preset/search/type/relation/status меняют view client-side. Никакие UI operations кроме explicit refresh не вызывают API. Clipboard remediation копирует только exact provided command text, не передаёт command execution message.
- Передать workspace folder name в header; existing ID-based messages/open containment сохраняются. Добавить RU/EN labels для новых actions/sections/states/metadata, aria/focus/Enter и ненулевые problem accents по theme variables.
- Разделить host navigation intent и per-panel client view state: Full graph очищает focus; exact-ID search выделяет match без утраты stored view; clear search возвращает preset/filters/focus; snapshot сохраняет валидные filters/viewport, удаляет исчезнувшие selected/focus IDs; external context reveal нового ID снимает мешающие search/preset/filters и делает node доступным. Отличать новый reveal intent от обычного select echo/model refresh без сброса client UI. При необходимости узко расширить host-to-WebView presentation intent, не permissions.

**Files:**
- src/projectGraph/dependencyGraphWebview.ts
- src/projectGraph/dependencyGraphRuntime.ts
- src/projectGraph/dependencyGraphStyles.ts
- src/projectGraph/dependencyGraphPanel.ts
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json
- tsconfig.json
- tsconfig.unit.json

**Tests:**
- Shipped runtime исполняется, имеет overview/sidebar/inspector/health markers без raw pre/JSON
- Selection/highlight/filter/search/reset/refresh/error/empty state и no API invocations для локальных операций
- Localization/theme/CSP/ID-only message security и production bundle runtime serialization

**Risks:**
- Serialization factories запрещает внешние runtime bindings; production bundle test ловит minifier regressions
- Не расширять process/cache/watch boundaries или arbitrary message permissions

### 4. Доказать observable UI и Extension Host регрессии

- Обновить existing shipped-script DOM adapter tests под новое DOM дерево, проверяя пользовательские операции и реальные handlers вместо привязки к старым dropdown positions. Покрыть все presets, type/status/relation filters, search restore, direct relations selection, long labels, chain/cycle, empty/MISSING/degraded/error и structured inspector/diagnostics.
- Extension Host graph tests EN/RU расширить overview/inspector markers, full snapshot/context focus, open/MISSING/containment, refresh и root isolation. Boundary spies подтверждают отсутствие дополнительных API процессов на select/related/reset и других client-side операциях, сохраняя существующие process tests.
- Проверить renderer в Chromium preview с payload из актуального API и representative fixture около 200 nodes/400 edges; widths 1200/800/480, light/dark/custom/high contrast variables, keyboard/actions/focus, zoom/pan/fit/selection/search/presets. Capture observed responsiveness, отсутствие UI process invocations и shipped minified runtime correctness. Не добавлять постоянный frontend/backend ради preview.

**Files:**
- tests/unit/dependencyGraphRuntime.test.ts
- tests/unit/dependencyGraphWebview.test.ts
- tests/unit/dependencyGraphViewModel.test.ts
- tests/unit/dependencyGraphLayout.test.ts
- tests/unit/fixtures/projectState.ts
- src/test/integration/mvp/dependencyGraph.test.ts

**Tests:**
- yarn test:unit и yarn test:integration
- Production bundle/packaged EN/RU regression
- Manual renderer widths/themes/accessibility и representative scale

**Risks:**
- DOM adapter не заменяет visual/layout browser check; preview не заменяет Host navigation/security integration

### 5. Актуализировать пользовательскую документацию и verification evidence

- Обновить README.md и graph описание docs/marketplace/README.md: overview/inspector/presets/search/health, API-derived metrics, client-side presentation и read-only boundary; не менять accepted architecture decisions. Человекочитаемую новую документацию писать по языковой политике проекта.
- Выполнить canonical Verification через dispatcher; remediation возникающих typecheck/lint/format/test/package failures остаётся в scope. Manual observations передать exact строками согласно Verification. Sync projections до проверки, чтобы validate не мутировал tracked artifacts.
- После всех gates передать реализацию independent review; не ставить completed, не создавать git commit.

**Files:**
- README.md
- docs/marketplace/README.md
- planning/tasks/STEP-019.md

**Tests:**
- Typecheck/lint/format/unit/integration/production build/package/inspect/packaged
- Harness validation/git diff --check и независимый schema-valid review

**Risks:**
- Completion требует fresh independent PASS для фактической revision, а не self-approval

## Evidence









<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-10-04T11:23:53Z
- Status: PASS
- Git head: de9ec3b3e77ef06eda7f5e554a58e35be04c93c3
- Worktree hash: sha256:72fc3ca61272ec10d9bd388480e9e62a63bb1db60551d81bd4a517a35aa532ab
- Verification contract basis: sha256:0f9991796ad91353cadb4a99d869e55be1dee82f926bc44057e895b5499ddc30
- Subject git head: de9ec3b3e77ef06eda7f5e554a58e35be04c93c3
- Subject worktree hash: sha256:24569267a0182fe0cd8eef84ad64dc295b823f0c3eea85b9477d4136a1af34ec

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4422
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5420
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1715
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7924
  - stdout sha256: dd328b22b4b866a085b14ecd1c5a617fddbff1a6fe30ba99b43a95d8b860b8bb
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 24625
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 76429
  - stdout sha256: d91afc9a7b0819a27c958def4263295460633472a94a54a3be333e33474f0e6a
  - stderr sha256: 94b521ed46ea03268445abc85e6f29fd4982f064c5f85ec9a4cfee305da55996
  - stdout bytes: 45829
  - stderr bytes: 28250
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 564
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4570
  - stdout sha256: b98d6d5df6659694c799be711f10d24db49eff4e27408be02345eb8d0dec17c0
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 857
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 364
  - stdout sha256: b9473f86e7cf193cbc40ee9c0bd4810e28c84dd0dc573b06fa0da65330487faa
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:packaged
  - Status: PASS
  - Exit code: 0
  - Duration ms: 56615
  - stdout sha256: 9b10c300fc45e02ffda4f38193eeb7349517ca7c4a8f8a1fac687034bb338ec4
  - stderr sha256: 310e8bba277202a2075f6d33809c71c675d173a8850fd557bd9cf04735d0d33b
  - stdout bytes: 28764
  - stderr bytes: 15393
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 2016
  - stdout sha256: 73b056baa44810dc6db011686ffda6d7743faefe33a6b40e8e567baa47538dd4
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 830
  - stderr bytes: 0

### Manual verification
- Check: В Extension Development Host либо браузерном preview того же shipped production renderer проверить light/dark/custom/high contrast themes, keyboard/Enter/focus/aria, читаемость titles и направление edges, реальные metrics/diagnostics, ширины 1200/800/480 CSS px и понятные empty/error/degraded/MISSING states. Host integration отдельно подтверждает navigation/root boundaries.
  - Status: PASS
  - Observed: "PASS: браузерный preview production renderer, собранного esbuild --minify, и фактический HTML Extension Host. Проверены light/dark/custom/high contrast при 1200/800/480 CSS px: горизонтального overflow нет, theme accents/focus читаемы, inspector переносится вниз на узких ширинах. Keyboard Enter выбирает STEP/REVIEW/MISSING; checkbox сохраняет focus после redraw; ArrowRight перемещает viewport, Home выполняет Fit. Title полностью доступен в SVG title/aria и inspector, text clipping не выходит за rect. Edge marker-end, source/target/type/declaredBy соответствуют API. Captured настоящего schema-v1 API: 39 canonical artifacts при 84 graph nodes, 1 blocker, 1 missing reference, 1 invalid review; diagnostics показывают source/target/relation либо path/errors. Degraded остаётся интерактивным, MISSING не имеет Open, no-match показывает empty state, malformed snapshot показывает localized error без nodes и без нулевых выдуманных metrics. Actual Host подтверждает безопасную ID navigation, Workspace Trust и root isolation; UI select/related/reset не увеличивают child_process.spawn count. Наблюдения: /tmp/navigator-step019-browser-themes.txt, /tmp/navigator-step019-keyboard-pan.txt, /tmp/navigator-step019-browser-host-ru.txt; скриншоты /tmp/navigator-step019-step-inspector.png и /tmp/navigator-step019-host-ru-*.png. RU проверен с установленным в изолированный .vscode-test/extensions русским language pack: реальный HTML Host содержит Граф зависимостей, Полный граф и русскую keyboard-подсказку; дополнительный mvp-ru PASS exit 0 (33 passing, 1 existing pending). Runtime/cache тестов перенесены в /tmp из-за read-only /run/user/1000. Дополнительный production VSIX packaged-ru graph suite PASS: 10 passing, exit 0; /tmp/navigator-step019-real-ru-packaged.log. Обнаружен существующий дефект вне STEP-019: integration-ru Command Catalog / openCommandDocumentation проверяет declared.title.startsWith и падает, когда VS Code с language pack возвращает localized title object. Исходная среда default full suite (English fallback без language pack) восстановлена; actual RU graph suite проверен отдельно на language pack и PASS. Дефект unrelated test не исправлялся и не скрывается; диагностический лог /tmp/navigator-step019-integration-ru-diagnostic.log. STEP FIX F-001: src/projectGraph/dependencyGraphRuntime.ts сопоставляет соседние IDs только provided API longestChain с existing depends_on независимо от порядка, сохраняя source/target/marker. tests/unit/dependencyGraphRuntime.test.ts проверяет exact canonical endpoints девяти highlighted edges и toggle-off; отдельный запуск runtime tests exit 0, 9 passing. Свежий minified renderer в Chromium на captured API после chain toggle: 10 highlighted nodes, 9 highlighted canonical depends_on edges, marker-end url(#arrow), messages [], после выключения 0 chain classes; literal output /tmp/navigator-step019-fixed-chain-browser.txt."
- Check: На representative fixture около 200 nodes/400 edges выполнить search, filters/presets, selection и zoom/pan/fit: интерфейс остаётся отзывчивым, UI operations не увеличивают API invocation count. Зафиксировать фактические наблюдения, включая исполнение shipped minified runtime.
  - Status: PASS
  - Observed: "PASS: minified production renderer исполняется в Chromium на captured API fixture 201 nodes (200 STEP плюс PROJECT), 400 depends_on edges. Реально выполнены search/clear, STEP/cycles/full presets, type/relation filters, selection, zoom/wheel, pointer pan и Fit, затем keyboard pan/Home. После bounded binary-search truncation full/preset redraw измерен 115.9–137.8 ms; exact-ID search 5 ms и selection 2.3 ms в предыдущем замере; zoom/fit около 5 ms. Selection сохраняет существующие SVG node objects (sameNode=true), pan/zoom изменяют только viewBox. Локальные operations создали 0 refresh messages; настоящий Host integration независимо подтвердил неизменный API spawn count для select/related/reset. Полные результаты браузера /tmp/navigator-step019-browser-scale.txt и /tmp/navigator-step019-keyboard-pan.txt; snapshot fixture получен исходным project-state API, новые blockers/cycles/impact не вычислялись WebView. Unit test исполняет извлечённый inline script как dev, так и minified esbuild HTML, без дублирования алгоритма в adapter. Свежий FIX renderer повторно проверен на 201/400: search, STEP/full presets, keyboard selection, zoom, ArrowRight/Home работают, refreshCount=0. На этом циклическом API snapshot longestChain отсутствует, поэтому chain button корректно disabled; chain подсветка отдельно реально исполнена на captured fixture 10 nodes/9 edges. Literal output /tmp/navigator-step019-fix-scale.txt; fresh theme/width matrix /tmp/navigator-step019-fix-themes.txt."
<!-- VERIFICATION-EVIDENCE:END -->

- STEP ADD 2026-10-04: semantic overlap проверен по canonical STEP/REQ. STEP-018 реализует backend и базовый graph; STEP-019 добавляет аналитический UI по новому REQ-012, сохраняя REQ-011. Максимальный текущий и исторический STEP ID — 018.
- Read-only baseline: `git ls-remote origin refs/heads/main`, exit 0; удалённый main совпадает с локальным HEAD `de9ec3b3e77ef06eda7f5e554a58e35be04c93c3`, исходное рабочее дерево чистое.
- `python3 .harness/tools/project-state.py --json`, exit 0: snapshot PASS, integrity ok; наблюдались summary/insights и STEP metadata, описанные в Context. Это проверка доступности текущих facts, а не verification будущего UI.
- Requirements Quality Gate: `python3 .harness/tools/requirements-quality.py --payload-file /tmp/navigator-step-019-requirements-quality.json`, exit 0, status PASS; completeness/clarity/measurability/scenarioCoverage — pass, findings отсутствуют. Семантически проверены источник/ownership данных, optional поля, error/empty/degraded/MISSING states, client-side operations, navigation и измеримые проверки UI; blocking ambiguity не обнаружена.
- `python3 .harness/tools/sync-projections.py`, exit 0: обновлены requirements SPEC/STATUS и planning PLAN/STATUS. `python3 .harness/tools/validate.py --mode manual`, exit 0: HARNESS VALIDATION PASS; warnings о stale plan context_basis существующих завершённых STEP. `git diff --check`, exit 0. Production gates перечислены для будущей реализации и при STEP ADD не запускались.









## Blocker / Failure reason

—
