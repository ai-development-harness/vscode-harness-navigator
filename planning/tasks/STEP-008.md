---
schema: 1
id: STEP-008
status: completed
type: bugfix
priority: high
phase: project-model
depends_on:
  - STEP-001
requirements:
  - REQ-002
  - REQ-008
adrs:
  - ADR-001
  - ADR-005
architecture_refs:
  - "docs/architecture.md#security-boundaries"
risk_flags:
  - architecture
  - security-sensitive
plan:
  status: ready
  revision: 3
  context_basis: sha256:1b396e3dc3c51beb723bd972e0f3b64254783607081c589400729249afc01cfc
  content_hash: sha256:5a274a58665148d6413e6864f0abb83441defbb368201b46e974892b9a55578d
  reviewed_report: planning/plan-reviews/STEP-008/PLAN-REVIEW-20260921T195800Z.md
  planned_at: 2026-09-21T19:59:43+00:00
---

# STEP-008 — Кросс-платформенное no-follow containment чтение manifest и полнота localization regression

## Goal

Устранить два подтверждённых дефекта независимого review `STEP-002`
(`planning/reviews/STEP-002/REVIEW-20260921T184919Z.md`, F-009 и F-010), из-за
которых `STEP-002` заблокирован исчерпанным deterministic FIX/REVIEW budget:
валидный Harness workspace должен достигать состояния `valid` на всех
заявленных platform, а regression test production localization keys обязан
детерминированно ловить удаление любого ключа независимо от того, как этот
ключ формируется.

## Context

`STEP-002` реализовал `detectProject`/`readBoundedManifest`
(`src/projectModel/manifestService.ts`) для read-only определения Harness
workspace. Deterministic repair budget этого STEP
(`.harness/manifest.yaml → execution.maxFixReviewCycles: 3`) исчерпан после
трёх успешных FIX-циклов (F-001–F-008), поэтому дальнейшее исправление F-009 и
F-010 не может продолжаться внутри orchestration `STEP RUN STEP-002` и
оформляется как corrective STEP по паттерну `EXECUTION_PROTOCOL.md` §23
(`current STEP blocked by corrective STEP`). `STEP-002` остаётся
заблокированным до завершения этого STEP.

`assertReliableNoFollowSupport()` (`src/projectModel/manifestService.ts:437`)
сейчас безусловно бросает `ManifestContainmentError` для любого
`process.platform !== 'linux'`, а `detectProject()` преобразует эту ошибку в
`configurationBlocked` с сообщением о выходе manifest за границы workspace —
хотя реальная причина в другом, а `package.json` (`engines.vscode`) не
ограничивает поддерживаемую OS и `docs/architecture.md` не описывает
Linux-only продукт. В результате корректный пустой Harness 0.6.0+ workspace на
macOS/Windows никогда не достигает `valid`, что нарушает Acceptance REQ-002.

Первая версия этого плана предлагала считать портируемую `dev/ino` identity
проверку (`assertOpenedManifestContained`,
`src/projectModel/manifestService.ts:442-459`) достаточной заменой Linux-only
`/proc/self/fd/<fd>` re-derivation на любой platform. Независимый
planning-review (`planning/plan-reviews/STEP-008/PLAN-REVIEW-20260921T193300Z.md`,
F-001/F-002) экспериментально опроверг это: `dev/ino` ловит подмену
**финального** path component, но не ловит гонку с подменой **промежуточного**
ancestor directory между containment check и `open` — это ловит только
canonical-path re-derivation открытого descriptor, а portable (без native
addon) эквивалента `/proc/self/fd` на macOS/Windows не существует
(`/dev/fd` на macOS — не symlink на target, а отдельный `fdesc`-механизм;
настоящий API — `fcntl(F_GETPATH)`, которого Node `fs` не экспонирует;
POSIX-специфичные open-флаги вроде `O_NOFOLLOW`/`O_NONBLOCK` на `win32` в
`node:fs` не определены вовсе). Это — реальное инженерное ограничение, а не
исправимый в коде баг, поэтому platform-scoped containment guarantee
зафиксирована отдельным решением владельца проекта:
`docs/adr/ADR-005-platform-scoped-manifest-containment.md`. Implementation
plan ниже реализует именно эту ADR, а не более раннюю (опровергнутую) идею
полного паритета.

