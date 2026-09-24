# Валидаторы и validation gates AI Development Harness

Этот раздел описывает Python-инструменты, которые **проверяют** состояние Harness, project contracts, command protocol, Git mutation preconditions и durable artifacts.

Цель раздела — отделить три разных класса инструментов:

1. **публичные валидаторы и gates** — их можно запускать напрямую из CLI;
2. **внутренние contract-модули** — вызываются агрегирующими валидаторами и другими tools;
3. **self-tests** — проверяют сами валидаторы на synthetic fixtures, но не являются валидаторами пользовательского проекта.

Валидаторы по умолчанию работают fail-closed: отсутствие обязательного входа, повреждённая schema, недоказуемое состояние или ошибка чтения не должны превращаться в PASS.

---

## Общая модель результатов

Используются четыре смысловых результата:

- **PASS** — проверяемый contract доказан;
- **FAIL** — вход читается, но нарушает deterministic contract;
- **DRIFT** — состояние валидно как наблюдение, но отличается от canonical/generated representation;
- **BLOCKED** — проверку нельзя безопасно завершить из-за отсутствующего prerequisite, Git/config/runtime error или недоказуемого состояния.

Конкретный CLI может использовать не все четыре состояния. Exit codes описаны отдельно для каждого entry point.

---

## Канонический шаблон раздела валидатора

Новые public validators/gates документируются в том же порядке:

```text
# N. Название

## Файл / Файлы
## Роль
## Когда использовать
## Что проверяет
## CLI
### Аргументы
## Exit codes
## Примеры
## Внутренние зависимости / Граница ответственности
```

Для internal contract-модуля без CLI сохраняются блоки **Файл → Роль → Когда используется → Что проверяет → Внутренние зависимости / Граница ответственности**. Не нужно придумывать искусственный CLI только ради одинакового шаблона.

---

# 1. Repository integrity validator

## Файл

`.harness/tools/validate.py`

## Роль

Главный агрегирующий валидатор Harness. Это baseline gate для локальной проверки, `GIT COMMIT` и Harness Integrity CI.

Validator проверяет protocol/repository invariants, но **не заменяет product-specific test/lint/build**.

## Когда использовать

- после изменений protocol/tooling/config;
- перед `GIT COMMIT`;
- в Harness Integrity CI;
- после `HARNESS UPDATE APPLY`;
- после `PROJECT RECONCILE`;
- при диагностике повреждённого Harness repository.

## Что проверяет

Основные группы checks:

- schema и обязательные ключи `.harness/harness-policy.toml`;
- tracked files через реальный Git index;
- update graph и release metadata consistency;
- обязательные protocol files, skills, agents и commands;
- active project document model;
- CTS graph и command surface;
- deprecated command references;
- runtime bindings Codex/Claude;
- обязательный Claude project-level `permissions.deny` набор для прямых Git mutations в обход `git-action.py`;
- `.gitignore` semantics через `git check-ignore`;
- forbidden tracked paths/secrets/artifacts;
- UTF-8, final newline, trailing whitespace, merge markers;
- комментарии и примеры у managed YAML/TOML parameters;
- manifest language/review/execution policies;
- Git policy schema и safety semantics;
- configured project artifacts, projections, reports, templates и update lock.

## CLI

```bash
python3 .harness/tools/validate.py [--mode manual|commit|ci]
```

### Аргументы

#### `--mode manual`

Ручная проверка repository.

Особенности manual mode после Harness update:

- целостное legacy migration-pending состояние инициализированного проекта может быть выдано warning, чтобы пользователь смог выполнить `PROJECT RECONCILE`;
- до `PROJECT INIT` target validator на reload boundary может временно принять только доказанный old-release template drift: existing frontmatter values, preamble и sections должны совпадать с current target, отсутствовать могут только новые target keys/sections. Это warning до обязательного reload/repeat APPLY; custom drift остаётся failure.

#### `--mode commit`

Строгий gate перед commit. Legacy project schema не допускается.

Если staged files ещё нет, validator может выдать warning: staging выполняется отдельным Git workflow.

#### `--mode ci`

Самый строгий режим Harness Integrity CI. Legacy migration-pending state не допускается.

## Exit codes

- `0` — PASS;
- `1` — deterministic validation failures;
- `2` — BLOCKED/bootstrap failure, например недоступный Git index или критически повреждённый bootstrap config.

## Примеры

```bash
python3 .harness/tools/validate.py --mode manual
python3 .harness/tools/validate.py --mode commit
python3 .harness/tools/validate.py --mode ci
```

## Внутренние зависимости

Validator агрегирует `project_integrity.py`, `planning_contract.py`, `review_contract.py`, `report_contract.py`, `projection_contract.py`, `template_contract.py`, CTS и config layer.


`HARNESS DOCTOR` не заменяет этот validator: он использует его как required health check и дополнительно показывает dependency/capability availability. Отсутствующий optional runtime или `gh` не превращает validator/Doctor в failure, если core Harness исправен.

Harness UX regression отдельно выполняет `.harness/tools/harness-ux-self-test.py`, который проверяет STEP LIST/SHOW и RESUME semantics на synthetic repository.

---

# 2. Command Transition System validator

## Файлы

- CLI: `.harness/tools/validate-command.py`
- engine: `.harness/tools/command_transitions.py`

