---
schema: 1
id: STEP-015
status: completed
type: implementation
priority: low
phase: release-preparation
depends_on:
  - STEP-014
requirements:
  - REQ-007
adrs:
  - ADR-003
  - ADR-005
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:043941525d0f0fc6a4cb8b5d7c13e5d1faed50f2408c79ba9ec2fef097833f6b
  content_hash: sha256:4792f583265064905ab1c29c0a9c6785692476f633f1e2dbfd411c17ae540501
  reviewed_report: planning/plan-reviews/STEP-015/PLAN-REVIEW-20260924T112716Z.md
  planned_at: 2026-09-24T11:27:16+00:00
---

# STEP-015 — Пункт «Открыть документацию» в меню команд Harness

## Goal

Добавить в контекстное меню каждой команды представления «Команды Harness» пункт «Открыть документацию» (EN: «Open Documentation»), открывающий в редакторе раздел документации команды из поля `documentation` Command Catalog.

## Context

Command graph (`.harness/command-transitions.json`) содержит у команд поле `documentation` формата `путь#якорь`, например `.harness/docs/COMMANDS.md#command-git-check`. Пользователь сейчас не может перейти к документации команды из view. После STEP-014 команды объявляются с `category` «Harness» и коротким `title`; пункт контекстного меню `copyCommand` находится в `view/item/context` (`viewItem == harnessCommandItem`). Поле `documentation` в модели каталога (`src/commandCatalog/`) может не разбираться — это выясняется на STEP PLAN; формат самого графа не меняется. Навигация проходит containment-проверки по ADR-005 (traversal, абсолютный путь, symlink за пределы root запрещены).

## Scope

- Новая команда `harnessNavigator.openCommandDocumentation`: `category` «Harness», `title` без префикса («Open Documentation» / «Открыть документацию»), в Command Palette скрыта (`when: false`, как `copyCommand`).
- Пункт в `view/item/context` для `viewItem == harnessCommandItem`, группа `navigation@2`, сразу после «Скопировать команду»; при пустом `documentation` пункт не показывается либо недоступен (механизм — на STEP PLAN, например через отдельный `contextValue`/`when`).
- Разбор `documentation` в `путь` и `якорь`; резолв пути относительно workspace folder, которому принадлежит команда, с теми же containment-проверками, что и остальная навигация; без хардкода путей вне данных графа.
- Открытие файла в редакторе и перевод курсора на секцию по якорю (заголовок либо HTML-якорь; способ выбирается на STEP PLAN по реальному `COMMANDS.md`).
- Поведение при ошибках без исключений: файл не найден — информационное сообщение; якорь не найден — файл открывается с начала; пустое значение, traversal, абсолютный путь и symlink за root — отказ с информационным сообщением без открытия файла.
- Локализация: `package.nls.json`, `package.nls.ru.json` (title), l10n-сообщения.
- Unit-тесты резолва `путь#якорь` (пустое значение, traversal, абсолютный путь, отсутствующий якорь) и интеграционные тесты меню и открытия документа (RU/EN).
- Обновление `docs/marketplace/README.md` (перечень пунктов меню), если он их перечисляет.

## Mutation policy

### Allowed

- `package.json`: новая команда, `menus.commandPalette` (when: false), `menus.view/item/context`.
- `package.nls.json`, `package.nls.ru.json`, l10n bundle.
- `src/commandCatalog/**`, `src/commands/**`, `src/extension.ts` — новый обработчик, регистрация и (при необходимости) чтение уже существующего поля `documentation` в модели каталога.
- Тесты: unit и integration; fixtures только в `src/test/fixtures`.
- `docs/marketplace/README.md`, `docs/development.md` (если перечисляют меню).

### Conditional

- Правка `contextValue` элементов Commands View — только если нужна для скрытия пункта при пустом `documentation`; остальные `when`-условия не менять.
- Обновление REQ-007 (Acceptance) — если PLAN решит, что это новый product contract.

