---
schema: 1
id: STEP-004
status: completed
type: implementation
priority: high
phase: workspace-ui
depends_on:
  - STEP-003
requirements:
  - REQ-001
  - REQ-004
  - REQ-008
adrs:
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#основные-потоки"
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:94872f1d6367798d8254d611259e06621d6910d41c39a03f06a323bb02738f3a
  content_hash: sha256:ea9ee31ad8c3294cd5e014737bf6cdd37b37dfcac50adf0fa6d0736d33932bd3
  reviewed_report: planning/plan-reviews/STEP-004/PLAN-REVIEW-20260922T225413Z.md
  planned_at: 2026-09-22T22:55:34+00:00
---

# STEP-004 — Views артефактов, фокуса и поиск

## Goal

Предоставить нативные Harness Artifacts и Harness Focus Tree Views, пользовательскую сортировку/фильтрацию и `Harness: Go to Artifact`.

## Context

STEP-003 создаёт общий project model; этот STEP преобразует его в standard VS Code UI без нового parsing documents.

## Scope

- Activity Bar container, Artifacts View и Focus View на основе общего Artifact Index.
- Tree items, opening canonical files, context actions, sort/filter workspace settings и clear filters.
- Quick Pick `Harness: Go to Artifact` с fuzzy search ID/title/kind.
- Tests views, actions, sorting/filtering and artifact search.

## Mutation policy

### Allowed

- Source, tests, extension contributions и localized UI strings для artifact/focus/search flows.

### Conditional

- Изменение shared view wiring, если требуется для disposal/refresh subscriptions.

### Forbidden

- WebView, самостоятельный parsing files в provider или выбор следующего STEP за пользователя.
- Изменение Harness artifacts и запуск команд из context menu.

## Out of scope

- Harness Commands View и command catalog.
- Definition, hover, completion, reference и highlighting providers.

## Acceptance criteria

- Artifacts View показывает grouped STEP/REQ/ADR/OQ с ID, title и status через native Tree View API.
- Focus View показывает active/blocked STEP и open OQ, не назначая работу.
- Sort/filter/clear filters соответствуют supported fields и сохраняют workspace preferences.
- `Harness: Go to Artifact` fuzzy-ищет известные artifacts по ID/title/kind и открывает выбранный canonical Markdown file.

## Verification

- Реальные `typecheck`, `lint` и targeted tests views/search.
- Extension Host scenario с artifact selection, filters и empty state.

## Deliverables

- Tree providers/items, artifact search command, sort/filter state, localized UI and tests.

## Implementation plan

1. **Наблюдаемость изменений общего project model.** `ProjectStateService` и
   `ArtifactIndex` сейчас не публикуют событие изменения: `refreshRoot` и
   watcher-callback обновляют derived state молча, поэтому live Tree View не
   может узнать, что snapshot устарел. Добавить в `ProjectStateService`
   единственный `vscode.EventEmitter<void>` и публичный
   `onDidChangeProjectModel`, срабатывающий в конце `refreshRoot` и после
   `handleArtifactWatcherEvent` в `createArtifactWatcher`; emitter освобождать
   в существующем `dispose()`. Это ровно Conditional-изменение shared view
   wiring ради refresh/disposal subscriptions: parsing, containment и сам
   индекс не трогать. Consumers получают данные только через
   `getIndex(folder)?.snapshot()` и `ProjectStateService.all`; никакого
   собственного чтения файлов в providers нет.

2. **Vscode-независимая view model.** Вынести всю логику представления в
   `src/views/artifactViewModel.ts` без runtime-импорта `vscode` (допустим
   только `import type`, как в `lifecycle/disposableRegistry.ts`), чтобы её
   можно было покрыть обычными `node:test` unit tests из `tests/unit/`.
   Модуль принимает `readonly Artifact[]` и текущие preferences и возвращает
   детерминированные структуры: группировку по `kind` в фиксированном порядке
   STEP/REQ/ADR/OQ, применённый sort order, применённые фильтры, выборку для
   Focus View и список кандидатов Quick Pick. Фильтрация STEP по
   `status`/`type`/`priority`/`phase` читает уже разобранные значения из
   `Artifact.status` и `Artifact.metadata` — нового parsing не вводить.
   Sort orders: по `id` (default, совпадает с порядком `snapshot()`), по
   `title`, по `status`, по `priority`; для неизвестного/отсутствующего поля
   задать стабильный tail-порядок, чтобы сортировка оставалась total и
   воспроизводимой. Focus View отбирает STEP со `status: in_progress`,
   STEP со `status: blocked` и OQ со `status: open`, сохраняя порядок внутри
   группы по ID; никакого ранжирования, «next step» или рекомендаций —
   выбор следующей работы остаётся за пользователем.

