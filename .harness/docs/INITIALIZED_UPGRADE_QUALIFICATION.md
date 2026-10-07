# Initialized Upgrade Qualification

Этот gate проверяет release candidate не на чистом template, а на already initialized downstream-проекте.

## Boundary

Core runner **не получает GitHub credentials и не клонирует private repository по сети**. Caller заранее checkout-ит:

1. exact stable baseline project, например `release-canary`;
2. exact Harness candidate source checkout.

После этого core работает только с локальными paths и disposable clones.

## CLI

~~~bash
python3 .harness/tools/release-upgrade-qualification.py \
  --baseline-project /path/to/release-canary \
  --baseline-sha '<exact-canary-baseline-sha>' \
  --candidate-source /path/to/ai-development-harness-template \
  --candidate-sha '<exact-release-candidate-sha>' \
  --json
~~~

Оба входных checkout должны быть clean. Baseline `HEAD` обязан совпадать с `--baseline-sha`. Candidate commit должен существовать в локальном source repository.

## Candidate должен быть release-prepared

Candidate identity читается **из exact candidate tree**:

- `.harness/harness.lock.json → release/source.ref`;
- `.harness/harness-update-graph.json → latest`.

Runner требует `source.ref == v<release>` и `graph.latest == source.ref`. Обычный feature commit со старой release metadata получает `CANDIDATE_NOT_RELEASE_PREPARED`.

Это важно: qualification предыдущего stable → candidate должна проверять именно тот tree, который готовится к распространению.

## Ephemeral source mirror

Production tag до публикации отсутствует. Для штатного updater это решается без изменения origin:

1. создаётся temporary bare mirror candidate source;
2. `refs/heads/main` mirror направляется на exact candidate SHA;
3. candidate release tag создаётся **только в mirror** и указывает на exact candidate SHA;
4. stable historical tags остаются исходными;
5. canary updater вызывается с maintainer/testing boundary `--source-url <mirror>`.

Таким образом используется реальный immutable-tag update path, но GitHub tag/release до qualification не создаётся.

## Disposable baseline

Canary baseline клонируется локально во временный worktree. Canonical canary checkout не мутируется.

Flow:

~~~text
exact stable canary baseline
        ↓ disposable clone
ephemeral candidate source mirror
        ↓
HARNESS UPDATE APPLY TO candidate
        ↓ repeat after every UPDATER_RELOAD_REQUIRED
deterministic project schema reconcile if pending
        ↓
HARNESS STATUS / HARNESS DOCTOR
validate / full discoverable self-tests
        ↓
project-owned preservation proof
        ↓
repeat exact APPLY
        ↓
NO_UPDATE + no canonical mutation
~~~

Количество reload repeats bounded; unknown updater status fail-closed.

## Project-owned preservation

Runner byte-for-byte сохраняет выбранные durable downstream surfaces:

- все `docs/adr/**`;
- все `planning/init-reviews/**`;
- customized `planning/reviews/TEMPLATE.md`, если существует;
- canary state/baseline/qualification docs, если существуют.

Это минимальный release-level proof, что update/reconcile не переписали accepted decisions, immutable INIT evidence или intentionally customized canary state.

## Schema reconcile

После update runner выполняет `migrate-project-schema.py --check --json`.

Если возвращён `MIGRATION_REQUIRED`, выполняется deterministic migration CLI и повторный check обязан вернуть `CURRENT`.

Это именно deterministic schema part update/reconcile lifecycle. Семантический documentation audit `PROJECT RECONCILE` не подменяет release automation и не нужен для machine release gate.

## Idempotence

После всех gates выполняется тот же exact APPLY второй раз. PASS требует фактический `NO_UPDATE` и `repositoryMutated != true`.

Пустой diff без штатного `NO_UPDATE` недостаточен.

## Host isolation

После disposable run runner повторно проверяет:

- baseline checkout остался на исходном exact SHA и clean;
- candidate source checkout сохранил исходный HEAD и clean.

Mutation source checkout или canonical canary запрещает PASS.

## Machine result

JSON result schema v1 имеет kind `harness_initialized_upgrade_qualification` и связывает:

- exact baseline SHA/release;
- exact candidate SHA/release;
- ordered stage results;
- migration outcome;
- aggregate PASS/FAIL и fail-closed reason.

## Ownership между repositories

- Harness core владеет этим deterministic runner;
- `release-canary` хранит long-lived representative initialized state;
- `maintainer-tools` владеет authenticated private checkout, exact input selection, artifacts/Checks и publish hard gate.

Private App access проверяется в maintainer-tools #7, а не внутри core runner.


## Candidate mirror routing refs

The qualification mirror normalizes both local and remote-tracking refs for the configured candidate default branch to the exact candidate SHA so stale refs cannot shadow candidate update metadata.