### Forbidden

- Изменение формата command graph, tooltip и остальных пунктов меню; id существующих команд.
- Запуск Harness-команд, shell, сеть, запись в файлы (только открытие документа).
- Изменение `engines`, зависимостей, `yarn.lock`, `.github/`, `.harness/`.

## Out of scope

- Открытие документации из других view и editor/context.
- Рендеринг Markdown preview, поиск по документации, открытие внешних URL.
- Кэширование содержимого документации.

## Acceptance criteria

- Пункт «Открыть документацию» / «Open Documentation» показывается у каждой команды с непустым `documentation` в `navigation@2` сразу после «Скопировать команду»; в Command Palette отсутствует; в палитре-независимых местах title без префикса.
- Открывается файл из `documentation` относительно workspace folder команды; курсор стоит на секции якоря; при отсутствующем якоре файл открывается с начала.
- Пустое `documentation` — пункт скрыт/недоступен; отсутствующий файл — информационное сообщение; traversal, абсолютный путь и symlink за root отклоняются без открытия файла и без исключений.
- Формат графа, tooltip и остальные пункты меню не изменились; расширение остаётся read-only.
- Title и сообщения локализованы (RU/EN), наборы ключей `package.nls*.json` идентичны.
- Все проверки Verification проходят.

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
- manual: В Commands View контекстное меню команды содержит «Открыть документацию» после «Скопировать команду» (RU/EN); открывается COMMANDS.md на нужной секции; в Command Palette пункта нет.

## Deliverables

- Обновлённые `package.json`, `package.nls*.json`, l10n, код открытия документации, unit/integration тесты и `docs/marketplace/README.md`.

## Implementation plan

### 1. Чистый модуль резолва documentation

- Создать src/commandCatalog/documentationTarget.ts без импорта vscode (паттерн commandCatalogMessages.ts, тестируется unit-тестом).
- parseDocumentationRef(value): trim; пустое → {kind:'empty'}; делит по первому '#' на relativePath и anchor (anchor может быть пустым); пустой relativePath → empty.
- resolveDocumentationPath(realRoot, value): отклоняет абсолютный путь и сегмент '..' до обращения к ФС; path.resolve + проверка вхождения в root; realpathSync существующего файла должен оставаться внутри root (symlink наружу и dangling symlink → {kind:'unsafe'}); несуществующий/не файл → {kind:'missing'}; иначе {kind:'ok', fsPath, anchor}. Логика повторяет ADR-005 containment (resolveContainedPath в manifestService приватна, projectModel вне Mutation policy — реализуется локально, без правок manifestService). Уточнения: realRoot=realpathSync(folder.uri.fsPath) в try/catch (ошибка → unsafe); contained() = path.relative не '', не '..', не начинается с '..'+sep и не absolute (как в manifestService/readContainedMarkdown из artifactIndex.ts — допустим reuse экспортируемого helper вместо дубля); fsPath в результате — realpath файла, именно его получает openTextDocument. Остаточный TOCTOU принят: VS Code читает файл сам, post-open dev/ino проверка ADR-005 неприменима.
- findAnchorLine(text, anchor): 0-based строка. Сначала HTML-якорь `<a id="anchor">` / `name="anchor"` (реальный COMMANDS.md использует `<a id="command-..."></a>` перед заголовком `## `), затем fallback — заголовок Markdown, чей GitHub-slug (lower-case, пробелы→'-', без пунктуации) равен anchor; иначе undefined. Пустой anchor → undefined. Регистронезависимо не сравнивать для id (точное совпадение). Если после HTML-якоря следующей строкой идёт заголовок Markdown, курсор ставится на строку заголовка.

**Files:**
- src/commandCatalog/documentationTarget.ts

**Tests:**
- tests/unit/documentationTarget.test.ts