3. **Contributions, настройки и локализация.** В `package.json` добавить
   `viewsContainers.activitybar` (`harnessNavigator`, `ThemeIcon`-совместимый
   built-in icon без fixed RGB), два `views` — `harnessNavigator.artifacts` и
   `harnessNavigator.focus`, команды `harnessNavigator.goToArtifact`,
   `harnessNavigator.setSortOrder`, `harnessNavigator.setFilter`,
   `harnessNavigator.clearFilters`, `harnessNavigator.copyArtifactId`,
   `harnessNavigator.copyArtifactPath`, соответствующие `menus`
   (`view/title` для sort/filter/clear, `view/item/context` для copy-действий,
   `commandPalette`-видимость только для осмысленных команд) и
   `configuration`-секцию `harnessNavigator.artifacts.sortOrder`,
   `...filter.status`, `...filter.type`, `...filter.priority`,
   `...filter.phase` со `scope: "resource"`/`"window"` по смыслу и enum-ами,
   совпадающими с machine enums STEP (`planned | in_progress | blocked |
   completed | deferred | cancelled`, типы STEP) — сами enum-значения не
   локализуются. Записывать preferences только через
   `workspace.getConfiguration(...).update(..., ConfigurationTarget.Workspace)`:
   это единственное допустимое persistent состояние по ADR-004, canonical
   Harness files не затрагиваются. Все новые titles/descriptions/placeholders/
   empty states завести парами в `package.nls.json` + `package.nls.ru.json` и
   `l10n/bundle.l10n.json` + `l10n/bundle.l10n.ru.json`; English остаётся
   fallback, canonical ID и enum в значениях bundle не появляются (это уже
   проверяет `tests/unit/localization.test.ts`).

4. **Artifacts View.** Реализовать `src/views/artifactsView.ts` с
   `vscode.TreeDataProvider`, зарегистрированным через существующий
   `LifecycleRegistry` в `activate()` тем же стилем, что и текущие команды.
   Верхний уровень — группы STEP/REQ/ADR/OQ; при нескольких valid Harness
   roots верхний уровень — узлы workspace folder, а группы становятся вторым
   уровнем, чтобы multi-root изоляция оставалась видимой. Leaf item: `label`
   = ID, `description` = title, `tooltip` = ID + title + status + relative
   path, `iconPath` — `ThemeIcon` по kind, `contextValue` для
   context-меню, `command` = `vscode.open` с `Uri.file(artifact.file)`
   (`Artifact.file` уже абсолютный и проверенный индексом, дополнительного
   containment-слоя не добавлять). Copy-действия пишут только в
   `vscode.env.clipboard` (ID или relative path). Провайдер подписывается на
   `onDidChangeProjectModel` и на `workspace.onDidChangeConfiguration` для
   своей секции и вызывает `onDidChangeTreeData`; подписки регистрируются в
   реестре. Empty state — локализованный `TreeView.message` (нормальное
   отсутствие артефактов, невалидный/не-Harness root и активный фильтр,
   скрывший всё, различаются текстом), чтобы recoverable состояние было
   диагностируемым и не ломало остальной UI. Команды sort/filter открывают
   обычный `showQuickPick` со значениями из contributions и сохраняют выбор
   в workspace settings; `clearFilters` сбрасывает все четыре ключа фильтра,
   не трогая sort order.

