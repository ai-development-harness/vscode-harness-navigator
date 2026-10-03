---
schema: 1
id: STEP-018
status: completed
type: implementation
priority: high
phase: project-graph
depends_on: []
requirements:
  - REQ-001
  - REQ-002
  - REQ-004
  - REQ-008
  - REQ-009
  - REQ-011
adrs:
  - ADR-008
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#основные-потоки"
  - docs/architecture.md#external-dependencies-integrations
  - docs/architecture.md#security-boundaries
risk_flags:
  - architecture
  - security-sensitive
plan:
  status: ready
  revision: 1
  context_basis: sha256:c5a79244cb035a6df0b4d5bc7dfd44bc64578062871a6fe9fc7d0a9358e2ef35
  content_hash: sha256:ed480d756c17d1a20532e5c326a0b663017b007be0da16e8db91f491c758c086
  reviewed_report: planning/plan-reviews/STEP-018/PLAN-REVIEW-20261003T094435Z.md
  planned_at: 2026-10-03T09:44:35+00:00
  execution_groups:
  context_components:
    - "ADR@ADR-008=sha256:720fcc4b69d7dce7db6c7a7c639866c05c890511a79ebffb86c469032c16abb1"
    - "ARCH@docs/architecture.md#external-dependencies-integrations=sha256:562fe3e29f0981601f17b3892d884c852f53f3ead266e45d80e5d2636f2a3e35"
    - "ARCH@docs/architecture.md#security-boundaries=sha256:f731111e192e740f7dde5bbf7de269691998d65e6396c912bb583bd2fde2a65a"
    - "ARCH@docs/architecture.md#основные-компоненты-границы=sha256:b20e31de215315620ffca4c01ff54ba3ac128dc2a6457d779d453e1f2020ac76"
    - "ARCH@docs/architecture.md#основные-потоки=sha256:5d196d05578bc8cb4a57bc55f0af9171526042b306bbe8c94784b4ae17a534b9"
    - "REQ@REQ-001=sha256:25349d3cf99301ba1849809c058c48001a0defee27337a4d759a06d1f566591a"
    - "REQ@REQ-002=sha256:368abe871d96bf222e6064bff288e69e0d22a49e5e51a35161e08b05f9c583cc"
    - "REQ@REQ-004=sha256:4a4b42b7e231be207f38e8777ab6aed83a3b45c72fc0ca5c5bf24e1b182db079"
    - "REQ@REQ-008=sha256:4281092e2876a322e9dabbb553b43d63308151000103a1984a258213a2734748"
    - "REQ@REQ-009=sha256:c35b95ab623558706409c5caaf0c392c425d65516fda6c68a434fe6c844d556f"
    - "REQ@REQ-011=sha256:7e7dea655cfca317c560d0894c32948ce51775ed0facbe50e2529e77f717c33d"
    - "STEP@STEP-018=sha256:a5488a3548454b86bcd5fe31641914c9379a2559ad01e26e2d81a80de8314bf1"
---

# STEP-018 — Интерактивный dependency Graph из Project State API

## Goal

Добавить локализованный read-only dependency Graph Harness-проекта на canonical Project State API Harness 0.10.3+ без дублирования его parser, relation normalization и analytics.

## Context

Текущий Navigator поддерживает Harness 0.6.0+ через manifest и собственные Artifact/Reference indexes, а ADR-001/ADR-004 запрещают processes и WebView. Project State API 0.10.3+ предоставляет graph, diagnostics, dependency insights и STEP planning metadata; ADR-008 вводит узкое trusted-workspace исключение, сохраняя запрет на runtime/orchestration.

## Scope

