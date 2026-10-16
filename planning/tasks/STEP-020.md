---
schema: 1
id: STEP-020
status: completed
type: bugfix
priority: medium
phase: quality
depends_on: []
requirements:
  - REQ-007
  - REQ-008
  - REQ-010
adrs:
  - ADR-003
  - ADR-004
architecture_refs:
  - docs/architecture.md#reliability-observability
  - docs/architecture.md#deployment-runtime-assumptions
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:7a36a04bfb7b4ee822b9ebf24a52526271c1a7fc31e96029e1c2b143a0a2b1af
  content_hash: sha256:6a9db913f068b8a16081a4953db3abbfc7371f7c995974cc09fec088128e3c22
  reviewed_report: planning/plan-reviews/STEP-020/PLAN-REVIEW-20261016T122728Z.md
  planned_at: 2026-10-16T12:27:28+00:00
  execution_groups:
  context_components:
    - "ADR@ADR-003=sha256:c6e7568face977162198f40476e1f7133e1997ecb0832b106359851b68ada3a9"
    - "ADR@ADR-004=sha256:c330d03d6528ed06f2a7358105a5c4b0cfd03d7b5fd8115727ed877645466f03"
    - "ARCH@docs/architecture.md#deployment-runtime-assumptions=sha256:d709c51fbc087ff54157588d7e467d7e359987209f3e25082394fe8dd52b1a06"
    - "ARCH@docs/architecture.md#reliability-observability=sha256:22fa2b3ad8700563d8d66ed338aac4678a7ea85dbeb9818e306b48026501bf03"
    - "REQ@REQ-007=sha256:52a853b6d84f7edbe0d66ee29f93329a30e17172c562db23af29a4d2e8bf3541"
    - "REQ@REQ-008=sha256:4281092e2876a322e9dabbb553b43d63308151000103a1984a258213a2734748"
    - "REQ@REQ-010=sha256:2c5b88ed25fbc7a8a876cb634e0616c8781c0cc8a2d2c9bef7a3b5d339e126ae"
    - "STEP@STEP-020=sha256:d31395fb31bca64b78c48a0eefcf9e4741b67e0942ca3c4fc06833cf0cd49fc3"
---

# STEP-020 — Проверка названия команды при локализованном manifest VS Code

## Goal

Устранить падение integration-теста Command Catalog при объектном представлении локализованного command title в Extension Host, сохранив проверку фактического названия, category и меню.

## Context

В Evidence STEP-019 от 2026-10-04 зафиксировано падение `integration-ru` с установленным RU language pack: VS Code возвращает локализованный `title` объектом, а тест `openCommandDocumentation: manifest, палитра и меню` вызывает `declared.title.startsWith` как у строки. Дефект теста не исправлялся в scope графа STEP-019.

PROJECT RECONCILE от 2026-10-16 подтвердил, что в `src/test/integration/commandCatalog.test.ts` сохраняются приведение `title: string` и непосредственный вызов `startsWith`. Изолированное исполнение существующих assertions проходит для строки `Открыть документацию`, но даёт TypeError для `{ value: 'Открыть документацию', original: 'Open Documentation' }`. Это ограниченный reproducer assertions, а не новый запуск RU Extension Host; историческое наблюдение реального Host хранится в STEP-019.

Duplicate/overlap search не обнаружил отдельного незавершённого владельца этой находки. STEP-008 проверяет полноту diagnostic keys, STEP-014 — category/title, STEP-015 — пункт документации; все завершены. Новая задача исправляет regression test существующего поведения, не меняет продуктовый контракт. Новых prerequisite implementations нет: работа выполняется над текущим завершённым baseline.

## Scope

- Уточнить тестовую модель command contribution и обработку строкового и объектного локализованного title в указанном integration-тесте.
- Сохранить assertions для ожидаемого EN/RU текста, отсутствия префикса в title, наличия category и правильных menu contributions.
- Добавить минимальную regression-проверку обеих форм title и неверного текста, чтобы исправление не свелось к пропуску assertions.
- Проверить сценарий в реальном Extension Host с активным RU language pack и зафиксировать фактическую locale и форму title.

