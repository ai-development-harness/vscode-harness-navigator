---
schema: 1
id: STEP-013
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
  context_basis: sha256:a9a624d4d40a52f703ab0286a1498a4a3f85334769f4d011983209d458f09f17
  content_hash: sha256:1748fd0e841f99f0ddbab022120fa7a0fa2441703e88f86e04367ea5dcf614ea
  reviewed_report: planning/plan-reviews/STEP-013/PLAN-REVIEW-20260924T070157Z.md
  planned_at: 2026-09-24T07:01:57+00:00
---

# STEP-013 — Закрепление GitHub Actions по commit SHA и Dependabot

## Goal

Закрепить third-party actions в `.github/workflows/ci.yml` по неизменяемым commit SHA с комментарием `# vN` и добавить Dependabot для еженедельного обновления GitHub Actions.

## Context

`ci.yml` (STEP-011) использует actions по изменяемым major-тегам (`actions/checkout@v7`, `actions/setup-node@v7`, `actions/cache@v6`, `actions/upload-artifact@v7`), тогда как `harness-integrity.yml` пинит их по commit SHA с комментарием `# v7`. Security-ревью STEP-011 отметило это как low-риск: перенос тега в upstream позволил бы выполнить подменённый код в CI с доступом к `GITHUB_TOKEN` (read-only) и подменить artifact/кэш. Без автоматического обновления SHA-пины устаревают, поэтому нужен `dependabot.yml` для экосистемы `github-actions`. Validator Harness требует комментарий с «Пример:» у каждого параметра только для `.github/workflows/*.yml` (`documented_config_globs`); `.github/dependabot.yml` под это правило не попадает, но по соглашению репозитория параметры комментируются так же, и это проверяется вручную.

## Scope

- В `.github/workflows/ci.yml` заменить теги на полные 40-символьные commit SHA тех же major-версий с комментарием `# vN` (checkout, setup-node, cache, upload-artifact); SHA должны соответствовать текущим тегам major (checkout SHA совпадает с пином в `harness-integrity.yml`).
- Добавить `.github/dependabot.yml`: экосистема `github-actions`, directory `/`, еженедельное расписание; комментарии к параметрам в стиле репозитория.
- Обновить раздел «Git и CI» в `docs/development.md`: actions пинятся по SHA, обновление через Dependabot.

## Mutation policy

### Allowed

- `.github/workflows/ci.yml`: только значения `uses:` и комментарии к ним.
- Новый файл `.github/dependabot.yml`.
- `docs/development.md` (раздел «Git и CI»).

### Conditional

- Комментарии к затронутым параметрам `ci.yml` — только чтобы validator конфигурации проходил.

### Forbidden

- Изменение логики, шагов, версий Node, триггеров, permissions, concurrency и jobs в `ci.yml`.
- Изменение `.github/workflows/harness-integrity.yml`, `package.json`, `.harness/`, runtime-кода.
- Секреты, publish/release-шаги, экосистемы Dependabot кроме `github-actions` (npm и др.).
- Автомерж Dependabot-PR и настройка branch protection.

## Out of scope

- Обновление major-версий actions сверх текущих.
- Dependabot для npm/yarn.
- Другие workflows (release, CodeQL).

## Acceptance criteria

- Все `uses:` в `ci.yml` — полные 40-символьные commit SHA с комментарием `# vN`, соответствующим текущему major; тегов и веток в `uses:` не осталось.
- SHA каждого action проверен как соответствующий тегу major в upstream-репозитории; SHA `actions/checkout` совпадает с пином в `harness-integrity.yml`.
- `.github/dependabot.yml` содержит одну запись `package-ecosystem: github-actions`, `directory: /`, `schedule.interval: weekly`, каждый параметр с комментарием.
- Логика `ci.yml` (шаги, команды, permissions, concurrency, Node 22) не изменилась: diff ограничен строками `uses:` и комментариями к ним.
- `harness-integrity.yml` не изменён; `docs/development.md` описывает SHA-пины и Dependabot.
- Workflow CI на PR зелёный (Quality, Package).

## Verification

