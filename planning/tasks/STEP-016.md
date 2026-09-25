---
schema: 1
id: STEP-016
status: completed
type: implementation
priority: medium
phase: workspace-ui
depends_on:
  - STEP-004
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
  context_basis: sha256:e5172c71605ee2ffc9cd679066dfb75b2a946ece965402dc89516fcb689413b1
  content_hash: sha256:928588649fcc61e2ff834ebced5492e8cf14a8ae1a9882d77abe068b13ffac3c
  reviewed_report: planning/plan-reviews/STEP-016/PLAN-REVIEW-20260925T073516Z.md
  planned_at: 2026-09-25T07:35:16+00:00
---

# STEP-016 — Семантические иконки артефактов в Harness Artifacts

## Goal

Сделать leaf-артефакты Harness Artifacts различимыми по их уже индексированному статусу или приоритету с помощью нативных Codicon и theme-aware цветов, не изменяя Harness Focus и read-only границу расширения.

## Context

STEP-004 отображает leaf-элементы Artifacts View нейтральными иконками по kind. Artifact Index уже предоставляет `kind`, `status` и `metadata.priority`, а ADR-002 запрещает повторный parsing документов в consumer. ADR-004 предписывает нативные `ThemeIcon`/`ThemeColor` без fixed RGB, поэтому визуальная семантика должна вычисляться только из snapshot индекса и обновляться его существующими refresh/watcher событиями.

## Scope

- Только Artifacts View: semantic `ThemeIcon` и `ThemeColor` для leaf STEP, REQ и ADR на основе существующего Artifact Index.
- Leaf OQ остаётся нейтральным: сохраняет текущий `ThemeIcon` `question` без заданного `ThemeColor`; семантическая матрица OQ не применяется.
- Полная таблица отображения: STEP `planned` → `circle-large-outline`/`editorInfo.foreground`, `in_progress` → `sync~spin`/`editorInfo.foreground`, `blocked` → `circle-slash`/`editorError.foreground`, `completed` → `pass-filled`/`testing.iconPassed`, `deferred` → `clock`/`editorWarning.foreground`, `cancelled` → `close`/`disabledForeground`; REQ `critical` → `flame`/`editorError.foreground`, `high` → `arrow-up`/`editorWarning.foreground`, `medium` → `dash`/`editorInfo.foreground`, `low` → `arrow-down`/`disabledForeground`; ADR `proposed` → `lightbulb`/`editorWarning.foreground`, `accepted` → `check`/`testing.iconPassed`, `superseded` → `history`/`disabledForeground`, `rejected` → `circle-slash`/`editorError.foreground`.
- Fallback для неизвестного, отсутствующего или некорректного значения: текущая нейтральная kind-иконка `checklist` (STEP), `bookmark` (REQ) или `book` (ADR) без заданного цвета.
- Unit-тесты полной матрицы и fallback; Extension Host integration-проверка representative STEP/REQ/ADR TreeItem, refresh и watcher-driven обновлений.

## Mutation policy

### Allowed

- `src/views/**` и узкие read-only test seams в `src/extension.ts`, необходимые для наблюдения TreeItem в Artifacts View.
- Unit- и integration-тесты Artifacts View и fixtures в `src/test/fixtures`.
- REQ-004 traceability и generated planning projections.

### Conditional

- Вынесение чистой функции выбора presentation из Artifacts View допускается только без runtime parsing, persistent cache или изменения публичного поведения Focus View.

### Forbidden

- Любые изменения Focus View, Tooltip, label, description, context actions, open command, сортировки или фильтрации.
- Повторный parsing Markdown, чтение файлов из provider, mutation workspace/Harness artifacts, fixed RGB, WebView, зависимости и изменения `.harness/`.

## Out of scope

- Новая семантическая матрица для OQ, групп и root-узлов.
- Новые статусы, приоритеты, фильтры, настройки или пользовательская настройка цветов.
- Изменение Artifact Index, watcher topology или модели Artifact.

## Acceptance criteria

- Каждый известный STEP, REQ и ADR из заданной матрицы отображается в Artifacts View с точным Codicon id и `ThemeColor` id; используются только `ThemeIcon`/`ThemeColor`, совместимые с активной темой.
- Неизвестный, отсутствующий либо некорректный `status`/`metadata.priority` у STEP/REQ/ADR даёт нейтральную kind-иконку без цвета.
- OQ в Artifacts View сохраняет `ThemeIcon.id === 'question'` без `ThemeColor`; его tooltip, label, description, действия, открытие, сортировка и фильтрация не изменяются.
- Focus View не меняется; tooltip, label, description, context actions, open command, сортировка и фильтрация Artifacts View сохраняют прежнее поведение.
- После `Harness: Refresh` и watcher-driven изменения Artifact Index Artifacts View выдаёт TreeItem с актуальными семантическими icon/color без повторного parsing Markdown и без записи workspace.
- Unit-тесты покрывают всю матрицу и fallback; integration-тест подтверждает ожидаемые `ThemeIcon.id` и `ThemeColor.id` у representative STEP/REQ/ADR.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: В светлой, тёмной и custom theme убедиться, что Artifacts View показывает заданные semantic icon/color, а Focus View остался без изменений.

## Deliverables

- Локальная логика presentation Artifacts View, unit-тесты матрицы/fallback и Extension Host integration-проверка обновления TreeItem.

## Implementation plan

### 1. Чистая матрица presentation для leaf-артефакта