## Mutation policy

### Allowed

- `src/test/integration/commandCatalog.test.ts`.
- `planning/tasks/STEP-020.md` и generated evidence текущего STEP.

### Conditional

- Узкий helper в `src/test/integration/support/` и его regression test в `tests/unit/`, если это необходимо для проверки обеих форм без дублирования логики.
- `docs/development.md`, если требуется уточнить воспроизводимый запуск с установленным language pack.
- `.vscode-test.mjs` и test preparation scripts — только при доказанной необходимости изолировать RU-профиль; без установки language pack в пользовательский профиль и без новых зависимостей.
- Детерминированная пересборка projections.

### Forbidden

- Production-код `src/` за исключением явно разрешённых файлов `src/test/`.
- Изменение package contributions, пользовательских переводов, command semantics и границ ADR-008.
- Ослабление assertions, подмена RU-проверки English fallback, переписывание Evidence и REVIEW завершённых STEP.
- Обновление Harness, toolchain/dependencies, публикация и Git mutations.

## Out of scope

- Редизайн Command Catalog и Dependency Graph.
- Массовый рефакторинг тестов локализации и изменение product/architecture contracts.
- Повторная приёмка завершённой истории STEP из-за обновления Harness.

## Acceptance criteria

- Integration-тест принимает корректные строковый и объектный локализованные title без TypeError и проверяет фактический title выбранной locale.
- Некорректный title и запрещённый префикс продолжают приводить к падению проверки; category и меню проверяются как прежде.
- Regression-проверка покрывает обе формы и отрицательный сценарий, используя тот же путь проверки, что integration-тест.
- Тест `openCommandDocumentation: manifest, палитра и меню` проходит в EN и в реальном RU Extension Host с установленным language pack. Evidence фиксирует `vscode.env.language`, наличие language pack и наблюдаемую форму title; English fallback не считается RU proof.
- Остальные unit и integration suites проходят; production-поведение расширения и исторические completion proofs не изменены.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn test:integration`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: В изолированном Extension Host с RU language pack (установлен только в .vscode-test/extensions) выполнить integration-ru, включая тест openCommandDocumentation: manifest, палитра и меню; зафиксировать из лога vscode.env.language, наличие MS-CEINTL.vscode-language-pack-ru, форму и текст title и результат; отдельно подтвердить EN. Запуск с English fallback не считать доказательством RU. После проверки восстановить исходное содержимое .vscode-test/extensions.

## Deliverables

- Исправленный integration-тест и минимальная regression-проверка.
- Свежие Verification evidence и независимый schema-valid review для STEP-020.

## Implementation plan

### 1. Vscode-независимый helper нормализации и проверки command title

- Создать src/test/integration/support/commandTitle.ts по образцу stackAttribution.ts (без импорта vscode): тип ManifestCommandTitle = string | { value: string; original: string }; функция commandTitleText(title: unknown): string возвращает строку как есть, для объекта с string value возвращает value, для любой другой формы бросает AssertionError с описанием фактического значения вместо TypeError.
- Добавить assertCommandTitle(title: unknown, expected: string, forbiddenPrefix: string): проверяет через commandTitleText, что текст не начинается с forbiddenPrefix и строго равен expected (assert.equal с выводом фактического текста). Placeholder '%command.openCommandDocumentation.title%' больше не принимается: это нерезолвленный nls key, а Acceptance требует фактический title выбранной locale.
- Добавить describeCommandTitleForm(title: unknown): 'string' | 'localized-object' | 'unknown' для Evidence-лога формы title.

**Files:**
- src/test/integration/support/commandTitle.ts

**Risks:**
- Если реальный EN Host вернёт нерезолвленный placeholder, строгая проверка упадёт: это будет наблюдаемым дефектом локализации, а не поводом вернуть ослабление; зафиксировать в Evidence и остановиться с BLOCKED.

### 2. Regression unit-тест обеих форм и отрицательных сценариев

- Создать tests/unit/commandTitle.test.ts (node:test, как stackAttribution.test.ts), импортирующий helper из src/test/integration/support/commandTitle.
- Позитивные кейсы: строка 'Open Documentation' и 'Открыть документацию'; объект { value: 'Открыть документацию', original: 'Open Documentation' } проходят assertCommandTitle с соответствующим expected.
- Отрицательные кейсы (assert.throws AssertionError, не TypeError): неверный текст в строке и в объекте; title с префиксом 'Harness' в строке и в объекте; нерезолвленный placeholder; объект без string value, null/number.
- Проверить describeCommandTitleForm для string, объекта и unknown.

**Files:**
- tests/unit/commandTitle.test.ts

**Tests:**
- yarn test:unit

### 3. Перевести integration-тест на общий путь проверки

- В src/test/integration/commandCatalog.test.ts в тесте 'openCommandDocumentation: manifest, палитра и меню' заменить приведение title: string на title: unknown и заменить startsWith/сравнение на assertCommandTitle(declared.title, expected, 'Harness'), где expected = russian() ? 'Открыть документацию' : 'Open Documentation'.
- Сохранить assert.ok(declared.category), проверку commandPalette when === 'false' и групп navigation@1/navigation@2 без изменений.
- Добавить console.log для Evidence: vscode.env.language, наличие vscode.extensions.getExtension('MS-CEINTL.vscode-language-pack-ru') и describeCommandTitleForm(declared.title) с фактическим текстом.

**Files:**
- src/test/integration/commandCatalog.test.ts

**Tests:**
- yarn test:integration

### 4. Проверка в EN и реальном RU Extension Host

- Выполнить полный yarn test:integration в стандартном окружении (без language pack, integration-ru здесь — English fallback и RU proof не является).
- Зафиксировать исходное содержимое .vscode-test/extensions/extensions.json, установить русский language pack только в изолированный .vscode-test/extensions (через CLI скачанного test-VS Code с --extensions-dir, без пользовательского профиля и без изменения package.json/зависимостей), затем выполнить integration-ru и убедиться по логу, что vscode.env.language начинается с 'ru', language pack найден, форма title записана и тест PASS.
- После RU-проверки вернуть .vscode-test/extensions в исходное состояние и зафиксировать это в Evidence; если установка language pack невозможна (сеть/marketplace), STEP завершается BLOCKED, English fallback не засчитывается.
- Если воспроизводимая процедура запуска с language pack не описана в docs/development.md, добавить краткий раздел (conditional mutation).

**Files:**
- docs/development.md

**Risks:**
- Нужен сетевой доступ к marketplace для установки language pack.

### 5. Статические проверки и Evidence

- Выполнить yarn typecheck, yarn lint, yarn format, yarn test:unit, git diff --check, python3 .harness/tools/validate.py --mode manual.
- Записать в Evidence STEP-020 команды, exit codes и наблюдаемые факты (locale, наличие language pack, форма title) для EN и RU; production-код src/ вне src/test/ и package contributions не изменяются.

**Files:**
- planning/tasks/STEP-020.md

## Evidence


<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-10-16T12:34:46Z
- Status: PASS
- Automated resumed: true
- Git head: f5c8a98eff9f9afbd076c1367b09dd398faf80cc
- Worktree hash: sha256:3eb2ec72fa2485237198790f2c8c15147e84e1096776f080ce2931fbf34d455a
- Verification contract basis: sha256:cc8819c252eaa420587975f42708dbc523a87284e25097691ca6bafccc72f39c
- Verification context basis: sha256:2b1bb0e430fb0f9802c13bd92ab5474050b8f2af650cb336a1fccaf9a5cceef7
- Subject git head: f5c8a98eff9f9afbd076c1367b09dd398faf80cc
- Subject worktree hash: sha256:7c237feff26f2959b04b447f745032dbe39df2c3090fd857e82a2d906fa0ef3b
- Subject content hash: sha256:09c845461882c547cba6fa0df6f8238bd9a3a83fd2b1a0e84f7d367fe4594172

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4270
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5421
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
  - Duration ms: 7824
  - stdout sha256: 29efd69d8b165fa57028e8c15dcd75f09afb823f3cbf7750335e738efc55979b
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 25241
  - stderr bytes: 0
- Command: yarn test:integration
  - Status: PASS
  - Exit code: 0
  - Duration ms: 72431
  - stdout sha256: 50f370a220d56d3593f48418c679ff75f4e7d7cc201d4f753665962efb8e06b7
  - stderr sha256: 9370e927dbf4655c7eccd4937b4527374e7dd16804c2d2ffd48391f557ef0ab5
  - stdout bytes: 24726
  - stderr bytes: 22728
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
  - Duration ms: 5521
  - stdout sha256: 951011f04e6b23040f400c2deb5775963fe180849e41c9c3e628be0189b40f1c
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0

### Product verification
- none

### Manual verification
- Check: В изолированном Extension Host с RU language pack (установлен только в .vscode-test/extensions) выполнить integration-ru, включая тест openCommandDocumentation: manifest, палитра и меню; зафиксировать из лога vscode.env.language, наличие MS-CEINTL.vscode-language-pack-ru, форму и текст title и результат; отдельно подтвердить EN. Запуск с English fallback не считать доказательством RU. После проверки восстановить исходное содержимое .vscode-test/extensions.
  - Status: PASS
  - Observed: "VS Code 1.142.0 из .vscode-test. EN/стандартное окружение: yarn test:integration exit 0; integration-en и integration-ru по 23 passing, mvp-en/mvp-ru 33 passing + 1 pending; лог теста в обоих integration-профилях: language=en ruLanguagePack=false titleForm=string title=\"Open Documentation\" — integration-ru здесь English fallback и RU proof не является. RU: .vscode-test/vscode-linux-x64-1.142.0/bin/code --extensions-dir=.vscode-test/extensions --user-data-dir=.vscode-test/user-data --install-extension MS-CEINTL.vscode-language-pack-ru, exit 0, установлен ms-ceintl.vscode-language-pack-ru v1.131.2026090407. Первый yarn vscode-test --label integration-ru: exit 0, 23 passing, но language=en ruLanguagePack=true titleForm=string (languagepacks.json заполнился только при этом старте) — как RU proof не засчитан. Повторный запуск integration-ru: exit 0, 23 passing, '✔ openCommandDocumentation: manifest, палитра и меню', лог: language=ru ruLanguagePack=true titleForm=localized-object title={\"value\":\"Открыть документацию\",\"original\":\"Open Documentation\"}. Дополнительно mvp-ru с pack: exit 0, 33 passing, 1 pending. Восстановление: --uninstall-extension с теми же каталогами, удалены каталог pack и .obsolete, восстановлены исходные .vscode-test/extensions/extensions.json ('[]') и .vscode-test/user-data/languagepacks.json ('{}'); в .vscode-test/extensions остался только extensions.json. Логи: .harness/local/tmp/exec-8c0b78e6de684195a492c39fe72d4ffa/{integration-default,integration-ru-pack,integration-ru-pack-2,mvp-ru-pack}.log (temporary)."
<!-- VERIFICATION-EVIDENCE:END -->

- PROJECT RECONCILE 2026-10-16: изолированное исполнение текущих assertions через Node vm — строковый RU title PASS, локализованный объект FAIL с TypeError. Полный RU Extension Host в reconcile не запускался.
- Исторический реальный RU failure и принятый scope графа описаны в Evidence STEP-019; исходная запись сохранена.
- Requirements Quality Gate: `python3 .harness/tools/requirements-quality.py --payload-file .harness/local/tmp/exec-9f9aeb9f90714c8393bca674a37f506d/requirements-quality.json`, exit 0, PASS. Проверены полнота scope, однозначность обеих форм title, отрицательные сценарии и отличие настоящей RU locale от fallback; blocking ambiguity не обнаружена. Временный payload не является durable proof будущей реализации.


## Blocker / Failure reason

—