## Роль

Проверяет **структуру пользовательской Harness-команды** до skill routing и выполнения.

Он отвечает только на вопросы:

- существует ли команда;
- корректен ли target/input;
- допустима ли chain syntax;
- существует ли каждый transition;
- какие runtime preconditions объявлены transition graph.

Он **не проверяет** фактический Git/STEP/update runtime state.

## Когда использовать

- перед dispatch любой canonical command;
- при изменении `.harness/command-transitions.json`;
- в CI как positive/negative CTS regression;
- при диагностике неправильной command chain.

## CLI

```bash
python3 .harness/tools/validate-command.py [--json] -- '<COMMAND>'
```

Можно передать command tokens и без `--`, но `--` рекомендуется для chains и аргументов, начинающихся с дефиса.

### Аргументы

- positional `command` — команда или chain;
- `--json` — machine-readable result.

## Exit codes

- `0` — command/chain structurally valid;
- `2` — invalid command/target/input/transition.

## Примеры

```bash
python3 .harness/tools/validate-command.py -- 'STEP PLAN STEP-001 > IMPLEMENT > REVIEW'
python3 .harness/tools/validate-command.py --json -- 'GIT CHECK > COMMIT > PUSH > PR'
python3 .harness/tools/validate-command.py -- 'GIT PR > COMMIT'
```

Последний пример должен завершиться non-zero: обратного PR → COMMIT edge нет.

## Engine checks

`command_transitions.py` валидирует:

- `schemaVersion`;
- validation order;
- chain separator;
- DOMAIN names;
- command uniqueness;
- target/input vocabulary;
- continuation aliases;
- transition source/target;
- allowed previous results;
- known runtime preconditions;
- duplicate/ambiguous edges;
- parsing и normalization raw command text.

Общий `validate.py` дополнительно проверяет cross-file contract поля `documentation`: формат `<path>#<anchor>`, repository-contained path, существование файла, уникальность ссылки и ровно один explicit `<a id="...">` в target Markdown.

---

# 2A. Stateful command dispatcher

## Файлы

- CLI: `.harness/tools/harness-dispatch.py`
- engine: `.harness/tools/command_dispatch.py`
- regression: `.harness/tools/command-dispatch-self-test.py`

## Роль

Canonical runtime boundary между raw Harness command и semantic моделью. Объединяет CTS structural gate, execution state, continuation и machine-readable dispatch metadata.

## Когда использовать

- для любого пользовательского canonical command в обычном runtime;
- для resume interrupted execution;
- при тестировании command→skill routing;
- при разработке нового deterministic command handler.

## CLI

```bash
python3 .harness/tools/harness-dispatch.py start --command '<raw command>'
python3 .harness/tools/harness-dispatch.py complete --root '<root>' --command '<command>' --result PASS
python3 .harness/tools/harness-dispatch.py resume [--root '<root>']
python3 .harness/tools/harness-dispatch.py route --command '<canonical command>'
```

По умолчанию output compact JSON; `--pretty` предназначен для ручной диагностики.

## Что доказывает/делает

- invalid chain не создаёт execution;
- command routing берётся только из CTS `dispatch` metadata;
- deterministic handlers, включая mutating `GIT SYNC` / `GIT PR FINISH`, завершаются без LLM;
- semantic node возвращает exact `skillPath`;
- PLAN/IMPLEMENT/REVIEW получают exact phase context через `step_context.py`;
- `complete` автоматически разрешает следующий chain segment;
- `resume` не создаёт ложную root execution для `HARNESS RESUME`;
- dispatch error fail-closed блокирует active execution.

Dispatcher не интерпретирует product semantics и не выполняет semantic skill вместо модели.

## Exit codes

- `0` — deterministic DONE/PASS/SUCCESS, semantic handoff или другой неблокирующий result;
- `1` — BLOCKED.

---

# 3. Deprecated command reference checker

## Файлы

- CLI: `.harness/tools/check-command-references.py`
- scanner: `.harness/tools/command_references.py`

## Роль

Ищет в **live project documentation** старые pre-namespace Harness commands и показывает canonical replacement.

Например, checker распознаёт старые pre-namespace формы planning, Git и self-update команд и для каждого finding возвращает соответствующую canonical namespaced command.

Historical examples могут содержать старую syntax намеренно; scanner только фиксирует match, а решение о drift принимает caller.

## Когда использовать

- после protocol rename;
- при `PROJECT RECONCILE`;
- в Harness Integrity CI;
- перед массовой синхронизацией docs.

## CLI

```bash
python3 .harness/tools/check-command-references.py [--json]
```

### Аргументы

- `--json` — machine-readable result с path, line, legacy, canonical и excerpt.

## Exit codes

- `0` — checker успешно отработал, независимо от PASS/DRIFT;
- `2` — BLOCKED: live document нельзя безопасно прочитать или определить scope.

Почему DRIFT возвращает `0`: наличие deprecated reference является audit result, а не runtime failure checker-а.

## Примеры

```bash
python3 .harness/tools/check-command-references.py
python3 .harness/tools/check-command-references.py --json
```

---

# 4. Durable operational report validator

## Файл

`.harness/tools/report_contract.py`

## Роль

Проверяет schema и immutable naming contract operational reports.

Поддерживаемые `kind`:

- `audit`;
- `release_check`;
- `skill_search`;
- `harness_update`.

Migration и STEP/planning reviews проверяются `review_contract.py`.

## Когда использовать

- после создания durable report;
- при диагностике Harness Integrity failure;
- при разработке нового report writer;
- перед использованием report как trust/evidence artifact.

## CLI

Проверить все operational reports:

```bash
python3 .harness/tools/report_contract.py --all [--json]
```

Проверить один report:

```bash
python3 .harness/tools/report_contract.py \
  --file <repository-relative-path> \
  --kind audit|release_check|skill_search|harness_update \
  [--json]
```

### Аргументы

- `--all` — проверить все configured operational report directories;
- `--file` — repository-relative path одного report;
- `--kind` — validator для конкретного report kind;
- `--json` — вывести `{"valid": ..., "errors": [...]}`.

Absolute path и `..` запрещены.

## Exit codes

- `0` — report contract valid;
- `1` — report contract invalid;
- argparse errors — стандартный exit code argparse.

## Примеры

```bash
python3 .harness/tools/report_contract.py --all
python3 .harness/tools/report_contract.py --all --json

python3 .harness/tools/report_contract.py \
  --file planning/releases/RELEASE-20260921T080000Z.md \
  --kind release_check

python3 .harness/tools/report_contract.py \
  --file planning/harness-updates/UPDATE-20260921T080000Z.md \
  --kind harness_update \
  --json
```

## Что проверяется

Общие invariants:

- symlink запрещён;
- `schema: 1`;
- ожидаемый `kind`;
- обязательные metadata;
- canonical filename;
- filename timestamp == `created_at`;
- обязательный H1;
- обязательные non-empty sections.

Каждый report kind добавляет собственные fields и semantic constraints.

---

# 5. Projection validator

## Файлы

- CLI: `.harness/tools/sync-projections.py`
- engine: `.harness/tools/projection_contract.py`

## Роль

Доказывает, что tracked projections byte-for-byte соответствуют canonical REQ/STEP/OQ state.

Проверяются:

- requirements `SPEC.md`;
- requirements `STATUS.md`;
- roadmap;
- project status;
- Open Questions index.

## Когда использовать

- после изменения REQ/STEP/OQ;
- после migration/reconcile;
- перед INIT finalization;
- при Harness Integrity failure `projection drift`.

## CLI: read-only check

```bash
python3 .harness/tools/sync-projections.py --check [--json]
```

### Аргументы

- `--check` — только сравнить projections, ничего не менять;
- `--json` — machine-readable result.

## CLI: regeneration

Без `--check` tool является mutator:

```bash
python3 .harness/tools/sync-projections.py [--json]
```

## Exit codes

В `--check`:

- `0` — PASS;
- `1` — DRIFT.

В mutation mode:

- `0` — UPDATED/no blocking derivation problem;
- `2` — BLOCKED: canonical state нельзя безопасно превратить в projection.

## Примеры

```bash
python3 .harness/tools/sync-projections.py --check
python3 .harness/tools/sync-projections.py --check --json
python3 .harness/tools/sync-projections.py --json
```

## Fail-closed derivation

Malformed canonical REQ/STEP, недоступный completion proof или ошибка relevant OQ не трактуются как «пустой»/planned state. Engine возвращает derivation error.

---

# 6. PROJECT INIT finalization gate

## Файл

`.harness/tools/finalize-project-init.py`

## Роль

Финальный deterministic gate PROJECT INIT.

`--check` проверяет готовность без mutation. Без `--check` tool атомарно выставляет `project.initialized=true` только после PASS всех prerequisites.

## Когда использовать

- в конце PROJECT INIT;
- для диагностики, почему INIT не может завершиться;
- после правок REQ/STEP/OQ/projections/init-review.

## CLI

Read-only:

```bash
python3 .harness/tools/finalize-project-init.py \
  --name '<project-name>' \
  --check \
  [--json]
```

Finalize:

```bash
python3 .harness/tools/finalize-project-init.py \
  --name '<project-name>' \
  [--json]
```

### Аргументы

- `--name` — обязательное имя проекта;
- `--check` — только проверить preconditions;
- `--json` — machine-readable output.

## Preconditions

Gate проверяет:

- `project.initialized == false`;
- непустое имя;
- отсутствие pending legacy schema;
- наличие project overview;
- минимум один настоящий canonical REQ;
- отсутствие template REQ;
- минимум один STEP;
- полный project integrity;
- projections;
- PASS INIT reviews для `requirements` и `roadmap`;
- отсутствие open PROJECT-level OQ.

## Exit codes

- `0` — PASS/INITIALIZED;
- `1` — BLOCKED.

Mutation mode имеет rollback: если postcondition после записи manifest не проходит, исходный manifest восстанавливается.

---

# 7. Specialized review gate

## Файл

`.harness/tools/review_gates.py`

Regression suite: `.harness/tools/review-gates-self-test.py`.

## Роль

Read-only preselector: определяет, нужны ли для STEP REVIEW специализированные `security` и/или `tests` reviewers.

Это не semantic reviewer. Tool только вычисляет обязательный набор проверок из deterministic facts.

## Когда использовать

- перед STEP REVIEW;
- при подготовке review metadata;
- при диагностике, почему security/tests review обязателен.