- Поднять minimum Harness version до 0.10.3 и дать localized unsupported state для older releases без legacy graph/fallback.
- Реализовать per-root typed Project State provider: fixed shell-free invocation, schema-v1 tolerant validation, bounded process lifecycle, cache/refresh/invalidation/debounce/cancellation и API diagnostics.
- Добавить isolated VS Code WebView dependency Graph, команды/menu flows, full graph/focus, details/open artifact, filters и `STEP dependencies` mode только из presentation model API.
- Представить API nodes, relations, `declaredBy`, MISSING/degraded/cycles/longest dependency chain и STEP metadata без собственных lifecycle/dependency conclusions.
- Обновить compatibility, read-only, UI, diagnostics, offline, architecture и marketplace documentation contracts; добавить RU/EN unit и Extension Host integration evidence.

## Mutation policy

### Allowed

- `src/projectModel/**`, новый graph service/presentation/WebView surface, narrowly required commands/views/extension wiring, package contributions, l10n resources и test seams.
- Unit/integration fixtures и tests для Project State API, Workspace Trust, process lifecycle, graph UX, refresh и multi-root isolation.
- REQ-001/002/004/008/009/011, ADR-008, architecture, marketplace/developer documentation и generated projections.

### Conditional

- Изменение existing ProjectStateService, ArtifactIndex, watchers или Relations flow допускается только как minimal integration boundary; graph не получает ArtifactIndex parser/fallback и не меняет существующую navigation semantics.
- WebView asset pipeline и CSP допускаются только для isolated presentation implementation с VS Code theme variables и без network/resource access за пределами approved WebView assets.

### Forbidden

- Запуск Harness commands, dispatcher, agents, terminal, arbitrary tools, user shell/text or any write-capable process.
- Изменение Harness artifacts, project-state API, its JSON schema, dependency analytics или lifecycle semantics; legacy support/fallback below 0.10.3.
- WebView filesystem/process/direct Extension Host access, network/telemetry, own critical-path/next-step/blocker conclusions, execution-group graph as merged project dependency graph.

## Out of scope

- Изменение Harness Project State API или поддержка future schema versions beyond tolerant schemaVersion 1 fields.
- Редактирование graph/artifacts, remote collaboration, persistence graph layout, custom color settings и полноценный execution-group DAG UI.

## Acceptance criteria

- Minimum supported Harness version is 0.10.3; lower releases show localized unsupported version and no legacy graph behavior.
- Graph uses only Project State API `project`, `summary`, `graph.nodes`, `graph.edges`, `insights`, `diagnostics` and `sources`; it handles all specified nodes/relations/provenance, MISSING, degraded integrity, cycles and the prescribed Longest dependency chain terminology.
- Trusted Extension Host invocation is fixed, non-shell, bounded, cancellable and per-root; untrusted workspace never executes Python. All API failures have localized diagnostics and never silently fallback.
- Command Palette, Harness View and artifact context action open full/focused graph. Node selection/details, canonical artifact opening, related selection, reset/fit, filters and STEP dependencies mode work with theme-aware rendering.
- WebView remains a presentation-only layer. It never reads/parses workspace data, invokes processes, mutates repository or gains arbitrary Extension Host API.
- Refresh/watch updates avoid concurrent/stale invocation per root, preserve offline operation and isolate multi-root graph/process/snapshot state.
- RU/EN unit and Extension Host integration tests cover all REQ-011 cases, including process failures, schema tolerance, graph semantics, Workspace Trust and live refresh.

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
- manual: В trusted и untrusted Extension Development Host, EN/RU и light/dark/custom theme проверить full/focused graph, MISSING/degraded/cycle/error states, filters, STEP dependencies mode, navigation и per-root refresh.

## Deliverables

- Typed Project State provider and bounded process boundary, graph presentation model and isolated dependency Graph WebView.
- Commands/context contributions, localized diagnostics/messages and multi-root refresh integration.
- Unit/integration fixtures and coverage for API, graph, security boundary, localization and workspace lifecycle.
- Updated canonical REQ/ADR/architecture/marketplace documentation and generated projections.

## Implementation plan

### 1. Совместимость и типизированный контракт Project State API

