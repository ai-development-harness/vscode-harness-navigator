---
schema: 1
id: STEP-010
status: completed
type: implementation
priority: medium
phase: release-preparation
depends_on:
  - STEP-007
requirements:
  - REQ-010
adrs: []
architecture_refs:
  - docs/architecture.md#deployment-runtime-assumptions
risk_flags:
  - release-critical
plan:
  status: ready
  revision: 1
  context_basis: sha256:f780aca713855f4be43bd860134d605c382cace8dc403bc68a4a9ff22b8de527
  content_hash: sha256:17db8215374c631ed3c51121f1af11c04d72a82ab2a2cebeea3c8dee06589a52
  reviewed_report: planning/plan-reviews/STEP-010/PLAN-REVIEW-20260924T044728Z.md
  planned_at: 2026-09-24T04:47:28+00:00
---

# STEP-010 — Подготовка расширения к публикации: иконка, README и метаданные VSIX

## Goal

Подготовить содержимое VSIX для будущей публикации: иконка расширения, marketplace-ориентированный README и связанные метаданные — так, чтобы `yarn inspect:package` и `yarn test:packaged` продолжали доказывать безопасное содержимое пакета.

## Context

По итогам STEP-007 пакет содержит ровно 10 entries из allowlist. У расширения нет собственной иконки (нет поля `icon` в `package.json` и файлов изображений), а `readme.md` внутри VSIX — README репозитория, а не описание для пользователей расширения; это записано в Evidence STEP-007 как известное ограничение вне его scope. Значок Activity Bar (`$(list-tree)`) и кнопки view — встроенные codicon и в изменениях не нуждаются (решение ADR-004: нативный UI).

## Scope

- Иконка расширения: PNG не меньше 128×128, подключение через `icon` в `package.json`; при необходимости `galleryBanner`.
- Marketplace-ориентированный README для VSIX (что делает расширение, read-only граница, требования к Harness 0.6.0+, RU/EN), не затрагивающий Harness-managed блок README репозитория.
- Обновление `.vscodeignore`, allowlist и правил `scripts/packageInspection.ts` (`ALLOWED_ENTRIES`, ограничения на тип и размер изображения), unit-тестов и `docs/development.md` (release checklist).
- Проверка, что packaged suites по-прежнему проходят на распакованном VSIX, а bundle не изменил runtime-поведение.

## Mutation policy

### Allowed

- Файлы изображений в каталоге `resources/` и README для пакета в `docs/marketplace/`.
- `package.json`: метаданные `icon`, `galleryBanner`, `keywords`, `categories`, `repository`; scripts `package` (флаг `--readme-path`) и `generate:icon`.
- Инструмент разработки для воспроизводимой генерации иконки: чистый модуль-кодировщик PNG и CLI-обёртка в `scripts/`, с unit-тестами в `tests/unit/`.
- `.vscodeignore`, `scripts/` и tests package inspection, документация разработки.

### Conditional

- Изменения `scripts/prepare-packaged-extension.ts` и `.vscode-test.mjs` — только если новый entry ломает извлечение или packaged-профили.
- Путь к README для пакета, если vsce требует иное расположение — только при подтверждённой необходимости.

### Forbidden

- Runtime-код расширения, новые product capabilities, WebView, сеть, telemetry.
- Изменение Harness-managed блока `README.md` и содержимого `.harness/`.
- Расширение allowlist сверх иконки и README (например, произвольные изображения, sourcemap).

## Out of scope

- Публикация: `vsce publish`, Marketplace/Open VSX, Git tag, GitHub Release и push релиза.
- Собственный монохромный SVG для Activity Bar вместо `$(list-tree)` (отдельное решение по бренду).
- Скриншоты и анимации в README; лицензирование, publisher account, CI-публикация.
- Локализация README сверх RU/EN.

## Acceptance criteria

