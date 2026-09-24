---
schema: 1
id: STEP-011
status: in_progress
type: implementation
priority: medium
phase: release-preparation
depends_on:
  - STEP-010
requirements:
  - REQ-010
adrs: []
architecture_refs:
  - docs/architecture.md#deployment-runtime-assumptions
risk_flags:
  - none
plan:
  status: ready
  revision: 1
  context_basis: sha256:0617d805b3eacf632fa305ddf925fc73da8facd2e6ad07d2c02b45ea154e6e77
  content_hash: sha256:aa741024114adbe33d887b3848ed5eef25298a438dc30508928caae7ddf0e98c
  reviewed_report: planning/plan-reviews/STEP-011/PLAN-REVIEW-20260924T061342Z.md
  planned_at: 2026-09-24T06:13:42+00:00
---

# STEP-011 — CI workflow GitHub Actions для quality gates и packaging

## Goal

Добавить `.github/workflows/ci.yml`, который автоматически запускает quality gates и проверку упакованного VSIX (включая `test:packaged` EN/RU) на push в `main` и на pull request.

## Context

Сейчас в `.github/workflows/` есть только `harness-integrity.yml` (baseline Harness validation). Проектные проверки (`typecheck`, `lint`, `format`, `test:unit`, `build`, `package`, `inspect:package`, `test:packaged`) выполняются вручную, а `docs/development.md` («Git и CI») прямо оставляет project-specific CI отдельному ограниченному шагу. `package.json`: `engines.node >=20.0.0`, `packageManager: yarn@4.10.3+sha512…`. `test:packaged` запускает VS Code через `@vscode/test-cli` (кэш `.vscode-test`) и требует X-сервера на Linux. Обычные `test:integration` остаются локальной проверкой.

## Scope

- Workflow `.github/workflows/ci.yml`: триггеры `push` в `main` и `pull_request`; Node 20; Yarn через corepack по `packageManager`; кэш зависимостей; `yarn install --immutable`.
- Job `quality`: `yarn typecheck`, `yarn lint`, `yarn format`, `yarn test:unit`, `yarn build`.
- Job `package`: `yarn package`, `yarn inspect:package`, `yarn test:packaged` под xvfb на `ubuntu-latest`, кэш `.vscode-test`, загрузка VSIX как artifact.
- `permissions: contents: read`, `concurrency` с отменой устаревших запусков, actions на major-версиях.
- Обновление раздела «Git и CI» в `docs/development.md` (и README, если нужно): что запускает CI и что остаётся локальным.

## Mutation policy

### Allowed

- Новый файл `.github/workflows/ci.yml`.
- Документация CI: `docs/development.md`, при необходимости `README.md` вне Harness-managed блока.

### Conditional

- Правки `.vscode-test.mjs`/scripts — только если без них `test:packaged` доказуемо не запускается в CI; иначе не трогать.

### Forbidden

- Изменение `.github/workflows/harness-integrity.yml` и дублирование его проверок.
- Runtime-код расширения, `package.json` scripts, `.harness/`.
- Публикация в Marketplace/Open VSX, secrets, tokens, release/tag workflows.
- Включение `yarn test:integration` в CI.

## Out of scope

- Другие workflows (release, publish, dependabot, CodeQL, matrix по ОС/версиям Node).
- Branch protection / required checks (настройка репозитория).
- Изменение самих тестов и quality gates.

## Acceptance criteria

- `ci.yml` запускается на `push` в `main` и на `pull_request`, использует Node 20 и Yarn из `packageManager` через corepack, `yarn install --immutable` и кэш зависимостей.
- Job `quality` выполняет ровно пять команд: typecheck, lint, format, test:unit, build.
- Job `package` выполняет `yarn package`, `yarn inspect:package`, `yarn test:packaged` под xvfb, кэширует `.vscode-test` и загружает VSIX как artifact; `test:integration` в workflow отсутствует.
- Workflow содержит `permissions: contents: read`, `concurrency` с `cancel-in-progress: true`, actions пинятся на major-версии, секретов и публикации нет.
- `harness-integrity.yml` не изменён; `docs/development.md` описывает CI.
- Workflow проходит на PR, включая job `package` с `test:packaged`.

## Verification

- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn build`
- command: `yarn package`
- command: `yarn inspect:package`
- command: `yarn test:packaged`
- command: `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Workflow CI успешен на PR, оба job (quality, package) зелёные, artifact VSIX загружен.

## Deliverables

- `.github/workflows/ci.yml`, обновлённая документация CI.

## Implementation plan

### 1. Каркас workflow ci.yml

- Создать .github/workflows/ci.yml с name: CI, on: push (branches: main) и pull_request; подробные комментарии в стиле harness-integrity.yml.
- Добавить permissions: contents: read; concurrency (group по workflow и PR-номеру/ref, cancel-in-progress: true).
- Actions пинить на актуальные major-теги, проверенные через gh api releases/latest: actions/checkout@v7, actions/setup-node@v7, actions/cache@v6, actions/upload-artifact@v7 (checkout/setup-python в harness-integrity.yml уже на v7). Устаревшие v4 не использовать. Секретов и publish-шагов не добавлять.
- Каждый checkout с persist-credentials: false (токен нужен только для чтения).