5. **Focus View и `Harness: Go to Artifact`.** `src/views/focusView.ts`
   переиспользует тот же snapshot и ту же подписку на изменения, отображая
   три локализованные группы (active STEP, blocked STEP, open OQ) с теми же
   item-семантикой и open-поведением; при пустом наборе — локализованный
   message, а не искусственный «следующий шаг». `Harness: Go to Artifact`
   (`src/commands/goToArtifact.ts`) собирает кандидатов по всем valid roots
   через view model и показывает `showQuickPick` с `label` = ID,
   `description` = title, `detail` = kind (+ имя root при multi-root) и
   опциями `matchOnDescription: true`, `matchOnDetail: true` — fuzzy-поиск по
   ID/title/kind обеспечивает штатный VS Code matcher, собственный алгоритм
   не писать. Выбор открывает canonical Markdown через `vscode.open`;
   отсутствие артефактов даёт локализованное сообщение, а не пустой picker.

6. **Тесты и реальные gates.** В `tests/unit/` добавить `node:test` покрытие
   view model: группировка и порядок kind, каждый sort order (включая
   отсутствующее поле и стабильность), каждый фильтр и их комбинация,
   `clearFilters`, отбор Focus View (in_progress/blocked/open OQ и пустой
   набор), формирование Quick Pick кандидатов и multi-root разделение.
   Расширить `tests/unit/localization.test.ts`-контракт новыми обязательными
   ключами (типизированный registry message keys, как в artifact
   diagnostics). В `src/test/integration/extension.test.ts` добавить сценарий
   Extension Host на существующем multi-root fixture: команды views
   зарегистрированы, дерево отдаёт ожидаемые элементы для `valid-project`,
   изменение fixture-артефакта обновляет дерево без restart (с тем же
   watcher-или-`Harness: Refresh` recovery-паттерном, что уже используется),
   применённый фильтр и последующий `clearFilters` наблюдаемо меняют выдачу и
   сохраняются в workspace settings, `Harness: Go to Artifact` открывает
   ожидаемый файл, а empty state виден на root без артефактов; проверки
   выполняются в обоих EN/RU запусках. Для наблюдаемости добавить узкий
   read-only test seam в `src/extension.ts` в духе уже существующего
   `getActiveArtifactSnapshot`, не раскрывая внутреннее состояние providers.
   Перед независимым review выполнить фактические `yarn typecheck`,
   `yarn lint`, `yarn format`, `yarn test:unit`, `yarn test:integration`,
   `yarn build`, `yarn package`, `python3 .harness/tools/validate.py --mode
   manual`, `python3 .harness/tools/sync-projections.py --check` и
   `git diff --check`, фиксируя только реально полученное evidence.

## Evidence

Implementation steps 4-6 (Artifacts View, Focus View, `Harness: Go to Artifact`,
copy commands, view model tests, localization, Extension Host tests)
реализованы поверх уже готовых steps 1-3 (`onDidChangeProjectModel`,
`src/views/artifactViewModel.ts`, package.json contributions/nls). Новые
файлы: `src/views/viewMessages.ts`, `src/views/artifactTreeItem.ts`,
`src/views/artifactsView.ts`, `src/views/focusView.ts`,
`src/commands/goToArtifact.ts`, `src/commands/copyArtifact.ts`,
`tests/unit/artifactViewModel.test.ts`. Изменённые файлы: `src/extension.ts`
(регистрация providers/tree views/commands + узкие read-only test seams
`getArtifactsViewSnapshot`/`getFocusViewSnapshot`/`getActiveTreeViewMessages`/
`getArtifactsViewChangeEventCount`/`getArtifactsViewArtifactNodes`),
`src/views/artifactViewModel.ts` (добавлены canonical enum-константы
`STEP_STATUS_VALUES`/`STEP_TYPE_VALUES`/`STEP_PRIORITY_VALUES` для filter
command), `l10n/bundle.l10n.json`/`l10n/bundle.l10n.ru.json`,
`tests/unit/localization.test.ts` (новый required-keys test для
`VIEW_MESSAGE_VALUES`), `src/test/integration/extension.test.ts` (новый
Extension Host сценарий на `valid-project` из существующего multi-root
fixture, plus `withQuickPickAnswers`/`withInputBoxAnswer` test helpers).