Отдельно, `tests/unit/manifestService.test.ts:100`
(`production diagnostic keys присутствуют в English и Russian bundles`)
извлекает production localization keys только regex-ом по прямым вызовам
`diagnostic(...)`. Ключи `Harness manifest must be a regular file.`
(`src/projectModel/manifestService.ts:385,407`) и
`Harness manifest exceeds {0} bytes.` (`:418`) создаются как `message` в
`ManifestInputError` и попадают в `diagnostic()` только динамически, в
catch-блоке — regex их не видит. Удаление любого из этих двух ключей из
bundle сейчас не ломает test.

## Scope

- Реализовать containment guard в `src/projectModel/manifestService.ts` по
  platform-scoped модели `ADR-005`: портируемая (все platform) защита от
  статического symlink и от подмены финального path component остаётся
  безусловной; дополнительная защита от гонки на промежуточном ancestor
  directory остаётся Linux-specific (`/proc/self/fd/<fd>`); на platform без
  этой re-derivation (macOS, Windows) корректный проект достигает `valid`,
  а не `configurationBlocked` по неверной причине — остаточный риск узкого
  race-сценария принят явно `ADR-005`, а не скрыт.
- Сделать platform capability (какие open-флаги реально применены, доступна
  ли canonical-path re-derivation) наблюдаемой типизированной структурой, а
  не подразумеваемой из `process.platform`/`constants.*` в разных местах —
  чтобы unit-тесты могли инъецировать её целиком и детерминированно
  проверять поведение под каждым profile, включая тот, что соответствует
  реальному Windows (нет `O_NOFOLLOW`, нет `O_NONBLOCK`, нет re-derivation).
- Собрать все производимые этим слоем production localization message,
  включая создаваемые через `ManifestInputError`, в единый источник (registry
  или эквивалентную детерминированную проверку), который `tests/unit/manifestService.test.ts`
  использует для полной, не хрупкой сверки с `l10n/bundle.l10n.json` и
  `l10n/bundle.l10n.ru.json`.
- Добавить/расширить capability-injection unit tests для valid-project path
  и хотя бы один real observable (Extension Host или эквивалентный) test,
  покрывающий ветку `ManifestInputError` (`must be a regular file` или
  `exceeds {0} bytes`).
- Обновить `Blocker / Failure reason` и, при необходимости, Evidence
  `planning/tasks/STEP-002.md`, зафиксировав, что F-009/F-010 закрыты этим
  corrective STEP.

## Mutation policy

### Allowed

- `src/projectModel/manifestService.ts` и его unit/integration tests.
- `l10n/bundle.l10n.json`, `l10n/bundle.l10n.ru.json` в объёме, необходимом
  для полноты regression-проверки (без добавления новых пользовательских
  строк сверх уже используемых).
- `planning/tasks/STEP-002.md` — только поле `Blocker / Failure reason` и
  ссылка на закрытие F-009/F-010; Scope/Acceptance/Goal `STEP-002` не менять.
- `docs/adr/ADR-005-platform-scoped-manifest-containment.md` и обратная
  ссылка на неё в `docs/requirements/REQ-002-project-detection-and-compatibility.md`
  уже созданы во время planning этого STEP (не во время implementation) —
  фиксируют platform-scoped containment decision, на котором строится этот
  Implementation plan; дальнейшие правки этих файлов вне scope, если не
  найдено фактическое расхождение с реализацией.

### Conditional

- Точечное изменение `docs/architecture.md#security-boundaries`, только
  если Implementation plan не сможет реализовать `ADR-005` буквально и
  потребуется уточнить формулировку security boundary без изменения самого
  решения.

### Forbidden

- Любое расширение product scope за пределы F-009/F-010 (новые artifact
  paths, parsing STEP/REQ/ADR, command graph, UI).
- Ослабление portable (все platform) защиты от статического symlink и от
  подмены финального path component — эта защита не зависит от `ADR-005` и
  не platform-scoped.
- Реализация полного паритета с Linux на macOS/Windows через native addon —
  явно отклонено `ADR-005` как отдельное, более тяжёлое решение.
- Изменение `package.json` (`engines`/`os`) — `ADR-005` явно сохраняет
  extension universal; ограничение поддерживаемых OS сюда не входит.
- Скрытая смена Accepted `ADR-001`/`ADR-005` или REQ-002 без отдельного
  ADR/REQ процесса.