**Risks:**
- Поведение на Windows (регистр и разделители): использовать path.relative/isAbsolute, как в manifestService, а не строковые префиксы.

### 2. Команда harnessNavigator.openCommandDocumentation

- Создать src/commandCatalog/openCommandDocumentation.ts: registerOpenCommandDocumentation(): узел Commands View {type:'command', folder, command} (type-guard по образцу isCommandNode, но с обязательным folder.uri.fsPath); чужой аргумент — молчаливый return.
- Пустое command.documentation → showInformationMessage(M.docNone); unsafe → M.docBlocked (файл не открывается); missing → M.docNotFound (с относительным путём); ошибки realpath/чтения перехватываются try/catch и дают информационное сообщение, исключения наружу не уходят.
- ok: vscode.workspace.openTextDocument(Uri.file(fsPath)) → showTextDocument; при найденной строке — selection/revealRange(InCenterIfOutsideViewport) на этой строке, иначе документ открывается с начала. Никаких записей, shell, сети. Причина, по которой пункт не скрывается: скрытие потребовало бы отдельного contextValue и правки when у copyCommand (Forbidden); «недоступен» = no-op + информационное сообщение. activationEvents не добавлять.
- Скрытие пункта при пустом documentation: contextValue 'harnessCommandItem' не меняется (по требованию when `viewItem == harnessCommandItem` и чтобы не трогать when у copyCommand), пункт остаётся видимым, а для пустого значения обработчик выдаёт информационное сообщение (вариант «недоступен» из Scope).
- Добавить сообщения docNone, docBlocked, docNotFound в COMMAND_CATALOG_MESSAGES (commandCatalogMessages.ts); зарегистрировать команду в src/extension.ts рядом с registerCopyCommand с передачей в disposable registry.

**Files:**
- src/commandCatalog/openCommandDocumentation.ts
- src/commandCatalog/commandCatalogMessages.ts
- src/extension.ts

**Tests:**
- src/test/integration/commandCatalog.test.ts

**Risks:**
- Открытие в non-Harness-aware файле: openTextDocument не привязан к Harness scope, поэтому containment — единственная защита; проверка обязана выполняться до openTextDocument.

### 3. Manifest и локализация

- package.json: команда harnessNavigator.openCommandDocumentation (category %category.harness%, title %command.openCommandDocumentation.title%); menus.commandPalette — when: false; menus.view/item/context — when `view == harnessNavigator.commands && viewItem == harnessCommandItem`, group navigation@2 (сразу после copyCommand@1). Существующие записи не менять; при необходимости добавить activationEvents по образцу соседних команд.
- package.nls.json: «Open Documentation»; package.nls.ru.json: «Открыть документацию» (наборы ключей идентичны).
- l10n/bundle.l10n.json и bundle.l10n.ru.json: три новых сообщения (EN-ключ → RU-перевод); проверяется tests/unit/localization.test.ts.

**Files:**
- package.json
- package.nls.json
- package.nls.ru.json
- l10n/bundle.l10n.json
- l10n/bundle.l10n.ru.json

**Risks:**
- inspect:package сверяет manifest с docs/marketplace/README.md — обновить README в том же шаге.

### 4. Документация

- docs/marketplace/README.md: в EN- и RU-перечнях пунктов «Harness Commands view items» / «Элементы представления «Команды Harness»» добавить Open Documentation / Открыть документацию.
- docs/development.md — только если там перечислены пункты меню.

**Files:**
- docs/marketplace/README.md
- docs/development.md

### 5. Тесты