- command: `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml`
- command: `yarn typecheck`
- command: `yarn lint`
- command: `yarn format`
- command: `git ls-files --error-unmatch .github/dependabot.yml`
- command: `git diff --check`
- command: `python3 .harness/tools/validate.py --mode manual`
- manual: Workflow CI на PR зелёный (Quality, Package); у каждого параметра .github/dependabot.yml (version, updates, package-ecosystem, directory, schedule, interval) есть комментарий с «Пример:»; файл парсится как YAML и содержит ровно одну запись github-actions / / / weekly; все uses: в ci.yml — 40-символьные SHA с # vN, соответствуют тегам major. Наблюдение GitHub (Insights → Dependency graph → Dependabot) доступно только после merge и не гейтит REVIEW: записывается в Evidence отдельной пометкой после GIT PR FINISH.

## Deliverables

- Обновлённый `.github/workflows/ci.yml`, новый `.github/dependabot.yml`, обновлённая документация CI.

## Implementation plan

### 1. Проверить SHA major-тегов в upstream

- Через gh api repos/actions/<name>/commits/<tag> получить полный 40-символьный SHA для checkout v7, setup-node v7, cache v6, upload-artifact v7; на момент планирования: checkout 3d3c42e5aac5ba805825da76410c181273ba90b1 (совпадает с пином в harness-integrity.yml), setup-node 820762786026740c76f36085b0efc47a31fe5020, cache 55cc8345863c7cc4c66a329aec7e433d2d1c52a9, upload-artifact 043fb46d1a93c77aae656e7c1c64a875d1fc6a0a.
- Перед правкой перепроверить, что теги не сдвинулись; если SHA отличается от указанного — использовать актуальный SHA тега и записать это в Evidence.
- Если тег указывает на annotated tag object, а не на commit, разрешить его до commit SHA (gh api .../git/ref/tags/<tag>, при type=tag — дополнительный запрос git/tags/<sha>).
- Если gh api вернул 404/ошибку — запасной вариант: git ls-remote --tags https://github.com/actions/<name> <tag> (у lightweight-тега SHA сразу указывает на commit; запись ^{} означает annotated tag — брать её SHA).

**Risks:**
- Пин на SHA tag-объекта вместо commit ломает workflow: проверить, что object.type = commit.

### 2. Пины в ci.yml

