---
schema: 1
id: STEP-002
status: completed
type: implementation
priority: high
phase: project-model
depends_on:
  - STEP-001
requirements:
  - REQ-001
  - REQ-002
  - REQ-008
adrs:
  - ADR-001
  - ADR-006
architecture_refs:
  - "docs/architecture.md#system-context"
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#security-boundaries"
risk_flags:
  - architecture
  - security-sensitive
plan:
  status: ready
  revision: 2
  context_basis: sha256:c46a73370d3feb0de37422a79750f884e987b1089d6906ac7d2ef270a397da80
  content_hash: sha256:191c75071dab3ac122e6f4c09370be3dfc5c6e479997a9cc2d569d9bb4a868c0
  reviewed_report: planning/plan-reviews/STEP-002/PLAN-REVIEW-20260922T063035Z.md
  planned_at: 2026-09-22T06:31:26+00:00
---

# STEP-002 — Определение проекта и чтение manifest

## Goal

Реализовать изолированное определение Harness workspace root, compatibility states и manifest-driven configuration.

## Context

Artifact parsing допустим только после доказуемого валидного manifest. При этом обычная папка, пустой проект и project-level incompatibility имеют разный UX.

## Scope

- Реализовать detection и manifest service для каждого workspace root.
- Проверить minimum release 0.6.0, поддерживаемую schema и configured paths.
- Implement containment validation для каждого resolved configured path относительно owning workspace root.
- Создать typed states для non-Harness, invalid, unsupported и valid empty project.
- Добавить command `Harness: Show Diagnostics` для details project detection state и стабильную taxonomy producer ошибок этого слоя.
- Покрыть detection и manifest cases tests.

## Mutation policy

### Allowed

- Source и tests слоя Harness detection/manifest.
- Локализованные messages и diagnostics, принадлежащие этому слою.

### Conditional

- Изменения базовой activation wiring, если это минимально нужно для регистрации project state.

### Forbidden

- Hardcoded fallback artifact paths, legacy parsing, auto migration/update Harness.
- Чтение за границами workspace по configured path, Git history, запуск tools Harness или mutation workspace.

## Out of scope

- Parsing STEP, REQ, ADR, OQ и построение views.
- Command graph и navigation providers.

## Acceptance criteria

- Каждый workspace root определяется по `.harness/manifest.yaml` и получает отдельное typed состояние.
- Версия ниже 0.6.0, malformed manifest и unsupported schema дают локализуемые диагностируемые состояния без legacy fallback.
- Все будущие artifact paths доступны только из успешно прочитанного manifest.
- Absolute, traversal и symlink configured path за пределами owning workspace root не читаются и формируют configuration blocker.
- `Harness: Show Diagnostics` раскрывает details detection/configuration state, используя stable categories этого слоя.
- Unit и integration tests наблюдаемо проверяют ordinary, invalid, unsupported и valid empty workspace.
- Tests проверяют containment для normal, absolute, traversal и symlink configured path.

## Verification

- Реальные `typecheck`, `lint` и targeted tests STEP-002.
- Extension Host integration scenario для нескольких workspace roots.
- Targeted containment and diagnostics command tests.

## Deliverables

- Detection/manifest services, project state model, localized diagnostics и tests.

## Implementation plan

1. **Модель состояния и taxonomy.** Сохранить `projectState.ts` как единственную
   discriminated-union модель `nonHarness`, `invalidManifest`, `unsupportedVersion`,
   `unsupportedSchema`, `configurationBlocked` и `valid`. `manifestService.ts` должен
   производить stable categories (`NotHarnessProject`, `InvalidManifest`,
   `UnsupportedHarnessVersion`, `UnsupportedSchema`, `ConfigurationBlocked`,
   `UnexpectedInternalError`) и registry `DIAGNOSTIC_MESSAGES`; UI локализует только
   message/key arguments через `vscode.l10n.t`. Не добавлять persistent state, dispatch
   или fallback paths.
2. **Manifest read boundary и compatibility.** Для каждого owning workspace root читать
   только `.harness/manifest.yaml`, ограничивая input размером и regular-file проверкой до
   YAML parsing. Проверять `harness.version` отдельно от SemVer `harness.release >= 0.6.0`;
   malformed/missing input, unsupported schema/release и I/O преобразовывать в typed state
   без исключения наружу, legacy parsing, migration или запуска Harness tools.
