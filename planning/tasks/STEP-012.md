---
schema: 1
id: STEP-012
status: completed
type: implementation
priority: low
phase: release-preparation
depends_on:
  - STEP-011
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
  context_basis: sha256:da08f92a8a78146aeeefb3f3cf13542df7e438cb767b4abe06e97f32eaa3719a
  content_hash: sha256:be62898d4e15ab84ce452901494f26145d38c7b89dd7129de5a2ab3bb912e584
  reviewed_report: planning/plan-reviews/STEP-012/PLAN-REVIEW-20260924T065017Z.md
  planned_at: 2026-09-24T06:50:17+00:00
---

# STEP-012 — Согласование engines.node с минимумом Node 22

## Goal

Привести `package.json → engines.node` и документацию в соответствие с реальным минимумом Node.js для development toolchain: Node 22 (тот же, что использует CI).

## Context

`package.json` объявляет `engines.node >=20.0.0`, но `yarn test:unit` (`node --import tsx --test "tests/unit/**/*.test.ts"`) использует glob в `node --test`, который поддержан только с Node 21. На Node 20 команда падает с `Could not find 'tests/unit/**/*.test.ts'` (наблюдалось в первом запуске CI STEP-011, PR #11); CI поэтому работает на Node 22, разработка ведётся на Node 24 (`@types/node ^24`). `docs/development.md` (Prerequisites) сейчас описывает минимум как «>= 20» с оговоркой про `test:unit`. `engines.node` относится к development toolchain: runtime расширения определяется `engines.vscode`.

## Scope

- Обновить `package.json → engines.node` до `>=22.0.0`.
- Обновить `docs/development.md` (Prerequisites): единый минимум Node 22 вместо оговорки «>= 20 / >= 21».
- Проверить, что `yarn install --immutable`, `yarn package` и `yarn inspect:package` не зависят от прежнего значения `engines.node`.

## Mutation policy

### Allowed

- Поле `engines.node` в `package.json` (значение `engines.vscode` и остальные поля не менять).
- Раздел Prerequisites в `docs/development.md`.

### Conditional

- `.nvmrc`/`.node-version`: только если файл уже существует в репозитории и содержит несогласованную версию; новый файл не создавать.
- `README.md`/`docs/marketplace/README.md`: только если там явно указан минимум Node.

### Forbidden

- Изменение `engines.vscode`, `@types/node`, зависимостей, `yarn.lock`, scripts.
- Изменение тестов, runtime-кода расширения, `.github/workflows/`, `.harness/`.
- Ограничение сверху (`<`) в `engines.node`.

## Out of scope

- Замена `node --test` glob на совместимый с Node 20 вариант.
- Изменение Node-версии в CI и матрицы версий Node.
- Закрепление actions по SHA / Dependabot.

## Acceptance criteria

- `package.json → engines.node` равен `>=22.0.0`; `engines.vscode` не изменён.
- `docs/development.md` называет минимумом Node 22 без противоречащих оговорок; версия согласована с CI (`node-version: 22`).
- Новых `.nvmrc`/`.node-version` не создано; scripts и зависимости не изменены.
- Все проверки Verification проходят, `yarn inspect:package` даёт `0 violations`.

## Verification

- command: `yarn install --immutable`
- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `yarn test:unit`
- command: `yarn build`
- command: `yarn package`
- command: `yarn inspect:package`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Workflow CI на PR остаётся зелёным (Quality, Package).

## Deliverables

- Обновлённые `package.json` (`engines.node`) и `docs/development.md`.

## Implementation plan

### 1. Обновить engines.node

- В package.json заменить только значение engines.node с >=20.0.0 на >=22.0.0; engines.vscode, scripts, зависимости и yarn.lock не менять.
- Верхнюю границу (<) не добавлять.

**Files:**
- package.json

**Risks:**
- Yarn Berry не блокирует install по engines.node по умолчанию, но проверить, что yarn install --immutable проходит без изменения yarn.lock.

### 2. Обновить Prerequisites в docs/development.md

- Строку 5 переписать: Node.js >= 22 (минимум согласован с CI, node-version: 22; проект разрабатывается на Node 24; на Node 20 glob в node --test не поддержан), без оговорки «>= 20 / >= 21».
- Других упоминаний минимума Node в README.md, docs/marketplace/README.md, .nvmrc/.node-version нет (проверено grep, файлов .nvmrc/.node-version в репозитории нет) — их не создавать и не трогать.
- Комментарии в .github/workflows/ci.yml про Node 21 не менять: workflows вне Mutation policy.

**Files:**
- docs/development.md

### 3. Проверка независимости упаковки от engines.node

- Прогнать yarn install --immutable, yarn package и yarn inspect:package и убедиться, что inspect:package даёт 0 violations, а yarn.lock не изменился (git diff --stat yarn.lock пуст).

**Tests:**
- yarn install --immutable
- yarn package
- yarn inspect:package

### 4. Quality gates и Evidence

- Прогнать typecheck, lint, format, test:unit, build, git diff --check, validate.py --mode manual; результаты записывает dispatcher в generated Evidence.
- Ручная проверка CI: открыть PR через GIT CHECK > GIT COMMIT > GIT PUSH > GIT PR при STEP в in_progress до REVIEW; в Evidence записать URL/ID запуска, статусы jobs Quality и Package (CI использует Node 22, значение engines.node его не меняет). В Evidence явно указать версии Node: локальный прогон (node --version) и CI (Node 22); работу на заявленном минимуме Node 22 доказывает только CI.

**Tests:**
- yarn typecheck
- yarn lint
- yarn format
- yarn test:unit
- yarn build
- git diff --check
- python3 .harness/tools/validate.py --mode manual

## Evidence


<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T06:53:52Z
- Status: PASS
- Git head: d3b4c45fd687c3424c4e2d0b4946458d6bfb0af1
- Worktree hash: clean

### Automated verification
- Command: yarn install --immutable
  - Status: PASS
  - Exit code: 0
  - Duration ms: 621
  - stdout sha256: db482cc529553704704709797a1a3b4e009677baea4365b8f97686326224807b
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 234
  - stderr bytes: 0
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3357
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4229
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1364
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: yarn test:unit
  - Status: PASS
  - Exit code: 0
  - Duration ms: 7623
  - stdout sha256: 80786f5b470e6f96e1a2bbd0b3d503ff5e06b3b916f11fe52617619cbd5d3ee6
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 19210
  - stderr bytes: 0
- Command: yarn build
  - Status: PASS
  - Exit code: 0
  - Duration ms: 543
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3576
  - stdout sha256: 8816faca546a524e46f023740d47959afbbfa5f0667721986f960c2114b8cfe1
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 856
  - stderr bytes: 0
- Command: yarn inspect:package
  - Status: PASS
  - Exit code: 0
  - Duration ms: 317
  - stdout sha256: 930692f3e409d439b5f1a4c2146f17b102bc1b3429ad7e273b5098393caec4da
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 1305
  - stderr bytes: 0
- Command: git diff --check
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: python3 .harness/tools/validate.py --mode manual
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1149
  - stdout sha256: 04cc80ae557696ad2488d4ca11ecf0b13d8be682b45605ff49433b597cba433a
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Workflow CI на PR остаётся зелёным (Quality, Package).
  - Status: PASS
  - Observed: "PR #12, run https://github.com/ai-development-harness/vscode-harness-navigator/actions/runs/35966586478 (head d3b4c45): Quality pass (31s), Package pass (1m15s), Validate Harness pass. Версии Node: локальный прогон 24.21.0, CI 22 (node-version: 22); работу на минимуме Node 22 доказывает CI."
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.


## Blocker / Failure reason

—