## CLI

```bash
python3 .harness/tools/review_gates.py STEP-NNN [--json]
```

### Аргументы

- positional `step_id`;
- `--json` — вывести required/reasons/changedPaths/surfaceMode/basis.

## Что учитывается

- `review.security` и `review.tests` policy;
- STEP type;
- `risk_flags`;
- changed Git paths, полученные NUL-delimited (`-z`) без Git path quoting/line splitting; Unicode, пробелы, tab/newline и trailing whitespace сохраняются как часть exact path;
- security-sensitive path patterns;
- test/code surface patterns;
- clean-tree fallback.

Clean-tree fallback fail-closed требует security + tests, потому что один последний commit не доказывает полный implementation surface STEP.

Path transport является отдельным safety invariant: collector читает `git diff`, `git diff --cached`, `git ls-files` и `git diff-tree` через NUL framing. Invalid UTF-8 path не подменяется escaped/замещённой строкой и считается caller-level blocker.

## Exit code

- `0` — gate успешно вычислен;
- unhandled config/document/Git errors считаются caller-level blocker.

## Примеры

```bash
python3 .harness/tools/review_gates.py STEP-042
python3 .harness/tools/review_gates.py STEP-042 --json
```

---

# 8. Deterministic Git preflight

## Файлы

- public wrapper: `.harness/tools/git-preflight.py`;
- engine: `.harness/tools/git_preflight.py`.

## Роль

Read-only safety gate перед Git mutations.

Tool **не выполняет commit/push/PR/merge**. Разрешён только configured `git fetch` для актуализации remote refs. На PASS возвращается exact mutation plan.

## Когда использовать

- перед `GIT CHECK`;
- перед `GIT COMMIT`;
- перед `GIT PUSH`;
- перед `GIT PR`;
- перед `GIT PR FINISH`;
- перед `GIT SYNC`.

## CLI

```bash
python3 .harness/tools/git-preflight.py \
  check|commit|push|pr|pr-finish|sync \
  [--json] \
  [--commit-type <type>] \
  [--slug <slug>]
```

### Аргументы

- action — `check`, `commit`, `push`, `pr`, `pr-finish`, `sync`;
- `--json` — machine-readable PASS/BLOCKED result;
- `--commit-type` — Conventional Commit type для deterministic branch planning;
- `--slug` — semantic branch slug; используется вместе с `commit`.

`--commit-type` и `--slug` значимы только для commit preflight.

## Exit codes

- `0` — PASS;
- `2` — BLOCKED/config/IO/Git error.

## Примеры

```bash
python3 .harness/tools/git-preflight.py check --json

python3 .harness/tools/git-preflight.py \
  commit --commit-type feat --slug user-export --json

python3 .harness/tools/git-preflight.py push --json
python3 .harness/tools/git-preflight.py pr --json
python3 .harness/tools/git-preflight.py pr-finish --json
python3 .harness/tools/git-preflight.py sync --json
```

## Safety invariants

Engine проверяет:

- strict `.harness/git-policy.toml`;
- attached branch;
- protected branches;
- staged/unstaged/untracked state;
- initial bootstrap exceptions;
- configured remote;
- exact ahead/behind;
- unconditional remote-ahead blocker при `force=never`;
- published PR head equality;
- PR base/template/tool availability;
- merged-PR provider state, local PR state, safe return-branch ff-only и non-force branch deletion для `pr-finish`;
- ff-only sync;
- Harness validator перед mutation, если это требует policy.

---

## Deterministic Git mutation executor

Файлы:

- `.harness/tools/git_action.py` — engine;
- `.harness/tools/git-action.py` — CLI wrapper.

Preflight отвечает на вопрос «разрешена ли mutation», executor — «как выполнить уже одобренную mechanical mutation и доказать postcondition».

```bash
python3 .harness/tools/git-action.py commit --json \
  --commit-type feat \
  --slug user-search \
  --message-file .harness/local/git/commit-message.txt
python3 .harness/tools/git-action.py push --json
python3 .harness/tools/git-action.py pr --body-file .harness/local/git/pr-body.md --json
python3 .harness/tools/git-action.py sync --json
python3 .harness/tools/git-action.py pr-finish --json
```

Executor повторяет canonical preflight непосредственно перед mutation. Semantic commit/PR inputs сначала читаются и проверяются Harness-ом как exact snapshot; primary `git`/`gh` consumer получает captured text через stdin (`git commit -F -`, `gh pr create --body-file -`) и не переоткрывает mutable source path. Original local input после postcondition очищается отдельно по identity-safe lifecycle.

- COMMIT создаёт только exact `requiredBranch`, если protected-branch preflight потребовал его; message file разрешён только под `.harness/local/git/`; postcondition — новый HEAD.
- PUSH исполняет только returned non-force argv; postcondition — configured remote branch совпадает с local HEAD.
- PR принимает semantic body/title только из `.harness/local/git/**`, сам ищет/reuse/create provider PR, сверяет exact head OID и сохраняет local PR state.
- SYNC разрешает только report/noop или exact `git merge --ff-only`; postcondition — local HEAD совпадает с configured remote.
- PR FINISH исполняет ordered exact steps, проверяет return branch и удаление verified local PR branch; local PR state удаляется только после полного успеха.