- `package.json` содержит `icon`, файл существует в VSIX; изображение — валидный PNG не меньше 128×128 и не больше заданного лимита размера.
- `yarn inspect:package` проверяет иконку (тип, размеры, размер файла) и по-прежнему отклоняет прочие лишние entries, sourcemap, секреты и запрещённые токены bundle.
- README в VSIX описывает расширение для пользователя, не содержит Harness-managed блок репозитория и ссылок на приватные пути.
- `yarn test:packaged` (EN/RU) проходит на распакованном VSIX; SHA-256 bundle совпадает с записью архива.
- `docs/development.md` описывает добавленные release-шаги; автоматическая публикация не выполняется.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn build`
- command: `yarn package`
- command: `yarn inspect:package`
- command: `yarn test:packaged`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Установить собранный VSIX в чистый профиль VS Code: иконка отображается в списке Extensions в светлой и тёмной теме, README открывается во вкладке Details без битых ссылок и изображений.

## Deliverables

- Иконка и README для пакета, обновлённые `package.json`, `.vscodeignore`, package inspection (правила и тесты), `docs/development.md`.

## Implementation plan

### 1. 1. Иконка: детерминированный генератор PNG без зависимостей (чистый кодировщик + CLI)

- Факт: в репозитории нет ни одного изображения, поля icon в package.json нет; внешних image-зависимостей добавлять нельзя. Создать scripts/iconEncoder.ts — чистый модуль без побочных эффектов при импорте (без top-level main()): функция рисования простого глифа навигатора (дерево узлов на сплошном фоне, без градиентов и текста) в буфер RGBA 256x256 и кодировщик PNG (signature, IHDR, IDAT через zlib.deflateSync, IEND, CRC32; node:zlib only). Создать scripts/generate-icon.ts — CLI-обёртка (запуск node --import tsx scripts/generate-icon.ts), пишет только resources/icon.png. Файл должен укладываться в 200 KiB (256x256 RGBA без сжатия ~263 KB, поэтому deflate level >= 6).
- Добавить package.json script generate:icon и закоммитить полученный resources/icon.png. Генератор — воспроизводимый источник, PNG можно позже заменить дизайнерским файлом того же формата без изменения правил inspection.
- Прописать в package.json поле "icon": "resources/icon.png" и "galleryBanner": {"color": "#1f2937", "theme": "dark"}. Каталог называть resources/, не images/ и не media/, чтобы не пересекаться с будущими артефактами.

**Files:**
- scripts/iconEncoder.ts
- scripts/generate-icon.ts
- resources/icon.png
- package.json
- tests/unit/generateIcon.test.ts

**Tests:**
- Unit tests/unit/generateIcon.test.ts: кодировщик возвращает валидную PNG-сигнатуру, IHDR 256x256 8-bit RGBA, корректные CRC всех чанков; импорт iconEncoder не пишет файлов.
- Unit: закоммиченный resources/icon.png имеет ту же IHDR и те же распакованные данные IDAT (zlib.inflateSync), что вывод генератора; сжатые байты не сравниваются, потому что вывод deflate может отличаться между версиями Node/zlib (engines.node >=20), а замена файла дизайнерским PNG допустима.

**Risks:**
- Глиф — минимально приемлемый, а не финальный бренд; замена файла остаётся за владельцем. Тест рассинхрона проверяет только, что закоммиченный файл соответствует генератору, и при осознанной замене иконки обновляется вместе с ней.
- scripts/**/*.ts входит в typecheck/lint/format (tsconfig.scripts.json); новые скрипты обязаны проходить их без исключений.

### 2. 2. README для пакета: отдельный файл вне Harness-managed README репозитория

- Факт: vsce 4.0.0 поддерживает --readme-path; сейчас в VSIX попадает README.md репозитория (Harness-managed блок PROJECT:START/END, ссылки на docs/planning). Создать docs/marketplace/README.md на английском и русском (один файл, два раздела): что делает расширение (навигация по STEP/REQ/ADR/OQ и справка по canonical-командам Harness 0.6.0+), read-only граница (не запускает Harness-команды, shell, сеть, не меняет артефакты), требования (VS Code ^1.85.0, Harness-проект с .harness/manifest.yaml), список view/команд из package.json contributes, настройки, RU/EN.
- Без относительных ссылок на docs/, planning/, .harness/, без ссылок вида #<число> (vsce переписывает их в ссылки на GitHub issues) и без изображений/скриншотов; ссылки только абсолютные https на репозиторий из package.json repository.url. Без Harness-managed блока и без PROJECT:START/END.
- Изменить script package в package.json на vsce package --no-dependencies --readme-path docs/marketplace/README.md; README.md репозитория не менять.

**Files:**
- docs/marketplace/README.md
- package.json

**Tests:**
- Unit packageInspection: README entry не содержит маркеров PROJECT:START/PROJECT:END и относительных ссылок вида ](docs/, ](planning/, ](.harness/ — иначе violation.
- Эмпирически после yarn package: extension/readme.md в VSIX совпадает с docs/marketplace/README.md (inspect:package сравнивает с исходным файлом, если он есть в рабочем каталоге; иначе действуют структурные правила выше). Правила README не должны падать из-за переписывания ссылок vsce — поэтому в README нет относительных ссылок и #<число>.

**Risks:**
- Если vsce 4.0.0 с --readme-path добавляет предупреждения о репозитории/относительных ссылках, устранять содержимым README, а не флагами --no-rewrite-relative-links/--baseContentUrl.
- docs/ исключён из VSIX правилами entries, но docs/marketplace/README.md — только источник; в архиве он оказывается как extension/readme.md.

### 3. 3. Package inspection: allowlist, проверка PNG и бинарные entries

- Факт: inspect-package.ts читает все прочие entries как UTF-8 и передаёт их в secret heuristics — для PNG это бессмысленный мусор и потенциальные ложные срабатывания. Изменить scripts/inspect-package.ts: entries с расширением .png собирать в отдельную Map<string, Uint8Array> binaryEntries и не декодировать в textEntries.
- scripts/packageInspection.ts: добавить extension/resources/icon.png в ALLOWED_ENTRIES; добавить в PackageInspectionInput поле binaryEntries; правила для иконки: manifest.icon строго равен resources/icon.png, entry существует, начинается с PNG-сигнатуры, IHDR width и height >= 128 и <= 1024, квадратная, размер файла <= 200 KiB, нет чанков tEXt/iTXt/zTXt (метаданные и возможные секреты) и нет дополнительных изображений в архиве; galleryBanner.color — строка вида #RRGGBB, theme — light|dark.
- Прочие изображения (svg, gif, jpg, ico, webp) остаются запрещёнными: добавить их в FORBIDDEN_ENTRY_PATTERNS; .png допускается только по точному имени из allowlist.
- Поднять MAXIMUM_ARCHIVE_BYTES с учётом иконки только при необходимости (сейчас 2 MiB, иконка <=200 KiB — лимит менять не требуется); README-правила из шага 2.

**Files:**
- scripts/packageInspection.ts
- scripts/inspect-package.ts
- tests/unit/packageInspection.test.ts

**Tests:**
- Unit: эталонный набор entries с валидной иконкой (синтетический PNG, собранный в тесте через экспортируемый кодировщик из шага 1) проходит; нарушения: 64x64, неквадратная, >1024, >200 KiB, не PNG-сигнатура, tEXt-чанк, иконка не по пути из manifest.icon, отсутствует entry при заданном icon, лишний svg/gif/ico/jpg/webp, второй png, некорректный galleryBanner.
- Unit: существующие кейсы (лишние entries, sourcemap, require, токены, secret heuristics, manifest) остаются зелёными; README-кейсы шага 2.

**Risks:**
- Границы 128..1024 и 200 KiB выбраны как консервативные для Marketplace; менять осознанно, а не ослаблением проверки.
- Чтение PNG в inspection — только разбор заголовка и списка чанков, без декодирования пикселей и без исполнения содержимого.

### 4. 4. .vscodeignore, packaged-профили и extraction

- Добавить в .vscodeignore !resources/icon.png (иначе vsce падает с 'icon wasn't found'; остальное остаётся под ** — allowlist-подход сохраняется). Удалить строку !README.md: при --readme-path vsce сам добавляет указанный файл как extension/readme.md, а оставленный !README.md добавил бы README репозитория отдельным entry extension/README.md (вне allowlist).
- Проверить scripts/prepare-packaged-extension.ts: он извлекает только extension/** и считает SHA-256 из данных записей VSIX — новый бинарный entry должен извлекаться без перекодирования; при необходимости исправить (conditional: только если тест на извлечение упадёт).
- yarn test:packaged должен пройти без изменения самих suites: runtime-код расширения и bundle не меняются, SHA-256 bundle совпадает с записью архива.

**Files:**
- .vscodeignore
- scripts/prepare-packaged-extension.ts

**Tests:**
- yarn package && yarn inspect:package: ровно 11 разрешённых entries (10 прежних + extension/resources/icon.png), 0 violations.
- yarn test:packaged: EN/RU passing, bundle SHA-256 совпадает.

**Risks:**
- Порядок: yarn build выполняет clean (rm -rf dist out); resources/ не очищается и не должен зависеть от clean.
- Если vsce включает иконку только при наличии поля icon и существующем файле — это ожидаемо; отсутствие файла при заданном icon даёт ошибку package, а не молчаливый пропуск.

### 5. 5. Документация: release checklist и снятие известного ограничения

- docs/development.md: добавить yarn generate:icon, назначение resources/icon.png и docs/marketplace/README.md, шаг release checklist «проверить иконку и README в VSIX» (entries, размеры, README без Harness-блока); удалить формулировку об известном ограничении readme.md как README репозитория.
- Явно оставить: автоматическая публикация, vsce publish, Marketplace/Open VSX, Git tag/push релиза не выполняются проектом (Out of scope).

**Files:**
- docs/development.md

**Tests:**
- Каждая команда в docs/development.md существует в package.json scripts и выполнена в Verification (generate:icon — в unit-проверке рассинхрона шага 1 и вручную при реализации).

**Risks:**
- README.md репозитория и его Harness-managed блок не менять.

### 6. 6. Финальный прогон gates и evidence

- Выполнить Verification в указанном порядке; зафиксировать в Evidence команды, exit codes, отсортированный список VSIX entries (11) с SHA-256, размер архива, размеры и хеш иконки, факт, что tracked fixtures не изменены, и что публикация не выполнялась — без реконструкции terminal output.
- Ручная проверка: установить VSIX в чистый профиль VS Code (code --user-data-dir <tmp> --extensions-dir <tmp2> --install-extension <vsix>; одного --user-data-dir мало, иначе расширение попадёт в ~/.vscode/extensions): иконка в списке Extensions в светлой и тёмной теме, README на вкладке Details без битых ссылок; результат передаёт владелец через dispatcher.

**Files:**
- planning/tasks/STEP-010.md

**Tests:**
- Полный набор Verification ниже.

**Risks:**
- Ручная установка выполняется владельцем; без неё completion невозможен (MANUAL_REQUIRED).
- Integration/packaged suites требуют display; в среде без display фиксировать BLOCKED среды, а не PASS.

## Evidence




<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T05:29:55Z
- Status: PASS
- Git head: 336ea86b2068c5ac997c850c24d1a31c1ecb6749
- Worktree hash: sha256:23883d345f251243eb67d058146ff7fe4b99783dab80fe5f7a09570ef9b26cc0

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3436
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4344
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1355
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7674
  - stdout sha256: 5aa8dbcd02465770cc9c0aa51dc8d42df5c44eca4ccaf51f96bcc686faefc23b
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 19209
  - stderr bytes: 0
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 509
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3505
  - stdout sha256: 389224d40d97a9a1bce2455c27800bd46210f543465ebcedeeaa231bce5d8af4
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 856
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 321
  - stdout sha256: eef5ccd6e50bf24762f41f5482f5267ef3983a15c9f86e63358203befd748534
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:packaged
  - Status: PASS
  - Exit code: 0
  - Duration ms: 31454
  - stdout sha256: 775d4215a45d3ee2e3c14c9ed14d522fa14498bd5fc081d876dc5444ee3e82b1
  - stderr sha256: cbb4dcf0befc77268b6188a994e3565b7584f8717c07538f4f23ab28c652f4f3
  - stdout bytes: 24399
  - stderr bytes: 15128
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 5
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1111
  - stdout sha256: 7be84e6040f357deaec02bac37c0b62eaab4f71553874c4bb2becaaffde81e8d
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Установить собранный VSIX в чистый профиль VS Code: иконка отображается в списке Extensions в светлой и тёмной теме, README открывается во вкладке Details без битых ссылок и изображений.
  - Status: PASS
  - Observed: "После FIX пользователь в ответ на запрос проверить иконку в светлой и тёмной теме и вкладку Details сообщил: «ручная проверка успешно прошла». Конкретных наблюдений и профиль установки не указал."
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.

Реализация шагов 1-5 плана (шаг 6 — финальный прогон Verification и ручная установка — выполняет dispatcher/владелец). Фактические наблюдения; терминальный вывод не цитируется.

- `yarn generate:icon` — exit 0; записан `resources/icon.png`: 3019 bytes, SHA-256 `107a6237611d1f0b63a8a751b767aa50989a50a84232adedc183e2c0fec24d44`, IHDR 256x256, 8-bit RGBA. Рассинхрон файла и генератора проверяет unit-тест `tests/unit/generateIcon.test.ts` (IHDR и распакованные данные IDAT).
- `yarn typecheck`, `yarn lint`, `yarn format` — exit 0.
- `yarn test:unit` — exit 0; 156 tests, 156 pass, 0 fail.
- `yarn build` — exit 0. `yarn package` — exit 0; `vsce` сообщил 11 files; архив `vscode-harness-navigator-0.0.1.vsix` 50957 bytes.
- `yarn inspect:package` — exit 0; `package inspection: PASS (0 violations)`. Entries (SHA-256, size):
  - `[Content_Types].xml` 709ad4ed6efc962fbdac0438984b1843fa52a8a01e323fa19d2276277ed5f8b8, 462
  - `extension.vsixmanifest` a4c74a56d247e2342eed20420e641a29f5a74898156988505fc79e2c9f46e4d8, 3039
  - `extension/dist/extension.js` aea3eeb9592e4c664962235bd13f60dbee6512744de98b752ac117c2836bd248, 113481
  - `extension/l10n/bundle.l10n.json` 12363c2dd454ca03f513152c4a9a9c5446b050fa41e55417bc0dc46fe70cbf02, 9541
  - `extension/l10n/bundle.l10n.ru.json` 4c61bb432542dc9879d5bef49ab9bbad5250267fa98d799dcd83f8bb5b809303, 12451
  - `extension/LICENSE.txt` d79fbd624486d0ae463e6465e84d3870e3cd1abbb99dd81c2024e8917eadbe8b, 1071
  - `extension/package.json` ca33471b276090f754ad6bb0c07071e0612bb6c83b0a23d05a84646799cf9180, 11332
  - `extension/package.nls.json` cfa83f79f06a410e086e47e27f9def69c31f28930ece9350d2d3d41576ba0bc1, 1806
  - `extension/package.nls.ru.json` 349eb5843b053ceb169ac25f9c621841c9de6597871e6769d10a056d24ffd4b0, 2427
  - `extension/readme.md` 2ec8b0014debb97a35400b959936d14f86b00e7594f9f8a07ccce40412251a04, 3713
  - `extension/resources/icon.png` 107a6237611d1f0b63a8a751b767aa50989a50a84232adedc183e2c0fec24d44, 3019
- Проверка `unzip -p ... extension/readme.md | cmp - docs/marketplace/README.md` — exit 0 (идентичны); entry `extension/README.md` в архиве отсутствует (в списке одно совпадение с README.md — `extension/readme.md`).
- `DISPLAY=:1 yarn test:packaged` — exit 0; в наблюдаемом хвосте вывода 24 passing, Extension Host завершился с кодом 0.
- STEP FIX (findings 2-4): усилены `inspectIcon` (CRC каждого чанка, IDAT, отсутствие данных после IEND), правила README вынесены в `inspectReadmeText` и применяются к архивному и исходному README, сравнение вынесено в `compareReadmeWithSource` (при отсутствии исходника печатается явная строка `readme comparison: ...`), README разделён на Command Palette и контекстные меню. Повторный прогон: typecheck, lint, format, build, package, `inspect:package` — exit 0; `yarn test:unit` 159 tests, 159 pass; VSIX 51287 bytes, 11 entries, 0 violations; изменился только `extension/readme.md` (SHA-256 `8350adb631a872f89c70b060a5a88245e5c9a851edc668cc9846e90e852e1c67`, 5151 bytes), остальные entries совпадают с записанными выше; `DISPLAY=:1 yarn test:packaged` — exit 0, 24 passing.
- `git diff --check` — exit 0; tracked fixtures и `src/**` не изменены (`git status` показывает только файлы из Mutation policy). Публикация, tag, push и commit не выполнялись.




## Blocker / Failure reason

—