- Заменить значения uses: (строки для checkout ×2, setup-node ×2, cache, upload-artifact) на actions/<name>@<sha> # vN, комментарий vN — тот же major, что был в теге.
- Комментарии к параметрам uses: обновить в стиле harness-integrity.yml (Пример: actions/checkout@<sha> # v7), чтобы validator конфигурации проходил.
- Остальное в ci.yml не менять: шаги, команды, Node 22, permissions, concurrency, триггеры.

**Files:**
- .github/workflows/ci.yml

**Tests:**
- go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml

**Risks:**
- Случайное изменение логики: проверить git diff — допустимы только строки uses: и комментарии к ним.

### 3. Dependabot

- Создать .github/dependabot.yml: version: 2; updates: одна запись package-ecosystem: github-actions, directory: /, schedule.interval: weekly.
- Каждый параметр (version, updates, package-ecosystem, directory, schedule, interval) снабдить комментарием с «Пример:» в стиле harness-integrity.yml. Validator это НЕ проверяет (documented_config_globs покрывает только .github/workflows/*.yml), поэтому проверяется вручную.
- Других экосистем, automerge и reviewers не добавлять.

**Files:**
- .github/dependabot.yml

**Risks:**
- Untracked файлы validate.py и git diff --check не проверяют: перед Verification выполнить git add .github/dependabot.yml (гейт: git ls-files --error-unmatch .github/dependabot.yml).

### 4. Документация

- В docs/development.md, раздел «Git и CI», добавить: actions в ci.yml пинятся по commit SHA с комментарием # vN; обновление — еженедельными PR Dependabot (github-actions); обновлять SHA вручную не нужно.

**Files:**
- docs/development.md

### 5. Верификация и Evidence

- Прогнать команды Verification; результат записывает dispatcher в generated Evidence.
- Вручную проверить и записать в Evidence: все uses: в ci.yml — 40-символьные SHA с # vN, тегов нет (grep по файлу); SHA каждого action соответствует тегу major (gh api); diff ci.yml ограничен строками uses: и комментариями к ним; harness-integrity.yml не изменён. Дополнительно вручную: у каждого параметра dependabot.yml есть комментарий с «Пример:»; файл парсится как YAML и содержит одну запись github-actions / / / weekly.
- Ручная проверка CI: открыть PR через GIT CHECK > GIT COMMIT > GIT PUSH > GIT PR при STEP в in_progress до REVIEW; в Evidence записать URL/ID запуска и статусы Quality/Package. Наблюдение GitHub о принятии dependabot.yml (Insights → Dependency graph → Dependabot) доступно только после merge и REVIEW не гейтит: записать отдельной пометкой в Evidence после GIT PR FINISH.

**Tests:**
- yarn typecheck
- yarn lint
- yarn format
- git ls-files --error-unmatch .github/dependabot.yml
- git diff --check
- python3 .harness/tools/validate.py --mode manual

## Evidence




<!-- VERIFICATION-EVIDENCE:START -->
- Verification run: 2026-09-24T07:06:57Z
- Status: PASS
- Git head: f58d81f9783d59e57a2b5d656bf04a3a353bf604
- Worktree hash: sha256:ed349bf5f95e41186ec2286cc82059f044331768b017ace2ddc2d68ec160aa20

### Automated verification
- Command: go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/ci.yml
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3896
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn typecheck
  - Status: PASS
  - Exit code: 0
  - Duration ms: 3604
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn lint
  - Status: PASS
  - Exit code: 0
  - Duration ms: 4588
  - stdout sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 0
  - stderr bytes: 0
- Command: yarn format
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1445
  - stdout sha256: 17aa973d3f004560237d9a95171210b0671deff23d61628eecf7322ff5938f20
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 66
  - stderr bytes: 0
- Command: git ls-files --error-unmatch .github/dependabot.yml
  - Status: PASS
  - Exit code: 0
  - Duration ms: 1
  - stdout sha256: b4600e387519995446c16412462cc96e4370c9f9e1e75de764efb24c5cc51d6d
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 23
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
  - Duration ms: 1208
  - stdout sha256: ab1199f147db306b8457c6b85c6ada99138a6755eb293f0d75267807a751c16e
  - stderr sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  - stdout bytes: 424
  - stderr bytes: 0

### Manual verification
- Check: Workflow CI на PR зелёный (Quality, Package); у каждого параметра .github/dependabot.yml (version, updates, package-ecosystem, directory, schedule, interval) есть комментарий с «Пример:»; файл парсится как YAML и содержит ровно одну запись github-actions / / / weekly; все uses: в ci.yml — 40-символьные SHA с # vN, соответствуют тегам major. Наблюдение GitHub (Insights → Dependency graph → Dependabot) доступно только после merge и не гейтит REVIEW: записывается в Evidence отдельной пометкой после GIT PR FINISH.
  - Status: PASS
  - Observed: "PR #13, run https://github.com/ai-development-harness/vscode-harness-navigator/actions/runs/35967618056 (head f58d81f): Quality pass (49s), Package pass (1m31s), Validate Harness pass. Все 6 uses: в ci.yml — @<40 hex> # vN, тегов нет; SHA сверены с git ls-remote (lightweight-теги checkout v7 3d3c42e5, setup-node v7 82076278, cache v6 55cc8345, upload-artifact v7 043fb46d), SHA checkout совпадает с harness-integrity.yml; diff ci.yml — только uses: и комментарии Пример; harness-integrity.yml не изменён. dependabot.yml: yaml.safe_load даёт version 2, одна запись github-actions / / weekly, у всех 6 параметров комментарий с Пример. Наблюдение GitHub по Dependabot доступно только после merge — будет записано в Evidence после GIT PR FINISH."
<!-- VERIFICATION-EVIDENCE:END -->

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.




## Blocker / Failure reason

—