3. **Platform-scoped containment по ADR-006.** До чтения доказывать containment реального
   manifest и каждого configured path; absolute, traversal и static symlink за пределы root
   должны оставаться `configurationBlocked`. Использовать единую injectable
   `ManifestOpenCapability`: portable pre-open realpath и post-open `dev`/`ino` identity
   check действуют везде, а canonical re-derivation descriptor (`/proc/self/fd`) — только
   на Linux. На macOS/Windows отсутствие re-derivation не блокирует корректный проект и
   остаётся явно ограниченным ADR-006 residual risk; native addon не добавлять.
4. **Derived workspace diagnostics.** `ProjectStateService` хранит только in-memory state,
   изолированный по URI каждого root. Единственная команда `Harness: Show Diagnostics`
   выводит локализованные summary и безопасные technical details в Output Channel `Harness
   Navigator`, ничего не выполняя и не изменяя workspace; registrations остаются у
   существующего lifecycle owner. Не создавать artifact parsing, views, watchers или
   command catalog из будущих STEP.
5. **Наблюдаемое доказательство текущей реализации.** Подтвердить unit tests для ordinary,
   malformed, SemVer/schema, valid empty, normal/absolute/traversal/static-symlink paths,
   final-component swap и Linux ancestor race. Capability-injection tests обязаны покрывать
   Linux/macOS/Windows-shaped profiles, включая отсутствие POSIX flags на Windows; registry
   должен делать удаление любого production localization key и новый literal TypeScript
   error. Real EN/RU Extension Host tests проверяют multi-root isolation, diagnostics command
   и ветку `ManifestInputError`. Перед review выполнить реальные `typecheck`, `lint`,
   `format`, unit/integration tests, build/package, `git diff --check`, Harness validation и
   синхронизацию projections; Evidence дополнять только фактическим output.

## Evidence

- `yarn typecheck` — exit code 0; strict TypeScript-проверка production, unit и Extension Host test configs прошла.
- `yarn lint` — exit code 0; ESLint не выявил нарушений в затронутом коде.
- `yarn format` — exit code 0; форматирование source, tests и localization bundles соответствует Prettier.
- `yarn test:unit` — exit code 0; 17 tests прошли, включая ordinary, malformed, unsupported release/schema, valid empty и normal/absolute/traversal/symlink containment.
- `yarn test` — exit code 0; unit suite и два реальных Extension Host запуска (English/Russian) прошли, по 4 integration tests; multi-root workspace изолирован, `harnessNavigator.showDiagnostics` зарегистрирована и возвращает derived states.
- `yarn build` — exit code 0; production bundle собран.
- `yarn package` — exit code 0; VSIX `vscode-harness-navigator-0.0.1.vsix` собран.
- `python3 .harness/tools/validate.py` — exit code 0; `HARNESS VALIDATION: PASS (216 tracked files checked, mode=manual)`.
- `git diff --check` — exit code 0; ошибок whitespace не обнаружено.
- `yarn typecheck` — exit code 0; после исправления F-001—F-004 strict TypeScript-проверка прошла.
- `yarn lint` — exit code 0; ESLint не выявил нарушений в затронутом manifest/diagnostics коде.
- `yarn test:unit` — exit code 0; 22 tests прошли, включая SemVer prerelease/build metadata,
  missing release, `UnexpectedInternalError`, oversized и deeply nested manifest.
- `yarn test:integration` — exit code 0; два реальных Extension Host запуска (English/Russian),
  по 4 tests; diagnostics command наблюдаемо вернула ту же локализованную строку, что записана
  в Output Channel.
- `python3 .harness/tools/validate.py --mode manual` — exit code 0; `HARNESS VALIDATION: PASS
  (216 tracked files checked, mode=manual)`.
- `yarn typecheck`, `yarn lint`, `yarn format`, `yarn test:unit`, `yarn build` и
  `yarn package` — exit code 0 на current ADR-006 revision; unit suite: 34 passing.
- `yarn test:integration` — exit code 0 вне sandbox: English и Russian Extension Host
  выполнили по 4 passing tests; sandbox-only EROFS при создании VS Code socket не является
  product failure и воспроизведённый вне sandbox run прошёл.
- `python3 .harness/tools/validate.py --mode manual`,
  `python3 .harness/tools/sync-projections.py --check` и `git diff --check` — каждый exit
  code 0 на current revision.
- `STEP FIX STEP-002` F-012: `yarn typecheck`, `yarn lint`, `yarn format`,
  `yarn test:unit` (35/35), `yarn build`, `yarn package`, Harness validation,
  projection check и `git diff --check` — exit code 0. `yarn test:integration` вне sandbox:
  English и Russian Extension Host выполнили по 4 passing tests. Direct и nested dangling
  configured-path symlink теперь детерминированно возвращают `configurationBlocked`.