### STEP FIX по `STEP REVIEW` `planning/reviews/STEP-004/REVIEW-20260923T053851Z.md` (verdict: fail)

Исправлены все findings обязательного `reviewer` (F-001..F-006) и все
findings обязательного `tests` reviewer (1-5 в тексте review), без
переработки архитектуры и без выхода за Scope/Mutation policy STEP-004.

- **F-001 (evidence, high)** — `status: planned → in_progress` действительно
  внесён этим implementation-проходом (не унаследован от planning-фазы, как
  ошибочно утверждал предыдущий Evidence) и по
  `.harness/docs/EXECUTION_PROTOCOL.md` §9 п.3 требовал регенерации
  проекций. Выполнено: `python3 .harness/tools/sync-projections.py`
  (обновил `planning/PLAN.md`, `planning/STATUS.md`); `--check` и
  `validate.py --mode manual` теперь оба exit 0 (см. ниже). Прежний
  ошибочный блок "Blocker" убран из этого раздела.
- **F-002 (implementation, medium)** — `Harness: Set Filter`/`Harness: Clear
  Filters` спрашивали root, но писали `ConfigurationTarget.Workspace`
  (workspace-wide), поэтому per-root изоляция была фиктивной. Исправлено по
  простому/безопасному варианту из review: root-picker (`pickValidFolder`)
  убран из обеих команд; `filter.*` читается/пишется без resource-scope;
  `harnessNavigator.artifacts.filter.*` в `package.json` переведены с
  `scope: "resource"` на `scope: "window"` (как у `sortOrder`). Покрыто
  Extension Host сценарием (`config().get('filter.status')` без какого-либо
  `Uri` видит то же значение, что записала команда).
- **F-003 (implementation, medium)** — `PRIORITY_RANK` был plain object
  литерал: `priority: toString` резолвился в унаследованный
  `Object.prototype.toString` вместо `undefined`, ломая total order через
  `NaN`. Исправлено: `PRIORITY_RANK` теперь строится на `Object.create(null)`
  и читается через `Object.hasOwn(...)` (`priorityRank(...)` helper).
  Добавлен unit test с `priority: 'toString'`/`'constructor'`, подтверждающий
  стабильный tail-порядок и воспроизводимость.
- **F-004 (implementation, low)** — RU-перевод `filteredEmpty` ссылался на
  английское `"Harness: Clear Filters"`, которого нет в RU command palette
  (`Harness: Очистить фильтры`). Исправлено переформулировкой сообщения без
  буквального имени команды (EN: "Clear the active filter to see them all.";
  RU: "Очистите фильтр, чтобы увидеть все артефакты.") — и в
  `src/views/viewMessages.ts`, и в обоих `l10n/bundle.l10n*.json`.
