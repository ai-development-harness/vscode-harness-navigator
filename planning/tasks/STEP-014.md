---
schema: 1
id: STEP-014
status: in_progress
type: implementation
priority: low
phase: release-preparation
depends_on:
  - STEP-013
requirements:
  - REQ-008
adrs: []
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:2515f9c4fccd00ff1599d646926e19b415d13d61ca763d6dcf1e52a7cc86e543
  content_hash: sha256:6a66e1cf75866be762ec1f2a652bad17aa386096d132cd5cc627f0aa7a016a43
  reviewed_report: planning/plan-reviews/STEP-014/PLAN-REVIEW-20260924T074120Z.md
  planned_at: 2026-09-24T07:41:20+00:00
---

# STEP-014 — Префикс «Harness:» только в Command Palette (category вместо title)

## Goal

Убрать префикс «Harness:» из `title` команд расширения и вынести его в поле `category`, чтобы он показывался только в Command Palette, а в представлениях, их контекстных меню и на кнопках заголовков были короткие названия действий.

## Context

Все 12 команд `harnessNavigator.*` объявлены в `package.json` с `title`, в который префикс «Harness: » вшит через `package.nls.json` и `package.nls.ru.json` (например «Harness: Copy Command»); поля `category` нет. Команды показываются: в Command Palette; на кнопках `view/title` (`setSortOrder`, `setFilter`, `clearFilters`); в `view/item/context` (`copyArtifactId`, `copyArtifactPath`, `findAllReferences`, `showRelations`, `copyCommand`); в `editor/context` для Markdown (`findAllReferences`, `showRelations`). Внутри view пользователь и так знает, что работает с Harness, поэтому префикс там избыточен. VS Code показывает `category` только в Command Palette (и списке keyboard shortcuts) как «Category: Title», а в меню и на кнопках — только `title`.

Оговорка: в `editor/context` для Markdown без префикса пункт «Find All References» неотличим от встроенного пункта VS Code. Для этих двух команд в редакторе нужен различимый заголовок. Один `title` на команду действует во всех меню, поэтому механизм (title с префиксом только у этих двух команд либо menu-only алиасы без дублирования логики) выбирается на STEP PLAN.

`REQ-008` требует локализации views, commands и menus и упоминает `Harness: Show Diagnostics` — в Command Palette этот заголовок сохраняется (category + title), контракт не меняется. `docs/marketplace/README.md` перечисляет заголовки команд по местам и проверяется `inspect:package`; `src/test/integration/extension.test.ts` и другие тесты ссылаются на строки «Harness: …».

## Scope

- Для всех команд `harnessNavigator.*` в `package.json` задать `category` «Harness» (локализуемо через `package.nls*.json`), а `title` оставить только действием на EN и RU (например «Copy Command»/«Скопировать команду», «Set Filter»/«Задать фильтр»).
- В Command Palette заголовки остаются «Harness: <действие>»; в `view/title` и `view/item/context` — только действие.
- Выбрать и реализовать различимый заголовок с префиксом «Harness:» для `findAllReferences` и `showRelations` в `editor/context`.
- Обновить `package.nls.json`, `package.nls.ru.json`, `docs/marketplace/README.md` (перечни команд и меню по местам) и тесты, проверяющие manifest, заголовки и локализацию (RU/EN).

## Mutation policy

### Allowed

- `package.json`: `contributes.commands` (поля `category`, `title`), записи `menus.commandPalette` (when: false) для menu-only алиасов и `menus.editor/context`.
- `src/extension.ts`: только регистрация двух menu-only алиасов как тонких обёрток над оригинальными командами.
- `package.nls.json`, `package.nls.ru.json`.
- `docs/marketplace/README.md`, `docs/development.md` (если там перечислены заголовки).
- Тесты, проверяющие заголовки, manifest и локализацию.

### Conditional

- Комментарии в `src/**` со ссылками на «Harness: …» — только если правка нужна для консистентности; логику не менять.
- Логика команд `findAllReferences`/`showRelations` не меняется; алиасы только делегируют оригиналам.

### Forbidden

- Изменение id команд, поведения, `when`-условий, порядка групп и видимости в Command Palette.
- Изменение `engines`, зависимостей, `yarn.lock`, `.github/`, `.harness/`.
- Новые пользовательские функции и пункты меню.

## Out of scope

- Добавление пункта «Открыть документацию» (отдельный STEP).
- Переименование самих действий (формулировки за пределами удаления префикса).
- Смена id команд и settings.

## Acceptance criteria

