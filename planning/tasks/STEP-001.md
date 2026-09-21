---
schema: 1
id: STEP-001
status: completed
type: implementation
priority: high
phase: foundation
depends_on: []
requirements:
  - REQ-001
  - REQ-008
  - REQ-010
adrs:
  - ADR-001
  - ADR-004
architecture_refs:
  - "docs/architecture.md#system-context"
  - "docs/architecture.md#deployment-runtime-assumptions"
risk_flags:
  - architecture
plan:
  status: ready
  revision: 1
  context_basis: sha256:b5de417446faf8102fa1cacae0b1f379e9baa7173ee3b62ab76649a20ea29494
  content_hash: sha256:09b13bd57a31f2a31907b6709e5cb780d6d88e16216c274fb05aa984d785ce58
  reviewed_report: planning/plan-reviews/STEP-001/PLAN-REVIEW-20260921T143700Z.md
  planned_at: 2026-09-21T14:37:25+00:00
---

# STEP-001 — Базовый каркас расширения и toolchain

## Goal

Создать минимальный production-ready каркас TypeScript VS Code extension с локализацией и проверяемым toolchain без реализации product-функций Navigator.

## Context

В репозитории отсутствует application code и package tooling. Последующие STEP нуждаются в общей extension lifecycle, localization boundary и реальных commands для проверки.

## Scope

- Настроить Yarn-проект, strict TypeScript, официальный VS Code Extension API, production bundling, ESLint и Prettier.
- Создать минимальную activation/deactivation основу, disposable lifecycle и RU/EN localization resources.
- Настроить unit и integration test foundations с реальными scripts lint, typecheck, test, build и package.

## Mutation policy

### Allowed

- Новые source, test, configuration и package files расширения.
- Документация разработки, необходимая фактическому toolchain.

### Conditional

- Минимальные dependencies только после проверки их необходимости для VS Code API, YAML parsing, bundling или tests.

### Forbidden

- Реализация artifact parsing, command catalog, navigation providers или выполнение Harness-команд.
- Сетевые, telemetry, shell или persistent project-state integrations.

## Out of scope

- Полные Views, индексы и language providers.
- Product-specific CI beyond commands, которые реально создаёт этот STEP.

## Acceptance criteria

- TypeScript compile работает в strict mode, а package содержит production bundling, ESLint, Prettier и Yarn scripts для typecheck, lint, test, build и package.
- Extension корректно активируется и освобождает registrations без реализации command execution Harness.
- Пользовательские strings имеют RU и EN resources с English fallback; canonical Harness tokens не локализуются.
- Unit и integration test foundations запускаются реальными project scripts.

## Verification

- Реальные scripts `typecheck`, `lint`, `test`, `build` и `package`, созданные в этом STEP.
- Изолированная проверка Extension Host после появления integration harness.

## Deliverables

- VS Code extension manifest, TypeScript source skeleton, localization resources, test configuration и development documentation.

## Implementation plan

1. **Toolchain и package baseline.** Создать корневой Yarn-проект с manifest расширения VS Code (`name`, `publisher`, `engines.vscode`, `main`, `l10n`) и strict TypeScript (`strict: true`, включая `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`) с раздельными конфигурациями для source и tests. Зафиксировать минимальный `engines.vscode`, поддерживающий `vscode.l10n`, и выровнять с ним `@types/vscode`. Yarn настроить на `node-modules` linker: PnP несовместим с `@vscode/vsce` и загрузкой Extension Host в тестах. Подключить esbuild как production bundler (CommonJS, `--external:vscode`, minify, отдельный dev-режим с sourcemap), ESLint (typescript-eslint, type-aware) и Prettier без конфликтующих правил. Объявить реальные scripts `typecheck`, `lint`, `test`, `build`, `package` и зафиксировать lockfile.
2. **Extension lifecycle.** Реализовать единственную entrypoint-пару `activate`/`deactivate`: активация не читает workspace, не запускает процессы, не выполняет команды Harness и не создаёт product services. Ввести внутренний lifecycle-реестр, который регистрирует каждый собственный disposable через `ExtensionContext.subscriptions`; `deactivate` идемпотентен и не бросает исключения. Из `activate` возвращать минимальный test-observable результат (состояние активации и счётчик зарегистрированных disposables), чтобы disposal проверялся наблюдаемым поведением, а не приватным состоянием. Activation event выбрать нефункциональный (`onStartupFinished`); product commands, views и menus в `contributes` на этом STEP не добавлять. Настроить `.vscodeignore` так, чтобы в VSIX попадали только bundle, manifest, localization resources, README и LICENSE, но не sources, tests и `node_modules`.
3. **Localization boundary.** Ввести стандартный двухслойный механизм VS Code: `package.nls.json` (English default) + `package.nls.ru.json` для строк manifest и `l10n/bundle.l10n.json` + `l10n/bundle.l10n.ru.json` с доступом через `vscode.l10n.t` для runtime-строк. English остаётся fallback locale: отсутствующий русский ключ обязан давать английский текст, а не пустую строку или ключ. Canonical Harness IDs, enum-значения, имена команд, настроек и технические ключи не локализуются и не попадают в bundles как переводимые значения. Product views, providers, parsers, diagnostics taxonomy и каталог команд на этом STEP не создаются: закладывается только граница локализации.
4. **Test foundation.** Настроить два реально запускаемых слоя. Unit-слой — Node-процесс без Extension Host, покрывающий locale-independent код: паритет ключей `package.nls.*`/`bundle.l10n.*`, English fallback при отсутствующем русском ключе и поведение lifecycle-реестра (регистрация и освобождение). Integration-слой — изолированный Extension Host через `@vscode/test-electron`/`@vscode/test-cli`: получить расширение по его id, активировать, проверить наблюдаемый результат активации и корректное освобождение registrations. Fixtures минимальные и без Harness-артефактов; запрещено доказывать поведение только helper-моками вместо реальной активации. Оба слоя должны запускаться script-ом `test`; учесть, что integration-слою нужна локальная загрузка VS Code build при первом запуске.
5. **Документация и verification evidence.** Описать в `docs/development.md` фактические установку, запуск, отладку Extension Host, lint/format, структуру тестов и packaging — только команды, реально созданные этим STEP. Выполнить `typecheck`, `lint`, `test`, `build`, `package` и изолированную проверку Extension Host; зафиксировать в `## Evidence` для каждой проверки `Command`, `Exit code` и `Observed`, различая буквальный захваченный output и нормализованное резюме. Расхождение между объявленным и фактически работающим script-ом устранять до завершения STEP, не расширяя scope.