- **F-005 (implementation, low)** — `clearFilters` писал явный `null` в
  четыре filter-ключа вместо удаления ключей. Исправлено: `config.update(key,
  undefined, ...)` для всех четырёх ключей и для "Any"/пустого `phase` в
  `pickFilterValue` (новый `FilterValuePick` различает "cancelled" и "clear
  → undefined"). Extension Host тест дополнительно проверяет byte-level
  отсутствие `filter.status`/`filter.phase` в settings JSON после
  `clearFilters`.
- **F-006 (implementation, low, coverage gaps от test reviewer)** —
  добавлены: (a) Extension Host проверка `copyArtifactId`/`copyArtifactPath`
  с реальным tree node (новый seam `getArtifactsViewArtifactNodes`) и
  реальным `vscode.env.clipboard`; (b) cancellation-пути `showQuickPick` для
  `setSortOrder`/`setFilter` (на выборе поля и на выборе значения); (c)
  `phase`-фильтр через `showInputBox` (новый `withInputBoxAnswer` helper):
  установка значения, пустой ввод → clear, Escape → cancel; (d) fallback
  `readSortOrder` на невалидном значении настройки; (f) доказательство, что
  `workspace.onDidChangeConfiguration` реально триггерит
  `onDidChangeTreeData` (новый read-only counter seam
  `getArtifactsViewChangeEventCount`, а не только что `getChildren()`
  напрямую возвращает новые данные). (e) — ветка `>1 valid root` обоих tree
  providers — оставлена документированным gap, как и предлагал review: общий
  multi-root fixture содержит только один valid Harness root, и добавление
  второго затронуло бы существующие STEP-001..STEP-003 assertions по числу
  root; это вне Scope этого STEP FIX.

Findings независимого `tests` reviewer (текст review, не F-нумерация):

1. `filteredEmpty` теперь реально проверяется отдельным сценарием: STEP-only
   fixture (REQ/ADR/OQ временно удалены — они всегда проходят STEP-only
   filter, см. `matchesFilter`) с фильтром, не совпадающим ни с одним STEP;
   assert на `getActiveTreeViewMessages().artifacts === filteredEmptyMessage`
   (в обоих EN/RU прогонах, так как suite целиком запускается дважды).
2. `computeEmptyState` теперь единственный источник истины: её сигнатура
   изменена с `(totalArtifacts: number, filter)` на `(artifacts: readonly
   Artifact[], filter)` и она реально фильтрует переданные artifacts вместо
   того, чтобы просто проверять "есть ли активный filter key" (у прежней
   реализации `computeEmptyState(3, {status:'blocked'})` возвращала
   `'filteredEmpty'`, даже если результат после filter был бы непустым — это
   была расходящаяся с `matchesFilter`, буквально неверная семантика).
   `ArtifactsTreeDataProvider.computeMessage` теперь вызывает эту функцию
   напрямую (artifacts агрегируются across valid roots — суммарный
   filtered/unfiltered count конкатенированного массива равен сумме per-root
   count, поэтому агрегация не меняет наблюдаемое поведение), вместо
   собственного parallel-расчёта.
3. Добавлен Extension Host тест на "ни один root не valid Harness project":
   временная порча единственного valid root fixture (`valid-project`)
   делает весь workspace без valid roots (три остальных fixture root уже
   заведомо невалидны), assert на `noHarnessProject` message в обоих Artifacts
   View и Focus View.
4. Добавлены unit-тесты: `buildQuickPickCandidates` с одним из двух roots
   без артефактов (пустой root не ломает candidates другого root);
   `groupArtifacts` на пустом массиве (все группы пустые, порядок сохранён).
5. Добавлен unit test `matchesFilter` для STEP без `status` при активном
   `status` filter (исключается) и без активного filter (не исключается).

Дополнительно (минимальный supporting cleanup, не самостоятельный scope):
`pickFolderPlaceholder` ключ в `viewMessages.ts`/`l10n/bundle.l10n*.json`
удалён — стал mёртвым после удаления root-picker из `runSetFilter`/
`runClearFilters` (F-002).

Команда: `yarn typecheck`
Exit code: 0
Observed: без вывода (все три tsconfig — `tsconfig.json`, `tsconfig.unit.json`,
`tsconfig.test.json` — прошли `tsc --noEmit` без ошибок).

Команда: `yarn lint`
Exit code: 0
Observed: без вывода (eslint над `src`, `tests`, `esbuild.js`,
`eslint.config.mjs`, `.vscode-test.mjs` не нашёл ошибок).

Команда: `yarn format`
Exit code: 0
Observed:
```
Checking formatting...
All matched files use Prettier code style!
```

Команда: `yarn test:unit`
Exit code: 0
Observed: `tests 88`, `pass 88`, `fail 0`, `cancelled 0`, `skipped 0`, `todo 0`,
`duration_ms 271.072448`. Новые/изменённые тесты в
`tests/unit/artifactViewModel.test.ts`: `sortArtifacts по priority не
резолвит untrusted значения в Object.prototype (F-003)`, переписанный
`computeEmptyState различает populated/noArtifacts/filteredEmpty` (новая
сигнатура) + новый `computeEmptyState игнорирует filter для не-STEP
artifacts`, `matchesFilter исключает STEP без status, когда активен status
filter`, `buildQuickPickCandidates: один из нескольких roots без артефактов
не ломает выдачу других roots`, `groupArtifacts на пустом массиве artifacts
...` — прошли в общем прогоне вместе с существующими STEP-001/STEP-002/
STEP-003 unit tests.

Команда: `yarn test:integration`
Exit code: 0
Observed (два runner-прогона — EN и RU locale, оба `8 passing`):
```
    ✔ обнаруживается по своему manifest id
    ✔ активируется и возвращает наблюдаемый результат активации (66ms)
    ✔ изолирует multi-root project states и регистрирует diagnostics command
    ✔ команда refresh пересобирает derived state без записи workspace
    ✔ watcher обновляет artifact и manifest state без restart, refresh не меняет bytes (447ms)
    ✔ Artifacts View/Focus View: команды, дерево, sort/filter/clearFilters, Go to Artifact и empty state (961ms)
    ✔ Artifacts View/Focus View: noHarnessProject empty state, когда ни один root не valid (53ms)
    ✔ deactivate безопасно вызывается и идемпотентен
  8 passing (2s)
```
(второй прогон: те же 8 тестов, `8 passing (2s)`, `watcher...` 477ms,
`Artifacts View/Focus View...` 881ms). Новый `getArtifactsViewArtifactNodes`/
`getArtifactsViewChangeEventCount` test seams используются только этим
Extension Host сценарием (read-only, не раскрывают internal provider state
сверх уже публичных `TreeItem`/event count). После каждого прогона
`git status --porcelain -- src/test/fixtures` подтверждён чистым, но
byte-restore `multi-root.code-workspace` в `finally` остаётся load-bearing,
а не defensive-only (второй review-раунд это подтвердил): сценарий четыре
раза пишет `sortOrder` через `ConfigurationTarget.Workspace` для проверки
sort/fallback/cancellation-путей, и до этого исправления последний из этих
`update()` в конце sortOrder-блока записывал явное значение `'id'` вместо
того, чтобы удалять ключ, поэтому committed fixture перед restore реально
содержала `"settings": {"harnessNavigator.artifacts.sortOrder": "id"}`.
Исправлено: этот финальный `update('sortOrder', 'id', ...)` заменён на
`update('sortOrder', undefined, ...)` (`src/test/integration/extension.test.ts`
~470) — ключ теперь удаляется, а не перезаписывается значением, совпадающим
с default; `config().get('sortOrder')` при отсутствующем ключе возвращает
default `'id'`, поэтому последующая cancellation-проверка не меняет
поведение. Byte-restore в `finally` сохранён как defensive safety net на
случай других незавершённых записей/падения теста в середине сценария, а не
потому что он необходим для sortOrder-пути конкретно.

Новый сценарий проверяет дополнительно к прежнему: `copyArtifactId`/
`copyArtifactPath` с реальным tree node пишут в `vscode.env.clipboard`
(F-006a); `workspace.onDidChangeConfiguration` реально триггерит
`onDidChangeTreeData` (F-006f, через `getArtifactsViewChangeEventCount`);
fallback `readSortOrder` на невалидном значении настройки откатывается на
`'id'` (F-006d); cancellation `showQuickPick` для `setSortOrder`/`setFilter`
на выборе поля и на выборе значения ничего не пишет (F-006b); `phase` filter
через `showInputBox` — установка/пустой ввод (clear)/Escape (cancel)
(F-006c); `filteredEmpty` state на STEP-only fixture с непересекающимся
filter (test reviewer finding 1); `noHarnessProject` message, когда ни один
root не valid (новый отдельный test, test reviewer finding 3). Multi-root
разделение (`buildQuickPickCandidates`, `groupArtifacts` на пустом root)
отдельно покрыто unit-тестами (test reviewer finding 4) — общий fixture
по-прежнему содержит только один valid Harness root, поэтому root-уровень
`ArtifactsTreeDataProvider`/`FocusTreeDataProvider` (>1 valid root) Extension
Host сценарием не покрыт (F-006e, документированный gap — вне Scope).

Команда: `yarn build`
Exit code: 0
Observed: без вывода (production esbuild bundle собран успешно,
`dist/extension.js`).

Команда: `yarn package`
Exit code: 0
Observed:
```
 DONE  Packaged: vscode-harness-navigator-0.0.1.vsix (10 files, 33.8 KB)
```
(включает `dist/extension.js`, `package.nls*.json`, `l10n/bundle.l10n*.json`).

Команда: `python3 .harness/tools/sync-projections.py`
Exit code: 0
Observed:
```
UPDATED
- planning/PLAN.md
- planning/STATUS.md
```
Причина (F-001): `status: planned → in_progress` в frontmatter этого STEP —
mutation, внесённая этим implementation-проходом, — требовала регенерации
canonical roadmap/status проекций (`.harness/docs/EXECUTION_PROTOCOL.md` §9
п.3). Regeneration через `sync-projections.py`, а не ручное редактирование
`planning/PLAN.md`/`planning/STATUS.md`.

Команда: `python3 .harness/tools/sync-projections.py --check`
Exit code: 0
Observed:
```
PASS
```

Команда: `python3 .harness/tools/validate.py --mode manual`
Exit code: 0
Observed:
```
WARNINGS:
  - planning: STEP-001: ready plan context_basis is stale
  - planning: STEP-008: ready plan context_basis is stale
HARNESS VALIDATION: PASS (259 tracked files checked, mode=manual)
```
Остаточные `STEP-001`/`STEP-008` "ready plan context_basis is stale"
warnings — pre-existing, не относятся к STEP-004 и не влияют на exit code.

Команда: `git diff --check`
Exit code: 0
Observed: без вывода (whitespace errors отсутствуют).

### Второй fix-review цикл

Второй `STEP REVIEW STEP-004` (immutable report
`planning/reviews/STEP-004/REVIEW-20260923T060500Z.md`) подтвердил F-001..F-006
первого раунда устранёнными и обязательный `tests` reviewer вернул PASS, но
дал FAIL по двум новым findings:

- **F-001 (evidence)** — абзац Evidence про byte-restore `multi-root.code-workspace`
  был неточен: restore фактически load-bearing, а не defensive-only. Причина:
  sortOrder-блок сценария (`src/test/integration/extension.test.ts`, тогда
  ~470) в конце писал `config().update('sortOrder', 'id', ...)` — явное
  значение, совпадающее с default, вместо удаления ключа, поэтому committed
  fixture перед restore реально содержала `sortOrder: "id"` в `settings`.
  Исправлено: `update('sortOrder', 'id', ...)` → `update('sortOrder',
  undefined, ...)`; `config().get('sortOrder')` при отсутствующем ключе
  по-прежнему возвращает default `'id'`, поэтому последующая
  cancellation-проверка (`sortOrderBeforeCancel`) не изменилась. Абзац Evidence
  выше переписан с точной причиной.
- **F-002 (orphan l10n key)** — `pickFolderPlaceholder`-строка
  (`"Select a Harness workspace root"`) была удалена из `viewMessages.ts`, но
  осталась висячим ключом в `l10n/bundle.l10n.json:39` и
  `l10n/bundle.l10n.ru.json:38`, ничем не используемая (`grep` по `src/`/`tests/`
  подтверждает отсутствие ссылок). Удалена из обоих bundle.

Повторный полный прогон gates после этих двух правок (заменяет предыдущие
записи выше как актуальный результат):

Команда: `yarn typecheck` — exit 0, без вывода.
Команда: `yarn lint` — exit 0, без вывода.
Команда: `yarn format` — exit 0, `All matched files use Prettier code style!`.
Команда: `yarn test:unit` — exit 0, `tests 88`, `pass 88`, `fail 0`.
Команда: `yarn test:integration` — exit 0, два runner-прогона (EN и RU), оба
`8 passing`; после прогона `git status --porcelain -- src/test/fixtures` пуст.
Команда: `yarn build` — exit 0, без вывода.
Команда: `yarn package` — exit 0, `Packaged: vscode-harness-navigator-0.0.1.vsix
(10 files, 33.77 KB)`.
Команда: `python3 .harness/tools/validate.py --mode manual` — exit 0,
`HARNESS VALIDATION: PASS (259 tracked files checked, mode=manual)` (те же
pre-existing STEP-001/STEP-008 warnings).
Команда: `python3 .harness/tools/sync-projections.py --check` — exit 0, `PASS`.
Команда: `git diff --check` — exit 0, без вывода.

## Blocker / Failure reason

—
