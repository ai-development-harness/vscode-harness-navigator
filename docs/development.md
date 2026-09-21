# Development

## Prerequisites

- Node.js >= 20 (проект разрабатывается на Node 24).
- Corepack-managed Yarn (Berry) с `node-modules` linker. Один раз выполните `corepack enable`,
  после чего `yarn` внутри репозитория автоматически использует версию, зафиксированную в
  `package.json#packageManager`.
- Yarn настроен на `node-modules` linker в `.yarnrc.yml`. Plug'n'Play намеренно не используется:
  он несовместим с packaging через `@vscode/vsce` и с тем, как `@vscode/test-electron` загружает
  расширение в реальный Extension Host.

## Local setup

```bash
yarn install
```

Эта команда устанавливает зависимости в `node_modules/` по зафиксированному `yarn.lock`.

## Development commands

| Command | Назначение |
| --- | --- |
| `yarn typecheck` | Строгая проверка типов TypeScript для source, unit и integration tests (без emit). |
| `yarn lint` | ESLint (type-aware) для `src/`, `tests/` и собственных tooling-скриптов репозитория. |
| `yarn format` | Проверка форматирования Prettier (файлы не переписываются). |
| `yarn format:fix` | Применение форматирования Prettier. |
| `yarn build:dev` | esbuild-сборка `src/extension.ts` в `dist/extension.js` с sourcemap, без минификации. |
| `yarn build` | Production esbuild-сборка: CommonJS, `--external:vscode`, минификация, без sourcemap. |
| `yarn compile:tests` | Компилирует `src/test/**/*.ts` (integration tests) в `out/test/**` через `tsc`. |
| `yarn test:unit` | Запускает unit-слой тестов (обычный Node-процесс, без Extension Host). |
| `yarn test:integration` | Собирает dev-bundle, компилирует integration tests, затем запускает их в реальном изолированном Extension Host через `@vscode/test-cli`/`@vscode/test-electron`. |
| `yarn test` | Запускает оба слоя тестов (`test:unit`, затем `test:integration`). |
| `yarn package` | Упаковывает расширение в `.vsix` через `@vscode/vsce` (production-сборка запускается автоматически через скрипт `vscode:prepublish`). |

## Запуск / отладка Extension Host вручную

1. Откройте этот репозиторий в VS Code.
2. Выполните `yarn build:dev`, чтобы создать `dist/extension.js`. Это one-shot сборка: после
   изменения исходников выполните её повторно перед новым запуском Extension Development Host.
3. Нажмите `F5` (или *Run and Debug → Run Extension*), чтобы запустить окно Extension
   Development Host с загруженным расширением. VS Code использует `package.json#main`
   (`./dist/extension.js`) как точку входа.
4. Breakpoints, установленные в `src/extension.ts`, срабатывают благодаря sourcemap,
   создаваемому `build:dev`.

Пока не существует product UI, который можно было бы «покликать» вручную: STEP-001 закладывает
только extension lifecycle (`activate`/`deactivate`) и границу локализации. Активация происходит
незаметно на `onStartupFinished` и не читает workspace, не запускает процессы и не выполняет ни
одной команды Harness.

## Структура тестов

Два независимо запускаемых слоя, оба вызываются через `yarn test`:

- **Unit-слой** — `tests/unit/*.test.ts`, запускается напрямую встроенным test runner Node через
  `tsx` (`node --import tsx --test`). Без Extension Host, без модуля `vscode`. Покрывает:
  - паритет ключей между `package.nls.json`/`package.nls.ru.json` и то, что
    русский runtime bundle является подмножеством English fallback bundle;
  - наличие намеренно отсутствующего в русском runtime bundle fallback key;
  - guard против попадания canonical Harness ID/enum-значений/command names в переводимые
    значения bundle;
  - регистрацию, disposal, порядок disposal, идемпотентность и устойчивость к исключениям
    lifecycle-реестра.
- **Integration-слой** — `src/test/integration/*.test.ts`, компилируется в
  `out/test/integration` через `tsc -p tsconfig.test.json` и запускается в реальном изолированном
  Extension Host, который поднимает `@vscode/test-cli` (`.vscode-test.mjs`) через
  `@vscode/test-electron`. При первом запуске это скачивает локальную test-сборку VS Code
  (далее кэшируется в `.vscode-test/`). Покрывает:
  - расширение обнаруживается по своему manifest id;
  - активация возвращает документированный test-observable результат, включая
    локализованную runtime-строку и английский fallback;
  - English и Russian Extension Host запускаются с `--locale en` и `--locale ru`;
  - `deactivate()` освобождает registrations до нуля, безопасен и идемпотентен.

## Lint / formatting / type checking

- `yarn typecheck` — строгий TypeScript (`strict`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`) для исходного кода, unit и integration tests.
- `yarn lint` — ESLint 10 с type-aware конфигом `recommendedTypeChecked` из `typescript-eslint`,
  плюс `eslint-config-prettier`, отключающий стилистические правила, конфликтующие с Prettier.
- `yarn format` / `yarn format:fix` — Prettier, ограниченный файлами, которыми владеет этот
  проект (`src/`, `tests/`, `l10n/*.json`, `package.nls*.json`, корневые config-файлы), чтобы
  посторонняя документация не переформатировалась как побочный эффект.

## Build

`yarn build:dev` и `yarn build` оба запускают `esbuild.js`, который собирает `src/extension.ts` в
единый CommonJS `dist/extension.js`, ориентируясь на Node runtime Extension Host в VS Code и
исключая модуль `vscode` (он подставляется host-ом в runtime). `--production` (используется
`yarn build`) минифицирует сборку и не создаёт sourcemap; режим по умолчанию (dev) сохраняет
sourcemap и пропускает минификацию.

## Packaging

`yarn package` запускает `@vscode/vsce package --no-dependencies` (у расширения нет runtime
`dependencies`, только `devDependencies`, поэтому определение дерева зависимостей не требуется).
`vscode:prepublish` автоматически запускает перед этим production-сборку `yarn build`.
`.vscodeignore` ограничивает итоговый `.vsix` production-bundle, манифестом, ресурсами
локализации, `README.md` и `LICENSE` — исходники, тесты и `node_modules` исключены.

## Environment / configuration

Переменные окружения и внешняя конфигурация не требуются. Расширение не выполняет сетевых
обращений, telemetry или запуска shell/процессов.

## Database / migrations

Не применимо.

## Git и CI

Repository Git workflow задаётся `.harness/docs/GIT_WORKFLOW.md` и `.harness/git-policy.toml`.
Harness Integrity CI является baseline; project-specific CI (запуск `typecheck`, `lint`,
`test`, `build`) предполагается добавить после того, как этот toolchain будет проверен как
стабильный, отдельным, явно ограниченным по scope шагом.