## Out of scope

- Любые новые findings, не относящиеся к F-009/F-010.
- Roadmap-функциональность `STEP-003`+.

## Acceptance criteria

- На **любой** заявленной platform (Linux/macOS/Windows) корректный пустой
  Harness 0.6.0+ workspace достигает typed состояния `valid`, а не
  `configurationBlocked` — по `ADR-005`, без platform gate на этом пути.
- Portable (все platform) защита от статического symlink вне root и от
  подмены финального path component во время open не ослаблена нигде,
  включая symlink-swap regression из F-008 на Linux.
- Дополнительная защита от гонки на промежуточном ancestor directory
  остаётся действующей на Linux (через canonical-path re-derivation) без
  изменений в наблюдаемом поведении; на platform без re-derivation её
  отсутствие — задокументированный по `ADR-005` остаточный риск, а не
  скрытая деградация.
- Platform capability (какие open-флаги применены, доступна ли
  re-derivation) наблюдаема тестами через инъекцию всей capability-структуры
  целиком (не только `process.platform`), включая профиль, буквально
  соответствующий реальному Windows (`O_NOFOLLOW`/`O_NONBLOCK` недоступны,
  re-derivation недоступна).
- Regression test детерминированно падает при удалении **любого**
  production diagnostic key этого слоя из `l10n/bundle.l10n.json` или
  `l10n/bundle.l10n.ru.json`, включая ключи, создаваемые через
  `ManifestInputError`, и при добавлении в код **нового** необрегистрированного
  message literal — сверка типа компилятором (`yarn typecheck`), а не только
  unit test.
- Хотя бы один real observable test покрывает ветку `ManifestInputError`
  (`must be a regular file` или `exceeds {0} bytes`) целиком, а не только
  прямые вызовы `diagnostic()`.
- `planning/tasks/STEP-002.md` фиксирует, что F-009 и F-010 закрыты этим STEP.

## Verification

- `yarn typecheck`, `yarn lint`, `yarn format`, `git diff --check`.
- `yarn test:unit` — полный unit suite, включая capability-injection tests
  (доказывающие поведение под каждым platform profile без реального
  non-Linux раннера) и типизированный localization-registry regression test.
- `yarn test:integration` вне sandbox (EN/RU Extension Host, реальный Linux
  раннер этой сессии) — доказывает Linux-ветку и `ManifestInputError` real
  observable test; не доказывает и не заявляется как доказательство
  macOS/Windows поведения (это доказывается только capability-injection
  unit-тестами по `ADR-005`).
- `yarn build`, `yarn package`.
- `python3 .harness/tools/validate.py --mode manual`.

## Deliverables

- Platform-scoped (по `ADR-005`) containment reader в `manifestService.ts` с
  наблюдаемой typed platform capability structure.
- Типизированный, не хрупкий localization message registry и regression test
  для production diagnostic keys этого слоя.
- Capability-injection unit tests, доказывающие Linux/macOS/Windows profile
  без реальных non-Linux раннеров.
- Обновлённое поле `Blocker / Failure reason` `STEP-002.md`.

## Implementation plan

### F-009 — Platform-scoped containment чтение manifest (по `ADR-005`)

Текущий `src/projectModel/manifestService.ts`:

- `assertReliableNoFollowSupport()` (:437) безусловно бросает
  `ManifestContainmentError`, если `process.platform !== 'linux'`.
- `assertOpenedManifestContained()` (:442-459) доказывает identity/containment
  открытого descriptor через `realpathSync('/proc/self/fd/<fd>')` (ловит
  подмену **промежуточного ancestor** во время open — Linux-only) и через
  `currentPathStats = lstatSync(manifestPath)` vs `dev/ino` fstat-нутого
  descriptor (ловит подмену **финального** path component — портируемо,
  не зависит от platform; это единственная часть, реально закрывающая
  symlink-swap regression F-008, что подтвердил planning-review).
- Флаги открытия собираются как `constants.O_RDONLY | constants.O_NONBLOCK |
  constants.O_NOFOLLOW` (:400-403); `x | undefined` в JS даёт `x | 0`, поэтому
  на platform без какой-либо из этих констант она беззвучно исчезает без
  какого-либо наблюдаемого сигнала.

Изменения — единая injectable capability вместо разрозненных
`process.platform`/`constants.*` проверок:

1. Ввести чистую функцию
   `resolveManifestOpenCapability(platform: NodeJS.Platform, posixConstants: { O_NOFOLLOW?: number; O_NONBLOCK?: number }): ManifestOpenCapability`,
   где
   ```ts
   interface ManifestOpenCapability {
     readonly noFollowFlag: number | undefined;   // O_NOFOLLOW, если реально доступен
     readonly nonBlockFlag: number | undefined;    // O_NONBLOCK, если реально доступен (F-006 guard)
     readonly deriveOpenedPath: ((descriptor: number) => string) | undefined; // canonical-path re-derivation
   }
   ```
   - `noFollowFlag`/`nonBlockFlag` берутся из `posixConstants.O_NOFOLLOW`/`O_NONBLOCK`
     ТОЛЬКО если они не `undefined` — без bitwise OR с возможным `undefined`.
   - `deriveOpenedPath` определена только для `platform === 'linux'`
     (`(fd) => realpathSync('/proc/self/fd/${fd}')`). **Для `darwin` и любой
     другой platform, включая `win32`, — `undefined`.** Ранняя версия этого
     плана предполагала `/dev/fd` как эквивалент на macOS; planning-review
     (F-002) экспериментально показал, что `/dev/fd` на macOS не является
     symlink на target (это отдельный `fdesc`-механизм; настоящий API —
     недоступный из Node `fcntl(F_GETPATH)`), поэтому такая ветка **не
     реализуется** — macOS относится к той же категории, что и Windows.
   - Реализация обязана быть чистой функцией без обращения к реальным
     `process`/`fs` — только через параметры — чтобы unit-тест мог
     сконструировать capability для любого сценария, включая тот, что
     буквально соответствует Windows (`{}` — оба флага и constants
     отсутствуют).
2. `readBoundedManifest`/`assertOpenedManifestContained` принимают уже
   готовый `ManifestOpenCapability` (не `platform`, не сырые `constants`)
   как параметр:
   - open flags собираются явной функцией, которая добавляет
     `capability.noFollowFlag`/`nonBlockFlag` в composed flags только если
     они определены (никакого `| undefined`);
   - `assertOpenedManifestContained` всегда выполняет портируемую dev/ino
     identity проверку (без изменений в логике) — это единственное, что
     обязано работать одинаково на любой capability;
   - если `capability.deriveOpenedPath` определена, дополнительно требовать
     `isContained(realRoot, capability.deriveOpenedPath(descriptor))`, как
     сегодня на Linux;
   - если `capability.deriveOpenedPath === undefined`, **не** бросать
     `ManifestContainmentError` только по этой причине — по `ADR-005` это
     осознанно принятый остаточный риск, а не пропущенная проверка; рядом
     оставить короткий комментарий со ссылкой на
     `docs/adr/ADR-005-platform-scoped-manifest-containment.md`.
3. Убрать `assertReliableNoFollowSupport()` полностью (вместе с её
   безусловным throw) — она перестаёт быть нужна: platform gate заменён
   capability-based flag composition из шага 1-2.
4. `detectProject` вызывает `resolveManifestOpenCapability(process.platform,
   constants)` один раз с реальными `process`/`constants` — единственная
   точка входа реального (не тестового) platform/constants значения в этот
   слой.
5. Не менять public поведение `detectProject` для `ManifestContainmentError`/
   `ELOOP` (тот же `configurationBlocked` с тем же diagnostic) — это
   по-прежнему покрывает финальный-component swap и static outside-root
   symlink на любой platform.

Capability-injection tests (`tests/unit/manifestService.test.ts`), полностью
заменяющие «симулированный platform»-подход из первой версии плана:

- unit test на `resolveManifestOpenCapability` с синтетическими
  `(platform, posixConstants)` для `'linux'` (оба flag + `deriveOpenedPath`
  определены), `'darwin'` (flags определены — POSIX системный вызов
  поддерживает `O_NOFOLLOW`/`O_NONBLOCK`, но `deriveOpenedPath === undefined`)
  и `'win32'` (оба flag и `deriveOpenedPath` — `undefined`, поскольку Node
  документирует эти POSIX-константы как неопределённые на win32). Тест не
  трогает реальный `process.platform` и не читает реальный `constants`
  модуль — оба входа синтетические, поэтому Linux-раннер не может дать
  ложный результат для не-Linux веток (устраняет F-004).