- Unit tests/unit/documentationTarget.test.ts (временный каталог с fs): пустое/пробельное значение; путь без якоря; путь#якорь; traversal '../x' и 'a/../../x'; абсолютный путь; symlink на файл вне root; dangling symlink; несуществующий файл; каталог вместо файла; findAnchorLine для `<a id>`, для заголовка по slug, отсутствующего якоря, пустого якоря.
- Integration (commandCatalog.test.ts, режимы en и ru): manifest — команда объявлена, category+title без префикса, palette when:false, пункт view/item/context navigation@2 после copyCommand@1, title локализован по vscode.env.language; выполнение команды на узле из getCommandsViewCommandNodes открывает activeTextEditor с ожидаемым файлом и курсором на строке якоря; отсутствующий якорь → курсор на строке 0; отсутствующий файл и пустое documentation → редактор не открыт, исключений нет. Fixture с .harness/docs/COMMANDS.md в mvp-fixtures/тестовом workspace. Дополнительный кейс через graphText(mutate): documentation '../outside.md#x' и абсолютный путь → редактор целевого файла не открывается, executeCommand не reject. Fixture .harness/docs/COMMANDS.md создаётся в workspace root, куда commandCatalog.test.ts пишет граф (в runtime вместе с графом), с '<a id="command-step-list"></a>' и заголовком после него.
- Существующие тесты tooltip/contextValue/меню не менять — они служат регрессией «не менять формат графа, tooltip и остальные пункты».

**Files:**
- tests/unit/documentationTarget.test.ts
- src/test/integration/commandCatalog.test.ts
- src/test/fixtures

**Risks:**
- Symlink-тесты на Windows могут требовать прав — пропускать через t.skip при EPERM.

### 6. Верификация и Evidence

- Выполнить все команды Verification, зафиксировать command, exit code и observed facts в ## Evidence; ручную проверку меню (RU/EN) описать фактами.
- Не менять REQ-007: поведение — расширение Commands View по уже принятому Copy/Find контракту; если reviewer сочтёт это новым product contract, вернуться через STEP FIX/REQ.

## Evidence




<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T11:37:58Z
- Status: PASS
- Git head: 40e593f781be7d16a5df3e535ce8f74b48cfceed
- Worktree hash: sha256:c8adebfafd0e3fe7411a001792c7f6970452271ce9bfcc8c841bb7b2ad8b2f58

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3783
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4900
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1548
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 8021
  - stdout sha256: 7596b9d82087ad3c1e4bd72c25a1e743e8eaa71a0032e2c1aa08fca501266190
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 19931
  - stderr bytes: 0
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 544
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3709
  - stdout sha256: 52540901a2857373ee7a6da3b22896e881df80e0d8843ba2c0d8f04fee45f348
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 855
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 352
  - stdout sha256: e36b235fa15ea7090a81509f9a348b2b469ae404205384470dbf8e1a91143529
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 47613
  - stdout sha256: cfd11e8fe95c0d7b5fee41c7e249441bedd9099a66bd1289dff73add41268b17
  - stderr sha256: 6f40eeb3c90193791d6fffab1f17b0fda7cb00a488e3d0059ce30f9e9d30841d
  - stdout bytes: 40426
  - stderr bytes: 30256
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
  - Duration ms: 1225
  - stdout sha256: 362b6d3ae69649fb3f6d1877edb13c134504ada6a17b7f212854e6f6623cebe0
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: В Commands View контекстное меню команды содержит «Открыть документацию» после «Скопировать команду» (RU/EN); открывается COMMANDS.md на нужной секции; в Command Palette пункта нет.
  - Status: PASS
  - Observed: "Визуальная проверка в GUI не выполнялась (headless среда). Наблюдалось через yarn test:integration (Extension Host, режимы en и ru, 23 passing в каждом): manifest объявляет команду с category и коротким title, в commandPalette when:false, в view/item/context группа navigation@2 после copyCommand@1; выполнение команды на узле Commands View открывает COMMANDS.md с курсором на строке якоря (line 5); отсутствующий якорь — курсор на строке 0; пустое значение, отсутствующий файл, traversal и абсолютный путь — редактор не открывается, исключений нет."
<!-- VERIFICATION-EVIDENCE:END -->




## Blocker / Failure reason

—
