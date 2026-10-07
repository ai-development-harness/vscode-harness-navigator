# Harness Integrity CI

`Harness Integrity` — baseline CI, который существует ещё до выбора технологического стека проекта.

Полное описание каждого Python validator/gate, его CLI, ключей, exit codes и внутренних contract-модулей находится в [`VALIDATORS.md`](VALIDATORS.md).

Workflow: `.github/workflows/harness-integrity.yml`.

Validator написан на Python и использует только standard library. Минимальная версия — Python 3.11+, потому что структурная проверка TOML опирается на `tomllib`. Это осознанная небольшая tooling dependency Harness, а не зависимость будущего продукта.

Bash не используется как реализация validator: текущие проверки требуют корректного TOML parsing, работы с Git index, glob/path semantics, UTF-8/binary content и структурой skills/configs. Перенос в shell либо ослабил бы эти проверки, либо добавил внешние parser dependencies. Docker также не является обязательным runtime, чтобы локальная validation не зависела от daemon/image/network.

В GitHub Actions версия Python задаётся явно через `actions/setup-python`, а runner закреплён (`ubuntu-24.04`), поэтому CI не меняется молча при смене `ubuntu-latest`.

Workflow запускает baseline validator, public CLI smoke checks и единый discoverable regression runner:

```bash
python3 .harness/tools/validate.py --mode ci
python3 .harness/tools/check-command-references.py --json
python3 .harness/tools/validate-command.py --json -- 'GIT CHECK > COMMIT > PUSH > PR'
python3 .harness/tools/run-self-tests.py
```

`run-self-tests.py` автоматически обнаруживает все `.harness/tools/*-self-test.py`, выполняет их в стабильном порядке и не требует ручного добавления нового regression-файла в workflow. `--list` показывает discovery surface, `--json` возвращает compact aggregate result.

## Harness Integrity и Release Qualification

Harness Integrity остаётся baseline commit-level gate. Он отвечает за structural/repository correctness текущего checkout и запускается на обычных PR/push.

Release Qualification — отдельный release-level contract для **exact candidate SHA**. Canonical executable:

```bash
python3 .harness/tools/release-qualification.py \
  --lane current \
  --expect-sha "$(git rev-parse HEAD)" \
  --json
```

Один executable используется для `current`, `minimum` и `windows` lanes. External release workflow выбирает runner/Python и вызывает этот же entrypoint; core gate list не копируется в maintainer workflow.

PASS Harness Integrity не означает PASS Release Qualification. Release-level result дополнительно собирает downstream upgrade/canary, stress и exact-SHA publish evidence. Подробно: [`RELEASE_QUALIFICATION.md`](RELEASE_QUALIFICATION.md).

GitHub Actions official actions pinned по immutable commit SHA, соответствующим используемому major tag. Harness Integrity запускается для Pull Request в `main`; push-проверка также выполняется только для `main`. Workflow concurrency группируется по номеру Pull Request или ref: новый commit в Pull Request отменяет его устаревший run, а проверки push в `main` не отменяются — каждый merge commit проверяется до конца.

Pull Request проверяется собственным validator-ом из своего же дерева, поэтому изменения trust boundary (`.harness/tools/**`, policy TOML, `.claude/settings.json`, `.codex/**`, `.github/**`) шаг `Flag Harness trust boundary changes` помечает warning-аннотациями для обязательного ручного review (см. `THREAT_MODEL.md`).
Для command transition gate workflow дополнительно проверяет отрицательный case (`GIT PR > COMMIT` обязан завершиться non-zero).

Context budget gate фиксирует размер Harness-controlled always-on instructions до выбора skill. Generated project blocks в `AGENTS.md` учитываются отдельно и не входят в core limit. Текущий baseline: 7 224 chars для Codex и 8 029 chars для Claude Code (после сокращения always-on bootstrap на ~60%). Подробности — в [`TOKEN_ECONOMY.md`](TOKEN_ECONOMY.md).

Отдельный gate границ вычислений модели проверяет, что `.harness/reasoning-boundaries.json` и generated-блок [`REASONING_BOUNDARIES.md`](REASONING_BOUNDARIES.md) совпадают с CTS, а каждый объявленный условный быстрый путь указывает на существующую функцию. Проверка входит в общий `validate.py`, а синтетическая регрессия автоматически обнаруживается `run-self-tests.py`.

Known-issues self-test (`.harness/tools/known-issues-self-test.py`) закрепляет ещё не исправленные defects как XFAIL: каждый case описывает правильное поведение и обязан падать ровно известным symptom-ом. XPASS или другой исход — FAIL, после fix case переносится в постоянный regression suite. Update engine regressions (журнал, recovery при прерывании, handover ownership, marker blocks, reload по загруженным модулям) закреплены в `update-engine-self-test.py`; bridge gate для проектов на v0.8.0 — в `update-migration-self-test.py`.

Repository hardening self-test проверяет validator boundaries на synthetic tracked checkout: фактическую Git ignore semantics через `git check-ignore`, отсутствие ignored/untracked TOML в config surface и containment Codex role configs внутри `.codex/agents`.

Git policy self-test проверяет fail-closed schema boundary через публичный validator: неизвестный/опечаточный safety key не может быть молча проигнорирован.