Exit codes: `0` — SUCCESS; `2` — BLOCKED/preflight/mutation/postcondition failure.

---

# 9. Internal project integrity aggregator

## Файл

`.harness/tools/project_integrity.py`

## Роль

Собирает в один список ошибки project document model.

Прямого CLI нет. Основной caller — `validate.py` и INIT finalization.

## Основные проверки

- planning contracts;
- canonical REQ;
- canonical ADR;
- review/migration reports;
- operational reports;
- projections;
- project-owned templates;
- initialized project invariants;
- configured artifacts;
- Harness update lock.

### `allow_legacy`

Используется только для строго распознанного migration-pending manual state. В strict modes legacy active documents блокируются.

### `ci_mode`

Передаётся в report/review validation для CI-specific immutable checks.

---

# 9A. Deterministic STEP NEXT resolver

## Файлы

- engine: `.harness/tools/step_next.py`
- CLI: `.harness/tools/step-next.py`
- regression: `.harness/tools/step-next-self-test.py`

## Роль

Возвращает один explainable next-step recommendation без LLM ranking.

Стабильный порядок:

1. resumable STEP execution;
2. in-progress перед planned;
3. `critical > high > medium > low`;
4. больший transitive downstream impact;
5. больше explicit non-`none` risk flags — только visibility tie-breaker, не severity score;
6. canonical roadmap order.

Для STEP без Ready plan dependency completion не блокирует `STEP PLAN`. Для Ready plan `STEP IMPLEMENT` допускается только при PASS `implementation_prerequisite_failures`. Current exact FAIL review маршрутизируется в `STEP FIX`.

## CLI

```bash
python3 .harness/tools/step-next.py
python3 .harness/tools/step-next.py --pretty
```

PASS возвращает exact `command`, selected candidate, compact alternatives и ranking breakdown. При отсутствии executable STEP возвращается `BLOCKED/NO_EXECUTABLE_STEP` с ограниченным списком blockers.


---

# 10. Planning contract validator

## Файл

`.harness/tools/planning_contract.py`

## Роль

Static validator и fingerprint engine для REQ/ADR/OQ/STEP planning model.

Прямого пользовательского CLI у модуля нет.

## Что проверяет

- canonical IDs и filenames;
- schema/enums;
- mandatory STEP sections;
- dependencies;
- REQ/ADR refs;
- architecture refs;
- risk flags;
- mutation policy structure;
- unresolved placeholders;
- dependency cycles;
- type-specific completion proofs: каждый STEP со `status=completed` обязан иметь durable proof; тот же proof используется lifecycle/projections и `STEP IMPLEMENT` runtime gate; completion state не входит в schema-v4 planning basis;
- relevant OQ blockers;
- `plan.context_basis`;
- `plan.content_hash`;
- matching planning-review PASS;
- INIT review basis.

Semantic качество плана static validator не оценивает — его подтверждает independent planning-review.

### Phase-specific STEP context manifest

Файлы:

- `.harness/tools/step_context.py` — engine;
- `.harness/tools/step-context.py` — CLI wrapper.

Tool не суммаризирует документы. Он детерминированно разрешает exact canonical paths и phase-specific facts:

```bash
python3 .harness/tools/step-context.py STEP-NNN --phase plan --json
python3 .harness/tools/step-context.py STEP-NNN --phase implement --json
python3 .harness/tools/step-context.py STEP-NNN --phase review --json
```

Общий result содержит `step`, `semanticInputs` и уникальный `readPaths`. Модель читает только эти canonical artifacts плюс действительно relevant code/tests/config.

- `plan` возвращает current schema-v4 `contextBasis`, `planContentHash` и явно сообщает, что dependency completion на этой фазе не требуется;
- `implement` возвращает deterministic `implementPrerequisites PASS|BLOCKED` с точными failures;
- `review` возвращает specialized-review gate и exact repository revision.

`--root <path>` предназначен для tests/tooling; обычный runtime использует repository root, содержащий tool. `--json` выдаёт компактный machine-readable JSON без pretty-print overhead.


---

# 10A. Deterministic STEP Verification runner

## Файлы

- engine: `.harness/tools/verification.py`
- CLI: `.harness/tools/verify-step.py`
- regression: `.harness/tools/verification-self-test.py`

## Роль

Исполняет machine-executable `## Verification` без LLM и формирует factual generated Evidence.

## Contract

- `- command: \`...\`` — argv-команда, запускаемая напрямую без shell;
- `- manual: ...` — действительно неавтоматизируемая semantic/visual проверка;
- shell control operators не разрешены; сложную проверку нужно вынести в repository script. Это защита от случайного shell-синтаксиса, а не sandbox: commands — доверенная часть STEP contract и исполняются с правами текущего пользователя;
- command запускается в отдельной process group; по timeout и после завершения lead process вся group завершается, фоновые процессы не переживают Verification;
- stdout/stderr читаются потоково: SHA-256 и byte count считаются по всему выводу, в памяти хранится только bounded tail;
- timeout берётся из `execution.verificationCommandTimeoutSeconds`;
- repository revision до/после каждой command обязана совпасть (`VERIFICATION_MUTATED_REPOSITORY`); refs и HEAD тоже (`VERIFICATION_MUTATED_REFS`);
- PASS Evidence хранит exit code, duration, stdout/stderr SHA-256 и byte counts; raw successful output не загружается в model context;
- FAIL может вернуть короткий diagnostic tail;
- manual checks не считаются PASS без exact supplied observation.