- существующий symlink-swap regression (F-008) продолжает проходить на
  реальной Linux capability (`resolveManifestOpenCapability(process.platform,
  constants)`) без изменений в наблюдаемом поведении.
- новый test: под capability с `deriveOpenedPath: undefined` (буквально
  Windows/macOS profile) валидный manifest fixture проходит `detectProject`
  до состояния `valid` — закрывает F-009 без реального non-Linux раннера.
- новый test: под той же capability подмена **финального** path component
  (F-008-style symlink swap) всё равно детерминированно даёт
  `ManifestContainmentError` через dev/ino mismatch — доказывает, что
  portable-часть защиты не зависит от `deriveOpenedPath`.
- явно **не** писать тест, утверждающий защиту от подмены **промежуточного**
  ancestor под capability с `deriveOpenedPath: undefined` — по `ADR-005` это
  принятый остаточный риск, а не гарантия; ложно-подтверждающий тест здесь
  был бы хуже отсутствия теста.

### F-010 — Типизированный, структурно полный localization registry

Planning-review (F-005/F-006) показал: простой `readonly string[]` registry
чинит текущую regression, но не мешает будущему разработчику добавить новый
`diagnostic('X', 'New message.')` без регистрации — unit-тест этого не
поймает, и класс дефекта F-010 воспроизводится в обратную сторону. Registry
обязан быть источником **типа**, а не только значения.

1. Определить единый map констант с ТОЛЬКО теми литералами, что реально
   доходят до пользователя через `diagnostic(...)`/`vscode.l10n.t` (F-006
   scope guard — исключает internal-only `ManifestContainmentError`
   messages, которые никогда не покидают эту функцию и не входят в l10n
   bundles):
   ```ts
   const DIAGNOSTIC_MESSAGES = {
     manifestAbsent: 'Harness manifest is absent.',
     manifestUnreadable: 'Harness manifest cannot be read.',
     manifestOutsideRoot: 'Manifest resolves outside of the workspace root.',
     manifestNotObject: 'Harness manifest must contain an object.',
     manifestNotRegularFile: 'Harness manifest must be a regular file.',
     manifestExceedsSize: 'Harness manifest exceeds {0} bytes.',
     manifestUnparsable: 'Harness manifest cannot be parsed.',
     missingRequiredField: 'Harness manifest is missing a required field: {0}.',
     unsupportedSchema: 'Harness manifest schema is not supported: {0}.',
     invalidRelease: 'Harness manifest contains an invalid release: {0}.',
     unsupportedRelease: 'Harness release is not supported: {0}.',
     configuredPathBlocked: 'A configured path is blocked by workspace containment.',
     manifestValid: 'Harness manifest is valid.',
   } as const;
   type DiagnosticMessage = (typeof DIAGNOSTIC_MESSAGES)[keyof typeof DIAGNOSTIC_MESSAGES];
   export const PRODUCTION_DIAGNOSTIC_MESSAGES: readonly DiagnosticMessage[] =
     Object.values(DIAGNOSTIC_MESSAGES);
   ```
   (Свериться с фактическим текущим набором call sites `diagnostic(...)` при
   реализации — список выше составлен по текущему `manifestService.ts` и
   должен быть точным, а не приблизительным.)
2. Типизировать параметр `message` у `diagnostic()` как `DiagnosticMessage`
   (не `string`) — незарегистрированный литерал перестаёт компилироваться.
3. Типизировать конструктор `ManifestInputError` тем же `DiagnosticMessage` и
   сохранить его в `readonly diagnosticMessage: DiagnosticMessage` (не
   полагаться на унаследованное `Error.message: string`, которое теряет
   литеральный тип); в catch-блоке `detectProject` использовать
   `diagnostic('InvalidManifest', error.diagnosticMessage, error.messageArguments)`.
   После этого добавление нового `diagnostic(...)`/`ManifestInputError` с
   незарегистрированным текстом ломает `yarn typecheck`, а не только unit
   test — устраняет F-005 структурно, а не через дисциплину.
4. В `tests/unit/manifestService.test.ts` заменить regex-экстракцию
   (`/diagnostic\([^,]+,\s*'([^']+)'/gu`) на импорт
   `PRODUCTION_DIAGNOSTIC_MESSAGES` и проверку каждого значения в
   `l10n/bundle.l10n.json` и `l10n/bundle.l10n.ru.json`.