- Все команды `harnessNavigator.*`, включая menu-only алиасы, имеют `category` «Harness»; `title` не содержит префикса «Harness:» ни на EN, ни на RU (кроме menu-only алиасов для editor/context, скрытых из Command Palette).
- В Command Palette заголовки остаются «Harness: <действие>» (EN/RU).
- В `view/title` и `view/item/context` показываются заголовки без префикса.
- В `editor/context` (Markdown) пункты `findAllReferences` и `showRelations` имеют различимый заголовок с префиксом «Harness:».
- id команд в `contributes.commands`, `when`-условия, группы, порядок и видимость в палитре существующих команд не изменились; в двух записях `menus.editor/context` меняется только `command` (на menu-only алиас), `when` и `group` сохраняются.
- `docs/marketplace/README.md` описывает заголовки по местам без противоречий; `yarn inspect:package` даёт `0 violations`.
- Все проверки Verification проходят; CI на PR зелёный.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn build`
- command: `yarn package`
- command: `yarn inspect:package`
- command: `yarn test:integration`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Command Palette показывает «Harness: <действие>»; контекстные меню view и кнопки view/title — без префикса; editor-меню Markdown — с префиксом «Harness:» и отличается от встроенного «Find All References» (RU и EN); Workflow CI на PR зелёный (Quality, Package).

## Deliverables

- Обновлённые `package.json`, `package.nls*.json`, `docs/marketplace/README.md` и тесты локализации.

## Implementation plan

### 1. Manifest: category и короткие title

- В package.json для всех 12 команд harnessNavigator.* задать category: %category.harness% (новый ключ в package.nls.json и package.nls.ru.json со значением «Harness» в обоих языках).
- В package.nls.json и package.nls.ru.json убрать префикс «Harness: » из command.*.title: EN — Show Diagnostics, Refresh, Go to Artifact, Set Sort Order, Set Filter, Clear Filters, Copy Artifact ID, Copy Artifact Path, Find All References, Show Relations, Find Command, Copy Command; RU — Показать диагностику, Обновить, Перейти к артефакту, Задать порядок сортировки, Задать фильтр, Очистить фильтры, Скопировать ID артефакта, Скопировать путь артефакта, Найти все ссылки, Показать связи, Найти команду, Скопировать команду.
- Ключи nls и id команд не переименовывать; наборы ключей en/ru остаются идентичными (проверяет tests/unit/localization.test.ts).
- Палитра: category + title даёт «Harness: <действие>» (для showDiagnostics сохраняется формулировка REQ-008).

**Files:**
- package.json
- package.nls.json
- package.nls.ru.json

**Risks:**
- Команды, скрытые из палитры (when: false), category не проявляют — это нормально; порядок групп, when-условия и id не менять.

### 2. Editor/context: различимый заголовок через menu-only алиасы

- Механизм: menu-only команды-алиасы harnessNavigator.editor.findAllReferences и harnessNavigator.editor.showRelations. У одной команды один title на все меню: с префиксом он остался бы в view/item/context (нарушение Acceptance), без префикса пункт в Markdown-редакторе неотличим от встроенного «Find All References» VS Code.
- В package.json объявить два алиаса с category: %category.harness% (в палитре скрыты через when: false, двойного префикса нет) и title с префиксом: %command.editor.findAllReferences.title% = «Harness: Find All References» / «Harness: Найти все ссылки», %command.editor.showRelations.title% = «Harness: Show Relations» / «Harness: Показать связи» (новые ключи в обоих nls-файлах).
- В menus.commandPalette добавить записи алиасов с when: false; оригинальные команды остаются в палитре (editorLangId == markdown) без изменений.
- В двух существующих записях menus.editor/context заменить только поле command на алиас; when (resourceLangId == markdown) и group (navigation@10 и navigation@11) сохранить; новых записей рядом со старыми не добавлять (без дублей пунктов меню).
- В src/extension.ts зарегистрировать алиасы двумя ОТДЕЛЬНЫМИ регистрациями с литеральными id: registerCommand('harnessNavigator.editor.findAllReferences', (...args) => vscode.commands.executeCommand('harnessNavigator.findAllReferences', ...args)) и аналогично для showRelations. Общий helper с параметром id не использовать: scripts/packageInspection.ts зафиксирует «bundle calls executeCommand with a non-literal id», и inspect:package не даст 0 violations. Disposable добавить в subscriptions; логика оригиналов не дублируется и не меняется.

**Files:**
- package.json
- package.nls.json
- package.nls.ru.json
- src/extension.ts

**Risks:**
- Аргумент из editor/context (Uri) пробрасывается в оригинальную команду через (...args); проверить integration-тестом, что результат алиаса совпадает с оригиналом.
- Тесты, перечисляющие команды манифеста, учтут алиасы: category есть, title с префиксом, скрыты из палитры, используются только в editor/context.
- Литерал 'harnessNavigator.*' в executeCommand разрешён ALLOWED_COMMAND_IDS; проверить yarn inspect:package (0 violations) и unit-тест packageInspection.

### 3. Документация: marketplace README

- В docs/marketplace/README.md (английская и русская части) обновить перечни: Command Palette — «Harness: <действие>» без изменений; Context menus и view title buttons — без префикса; Markdown editor — «Harness: Find All References», «Harness: Show Relations» с префиксом; сохранить требования к README (только абсолютные https-ссылки, без Harness-managed блока, изображений и ссылок вида #<число>).
- Проверить docs/development.md на перечни заголовков и при необходимости синхронизировать.

**Files:**
- docs/marketplace/README.md
- docs/development.md

### 4. Тесты

- Unit (tests/unit/localization.test.ts или соседний файл): для каждой команды harnessNavigator.* из contributes.commands — category = %category.harness%; title в EN/RU bundle без префикса «Harness:» у обычных команд, а у алиасов harnessNavigator.editor.* — с префиксом, скрытие из палитры (when: false) и использование только в editor/context; ключ category.harness есть в обоих bundle; в view/title и view/item/context нет алиасов.
- Integration (Extension Host, RU/EN): алиасы зарегистрированы и делегируют оригиналу с пробросом аргумента (executeCommand алиаса возвращает те же Locations/результат, что оригинал); существующие тесты, вызывающие команды по id, не меняются по смыслу.
- Комментарии в src/** со ссылками на «Harness: …» не трогать, если логика не затрагивается.

**Files:**
- tests/unit/localization.test.ts
- src/test/integration/extension.test.ts

**Tests:**
- yarn test:unit
- yarn test:integration

**Risks:**
- Проверка отображения в UI (палитра/меню) в Extension Host недоступна автоматически — выполняется вручную и фиксируется в Evidence.

### 5. Верификация и Evidence

- Прогнать команды Verification; dispatcher записывает generated Evidence. yarn test:integration запускает VS Code Extension Host (локальная проверка; нужен display, при headless — xvfb-run).
- Вручную зафиксировать в Evidence: Command Palette показывает «Harness: <действие>», контекстные меню view и кнопки view/title — без префикса, editor-меню Markdown — с «Harness:» и не совпадает со встроенным «Find All References» (RU и EN), inspect:package даёт 0 violations.
- Ручная проверка CI: PR открывается по GIT CHECK > GIT COMMIT > GIT PUSH > GIT PR при STEP в in_progress до REVIEW; в Evidence записать URL/ID запуска и статусы Quality/Package.

**Tests:**
- yarn typecheck
- yarn lint
- yarn format
- yarn build
- yarn package
- yarn inspect:package
- git diff --check
- python3 .harness/tools/validate.py --mode manual

## Evidence








<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T08:11:06Z
- Status: PASS
- Git head: 49c4ff3fcd964d2947831e8c1529b81e3b4530bf
- Worktree hash: clean

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3554
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4460
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1359
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7719
  - stdout sha256: 22dd462735ac843370ffdc6b8937bdf9053dc78a1454b7b4b45fd2b6a7a5888c
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 19466
  - stderr bytes: 0
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
  - Duration ms: 3673
  - stdout sha256: 92249da31d583049f33fe2ea73aab4932b10d008868e481a179743d2f83064f6
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 856
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 331
  - stdout sha256: bb20c57626e15400248c73d52a1f65dfcee56f56cf37b71cb7b36822053e8746
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 44417
  - stdout sha256: 036281dc220281d438e8188985ae8ebe2a3399a16a0eca11e2ea5791669311cf
  - stderr sha256: 53a17f4db0c4fbf1acac5a78632cc506b37d7a904cc10ee469940ad88a9eec67
  - stdout bytes: 36257
  - stderr bytes: 30256
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1200
  - stdout sha256: 776e98bb84a7dfaed278440e3eaf6623db0ccdafd2706e6c00dd834a0182ab4b
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Command Palette показывает «Harness: <действие>»; контекстные меню view и кнопки view/title — без префикса; editor-меню Markdown — с префиксом «Harness:» и отличается от встроенного «Find All References» (RU и EN); Workflow CI на PR зелёный (Quality, Package).
  - Status: PASS
  - Observed: "UI: пользователь вручную проверил собранный VSIX и сообщил «Ручная проверка успешна»; после этого менялись только тесты (integration-тест делегирования алиасов, unit-проверки записей меню), продукт не менялся. CI: PR #15 https://github.com/ai-development-harness/vscode-harness-navigator/pull/15, коммит 49c4ff3, run https://github.com/ai-development-harness/vscode-harness-navigator/actions/runs/35973474367 — Quality pass (49s), Package pass (1m23s); Validate Harness pass (run 35973474309). Для предыдущего коммита 3d46031: run 35972072670 — Quality и Package pass."
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.








## Blocker / Failure reason

—