## CLI

```bash
python3 .harness/tools/verify-step.py STEP-NNN
python3 .harness/tools/verify-step.py STEP-NNN --manual-json '[{"check":"...","status":"PASS","observed":"..."}]'
```

По умолчанию CLI обновляет только generated `VERIFICATION-EVIDENCE` block в STEP Evidence. `--no-write-evidence` оставляет artifact неизменным.

## Exit codes

- `0` — PASS;
- `1` — FAIL или MANUAL_REQUIRED;
- `2` — BLOCKED.

---

# 10B. Structured semantic artifact writers

## Файлы

- engine: `.harness/tools/semantic_artifacts.py`
- CLI: `.harness/tools/semantic-writer.py`
- regression: `.harness/tools/semantic-artifacts-self-test.py`

## Роль

Модель принимает semantic решения, но не форматирует canonical STEP/report artifacts вручную.

Поддерживаются:

- `plan-draft` — structured Implementation plan + Verification → mutation только соответствующих STEP sections и `plan.status=draft`;
- `planning-review` — verdict/findings/rationale → immutable planning-review с exact fingerprints; PASS atomically handoff-ится в canonical Ready stamp;
- `step-review` — structured findings/verdict/specialized results → immutable STEP review с exact repository revision и deterministic gate metadata.

## Payload boundary

`implementationPlan` — массив structured steps: `title`, `actions[]`, optional `files[]/tests[]/risks[]`. Markdown headings/lists рендерит Python.

Writer принимает payload через stdin (`--payload-file -`) либо regular JSON file только под `.harness/local/**`. Неожиданные keys, multiline structural fields и inconsistent verdict/findings блокируются fail-closed.

Для одноразового semantic transport предпочтителен stdin. Если используется local payload-файл, `semantic-writer.py` принимает только regular lexical path под `.harness/local/**` без symlink-компонентов. После нормального завершения writer удаляется только тот же неизменённый file identity; parsing/validation/write failure сохраняет payload для retry. Если secondary cleanup невозможен или path успел измениться, primary PASS/FAIL не откатывается — writer возвращает cleanup warning и оставляет файл.

## Trust chain

- timestamp/name резервируются через `O_CREAT|O_EXCL`;
- model не задаёт `context_basis`, `plan_content_hash`, repository revision или specialized gate basis;
- generated report до возврата результата проходит canonical validator;
- writer возвращает exact `completionResult`, который execution layer использует без повторного reasoning.


---

# 11. Machine-readable Markdown document contract

## Файл

`.harness/tools/document_contract.py`

## Роль

Низкоуровневый parser/validator schema-v1 Markdown documents.

Прямого CLI нет.

## Основные функции

- ограниченный YAML frontmatter parsing/serialization с round-trip type safety;
- fenced-aware ATX heading scanner;
- `##` section parsing без ложных boundaries внутри fenced code;
- duplicate section detection;
- H1 extraction;
- schema/kind checks;
- mandatory non-empty sections;
- unresolved placeholder detection;
- stable/content hashes;
- durable report timestamp identity;
- immutable durable report create через `O_CREAT|O_EXCL` без overwrite race;
- atomic UTF-8 writes.

Все более высокоуровневые validators должны использовать этот module вместо собственных несовместимых Markdown/YAML parsers.

`validate.py` для skill/Claude-agent frontmatter также вызывает canonical `split_frontmatter()` из `document_contract.py`; отдельного упрощённого YAML parser в агрегаторе больше нет.

`markdown_headings()` является общей structural primitive для machine-readable Markdown. Architecture refs используют тот же scanner, поэтому fenced examples не могут тихо обрезать planning fingerprint.

---

# 12. Review and migration report contract

## Файл

`.harness/tools/review_contract.py`

## Роль

Проверяет immutable review history и trust proofs.

Прямого CLI нет; используется project integrity, execution/review workflows и migration.

## Что проверяет

- migration reports;
- legacy review hash pins;
- implementation review schema;
- reviewed repository revision: dirty fingerprint включает Git path/status, index mode+object id, worktree mode/content/symlink и submodule HEAD;
- reviewer role/verdict/findings;
- specialized security/tests evidence;
- planning/init review references;
- durable report filename/created_at identity;
- immutable history: tracked durable reports нельзя изменить, удалить или rename.

## CLI

Проверить всю review history:

```bash
python3 .harness/tools/review_contract.py [--json]
```

Проверить все reviews одного STEP:

```bash
python3 .harness/tools/review_contract.py \
  --step STEP-NNN \
  [--json]
```

Проверить один report:

```bash
python3 .harness/tools/review_contract.py \
  --file <repository-relative-path> \
  [--current-revision] \
  [--json]
```

### Аргументы

- `--file` — repository-relative path одного review report;
- `--step` — проверить все `REVIEW-*.md` configured STEP review directory;
- `--current-revision` — для `--file` дополнительно потребовать, чтобы reviewed revision и specialized gate соответствовали **текущему** repository state;
- `--json` — machine-readable `status/errors`.

Если не заданы ни `--file`, ни `--step`, запускается полный `validate_all_review_reports()`.