5. Добавить/расширить real observable test (Extension Host EN и/или RU),
   который триггерит именно `ManifestInputError`-ветку — например, создаёт
   manifest fixture, являющийся FIFO/directory (`manifestNotRegularFile`)
   или превышающий `MAXIMUM_MANIFEST_SIZE_BYTES` (`manifestExceedsSize`),
   запускает `harnessNavigator.showDiagnostics` и наблюдает тот же
   локализованный текст, что записан в Output Channel — по аналогии с
   существующим EN/RU test для invalid release.

### Обновление STEP-002

После прохождения Verification этого STEP обновить
`planning/tasks/STEP-002.md → Blocker / Failure reason`, зафиксировав закрытие
F-009 и F-010 (Blocker `STEP-002` уже содержит forward-ссылку на `STEP-008`;
после этого STEP corrective work закрыт, но возобновление `STEP RUN STEP-002`
и его собственный independent review остаются отдельным действием вне scope
этого STEP).

## Evidence

- Command: `yarn typecheck`
  Exit code: `0`
  Observed: без output (успешный `tsc --noEmit`); подтверждает, что
  `diagnostic()`/`ManifestInputError` теперь типизированы `DiagnosticMessage`
  и незарегистрированный literal не компилируется.

- Command: `yarn lint`
  Exit code: `0`
  Observed: без output (ESLint не нашёл нарушений).

- Command: `yarn format`
  Exit code: сначала `1` (`[warn] src/projectModel/manifestService.ts` —
  требовалось Prettier форматирование после ручных правок), после
  `npx prettier --write src/projectModel/manifestService.ts` повторный
  запуск дал `0` (`All matched files use Prettier code style!`). После
  форматирования `yarn typecheck` и `yarn lint` повторно подтверждены `0`.

- Command: `git diff --check`
  Exit code: `0`
  Observed: без output (whitespace-ошибок не обнаружено).

- Command: `yarn test:unit`
  Exit code: `0`
  Observed: `tests 29`, `pass 29`, `fail 0`. Включает новые
  `resolveManifestOpenCapability даёт правильный profile для каждой platform`,
  `production diagnostic keys присутствуют в English и Russian bundles`
  (переписан на `PRODUCTION_DIAGNOSTIC_MESSAGES`),
  `корректный проект достигает valid под capability без deriveOpenedPath (ADR-005)`
  и `подмена финального component symlink-ом блокируется и под capability без
  deriveOpenedPath`; существующий F-008 regression
  (`подмена manifest внешним symlink перед open не читает внешний target`)
  прошёл без изменений в наблюдаемом поведении.

- Command: `yarn test:integration`
  Exit code: `0`
  Observed: запущен вне sandbox в этой же сессии (реальный Linux раннер, не
  требовал rerun из-за EROFS/IPC — в отличие от истории STEP-002, здесь
  ограничение песочницы не проявилось). Оба launch profile (`integration-en`,
  `integration-ru`) — `4 passing` каждый (4 workspace folders после добавления
  `non-regular-manifest-project`), `Exit code: 0`. Тест
  `изолирует multi-root project states и регистрирует diagnostics command`
  прошёл на обеих locale, включая новую assertion на `ManifestInputError`
  branch (`manifestNotRegularFile`, локализованный текст в Output Channel).

- Command: `yarn build`
  Exit code: `0`
  Observed: без output (esbuild bundle собран без ошибок).

- Command: `yarn package`
  Exit code: `0`
  Observed: `DONE  Packaged: vscode-harness-navigator-0.0.1.vsix (10 files, 23.97 KB)`;
  `dist/extension.js [51.32 KB]` включён в VSIX.

- Command: `python3 .harness/tools/validate.py --mode manual`
  Exit code: сначала `1` (`HARNESS VALIDATION: FAIL` — `projection drift:
  planning/PLAN.md`, `projection drift: planning/STATUS.md` после
  `status: in_progress` в frontmatter STEP-008), после
  `python3 .harness/tools/sync-projections.py` (`UPDATED` —
  `planning/PLAN.md`, `planning/STATUS.md`) повторный запуск дал
  `HARNESS VALIDATION: PASS (216 tracked files checked, mode=manual)`.
  Наблюдаемые warnings (`STEP-001: ready plan context_basis is stale`,
  `STEP-002: ready plan context_basis is stale`) — pre-existing состояние
  других STEP, не относящееся к scope этого STEP, и не блокирует `PASS`.

