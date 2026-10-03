---
schema: 1
id: STEP-017
status: completed
type: implementation
priority: medium
phase: workspace-ui
depends_on:
  - STEP-016
requirements:
  - REQ-004
adrs:
  - ADR-002
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#основные-потоки"
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:cc6411bb33bb36d53c3e7d288d8b3088f5e3988d81a5f0cbbf51b83856c16c9d
  content_hash: sha256:4c3419addafbf198dc1cf759fc4810ef11e0ddad2cf56a41b109ed8eb079a397
  reviewed_report: planning/plan-reviews/STEP-017/PLAN-REVIEW-20261003T083857Z.md
  planned_at: 2026-10-03T08:38:57+00:00
  execution_groups:
  context_components:
    - "ADR@ADR-002=sha256:20bc4d6cafab8c9f54b65959e567068590246b082d765472059dadb017d4d884"
    - "ADR@ADR-004=sha256:c330d03d6528ed06f2a7358105a5c4b0cfd03d7b5fd8115727ed877645466f03"
    - "ARCH@docs/architecture.md#основные-компоненты-границы=sha256:e10cae5eb9d76142083e93c3d7561c43bf086c4a855d9f7692d4079f6d45621c"
    - "ARCH@docs/architecture.md#основные-потоки=sha256:79529be95847ee8a6bd25d4466c4dd3b9497b1e86e14eae9397684d6258774a4"
    - "REQ@REQ-004=sha256:a13237dfa77c727e84fa7b2dde01660ec0dbca31a0d1a3a5b762d133a919a816"
    - "STEP@STEP-016=sha256:2a19a7bc77416e5546beb61ea4ddfe1a260175f39637609e2be3091704f27afd"
    - "STEP@STEP-017=sha256:91aabde926247bb41f5a997ac966f163ab6fac9788d71ae7fbb386f0779b229e"
---

# STEP-017 — Отдельный priority decoration в Harness Artifacts

## Goal

Показывать приоритет leaf-артефакта в Harness Artifacts отдельным нативным VS Code decoration, не заменяя принятую основную семантическую icon matrix.

## Context

STEP-016 сделал основную `TreeItem.iconPath` семантической, но VS Code позволяет показать только одну такую icon. Issue #22 требует выводить priority независимо через `FileDecorationProvider`. Принятая матрица основной icon сохраняется: STEP и ADR показывают status, REQ — priority, OQ остаётся нейтральным; для REQ priority icon и priority badge намеренно сосуществуют. Данные priority уже находятся в общем `ArtifactIndex`, поэтому provider не должен повторно читать или парсить файлы artifacts. Текущий tooltip leaf-артефакта показывает status, поэтому этот STEP добавляет в него локализованный известный priority, требуемый issue.

## Scope

- Зарегистрировать отдельный `FileDecorationProvider` для leaf-артефактов Harness Artifacts и связать decoration с существующим `TreeItem.resourceUri` штатным API VS Code.
- На основе уже индексированного canonical `metadata.priority` отображать `critical` как `!`, `high` как `H`, `medium` как `M`, `low` как `L`; для отсутствующего, неизвестного или некорректного значения decoration не возвращать.
- Использовать theme-aware `ThemeColor` без fixed RGB и локализованные RU/EN tooltip вида «Приоритет: Высокий» / `Priority: High`.
- Обновлять decoration после `ArtifactIndex` refresh и watcher-driven изменения metadata без перезапуска Extension Host; показывать в artifact tooltip локализованные status и известный priority.
- Добавить unit и Extension Host integration tests отображения, отсутствующего priority, локализации и обновления decoration.

## Mutation policy

### Allowed

- `src/views/**`, wiring/disposable registration в `src/extension.ts` и локализационные ресурсы, необходимые только для priority decoration.
- Узкие read-only test seams, unit/integration tests и test fixtures для Artifacts View.
- REQ-004 и двусторонняя traceability ADR-002/ADR-004; generated planning projections.

### Conditional

- Расширение существующего tree-item builder допускается только для установки стабильного `resourceUri` и opt-in строки priority tooltip в Artifacts View; оно не должно менять lifecycle/status presentation, Focus View, parsing, cache или filesystem access.

### Forbidden

- Повторный parsing Markdown или чтение файлов из provider, mutation workspace/Harness artifacts, WebView, fixed RGB, зависимости и изменения `.harness/`.
- Замена status icon, составные SVG `status + priority`, priority action-иконка, редактирование priority из Tree View.

## Out of scope

- Изменение canonical priority в Harness, его значений или сортировки/фильтрации.
- Decoration для групп, root-узлов или Focus View.
- Новая пользовательская настройка цветов или отдельный WebView.

## Acceptance criteria

- Основная `TreeItem.iconPath` сохраняет матрицу STEP-016: STEP и ADR показывают status, REQ — priority, OQ остаётся нейтральным; отдельный badge не заменяет ни одну из этих иконок. Для REQ одновременное отображение priority icon и badge ожидаемо.
- `critical`, `high`, `medium` и `low` отображают соответственно badge `!`, `H`, `M` и `L`; при отсутствующем или некорректном priority badge отсутствует.
- Decoration получает priority только из общего `ArtifactIndex`, привязан к Tree Item штатным механизмом VS Code и обновляется после изменения metadata без перезапуска Extension Host.
- Tooltip decoration локализован для RU и EN; цвета совместимы со светлой, тёмной и custom темами без fixed RGB.
- Tooltip артефакта показывает priority наряду со status и другими metadata; отсутствие или некорректность priority не создаёт некорректную локализованную строку.
- Unit и Extension Host integration tests доказывают матрицу badge, отсутствие decoration, RU/EN tooltip и refresh/watcher update.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: В светлой, тёмной и custom theme проверить, что Artifacts View показывает принятую primary icon и отдельный priority badge, а Focus View не меняется.