- Поднять minimum Harness release до 0.10.3 в manifest detection, typed unsupported-version state, fixtures и локализованной diagnostics без legacy compatibility behavior.
- Создать fail-safe parser schemaVersion 1 для Project State payload с tolerant сохранением unknown optional fields и typed presentation model для project, summary, graph, insights, diagnostics и sources.
- Нормализовать только API nodes, edges, declaredBy и supplied STEP metadata; представить MISSING, degraded integrity, BLOCKED и malformed/unsupported response без ArtifactIndex fallback или reciprocal edge synthesis.

**Files:**
- src/projectModel/manifestService.ts
- src/projectModel/projectState.ts
- src/projectGraph/projectStatePayload.ts
- tests/unit/manifestService.test.ts
- tests/unit/projectStatePayload.test.ts
- src/test/fixtures/**

**Tests:**
- Unit matrix minimum release, schemaVersion 1, optional fields, node/edge types, declaredBy, MISSING, degraded, BLOCKED, malformed and unsupported payload.

**Risks:**
- No legacy parsing or compatibility graph below 0.10.3.

### 2. Изолированный per-root Project State API provider

- Реализовать fixed non-shell boundary `.harness/tools/project-state.py --json` with separate executable/argv, canonical cwd, missing Python/tool handling, timeout, stdout/stderr limits, cancellation and child cleanup.
- Add per-root snapshot/cache/request ownership with explicit refresh, debounce, stale-request cancellation and no concurrent invocation.
- Integrate only owning-root invalidation for manifest/API/reviews/skills changes with ProjectStateService diagnostics/events; preserve ArtifactIndex semantics and UI snapshot reads.

**Files:**
- src/projectGraph/projectStateProcess.ts
- src/projectGraph/projectStateService.ts
- src/projectModel/projectStateService.ts
- src/projectModel/projectState.ts
- tests/unit/projectStateProcess.test.ts
- tests/unit/projectStateService.test.ts
- src/test/fixtures/**

**Tests:**
- Unit fixed invocation, failures, timeout, limits, cancellation, disposal, cache and multi-root isolation.

**Risks:**
- Only trusted Workspace may execute the single allowlisted process.

### 3. Dependency Graph WebView, commands и presentation protocol

- Создать presentation-only panel with strict CSP, VS Code theme variables and typed messages, without filesystem, process or arbitrary Extension Host access.
- Implement full/focused opening from command, Harness View and artifact context action; add details, related selection, canonical opening, reset/fit, filters and STEP dependencies mode.
- Render API-provided blocked/MISSING/selected/cycle/diagnostic/Longest dependency chain states and supplied STEP metadata without local lifecycle conclusions.

**Files:**
- src/projectGraph/dependencyGraphPanel.ts
- src/projectGraph/dependencyGraphPresentation.ts
- src/projectGraph/dependencyGraphWebview.ts
- src/commands/showDependencyGraph.ts
- src/views/**
- src/extension.ts
- package.json
- package.nls.json
- package.nls.ru.json
- l10n/**
- tests/unit/dependencyGraphPresentation.test.ts

**Tests:**
- Unit filters, mode, selection/navigation eligibility and localization; Extension Host EN/RU command/context/navigation/error/theme flows.

**Risks:**
- Reject malformed WebView messages; MISSING node never opens a file.

### 4. Workspace Trust, package boundary и integration evidence

- Declare restricted-mode behavior: UI informs, but Python never starts before workspace.isTrusted.
- Wire refresh/watch lifecycle and deactivation cleanup without cross-root subprocess refresh.
- Adapt spies and packaged tests to permit and observe only fixed API invocation while retaining denial of arbitrary child_process, shell, commands, mutations and network; update fixtures/docs/projections.

**Files:**
- package.json
- src/extension.ts
- src/projectGraph/**
- src/test/integration/mvp/boundary.test.ts
- src/test/integration/support/boundarySpies.ts
- src/test/integration/**
- docs/development.md
- docs/marketplace/README.md
- docs/PROJECT.md

**Tests:**
- Trusted/untrusted, multi-root, refresh and deactivation Extension Host tests.
- Packaged process/WebView boundary, VSIX allowlist, no mutation/network/terminal, RU/EN proof.

**Risks:**
- Mock-only process/WebView proof is insufficient; use production bundle and VSIX.

## Evidence





### Исправления графа по ручной проверке 2026-10-03

- Для STEP с API status `in_progress` добавлена отдельная theme-aware рамка. Легенда различает
  работу, blocked, dependency cycle и selection; status исторического REVIEW не обозначает текущий STEP.
- Длинные SVG ID и status сокращаются по фактической метрике шрифта до 170 единиц с многоточием
  и clipPath. Полные ID сохраняются в tooltip, aria-label и details.
- `yarn test:unit`: exit 0, 194 passing, включая production WebView script regression для
  STEP-018 рядом с blocked REVIEW STEP-002, длинного ID/status и refresh статуса.
- `yarn typecheck`, `yarn lint`, `yarn format`, `yarn build`, `git diff --check`: exit 0.
- `XDG_RUNTIME_DIR=/tmp/navigator-runtime XDG_CACHE_HOME=/tmp/navigator-host-cache yarn exec
  vscode-test --label mvp-en --label mvp-ru --grep 'Project State dependency Graph'`: exit 0,
  по 4 passing в production Extension Host на EN и RU.
- Chromium preview production SVG renderer с реальным Project State API snapshot: 104 nodes,
  208 labels, active только STEP-018; за ширину 170 не выходит ни одна подпись. Проверены
  тёмная тема и светлая тема с monospace 16px; полные REVIEW ID доступны в tooltip.
- Эта проверка подтверждает две UI-коррекции; общий manual checklist и independent review
  STEP-018 остаются отдельными completion gates.




### Названия артефактов на узлах графа

- SVG-узел показывает ID, затем API `title` с переносом до трёх строк, затем kind/status.
  Высота узла, вертикальный шаг сетки, центры рёбер и clipPath учитывают название;
  пустой title сохраняет компактный узел. Полное название доступно в tooltip, details
  и `aria-description`.
- Targeted regression: `node --import tsx --test tests/unit/dependencyGraphRuntime.test.ts
  tests/unit/dependencyGraphWebview.test.ts`, exit 0, 6 passing. Проверены title после ID,
  переносы, длинное слово, многоточие, отсутствующий/пустой title и refresh snapshot.
- Chromium preview production renderer на сохранённом API snapshot: 104 узла с title,
  361 текстовая подпись; ни одна не превышает ширину 170 SVG units. Визуально проверены
  REQ-010, REQ-011, ADR-008 и STEP-018 на тёмной теме и светлой теме с monospace;
  переполнений нет. Эта проверка не заменяет общий manual checklist STEP-018.

### Исправления REVIEW-20261003T120646Z

- F-001: перед каждым process, включая WebView refresh и debounce, общий manifest detector
  проверяет текущий owning root. Unsupported/invalid/удалённый root не запускает API;
  восстановленный manifest снова допускает graph. ArtifactIndex не перестраивается этой проверкой.
- F-002: стрелки заканчиваются за рамкой target, учитывая высоту title. Details и edge tooltip
  явно сохраняют `source → target`; reciprocal relations не синтезируются.
- F-003: missingPython использует `ProjectStatePythonUnavailable`; типизированный общий error
  catalog не позволяет указать категорию вне `ProjectDiagnosticCategory`.
- F-004: unit проверяет все error keys EN/RU; production Extension Host/VSIX suite проверяет
  localized panel и Show Diagnostics taxonomy для missingTool, missingPython, timeout,
  oversizedOutput, processError, BLOCKED, unsupportedSchema и malformed. Process failures
  получают реальные fixed Python invocation/отсутствующий executable, а не mock результата.
- Targeted unit command: `node --import tsx --test tests/unit/dependencyGraphRuntime.test.ts
  tests/unit/dependencyGraphWebview.test.ts tests/unit/projectStateService.test.ts`, exit 0,
  13 passing. Проверены также debounce blocker, recovery и оба направления, включая self edges.
- Targeted Host command: `XDG_RUNTIME_DIR=/tmp/navigator-runtime
  XDG_CACHE_HOME=/tmp/navigator-host-cache yarn exec vscode-test --label mvp-en --label mvp-ru
  --grep 'Project State dependency Graph'`, exit 0, по 10 passing EN/RU.
- Chromium на текущем API snapshot: dark/light/custom theme, 105 nodes, 159 edges;
  hiddenArrows=0 и node text overflow=0 на каждой теме. Визуально проверены видимые arrows,
  title, STEP selection/details и сохранение canonical direction.
- Полный ручной checklist ранее подтверждён пользователем 2026-10-03. Неизменённые сценарии
  сохраняют это user evidence; изменённые compatibility, diagnostics и arrow flows дополнительно
  проверены production Host EN/RU и текущим Chromium renderer. Это не новое подтверждение пользователя.

<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-10-03T12:26:52Z
- Status: PASS
- Git head: 69b7d8c33ac6c2b05ac3a77bb408e210349d8636
- Worktree hash: sha256:d2eb7a42e0ff0f7f2e74e55a3b788991b64e47853650fc5d44193c8f38da90e6
- Verification contract basis: sha256:74054810aae79737919af0600788ffb2e20c7d85f329716c100fe38439f0e568
- Subject git head: 69b7d8c33ac6c2b05ac3a77bb408e210349d8636
- Subject worktree hash: sha256:aa798c1676d90d8dad14d059a664395809787526df9561c359793d438f724748

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3971
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5022
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1716
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7928
  - stdout sha256: b15710666f1d049f4efc904c5370cc0c9f4b5d3b068f3b0168627bf290244869
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 23318
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 77710
  - stdout sha256: 61f3c9e5c79a38f39794960a3f3bddce281453d04b181cc77d981eddd026d897
  - stderr sha256: b82a0d3080d85c0015a30693067813e335ae0556ee682d64b98093d8e604d4cb
  - stdout bytes: 45297
  - stderr bytes: 27324
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 615
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4722
  - stdout sha256: 439075189df4af5d89cdbefa9f15e638af1ce58359ab4d30bfead9cebe334f59
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 854
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 364
  - stdout sha256: fb7b5c457880818d6eb7dd60dbd990a39c203292e18ebfbbd76cb5f8f0f4be32
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:packaged
  - Status: PASS
  - Exit code: 0
  - Duration ms: 57319
  - stdout sha256: 9c76308fbaeca69d87a52b44781203687febed2c6f082669f23a6cdf10158c2d
  - stderr sha256: 99fae2d0af49aea5e1cc4102a92580e3e20175b22978b45577bc581c84cb9df6
  - stdout bytes: 29039
  - stderr bytes: 13662
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 16
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1967
  - stdout sha256: 7fcd139752058a6f3b32e3a8f552294b106414abb7ba3a126ecc293dfc64cfde
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 830
  - stderr bytes: 0

### Manual verification
- Check: В trusted и untrusted Extension Development Host, EN/RU и light/dark/custom theme проверить full/focused graph, MISSING/degraded/cycle/error states, filters, STEP dependencies mode, navigation и per-root refresh.
  - Status: PASS
  - Observed: "\"Полный ручной checklist подтверждён пользователем 2026-10-03 до исправлений review. Неизменённые сценарии сохраняют это user evidence. Изменённые compatibility/diagnostics flows повторно проверены настоящим Extension Host EN/RU (по 10 passing); Workspace Trust, full/focus/navigation/refresh также входят в этот production suite. Текущий SVG renderer визуально проверен в Chromium: dark/light/custom theme, 105 nodes и 159 edges, hiddenArrows=0, node text overflow=0; видны title, directed arrows и selected STEP/details. Новое подтверждение пользователя не заявляется; источники проверки разделены в Evidence STEP-018.\""
<!-- VERIFICATION-EVIDENCE:END -->

Generated verification block записывает deterministic runner. Дополнительные semantic observations можно хранить вне generated markers.








## Blocker / Failure reason

—