Git preflight self-test создаёт synthetic repository + bare remote и прогоняет machine gates для protected branch, bootstrap push, feature publish, exact PR head, remote-ahead blocker и clean ff-only sync. `git-pr-action-self-test.py` сохраняет GitHub/`gh` create/reuse regression, а `pr-provider-self-test.py` отдельно проверяет Gitea/`tea`: self-hosted remote parsing, exact-host login selection, ambiguity/auth blockers, exact head/base lookup и secret redaction. Эти regressions не используют реальный GitHub/Gitea network и не создают внешние PR.

Детерминированная самопроверка обновлятора создаёт локальные синтетические source/project Git-репозитории и прогоняет реальный механизм обновления: явное принятие старого проекта, фиксацию неизменяемых тегов, CHECK/APPLY, трёхстороннее слияние, сохранение marker-блоков, владение core/project skills и конфликт при попытке нового core slug занять пользовательский skill. Отдельный сценарий закрепляет поддерживаемую нижнюю границу: `v0.6.0 → v0.7.0 → обязательная перезагрузка → v0.8.0`, включая продолжение с файлами Harness, созданными первым переходом и ещё не добавленными в индекс Git.

Update migration self-test отдельно сохраняет historical compatibility coverage: legacy route/reload boundaries, control-plane relocation, project-owned schema migration/idempotency и release metadata. Оба теста dependency-free и не запускают LLM/agent; real-project dogfood остаётся дополнительным уровнем проверки.

Execution self-test включает multi-process race на одном `execution-status.json`: все writers должны сериализоваться без lost update. Report contract self-test отдельно создаёт несколько immutable reports в один UTC second и доказывает exclusive `O_EXCL` reservation без overwrite.

Execution self-test также проверяет `step-context` во всех трёх фазах: PLAN возвращает exact inputs без dependency-completion requirement, IMPLEMENT отражает BLOCKED→PASS prerequisite transition, REVIEW переиспользует exact specialized gate/repository revision.

Baseline validator детерминированно проверяет schema-v1 planning contracts: configured task/REQ/ADR/OQ paths, strict refs/enums, dependency cycles, type-specific completion proofs, mutation-policy grammar, explicit architecture refs, Ready `context_basis` + отдельный `content_hash` и наличие matching immutable planning-review PASS. Stale context может быть warning на глобальной проверке, но resolver всё равно запрещает конкретный IMPLEMENT до fresh PLAN. `context_basis` schema v4 fingerprint-ит только semantic STEP/dependency contracts, semantic linked REQ/ADR, referenced architecture sections и relevant OQ; reverse traceability, priority/phase и dependency completion state исключены. `content_hash` отдельно fingerprint-ит Implementation plan, а completion proofs direct dependencies проверяются deterministic runtime gate непосредственно перед IMPLEMENT. Семантическую непротиворечивость static gate не угадывает — её доказывает обязательный independent planning-review.

Baseline validator также детерминированно проверяет requirements document model: уникальность `REQ-NNN`, соответствие filename/H1 и обязательных standalone-секций, одинаковый набор REQ в `SPEC.md`/`STATUS.md`, прямые ссылки projections на canonical `REQ-NNN-*.md` и совпадение названий. Смысл requirement validator не интерпретирует.

Проверяются только invariants Harness/repository hygiene. Этот workflow **не должен** пытаться угадать project-specific `test`, `lint`, `typecheck`, `build` или deploy commands.

После `PROJECT INIT` проект добавляет отдельные CI workflows, когда реальные команды известны из repository tooling. Они могут быть связаны с STEP Verification/Release Check, но Harness Integrity остаётся независимым structural gate.

## Локальный запуск

Требуются Git и Python 3.11+:

```bash
python3 .harness/tools/validate.py --mode manual
```

Отдельно посмотреть context budget:

```bash
python3 .harness/tools/context-budget.py
```

`manual` остаётся строгим для обычного состояния, но может разрешить явно распознанное active project schema migration-pending состояние после Harness update как warning. Это нужно только для завершения control-plane hop; `commit` и `ci` такое состояние не принимают. Перед commit необходимо выполнить `PROJECT RECONCILE`.

Для GIT COMMIT / GIT PUSH agent использует:

```bash
python3 .harness/tools/validate.py --mode commit
```

Если Python 3.11+ отсутствует, validator должен считаться недоступным gate, а не молча заменяться частичной shell-проверкой. То же относится к отсутствующему Git binary/repository metadata: проверки tracked state требуют реального Git index, поэтому validator возвращает `HARNESS VALIDATION: BLOCKED` (exit code 2), а не подменяет tracked files содержимым filesystem.

## Настройка

`.harness/harness-policy.toml` определяет required files/skills/agents/commands, forbidden tracked globs, managed formatting paths, максимальный размер tracked file и список self-documented YAML/TOML configs. Для этих configs validator требует комментарий и либо пример, либо описание формата непосредственно рядом с каждым параметром. Ослабляй правило только осознанно; если project действительно должен хранить необычный артефакт, добавь узкое исключение вместо отключения всего класса checks.


## Bounded stress CI

Concurrency/process-sensitive regressions вынесены в `.harness/stress-tests.json` и запускаются единым `run-stress-tests.py`.

Обычный Harness Integrity использует лёгкий explicit budget, чтобы не умножать стоимость каждого PR. Release Qualification/current всегда запускает полный bounded budget 20 iterations. Это не retry mechanism: первый non-zero/timeout scenario делает gate красным.

Первый scenario общего stress contract — regression #256 для concurrent authority fixture cleanup.