Absolute path и `..` для `--file` запрещены.

## Exit codes

- `0` — PASS;
- `1` — FAIL.

## Примеры

```bash
python3 .harness/tools/review_contract.py --json

python3 .harness/tools/review_contract.py \
  --step STEP-042 \
  --json

python3 .harness/tools/review_contract.py \
  --file planning/reviews/STEP-042/REVIEW-20260921T120000Z.md \
  --current-revision \
  --json
```

## Почему это отдельный contract

PASS review является доказательством только для **точной revision/fingerprint**. Поэтому review validation нельзя заменять наличием файла или mutable `latest verdict` field.

---

# 13. Projection contract

## Файл

`.harness/tools/projection_contract.py`

## Роль

Строит canonical projections и сравнивает tracked copies с ожидаемым content.

Прямой CLI предоставляется wrapper-ом `sync-projections.py`.

## Validator

`validate_projections(root)`:

- вычисляет все projections;
- fail-closed возвращает derivation failure;
- проверяет наличие tracked files;
- проверяет UTF-8;
- требует byte-for-byte equality.

---

# 14. Project template contract

## Файл

`.harness/tools/template_contract.py`

## Роль

Определяет canonical schema-v1 content project-owned templates и проверяет существующие templates.

Прямого CLI нет.

Validator следит, чтобы STEP/REQ/ADR/OQ/review/report templates соответствовали текущей document schema и не создавали заведомо невалидные artifacts.

Project templates принадлежат проекту после INIT, поэтому их mutation выполняет explicit reconciliation flow, а не silent self-update. До INIT действует bootstrap baseline: strict validation требует exact current template, кроме узкого manual update postcondition на reload boundary. Там допускается только semantic-subset proof старого release; после reload updater выполняет exact alignment и повторная strict validation обязана пройти.

---

# 15. Execution Status schema validator

## Файл

`.harness/tools/execution_status.py`

## Роль

Модуль в целом управляет crash-safe local execution state; validation-часть представлена `validate_status()`.

Прямого validator CLI нет.

## Что проверяет `validate_status()`

Current execution state использует schema v2. Validator проверяет active execution records, monotonic ordinals, bounded `recentTerminals`, optional `current.details` как JSON object с hard limit **16 KiB compact UTF-8 JSON**, `stepRecovery` baseline shape **и совпадение recovery key с `implementationBaseline.stepId`**, а также `nextOrdinal`. Legacy schema v1 остаётся только входом deterministic migration: сначала валидируется v1, затем строится/валидируется v2 и только после этого выполняется atomic replace. Повреждённый legacy state не превращается в empty state.


- `schemaVersion`;
- массив executions;
- уникальность `executionId`;
- mode/status;
- root command;
- sequence;
- current command/status/result;
- attempt;
- fix/review cycle counter.

`load_status()` и `save_status()` всегда вызывают schema validation, поэтому повреждённый local state не трактуется как пустой.

Public execution-state mutations держат advisory lock на всю transaction `load → mutate → save`. Self-test запускает параллельные процессы и проверяет отсутствие lost update/duplicate running record.

---

# 16. Config parser as validation boundary

## Файл

`.harness/tools/harness_config.py`

## Роль

Это не самостоятельный CLI-валидатор, но обязательный fail-closed config boundary для остальных validators.

## Что проверяется

- ограниченный YAML subset manifest/frontmatter;
- duplicate keys;
- indentation;
- запрещённые YAML features;
- repository-relative path containment;
- language tags;
- review/execution/skill policy values;
- configured paths;
- Git/update TOML loading.

Validator-ы должны использовать этот layer, а не повторять parsing path/config semantics самостоятельно.

---

# 17. Always-on context budget

## Файлы

- `.harness/tools/context_budget.py` — implementation;
- `.harness/tools/context-budget.py` — CLI wrapper;
- `.harness/tools/context-budget-self-test.py` — synthetic regression suite.

## Роль

Dependency-free gate фиксирует верхнюю границу Harness-controlled текста, который runtime получает до выбора command-specific skill. Он не оценивает semantic качество инструкций и не использует tokenizer конкретной модели.

## Когда использовать

- после изменения `AGENTS.md` или `CLAUDE.md`;
- при рефакторинге bootstrap/routing instructions;
- в Harness Integrity CI;
- при анализе token economy перед release.

## Что проверяет

- Codex controlled budget: `AGENTS.md` без generated `PROJECT-CONTEXT`/`SKILL-ROUTING`;
- Claude controlled budget: тот же controlled `AGENTS.md` + `CLAUDE.md`;
- корректность marker boundaries: malformed/duplicate START/END дают FAIL;
- наличие и UTF-8 читаемость always-on files;
- отсутствие роста controlled context выше текущего post-refactor ceiling: 7 224 chars для Codex и 8 029 chars для Claude.

`projectChars` и `observedChars` возвращаются для диагностики, но project-owned generated blocks не расходуют core Harness budget.

## CLI

```bash
python3 .harness/tools/context-budget.py [--json] [--root <path>]
```

### Аргументы

- `--json` — machine-readable результат;
- `--root <path>` — явно задать repository root; по умолчанию используется repository, содержащий tool.

## Exit codes

- `0` — PASS;
- `1` — budget/missing-file/marker contract FAIL;
- `2` — ошибка CLI arguments (`argparse`).