### FIX pass — `planning/reviews/STEP-008/REVIEW-20260921T202606Z.md` (verdict `fail`)

Исправлены F-001 и F-002 (required), а также F-003 и F-004 (optional) из
independent review. Production-код `src/projectModel/manifestService.ts` не
менялся — только `tests/unit/manifestService.test.ts` (5 новых unit tests) и
точечная правка формулировки `docs/adr/ADR-005-platform-scoped-manifest-containment.md
→ Security implications` (узкий conditional case Mutation policy: фактическое
расхождение точности формулировки с `Decision §1`, найденное review).

Новые tests в `tests/unit/manifestService.test.ts`:

- `подмена промежуточного ancestor (.harness) на symlink перед open
  блокируется реальной Linux capability (ADR-005)` (F-001) — через
  существующий `beforeOpen` seam подменяет именно `.harness` (промежуточный
  ancestor, не финальный component) на symlink во внешний каталог с
  `manifest.yaml`, под реальной (не инъецированной) Linux capability; тест
  падает, если `assertOpenedManifestContained`'s `deriveOpenedPath`-ветка
  (`src/projectModel/manifestService.ts:537-542`) удалена или обессилена —
  единственный сценарий, отличающий её от портируемого `dev`/`ino` check.
- `.harness/manifest.yaml как статический symlink на внешний файл
  блокируется под Windows-shaped capability (F-002)` и одноимённый тест под
  macOS-shaped capability — делают сам `manifest.yaml` статическим symlink
  на внешний valid manifest (не configured path — другая функция) и
  проверяют `configurationBlocked` без утечки внешнего `release` через
  `messageArguments`/`detail`.
- `корректный проект достигает valid под macOS-shaped capability без
  deriveOpenedPath (ADR-005, F-003)` и `подмена финального component
  symlink-ом блокируется и под macOS-shaped capability без deriveOpenedPath
  (F-003)` — вводят `DARWIN_LIKE_CAPABILITY` (реальные POSIX-флаги текущего
  раннера + `deriveOpenedPath: undefined`) и покрывают буквальный macOS
  profile end-to-end, а не только чистую `resolveManifestOpenCapability`.

Явно не написан зеркальный assertion ancestor-race protection под non-Linux
capability — по `ADR-005` это принятый остаточный риск, а не гарантия.

- Command: `python3 .harness/tools/planning-state.py review-revision`
  Exit code: `0`
  Observed: `git_head 65d3401f5010c6a2a19dce7931a57ba890a5461c` — совпадает с
  `reviewed_revision.git_head` проверяемого review (worktree_hash закономерно
  изменился после правок FIX pass).

- Command: `yarn typecheck`
  Exit code: `0`
  Observed: без output.

- Command: `yarn lint`
  Exit code: `0`
  Observed: без output.

- Command: `yarn format`
  Exit code: `0`
  Observed: `All matched files use Prettier code style!` (проверено дважды —
  после добавления unit tests и после правки `ADR-005`).

- Command: `git diff --check`
  Exit code: `0`
  Observed: без output.

- Command: `yarn test:unit`
  Exit code: `0`
  Observed: `tests 34`, `pass 34`, `fail 0` (29 pre-existing + 5 новых из
  этого FIX pass, перечисленных выше).

- Command: `python3 .harness/tools/validate.py --mode manual`
  Exit code: `0`
  Observed: `HARNESS VALIDATION: PASS (216 tracked files checked,
  mode=manual)`. После правки `ADR-005` появился дополнительный warning
  `STEP-008: ready plan context_basis is stale` (ожидаемо — `context_basis`
  зафиксирован до этой правки того же STEP, тот же класс pre-existing
  warning, что уже был у `STEP-001`/`STEP-002`); `PASS` не нарушен, новых
  projection-drift или structural ошибок нет.

`yarn test:integration`/`yarn build`/`yarn package` не перезапускались в этом
FIX pass — изменения ограничены unit-тестами одного модуля и doc-only правкой
`ADR-005`, не затрагивающими Extension Host, bundling или packaging surface
(per задача FIX: перезапуск требуется только при изменении
integration-test-relevant файлов).

## Blocker / Failure reason

—
