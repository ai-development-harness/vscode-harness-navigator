# Development

## Prerequisites

- Node.js >= 22 (минимум согласован с CI, `node-version: 22`; проект разрабатывается на Node 24; на Node 20 glob в `node --test` для `yarn test:unit` не поддержан).
- Corepack-managed Yarn 4 (Berry) с `node-modules` linker. Один раз выполните `corepack enable`,
  после чего `yarn` внутри репозитория автоматически использует версию, зафиксированную в
  `package.json#packageManager`.
- Python 3.11+ — только для Harness tools/validators (`python3 .harness/tools/validate.py`,
  `sync-projections.py`); сам код расширения Python не использует.
- Yarn настроен на `node-modules` linker в `.yarnrc.yml`. Plug'n'Play намеренно не используется:
  он несовместим с packaging через `@vscode/vsce` и с тем, как `@vscode/test-electron` загружает
  расширение в реальный Extension Host.

## Local setup

```bash
yarn install --immutable
```

Устанавливает зависимости в `node_modules/` строго по зафиксированному `yarn.lock`.

## Development commands

| Command | Назначение |
| --- | --- |
| `yarn typecheck` | Строгая проверка типов TypeScript для source, unit tests, integration tests и `scripts/` (без emit). |
| `yarn lint` | ESLint (type-aware) для `src/`, `tests/`, `scripts/` и корневых config-файлов. |
| `yarn format` | Проверка форматирования Prettier (файлы не переписываются). |
| `yarn format:fix` | Применение форматирования Prettier. |
| `yarn test:unit` | Unit-слой (обычный Node-процесс, без Extension Host). |
| `yarn test:integration` | `build:dev` → `compile:tests` → подготовка `out/test-workspace` → Extension Host профили `integration-en`, `integration-ru`, `mvp-en`, `mvp-ru`. |
| `yarn test` | `test:unit`, затем `test:integration`. |
| `yarn build:dev` | Очищает `dist`/`out` и собирает dev bundle `dist/extension.js` (sourcemap, без минификации). |
| `yarn build` | Очищает `dist`/`out` и собирает production bundle (минификация, без sourcemap). |
| `yarn compile:tests` | Компилирует `src/test/**/*.ts` в `out/test/**` через `tsc`. |
| `yarn generate:icon` | Детерминированно (без зависимостей) пересоздаёт `resources/icon.png` (256x256 RGBA PNG) из `scripts/iconEncoder.ts`; пишет только этот файл. Иконку можно заменить дизайнерским PNG, правила inspection не изменятся. |
| `yarn package` | Собирает `vscode-harness-navigator-<version>.vsix` через `@vscode/vsce` с `--readme-path docs/marketplace/README.md` (production-сборка запускается `vscode:prepublish`). |
| `yarn inspect:package` | Читает VSIX (zero-dependency ZIP reader, без исполнения), печатает entries с SHA-256 и завершается с кодом 1 при нарушении allowlist, bundle-правил или secret heuristics. |
| `yarn test:packaged` | `compile:tests` → извлечение VSIX в `out/packaged/extension` → подготовка `out/test-workspace` → Extension Host профили `packaged-en`, `packaged-ru` против извлечённого production bundle. Не пересобирает bundle: сначала выполните `yarn build && yarn package`. |

Integration и packaged suites запускают реальный VS Code Extension Host и требуют display. На
headless Linux используйте `xvfb-run -a yarn test:integration` и `xvfb-run -a yarn test:packaged`.
При первом запуске `@vscode/test-electron` скачивает test-сборку VS Code в `.vscode-test/`
(это сеть test tooling, а не runtime расширения); с заполненным кэшем прогон возможен offline.

## Запуск Extension Development Host вручную

1. Откройте репозиторий в VS Code и выполните `yarn build:dev`.
2. Нажмите `F5` (*Run Extension* из `.vscode/launch.json`) — откроется Extension Development
   Host с загруженным расширением; точка входа — `package.json#main` (`./dist/extension.js`).
3. Для ручной проверки MVP откройте `src/test/fixtures/mvp/mvp-valid` (или подготовленную копию
   `out/test-workspace/mvp/mvp.code-workspace`) в Extension Development Host в RU и EN локали,
   светлой и тёмной теме: Status Bar item читаем и использует theme colors, по click открывает
   Harness View, Summary view показывает release и counts.

## Структура тестов

- **Unit** — `tests/unit/*.test.ts` (`node --import tsx --test`), без Extension Host. Покрывает
  parsing/indexes/containment (включая capability injection для non-Linux), view models,
  Status Bar/Summary model, Command Catalog, локализацию, атрибуцию stack для boundary spies и
  правила package inspection.
- **Integration** — `src/test/integration/*.test.ts` (профили `integration-*`) и
  `src/test/integration/mvp/*.test.ts` (профили `mvp-*` и `packaged-*`): detection states,
  containment, taxonomy, views/providers/catalog, watcher refresh без restart, multi-root
  lifecycle, boundary suite (offline/no-shell/no-mutation через runtime spies) и RU/EN.
  Общие helpers — `src/test/integration/support/`.

### Изолированный test workspace