## Примеры

```bash
python3 .harness/tools/context-budget.py
python3 .harness/tools/context-budget.py --json
```

## Внутренние зависимости / Граница ответственности

Tool использует только Python stdlib и считает Unicode characters, а не model-specific tokens. Он измеряет bootstrap overhead Harness, но не запрещает project-owned context. `validate.py` вызывает тот же `evaluate_context_budget()` как часть baseline integrity gate.

Подробные правила token economy описаны в [`TOKEN_ECONOMY.md`](TOKEN_ECONOMY.md).

---

# 17A. Карта границ вычислений модели

## Файлы

- `.harness/tools/reasoning_boundaries.py` — движок;
- `.harness/tools/reasoning-boundaries.py` — командная обёртка;
- `.harness/tools/reasoning-boundaries-self-test.py` — регрессионная проверка;
- `.harness/reasoning-boundaries.json` — машиночитаемая проекция;
- `.harness/docs/REASONING_BOUNDARIES.md` — человекочитаемая таблица и диаграммы.

## Роль

Проверяет и публикует границу между смысловой работой модели и детерминированными скриптами для каждой канонической команды.

Источник истины — `.harness/command-transitions.json → reasoning`. Проекции не являются самостоятельным состоянием и вручную не редактируются.

## Когда использовать

- после изменения `dispatch` любой команды;
- после добавления или удаления быстрого пути;
- после переноса работы из модели в скрипт или обратно;
- перед выпуском новой версии Harness;
- при подготовке внешней документации на основе машиночитаемой проекции.

## Что проверяет

- у каждой команды есть режим `none | required | conditional`;
- детерминированная команда имеет только `mode=none`;
- команда с обязательной моделью перечисляет её смысловую работу;
- у условной команды есть хотя бы один быстрый путь;
- каждый быстрый путь ссылается на существующую функцию в `.harness/tools/*.py`;
- `.harness/reasoning-boundaries.json` точно соответствует таблице команд;
- generated-блок `REASONING_BOUNDARIES.md` точно соответствует таблице команд.

## CLI

```bash
python3 .harness/tools/reasoning-boundaries.py
python3 .harness/tools/reasoning-boundaries.py --json
python3 .harness/tools/reasoning-boundaries.py --check
python3 .harness/tools/reasoning-boundaries.py --write
```

### Аргументы

- `--json` — вывести текущую машиночитаемую проекцию;
- `--check` — проверить проекции и ссылки на быстрые пути без изменений;
- `--write` — пересобрать Markdown и JSON из таблицы команд.

`--check` и `--write` взаимоисключающие.

## Exit codes

- `0` — схема, быстрые пути и проекции согласованы;
- `1` — обнаружена ошибка схемы, отсутствующий быстрый путь или устаревшая проекция;
- `2` — ошибка аргументов командной строки.

## Примеры

После переноса части команды из модели в скрипт:

```bash
python3 .harness/tools/reasoning-boundaries.py --write
python3 .harness/tools/validate.py --mode manual
```

Проверка без изменений:

```bash
python3 .harness/tools/reasoning-boundaries.py --check
```

## Внутренние зависимости / Граница ответственности

Инструмент не решает, нужна ли модели смысловая работа. Это архитектурное решение фиксируется в CTS. Инструмент только проверяет структуру, существование заявленных функций и точность проекций.

Общий `validate.py` вызывает ту же проверку, поэтому рассинхронизация блокирует Harness Integrity.

---

# 18. Self-tests валидаторов

Self-tests проверяют implementation самих gates на synthetic repositories/fixtures. Канонический entry point:

```bash
python3 .harness/tools/run-self-tests.py
python3 .harness/tools/run-self-tests.py --list
python3 .harness/tools/run-self-tests.py --json
```

`run-self-tests.py` автоматически обнаруживает все `.harness/tools/*-self-test.py` и запускает их в стабильном порядке. Новый regression-файл не требует отдельной регистрации в CI; сам runner остаётся required Harness artifact.

Runner продолжает suite после отдельного failure и в конце возвращает non-zero, если упал хотя бы один test. PASS self-test означает, что gate выдержал известные positive/negative regressions; он **не заменяет** запуск baseline validator на текущем repository state.

---

# 19. Рекомендуемые последовательности

## Перед commit

```bash
python3 .harness/tools/git-preflight.py check --json
python3 .harness/tools/validate.py --mode commit
python3 .harness/tools/git-preflight.py commit --commit-type <type> --slug <slug> --json
```

## При изменении project documents

```bash
python3 .harness/tools/sync-projections.py --check --json
python3 .harness/tools/validate.py --mode manual
```

Если projections drifted:

```bash
python3 .harness/tools/sync-projections.py --json
python3 .harness/tools/validate.py --mode manual
```

## При диагностике reports

```bash
python3 .harness/tools/report_contract.py --all --json
python3 .harness/tools/validate.py --mode manual
```

## Перед PROJECT INIT finalization

```bash
python3 .harness/tools/finalize-project-init.py \
  --name '<project-name>' \
  --check \
  --json
```

## При проблемах command routing

```bash
python3 .harness/tools/validate-command.py --json -- '<command-or-chain>'
python3 .harness/tools/check-command-references.py --json
```