## Evidence

Все команды повторно выполнены после исправлений F-001—F-007 из
`planning/reviews/STEP-001/REVIEW-20260921T170700Z.md` (Node.js v24.21.0, Yarn 4.10.3 через
corepack, `node-modules` linker). Ниже `Observed` является нормализованным резюме фактического
вывода, кроме явно отмеченных коротких буквальных строк.

### `yarn typecheck`

- Command: `yarn typecheck` (`tsc --noEmit` для `tsconfig.json`, `tsconfig.unit.json` и `tsconfig.test.json`)
- Exit code: `0`
- Observed: strict TypeScript успешно проверил исходный код, unit и integration tests без emit.

### `yarn lint`

- Command: `yarn lint` (`eslint src tests esbuild.js eslint.config.mjs .vscode-test.mjs`)
- Exit code: `0`
- Observed: ESLint завершился без problems.

### `yarn format` (дополнительная проверка форматирования, не входит в обязательный список STEP, выполнена для полноты)

- Command: `yarn format`
- Exit code: `0`
- Observed (буквально): `Checking formatting...` / `All matched files use Prettier code style!`

### `yarn test` (unit + integration, как задекларировано в `package.json#scripts.test`)

- Command: `yarn test` (эквивалент `yarn test:unit && yarn test:integration`)
- Exit code: `0`
- Observed — unit-слой: `node --import tsx --test` выполнил 9 tests: `pass 9`, `fail 0`.
  Проверены единственный владелец lifecycle disposal, порядок и идемпотентность disposal,
  package-NLS parity, runtime bundle subset, намеренно отсутствующий русский fallback key и
  отсутствие canonical Harness tokens.

- Observed — integration-слой: два реальных изолированных Extension Host через
  `@vscode/test-cli`/`@vscode/test-electron`, VS Code `1.138.0` linux-x64, выполнены с
  `--locale en` и `--locale ru`; каждый завершился `3 passing` и `Exit code: 0`. Проверены
  локализованная runtime-строка через `vscode.l10n.t`, English fallback для отсутствующего
  русского ключа и переход счётчика registrations от положительного значения к нулю после
  `deactivate()`.

  При каждом запуске test-cli не смог получить remote index версий из-за network timeout, но
  детерминированно использовал уже установленную локальную VS Code `1.138.0`; оба реальных прогона
  завершились успешно.

### `yarn build` (production)

- Command: `yarn build` (`yarn clean && node esbuild.js --production`)
- Exit code: `0`
- Observed: `dist/extension.js` создан, минифицирован, без sourcemap (`dist/extension.js.map`
  отсутствует после production-сборки).

### `yarn package`

- Command: `yarn package` (`vsce package --no-dependencies`, production build запускается
  автоматически через `vscode:prepublish`)
- Exit code: `0`
- Observed (буквально):

  ```
  DONE  Packaged: vscode-harness-navigator-0.0.1.vsix (10 files, 6.19 KB)
  ```

  VSIX содержит только production bundle, manifest, localization resources, README и LICENSE — без
  sources, tests и `node_modules`, как того требует mutation policy. Сгенерированный `.vsix` удалён
  из рабочего дерева после проверки (не коммитится, см. `.gitignore`).

### Harness projections и validation

- Command: `python3 .harness/tools/sync-projections.py --json`
- Exit code: `0`
- Observed: синхронизированы производные `planning/PLAN.md` и `planning/STATUS.md`.

- Command: `python3 .harness/tools/validate.py --mode manual`
- Exit code: `0`
- Observed (буквально): `HARNESS VALIDATION: PASS (188 tracked files checked, mode=manual)`.

### FIX-2 после review `REVIEW-20260921T173001Z`

- Command: `rg -n "watch-режиме|one-shot сборка" docs/development.md esbuild.js`
- Exit code: `0`
- Observed: документация больше не обещает несуществующий watch-режим; она описывает
  фактическую one-shot `yarn build:dev` и необходимость повторной сборки после изменения исходников.

### Independent completion review

- Report: `planning/reviews/STEP-001/REVIEW-20260921T173400Z.md`
- Verdict: `PASS`
- Observed: новый независимый review подтвердил отсутствие material findings; обязательный
  test review прошёл (`9` unit tests и два Extension Host-прогона по `3 passing` для EN и RU).

## Blocker / Failure reason

—