`scripts/prepare-test-workspace.ts` удаляет и заново копирует `src/test/fixtures` в
`out/test-workspace/` (записи вне этого каталога запрещены) и генерирует то, что нельзя хранить
в Git: `node_modules/` MVP-фикстуры (в исходниках — `_node_modules`), static symlink-фикстуры,
manifest с абсолютным configured path и (POSIX, не root) каталог `.harness` без права поиска.
Если OS отказывает в создании symlink/chmod, скрипт пишет `out/test-workspace/mvp/skipped-fixtures.json`,
а соответствующие проверки явно пропускаются с причиной. Extension Host tests не изменяют tracked
`src/test/fixtures`; каждая suite проверяет, что workspace лежит в `out/test-workspace`.

### Packaged профили

`scripts/prepare-packaged-extension.ts` извлекает `extension/**` из VSIX в `out/packaged/extension`,
пишет `out/packaged/extracted-entries.json` (SHA-256 entries) и копирует скомпилированные suites в
`out/packaged/extension/__packaged_tests__/`. Extension Host выдаёт отдельный instance `vscode` API
на расширение, поэтому suites обязаны лежать внутри расширения, чтобы boundary spies были видны
bundle. `__packaged_tests__` — единственное дополнение к содержимому VSIX и в bundle не входит.

## Build и packaging

`esbuild.js` собирает `src/extension.ts` в единый CommonJS `dist/extension.js` (Node runtime,
`vscode` исключён). `.vscodeignore` ограничивает VSIX production bundle, manifest, `package.nls*`,
`l10n/`, `resources/icon.png` и `LICENSE`; sourcemap в пакет не входит. README репозитория в VSIX не
попадает: vsce с `--readme-path` кладёт `docs/marketplace/README.md` как `extension/readme.md`
(поэтому `!README.md` в `.vscodeignore` нет). `docs/marketplace/README.md` — двуязычный (RU/EN)
README для пользователей расширения: только абсолютные https-ссылки, без Harness-managed блока,
изображений и ссылок вида `#<число>`.

## Release checklist (ручной)

1. `yarn install --immutable`
2. `yarn typecheck`, `yarn lint`, `yarn format`, `yarn test:unit`
3. `xvfb-run -a yarn test:integration` (на машине с display — `yarn test:integration`)
4. `yarn build && yarn package`
5. `yarn inspect:package` — проверить список entries (11, включая `extension/resources/icon.png`) и
   `0 violations`; проверить иконку (PNG, квадратная 128..1024, до 200 KiB, без text-чанков) и что
   `extension/readme.md` совпадает с `docs/marketplace/README.md` и не содержит Harness-блока
6. `xvfb-run -a yarn test:packaged`
7. `git diff --check` и `python3 .harness/tools/validate.py --mode manual`
8. Ручная проверка Status Bar / Summary в Extension Development Host (RU/EN, светлая/тёмная тема).
9. Ручная установка VSIX в чистый профиль (`code --user-data-dir <tmp> --extensions-dir <tmp2>
   --install-extension <vsix>`; одного `--user-data-dir` мало): иконка в списке Extensions в светлой
   и тёмной теме, README на вкладке Details без битых ссылок.

Этот проект **не** выполняет автоматическую публикацию: `vsce publish`, Git tag, push и release
(включая Marketplace/Open VSX) находятся вне scope и делаются владельцем вручную.

## Security / containment

`.harness/manifest.yaml` и configured paths читаются read-only (ADR-007, ADR-005/006): абсолютный
путь, traversal и static symlink за пределы workspace root блокируются как `ConfigurationBlocked`
на всех platform; защита от подмены промежуточного ancestor (`/proc/self/fd`) доступна и
обязательна на Linux; на macOS/Windows корректный project остаётся `valid`, принимается только
остаточный риск конкурентной подмены ancestor. Runtime-границу (нет shell/network/auth/записи в
Harness artifacts) доказывают boundary suite и static bundle scan `yarn inspect:package`.

## Environment / configuration

Переменные окружения и внешняя конфигурация не требуются. Расширение не выполняет сетевых
обращений, telemetry или запуска shell/процессов.

## Git и CI

Repository Git workflow задаётся `.harness/docs/GIT_WORKFLOW.md` и `.harness/git-policy.toml`.
Harness Integrity CI (`.github/workflows/harness-integrity.yml`) является baseline. Project CI —
`.github/workflows/ci.yml` — запускается на `pull_request` и push в `main` (Node 22, Yarn из
`packageManager` через corepack, `yarn install --immutable`) и состоит из двух jobs:

- `quality`: `yarn typecheck`, `yarn lint`, `yarn format`, `yarn test:unit`, `yarn build`;
- `package`: `yarn package`, `yarn inspect:package`, `yarn test:packaged` (EN/RU) под `xvfb-run`;
  собранный VSIX загружается как artifact `vsix`. Скачанный VS Code кэшируется в `.vscode-test`
  с ключом по версии stable.

Actions в `ci.yml` закреплены по commit SHA с комментарием `# vN`; SHA обновляют еженедельные PR
Dependabot (`.github/dependabot.yml`, экосистема `github-actions`), вручную обновлять их не нужно.

Локальной проверкой остаётся `yarn test:integration` (в CI не запускается). Workflow не публикует
расширение и не использует secrets.