- Создать vscode-независимый модуль `src/views/artifactPresentation.ts`, который принимает уже индексированный `Artifact` и возвращает `{ iconId, colorId? }` только для presentation Artifacts View.
- Закодировать полную матрицу STEP по `status`, REQ по `metadata.priority` и ADR по `status`; не приводить неизвестные строки к известным enum-значениям.
- Для неизвестного, отсутствующего или некорректного значения вернуть существующие neutral kind-иконки STEP `checklist`, REQ `bookmark`, ADR `book` без `colorId`; для OQ всегда вернуть `question` без `colorId`.
- Не читать Markdown, filesystem или workspace settings: входом служат только поля уже построенного Artifact Index.

**Files:**
- src/views/artifactPresentation.ts

**Tests:**
- Добавить table-driven unit-тест полной таблицы Codicon/ThemeColor для всех STEP, REQ и ADR, включая отсутствующие, неизвестные и некорректные status/priority, а также постоянный neutral fallback OQ.

**Risks:**
- `metadata.priority` является недоверенным runtime-значением, поэтому lookup обязан fail-safe возвращать neutral fallback, а не полагаться на TypeScript enum.

### 2. Применение presentation только в Artifacts View

- Расширить общий `buildArtifactTreeItem` необязательным presentation-аргументом: по нему материализовать `new vscode.ThemeIcon(iconId, colorId === undefined ? undefined : new vscode.ThemeColor(colorId))`; без аргумента сохранить существующий kind-icon и отсутствие цвета.
- В `ArtifactsTreeDataProvider.getTreeItem` для leaf вызвать mapping из нового модуля и передать результат builder-у. Root и group nodes не менять.
- В `FocusTreeDataProvider` сохранить текущий двухаргументный вызов builder-а, поэтому иконки Focus, tooltip, label, description, contextValue, open command, сортировка и фильтрация не меняются.
- Не добавлять subscriptions, parser, cache или filesystem access: текущий `onDidChangeProjectModel` уже вызывает повторное построение TreeItem после refresh и watcher update из нового snapshot.

**Files:**
- src/views/artifactTreeItem.ts
- src/views/artifactsView.ts

**Tests:**
- Существующие unit/integration регрессии Artifacts/Focus остаются проверкой сохранения текстовых полей, команд, сортировки и фильтров.

**Risks:**
- Общий builder используется Focus View; presentation override обязан быть opt-in, иначе semantic colors непреднамеренно изменят Focus.

### 3. Extension Host evidence для TreeItem и обновлений индекса

- Добавить в `src/extension.ts` минимальный read-only integration seam, возвращающий реальные leaf `TreeItem` Artifacts View вместе с ID артефакта; не раскрывать mutable provider state и не изменять production UI.
- При необходимости добавить симметричный узкий Focus seam только для regression-assert, что его item остаётся neutral; не менять provider wiring.
- Расширить существующий сценарий Artifacts/Focus в `src/test/integration/extension.test.ts`: fixture-артефакты задают representative STEP, REQ с `priority` и ADR с `status`; assert проверяет на реальном `TreeItem` `ThemeIcon.id` и `ThemeColor.id` по матрице, OQ `question` без цвета и неизменённые Focus item semantics.
- В том же изолированном fixture-сценарии изменить status/priority, сначала проверить синхронное обновление после `harnessNavigator.refresh`, затем изменить artifact через existing watcher path и дождаться актуального TreeItem через существующий documented watcher/recovery helper; в `finally` восстановить fixture и workspace settings как в текущем тесте.

**Files:**
- src/extension.ts
- src/test/integration/extension.test.ts
- src/test/integration/support/helpers.ts

**Tests:**
- Extension Host integration EN/RU: real TreeItem matrix for representative STEP/REQ/ADR, OQ neutral fallback, refresh update and watcher-driven update.

**Risks:**
- Watcher delivery может быть platform-flaky; использовать уже принятый REQ-009 documented watcher-window plus refresh fallback, не вводить новый retry protocol.

### 4. Проверка и evidence

- Запустить полный verification contract STEP: typecheck, lint, format check, unit, integration, diff check и Harness manual validation.
- Зафиксировать только фактически полученные команды, exit code и наблюдения в Evidence; затем передать revision независимому STEP REVIEW.

**Files:**
- planning/tasks/STEP-016.md

**Tests:**
- Все команды из Verification STEP-016.

**Risks:**
- Integration suite запускается в реальном Extension Host в EN/RU и может потребовать времени; её результат нельзя заменять unit-результатом.

## Evidence





<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-25T08:12:20Z
- Status: PASS
- Git head: 1ff5bfed18840206e19b9d8db4ca46f5748dda14
- Worktree hash: sha256:0506a7613e1067b80769c166618c29e809086f123c51b40bd9cb1d69171ce580

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
  - Duration ms: 4722
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
  - Duration ms: 7878
  - stdout sha256: e5da42ce1f3590da4e547831bddaa8398eac61b4f72921e6908bbdf11b8ce6e5
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 20161
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 49247
  - stdout sha256: c776702ce153adda49156a07f6bb3e74f3d339339f8f2433049a832c5a2b43ee
  - stderr sha256: 50835751ca72d5f684967ee2e3d2610e14bef4deb8f2c011ab94ecf929fc39e1
  - stdout bytes: 40981
  - stderr bytes: 13676
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
  - Duration ms: 1616
  - stdout sha256: 12726af5260db12d26953ccb21e456215033b60f0d96cecddcb34fba5e0f4c56
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 482
  - stderr bytes: 0

### Manual verification
- Check: В светлой, тёмной и custom theme убедиться, что Artifacts View показывает заданные semantic icon/color, а Focus View остался без изменений.
  - Status: PASS
  - Observed: "Ручная проверка пройдена успешно; FIX изменил только read-only test seams и assertions, визуальное поведение не менялось."
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.





## Blocker / Failure reason

—
