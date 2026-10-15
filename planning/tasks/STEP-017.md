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
  revision: 2
  context_basis: sha256:0479c2b83f073fff9f08617d936b6af28f0ccefe5e07ddd923df4caa79dcfe32
  content_hash: sha256:62a749b7ae864e0499d4c359d2753e42e4db83e3b329122c1640ec00fd7b53c7
  reviewed_report: planning/plan-reviews/STEP-017/PLAN-REVIEW-20261015T210814Z.md
  planned_at: 2026-10-15T21:08:14+00:00
  execution_groups:
  context_components:
    - "ADR@ADR-002=sha256:20bc4d6cafab8c9f54b65959e567068590246b082d765472059dadb017d4d884"
    - "ADR@ADR-004=sha256:c330d03d6528ed06f2a7358105a5c4b0cfd03d7b5fd8115727ed877645466f03"
    - "ARCH@docs/architecture.md#основные-компоненты-границы=sha256:b20e31de215315620ffca4c01ff54ba3ac128dc2a6457d779d453e1f2020ac76"
    - "ARCH@docs/architecture.md#основные-потоки=sha256:5d196d05578bc8cb4a57bc55f0af9171526042b306bbe8c94784b4ae17a534b9"
    - "REQ@REQ-004=sha256:4a4b42b7e231be207f38e8777ab6aed83a3b45c72fc0ca5c5bf24e1b182db079"
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

### 1. Повторно подтвердить существующую priority presentation

- Сопоставить реализацию с priority-пунктом актуального REQ-004: сохранить primary icon matrix STEP-016 и отдельные badge !, H, M, L для canonical priority.
- Подтвердить fallback для отсутствующего и некорректного priority, ThemeColor и RU/EN tooltip по действующим unit и Extension Host сценариям.
- Сохранить opt-in связь Artifacts View с synthetic resourceUri; builder, открытие canonical файла, действия и Focus View остаются в границах принятого контракта.

**Files:**
- src/views/artifactPriorityPresentation.ts
- src/views/artifactTreeItem.ts
- src/views/artifactsView.ts
- src/views/viewMessages.ts

**Tests:**
- tests/unit/artifactPriorityPresentation.test.ts
- src/test/integration/extension.test.ts

### 2. Повторно подтвердить обновление decoration и lifecycle

- Сверить provider и регистрацию: priority получается из текущего общего ArtifactIndex, synthetic URI определяет root и canonical file, propagate выключен.
- Повторить существующие Extension Host сценарии primary icon, badge, цвета, RU/EN tooltip, invalid/missing priority и обновления после refresh/watcher без перезапуска Extension Host.
- Подтвердить invalidation по model event и владение disposable registration в пределах текущего wiring.

**Files:**
- src/views/artifactPriorityDecorationProvider.ts
- src/extension.ts
- src/test/integration/extension.test.ts

**Tests:**
- yarn test:unit
- yarn test:integration

### 3. Выполнить прежний Verification и сохранить актуальное evidence

- Выполнить все команды существующего Verification на текущей revision и зафиксировать реальные результаты.
- В светлой, тёмной и custom theme проверить принятую primary icon и отдельный priority badge в Artifacts View и сохранность Focus View.
- Сохранить актуальное evidence через canonical workflow и передать revision на независимый STEP REVIEW.

**Files:**
- planning/tasks/STEP-017.md

**Tests:**
- yarn typecheck
- yarn lint
- yarn format
- yarn test:unit
- yarn test:integration
- git diff --check
- python3 .harness/tools/validate.py --mode manual

## Evidence






<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-10-15T21:19:28Z
- Status: PASS
- Automated resumed: false
- Git head: 7fd4473cee30ea461cdfab918d55827d2fce549c
- Worktree hash: sha256:642425d019bdacd4008c80d41d92706dcf64ce9d415df7f5aaf884eb8d7fdeec
- Verification contract basis: sha256:f108a191952be4c4dc8bc36b9716a599b766395b65c32d601c73a7fb7c3373c8
- Subject git head: 7fd4473cee30ea461cdfab918d55827d2fce549c
- Subject worktree hash: sha256:e3fc5abe87214435c05a1b9930d27870f45491a0b3325a0bab430f1d881d6f6f

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5022
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e2f566e38f3ed1b1d2b6f80d22090ba040fd2a843083db28bc65a6831af3f3e6
  - stdout bytes: 0
  - stderr bytes: 97
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5523
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1766
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7876
  - stdout sha256: 547ded3b61ee68aa6cc2e88aa843681739f70cb7e50940925f2af66e2177b9b3
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 24555
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 73445
  - stdout sha256: 9d3e73889f3d46b86f029224beca385b4bc9f823e9c3bc3e09851e21d21bba20
  - stderr sha256: 6157c8969c41db1ee7705dadba1ba04c1e6bbd716e7d6841a5af2ccc44abcc86
  - stdout bytes: 25161
  - stderr bytes: 27603
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
  - Duration ms: 2317
  - stdout sha256: e95f7aa24a7c105219343fcb2d7674e1be9ac5188972f887e3ddcbfb1d58da24
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 772
  - stderr bytes: 0

### Product verification
- none

### Manual verification
- Check: В светлой, тёмной и custom theme проверить, что Artifacts View показывает принятую primary icon и отдельный priority badge, а Focus View не меняется.
  - Status: PASS
  - Observed: "Проверен реальный Extension Development Host VS Code 1.140.0 после yarn build:dev на disposable mvp-valid fixture. В Light Modern, Dark Modern и Dark Modern с custom theme colors визуально сохранены status icons STEP/ADR, priority icon REQ и отдельные H/M/L/! badges; Focus View показывает прежние icons без badges. Проверка снимков выполнена через view_image, DOM snapshot подтверждает badges только в Harness Artifacts. Снимки: .harness/local/priority-ui-017/light.png: sha256:7b58574e1e1b24f74a673cee4ea3cac9d3ee85777c4aac6b8a93a5e0a439239e; .harness/local/priority-ui-017/dark.png: sha256:d927a0aaca610b5fc0c4e67abcadd8decd166c791f46c96886827e85fbe4fa7b; .harness/local/priority-ui-017/custom.png: sha256:6e0e6214530a0f5e893ab08eb9a6230c0fa15ee6108c9101c23cb4a1bb6f24bd"
<!-- VERIFICATION-EVIDENCE:END -->

Generated verification block записывает deterministic runner. Дополнительные semantic observations можно хранить вне generated markers.






## Blocker / Failure reason

—