**Files:**
- .github/workflows/ci.yml

**Risks:**
- Не дублировать validate.py и не менять harness-integrity.yml.

### 2. Общая подготовка окружения в обоих jobs

- В каждом job (ubuntu-latest, timeout-minutes): checkout, corepack enable (версия Yarn берётся из packageManager), setup-node с node-version: 20 и cache: yarn (corepack enable ДО setup-node), затем yarn install --immutable.
- Без матриц ОС/Node (out of scope).

**Files:**
- .github/workflows/ci.yml

**Risks:**
- setup-node cache: yarn требует доступного yarn до setup-node — порядок шагов критичен.

### 3. Job quality

- Шаги строго в порядке: yarn typecheck, yarn lint, yarn format, yarn test:unit, yarn build — без дополнительных проверочных команд.

**Files:**
- .github/workflows/ci.yml

**Tests:**
- yarn typecheck
- yarn lint
- yarn format
- yarn test:unit
- yarn build

### 4. Job package

- Шаги: yarn package; yarn inspect:package; actions/cache для .vscode-test/vscode-* (только скачанные сборки VS Code, без user-data и extensions) с точным key = runner.os + hashFiles('.vscode-test.mjs','yarn.lock') + версия stable VS Code, резолвленная отдельным шагом до кэша (curl https://update.code.visualstudio.com/api/releases/stable, первый элемент, в GITHUB_OUTPUT). restore-keys не использовать: при выходе нового stable ключ меняется, и кэш содержит только актуальную сборку, без накопления старых.
- Установка xvfb: sudo apt-get update && sudo apt-get install -y xvfb; yarn test:packaged под xvfb-run --auto-servernum.
- Загрузить vscode-harness-navigator-*.vsix через actions/upload-artifact@v7 (if-no-files-found: error).
- yarn test:integration в workflow не включать.

**Files:**
- .github/workflows/ci.yml

**Tests:**
- yarn package
- yarn inspect:package
- yarn test:packaged

**Risks:**
- test:packaged на headless Linux зависит от xvfb и загрузки VS Code; правки .vscode-test.mjs/scripts — Conditional, только при доказанной необходимости.
- package.json scripts менять нельзя — xvfb-run оборачивает вызов yarn на уровне workflow.

### 5. Документация CI

- Обновить раздел «Git и CI» в docs/development.md: триггеры, jobs quality и package, artifact VSIX, что остаётся локальным (yarn test:integration), Harness Integrity остаётся baseline.
- README.md править только при наличии релевантного места вне Harness-managed блока.

**Files:**
- docs/development.md

### 6. Локальная верификация и Evidence

- Запустить реальный actionlint с зафиксированной версией, без установки в репозиторий и без изменения package.json: go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml (Go доступен; результат воспроизводим, @latest не использовать). Тот же argv записан в Verification, поэтому deterministic gate способен его выполнить. YAML-парсинг не считается заменой; при недоступности go/сети — BLOCKED, а не подмена проверки.
- Прогнать остальные команды Verification, зафиксировать Command/Exit code/Observed в Evidence.
- Ручная проверка CI: ci.yml срабатывает только на pull_request и push в main, поэтому до REVIEW (gate потребует manual на IMPLEMENT SUCCESS) владелец открывает PR по каноническому пути GIT CHECK > GIT COMMIT > GIT PUSH > GIT PR при STEP в in_progress. В Evidence записать: URL/ID запуска Workflow CI, статусы jobs quality и package, имя загруженного artifact VSIX.

**Tests:**
- git diff --check
- python3 .harness/tools/validate.py --mode manual

## Evidence


<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T06:23:25Z
- Status: MANUAL_REQUIRED
- Git head: 5aabc7ad07e5d1a7f524833706b2d86aa5db430e
- Worktree hash: sha256:d45ecf38283e8858a85216b445b87231ebea565e48329c230299750c8c1a6198

### Automated verification
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3417
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4305
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1362
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7713
  - stdout sha256: 4087d9781a9f41aa2d7061d6571531a600bec561e63b6658acae19149848ceef
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 19191
  - stderr bytes: 0
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 540
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3556
  - stdout sha256: 8816faca546a524e46f023740d47959afbbfa5f0667721986f960c2114b8cfe1
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 856
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 325
  - stdout sha256: 39294efb9644380d39a33672a61cb50f77f30617b98fb12029a4c524846ef0b0
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: yarn test:packaged
  - Status: PASS
  - Exit code: 0
  - Duration ms: 30327
  - stdout sha256: bed3cc4b0ac9800c4f81298866abb3a849b004ac5f9478ba566f01be92e31e01
  - stderr sha256: fa550d243d87594bf2325643351ce51a52ee9b69f29bd5c9ebc9e3042fff6396
  - stdout bytes: 24123
  - stderr bytes: 15128
- Command: go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4467
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1125
  - stdout sha256: 3b147ff45890ff3f8d69cf4c479ce8c0ba86ca522a33c29fa896a6ddf6083f56
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Workflow CI успешен на PR, оба job (quality, package) зелёные, artifact VSIX загружен.
  - Status: PENDING
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.


## Blocker / Failure reason

—