## Deliverables

- Нативный priority `FileDecorationProvider`, его lifecycle wiring и RU/EN resources.
- Unit и Extension Host integration coverage matrix, отсутствующего priority и live-обновления.
- Обновлённые REQ-004 и traceability ADR-002/ADR-004.

## Implementation plan

### 1. Изолированная priority presentation в Artifacts View

- Создать pure mapping canonical priority в badge, ThemeColor id и tooltip key с fail-safe undefined для missing, unknown и prototype значений.
- Создать stable synthetic resource URI с identity root и indexed canonical file; передавать его и opt-in priority tooltip только из ArtifactsTreeDataProvider.
- Расширить TreeItem builder opt-in параметрами, не меняя STEP-016 primary icon matrix, Focus View, команды открытия и context actions.

**Files:**
- src/views/artifactPriorityPresentation.ts
- src/views/artifactTreeItem.ts
- src/views/artifactsView.ts
- src/views/viewMessages.ts

**Tests:**
- Unit matrix badge/color/tooltip, unknown fallback и URI identity.

**Risks:**
- REQ сохраняет priority primary icon; вторичный badge намеренно дублирует priority.

### 2. FileDecorationProvider и lifecycle

- Реализовать provider поверх текущего ProjectStateService.getIndex(folder).getByFile без parsing, filesystem access, cache или сохранённой ссылки на index.
- Для synthetic URI вернуть FileDecoration с локализованным tooltip, ThemeColor и propagate выключенным; чужой URI и missing/invalid priority возвращают undefined.
- На onDidChangeProjectModel invalidировать decorations через undefined и зарегистрировать/освободить provider, listener и emitter в LifecycleRegistry.

**Files:**
- src/views/artifactPriorityDecorationProvider.ts
- src/extension.ts

**Tests:**
- Unit provider для foreign URI, valid/invalid priority и invalidation.

**Risks:**
- Глобальный provider не должен декорировать Explorer или Focus View.

### 3. Extension Host proof и handoff

- Расширить read-only seam и isolated fixtures для всех priority, absence/unknown, двух roots с одинаковым ID, refresh replacement, watcher update, удаления priority/artifact/root.
- В реальном EN/RU Extension Host доказать primary icon matrix, synthetic URI, badge/color/tooltip, сохранность Focus, открытия и context actions.
- Выполнить полный Verification contract, вручную проверить light/dark/custom themes и передать revision в independent STEP REVIEW.

**Files:**
- src/extension.ts
- src/test/integration/extension.test.ts
- tests/unit/artifactPriorityPresentation.test.ts
- tests/unit/artifactPriorityDecorationProvider.test.ts
- planning/tasks/STEP-017.md

**Tests:**
- yarn typecheck, lint, format, test:unit, test:integration, git diff --check, Harness validation и manual theme evidence.

**Risks:**
- Unit tests не заменяют real Extension Host и watcher lifecycle evidence.

## Evidence



<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-10-03T09:08:40Z
- Status: PASS
- Git head: 6f74bd31fa439c725820585aeae7bca3a896a90e
- Worktree hash: sha256:e140396105ad7cd709fd022a86dda675c9a7177ce79a3e1be9d0a6ce369fc389
- Verification contract basis: sha256:f108a191952be4c4dc8bc36b9716a599b766395b65c32d601c73a7fb7c3373c8
- Subject git head: 6f74bd31fa439c725820585aeae7bca3a896a90e
- Subject worktree hash: sha256:eb0426ec6d2d926303111b5efda643b09c0e65e2a4f5e25a1acc134e8e69dec7

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3620
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4570
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1466
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7775
  - stdout sha256: c00b5225ae4578240396ed885a09cc1b696805255d50659166d4684155f22d30
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 20440
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 49203
  - stdout sha256: 918df3bc1b3acecb1f55952cd7405168f9630ca0176ffbd0ba67862f20b89871
  - stderr sha256: da8f59ea3ae1233b29da19ae174f8b80db1ac9ce6152f04a9dd5f978abe4682d
  - stdout bytes: 41428
  - stderr bytes: 30173
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 15
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1866
  - stdout sha256: a927a46fd4407e224e50408ced479d98c51a31db20bb12d822b9f323289cb406
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 540
  - stderr bytes: 0

### Manual verification
- Check: В светлой, тёмной и custom theme проверить, что Artifacts View показывает принятую primary icon и отдельный priority badge, а Focus View не меняется.
  - Status: PASS
  - Observed: "Пользователь подтвердил успешное прохождение ручной проверки."
<!-- VERIFICATION-EVIDENCE:END -->

Generated verification block записывает deterministic runner. Дополнительные semantic observations можно хранить вне generated markers.



## Blocker / Failure reason

—