- `yarn typecheck`, `yarn lint`, `yarn format` и `git diff --check` — каждый exit code 0; strict
  types, ESLint, Prettier и whitespace gate подтверждают исправления F-007/F-008.
- `yarn test:unit` — exit code 0; 26 tests прошли, включая сверку всех production diagnostic
  keys с EN/RU bundles и детерминированную подмену manifest внешним symlink перед `open`.
- `yarn test:integration` — exit code 0 вне sandbox; English и Russian Extension Host выполнили
  по 4 passing tests. Diagnostics command наблюдаемо локализует invalid release `banana` в RU.
- `yarn package` — exit code 0; production VSIX содержит оба runtime localization bundle.
- `python3 .harness/tools/validate.py --mode manual` — exit code 0; `HARNESS VALIDATION: PASS
  (216 tracked files checked, mode=manual)`.
- `yarn test:unit` — exit code 0; 24 tests прошли после исправления F-005/F-006, включая
  malformed SemVer (`banana`, ведущий ноль) и изолированный FIFO probe с timeout 1 s.
- `yarn typecheck` / `yarn lint` / `yarn format` / `yarn build` — каждый exit code 0; изменённые
  manifest service и unit tests проходят статические, стилевые и production bundle проверки.
- `git diff --check` — exit code 0; ошибок whitespace не обнаружено после исправления F-005/F-006.
- `python3 .harness/tools/validate.py --mode manual` — exit code 0; `HARNESS VALIDATION: PASS
  (216 tracked files checked, mode=manual)`.
- `STEP REVIEW STEP-002` (`planning/reviews/STEP-002/REVIEW-20260922T065700Z.md`): independent
  verdict `PASS`. F-012 (dangling configured-path symlink проходил containment) закрыт по
  существу: `resolveContainedPath` в `src/projectModel/manifestService.ts` использует
  `lstatSync` вместо `existsSync` для ancestor-поиска, поэтому dangling symlink считается
  существующим, а fail-closed `realpathSync` отклоняет его вместо восхождения к contained
  parent. Независимый probe (8 сценариев configured path) и adversarial manifest probe (13
  недоверенных входов) не выявили regression. `yarn typecheck`, `yarn lint`, `yarn format`,
  `yarn test:unit` (35/35), `yarn test:integration` (English/Russian Extension Host, по 4
  passing), `yarn build`, `yarn package`, `python3 .harness/tools/validate.py --mode manual`,
  `python3 .harness/tools/sync-projections.py --check` и `git diff --check` — каждый exit code
  0 на reviewed revision (`git_head=65d3401f5010c6a2a19dce7931a57ba890a5461c`).

## Blocker / Failure reason

Заблокирован: независимый `STEP REVIEW STEP-002`
(`planning/reviews/STEP-002/REVIEW-20260921T184919Z.md`) вернул `FAIL` с
findings F-009 (валидный workspace недостижим вне Linux) и F-010 (неполное
покрытие localization regression), а deterministic FIX/REVIEW budget
(`execution.maxFixReviewCycles: 3`) уже исчерпан тремя выполненными циклами.
Дальнейшее исправление вынесено в corrective STEP `STEP-008` по паттерну
`EXECUTION_PROTOCOL.md` §23 (`current STEP blocked by corrective STEP`);
F-009 и F-010 закрыты реализацией `STEP-008`
(`planning/tasks/STEP-008.md`): containment reader переведён на
platform-scoped модель `docs/adr/ADR-005-platform-scoped-manifest-containment.md`
через injectable `ManifestOpenCapability`/`resolveManifestOpenCapability`
(F-009), а production diagnostic messages собраны в типизированный registry
`DIAGNOSTIC_MESSAGES`/`PRODUCTION_DIAGNOSTIC_MESSAGES`, делающий
незарегистрированный message literal ошибкой `yarn typecheck` (F-010).
Возобновление `STEP RUN STEP-002` и его собственный independent review
остаются отдельным действием вне scope `STEP-008`.
`STEP-002` возобновляется после закрытия `STEP-008`.

Разрешено: возобновлённый independent `STEP REVIEW STEP-002`
(`planning/reviews/STEP-002/REVIEW-20260922T064041Z.md`) вернул `FAIL` по новой
находке F-012 (dangling configured-path symlink проходил containment).
Corrective fix применён напрямую в scope STEP-002 (не потребовал отдельного
corrective STEP): `resolveContainedPath` теперь использует `lstatSync` вместо
`existsSync`, что делает dangling symlink fail-closed. Повторный independent
`STEP REVIEW STEP-002` (`planning/reviews/STEP-002/REVIEW-20260922T065700Z.md`)
вернул `PASS` без material findings. STEP более не заблокирован.
