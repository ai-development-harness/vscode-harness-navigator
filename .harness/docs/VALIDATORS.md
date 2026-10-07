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
- cross-contract `required_files ↔ updater ownership`: каждый обязательный Harness file должен совпадать ровно с одним из `harness_owned | shared | marker_merge`;
- обязательные protocol files, skills, agents и commands;
- для каждого `required_skills` — соседний `UPSTREAM.md` с `Source: project-native`, чтобы core workflow не терял provenance;
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
python3 .harness/tools/harness-dispatch.py complete --root '<root>' --command '<command>' --execution-id '<executionId>' --result PASS
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
- PR base/template/provider/tool availability, включая строгие пары `github→gh` и `gitea→tea`;
- merged-PR provider state, local PR state, safe return-branch ff-only и non-force branch deletion для `pr-finish`;
- ff-only sync;
- Harness validator перед mutation, если это требует policy.

---

## Deterministic Git mutation executor

Файлы:

- `.harness/tools/git_action.py` — mutation engine;
- `.harness/tools/pr_provider.py` — deterministic GitHub/Gitea provider adapters;
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

Executor повторяет canonical preflight непосредственно перед mutation. Semantic commit/PR inputs сначала читаются и проверяются Harness-ом как exact snapshot; primary consumer получает captured text через stdin (`git commit -F -`, `gh pr create --body-file -`, `tea pulls create --description-file -`) и не переоткрывает mutable source path. Provider adapter детерминированно разрешает remote host/repository, проверяет CLI/auth/login и нормализует GitHub/Gitea PR payload. Original local input после postcondition очищается отдельно по identity-safe lifecycle.

- COMMIT создаёт только exact `requiredBranch`, если protected-branch preflight потребовал его; message file разрешён только под `.harness/local/git/`; postcondition — новый HEAD.
- PUSH исполняет только returned non-force argv; postcondition — configured remote branch совпадает с local HEAD.
- PR принимает semantic body/title только из `.harness/local/git/**`, сам ищет/reuse/create provider PR через `github→gh` или `gitea→tea`, сверяет exact head OID и сохраняет local PR state. Self-hosted Gitea login выбирается только по exact remote host; неоднозначность блокируется.
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

### Codebase Grounding payload validator

Файлы:

- `.harness/tools/codebase_grounding.py` — contract engine;
- `.harness/tools/codebase-grounding.py` — CLI wrapper;
- `.harness/tools/codebase-grounding-self-test.py` — bounded-context regressions.

Validator не строит mental model и не читает repository произвольно. Он принимает уже сформированный semantic payload и Context Contract, затем fail-closed проверяет exact revision, explicit expansions, `simple|complex` budget, top-level `evidencePaths` и claim-level `evidence[]`; claim evidence обязано относиться к доступному context и индексироваться в `evidencePaths`.

```bash
python3 .harness/tools/codebase-grounding.py \
  --context-file '<context-contract-json>' \
  --payload-file '<grounding-json>' \
  --json
```

PASS возвращает normalized payload с `contextBudget.baseMetrics`, фактическим числом expansion files/chars и hard limits. Invalid revision, forbidden expansion, ungrounded evidence path или превышение budget возвращает `BLOCKED`/non-zero.

### Core Reasoning Principles selector

Файлы:

- selector/catalog validator: `.harness/tools/core_reasoning_principles.py`;
- regression: `.harness/tools/core-reasoning-principles-self-test.py`;
- leaves: `.agents/skills/core-reasoning-principles/leaves/CRP-*.md`.

Standalone user command отсутствует. Selector вызывается Context Contract resolver-ом и детерминированно возвращает только applicable `CRP-NNN` refs.

Проверяется:

- catalog size 6–10 leaves;
- stable namespace `CRP`, unique `CRP-NNN` IDs и slugs;
- required leaf sections `Trigger / applicability`, `Rationale`, `Actionable pattern`;
- closed-set roles/triggers;
- max 4 000 chars на leaf;
- deterministic applicability только из STEP/Context machine facts;
- ordinary phase не получает весь catalog;
- CRP остаётся отдельным полем `coreReasoningPrinciples[]` и не смешивается с project-owned `PRN-NNN` в `required`;
- runtime neutrality: одинаковые facts дают одинаковую selection для Codex/Claude.

Context Contract metrics отдельно публикуют `corePrincipleCount/corePrincipleChars`.

Подробная policy: [`CORE_REASONING_PRINCIPLES.md`](CORE_REASONING_PRINCIPLES.md).

### Structural Enforcement validator

Файлы:

- engine: `.harness/tools/structural_enforcement.py`;
- CLI: `.harness/tools/structural-enforcement.py`;
- regression: `.harness/tools/structural-enforcement-self-test.py`.

Scan mode агрегирует Review Contract v2 findings по stable `category + fingerprint` и dedupe-ит duplicate reports той же `reviewed_revision`:

```bash
python3 .harness/tools/structural-enforcement.py --step STEP-024 --json
```

Дополнительный structured evidence envelope поддерживает repair/progress stops, audit/reconcile findings, validator failures и durable decisions. Closed source registry не содержит transcript/chat/session.

Proposal validation enforce-ит:

- recurring threshold = 2 distinct factual occurrences;
- one-off class требует explicit caller `--explicit-single`;
- exact enforcement ladder `architecture-ownership → schema-type → validator-lint → regression-test → durable-instruction`;
- каждый weaker level обязан объяснить отказ от всех stronger levels;
- deterministic mechanism обязан иметь regression fixture contract;
- `--implemented` требует реально существующий regular fixture;
- evidence refs обязаны принадлежать выбранному class;
- architecture-level proposal требует explicit decision route;
- `automaticMutationAllowed=false` всегда.

Tool не исполняет regression command и не меняет architecture/code; фактический proof остаётся у canonical Verification/CI.

Подробности: [`STRUCTURAL_ENFORCEMENT.md`](STRUCTURAL_ENFORCEMENT.md).

### High-Rigor Arena / Interrogate validator

Файлы:

- engine: `.harness/tools/high_rigor.py`;
- CLI: `.harness/tools/high-rigor.py`;
- regression: `.harness/tools/high-rigor-self-test.py`.

Activation mode проверяет `.harness/manifest.yaml → highRigor.*`, phase и deterministic STEP `risk_flags`:

```bash
python3 .harness/tools/high-rigor.py \
  --mode arena \
  --phase plan \
  --step STEP-024 \
  --json
```

`explicit` без `--requested` и `disabled` всегда возвращают `SKIP`; `risk` может вернуть `RUN` только по closed high-risk flags.

Trace validation принимает local run под `.harness/local/high-rigor/**` и recompute-ит exact SHA-256/chars/bytes входов, rubric и outputs. Проверяется:

- configured candidate/reviewer seat count;
- минимум два independent completed seats;
- unique completed `sessionExecutionId`;
- одинаковый shared input для всех candidates/reviewers;
- одинаковый rubric;
- per-seat и total char budgets;
- requested/actual model и visible fallback/dropout;
- Arena: отдельный judge, completed base candidate, graft/disagreement/verification refs;
- Interrogate: consensus/disagreement map и lead judgment;
- `deterministicGatesReplaced=false`.

Runtime/model shortfall возвращает `DEGRADED`, а не скрытый PASS. Core validator не запускает модели и не хранит provider-specific model slugs.

Подробности: [`HIGH_RIGOR.md`](HIGH_RIGOR.md).

---

# 9D. Benchmark Methodology evidence gate

## Файлы

- engine: `.harness/tools/benchmark_methodology.py`
- CLI: `.harness/tools/benchmark-methodology.py`
- regression: `.harness/tools/benchmark-methodology-self-test.py`

## Роль

Проверяет достаточность performance evidence, не исполняя benchmark за модель. Вход — закрытый JSON contract с заранее сформулированным claim, exact revisions/argv/environment, raw samples, correctness counts и work-proof files.

Validator вычисляет median/range/variation для baseline/candidate, direction-normalized effect и консервативный noise band. Work-proof files проверяются как regular non-symlink repository paths и получают SHA-256.

## Результаты

- `PASS` — сравнение сопоставимо, correctness не нарушен, есть минимум 3 runs на arm, effect превышает observed variation и declared minimum effect, bottleneck/sanity/end-to-end checks выполнены;
- `INCONCLUSIVE` — evidence structurally valid, но недостаточен для claim: one/two-run ballpark, effect внутри variation, command/environment mismatch, correctness failure, missing relevance proof и т. п.;
- `BLOCKED` — malformed/unsupported/unverifiable evidence contract.

`INCONCLUSIVE` является валидным factual outcome и имеет exit code 0: caller обязан трактовать его буквально и не превращать reasoning-ом в performance PASS. Если STEP Acceptance зависит от quantitative claim, обычный Verification/Review остаётся незавершённым до достаточного evidence.

Microbenchmark может доказать только narrow claim. Когда end-to-end relevance проверена и отсутствует, PASS возвращает `claimRestriction=microbenchmark-only` и warning `MICROBENCHMARK_ONLY`.

Подробности: [`BENCHMARK_METHODOLOGY.md`](BENCHMARK_METHODOLOGY.md).

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
- `planning-review` — verdict/findings/rationale → immutable planning-review с exact fingerprints и `execution_id` active `STEP PLAN`; per-execution budget `execution.maxPlanReviewCycles` fail-closed блокирует следующий round после достижения лимита, historical reports других execution в счётчик не входят; PASS atomically handoff-ится в canonical Ready stamp;
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
- legacy completion baseline (`legacy_completed_steps`: только STEP id, без дублей, с разделом `## Legacy completion baseline`);
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
- fix/review cycle counter;
- optional `current.context.intentBasis`: bounded 16 KiB versioned envelope для `STEP PLAN/IMPLEMENT/REVIEW/FIX`. Known schema v1 проверяет STEP/command/context fingerprints/plan binding; unknown future sub-schema остаётся parseable, но resume fail-closed возвращает `INTENT_BASIS_SCHEMA_UNSUPPORTED`; legacy/diagnostic fresh start, где basis вычислить нельзя, сохраняет bounded `intentBasisError`, который делает последующий resume `INTENT_BASIS_UNAVAILABLE`;
- optional root `progressTelemetry`: schema v1, общий 16 KiB budget, максимум 8 samples, non-negative `unchangedResumes`/`driftStreak`, closed stopDecision `continue|EXECUTION_STAGNATION|EXECUTION_CYCLE|EXECUTION_DRIFT`; optional `progressTelemetryError` остаётся bounded diagnostic и не подменяет Intent Basis safety gate.

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

---

# Runtime Adapter Contract validator

## Файл / Файлы

- `.harness/runtime-adapter-contract.json`
- `.harness/tools/runtime_adapter_contract.py`
- `.harness/tools/runtime-adapter-contract-self-test.py`

## Роль

Проверяет provider-neutral boundary между Harness control plane и runtime adapters Codex/Claude: lifecycle methods, capability registry, support states и normalized event types.

Этот contract валидируется из `project_integrity.py`, поэтому malformed runtime schema блокирует обычный Harness integrity gate.

## CLI

```bash
python3 .harness/tools/runtime_adapter_contract.py --json
python3 .harness/tools/runtime_adapter_contract.py --runtime codex --json
python3 .harness/tools/runtime_adapter_contract.py --runtime claude --json
```

## Exit codes

- `0` — PASS;
- `1` — deterministic schema/capability violation;
- `2` — BLOCKED: contract нельзя безопасно прочитать.

## Что проверяет

- exact `contractId` и `schemaVersion`;
- закрытые registries lifecycle methods/capabilities/events/support states;
- explicit capability state `native|synthesized|unsupported`;
- полноту mappings каждого adapter;
- account source без credential persistence;
- invariants: command semantics принадлежат control plane, provider metadata optional, secrets persistence forbidden;
- normalized runtime events и запрет неизвестных полей.

Подробная семантика: [`RUNTIME_ADAPTER_CONTRACT.md`](RUNTIME_ADAPTER_CONTRACT.md).

---

# Review Contract v3 evidence-gated findings

## Файл / Файлы

- `.harness/tools/review_findings.py`
- `.harness/tools/review-findings-self-test.py`

## Роль

`review_findings.py` задаёт machine-readable handoff `REVIEW → FIX`. Новый STEP REVIEW хранится как immutable Markdown с canonical JSON-блоком `## Machine-readable findings`.

Human-readable `## Findings` нужен человеку. FIX/orchestration не должен повторно интерпретировать этот prose: он использует deterministic parser.

Review Contract v3 добавляет **Evidence Gate**: новый reviewer-derived scenario не становится durable finding, пока его необходимые предпосылки и project-specific verification не подтвердили, что проблема действительно существует.

## Contract finding v3

Каждый finding содержит:

- `id: F-NNN`;
- `severity: critical|high|medium|low`;
- `category: implementation|evidence|contract`;
- `location.path` и optional `location.line`;
- `scenario.given/when/then`;
- `expected` и `observed`;
- `impact`;
- `repair.direction` и `repair.admissibleAlternatives[]`;
- `constraints[]`;
- обязательный непустой `evidence[]`;
- обязательный `evidenceBasis`:
  - `kind: contract|reproduced|inferred`;
  - `source`;
  - `preconditions[]`; для `inferred` список не может быть пустым;
  - `verification.method`;
  - `verification.result`;
  - `verification.outcome: confirmed`;
- deterministic `fingerprint: sha256:...`.

`invalidated` или `unverified` outcome запрещён в durable finding. Такая гипотеза остаётся ephemeral reasoning и при необходимости кратко упоминается только в rationale текущего review.

Fingerprint вычисляется из factual identity: `category + location + scenario + expected + observed`. `evidenceBasis`, ID, title и wording repair guidance намеренно не входят в fingerprint: дополнительное подтверждение того же дефекта не создаёт новую defect identity.

Duplicate fingerprints в одном report запрещены.

## CLI

```bash
python3 .harness/tools/review_findings.py --step STEP-NNN --json
```

Команда возвращает latest **current v3** review и normalized findings. Если latest review historical v1/v2, malformed, не прошёл evidence gate или fingerprint не совпадает с содержимым, deterministic FIX handoff возвращает BLOCKED и требует свежий `STEP REVIEW`.

## Совместимость

Historical Review Contract v1 reports не переписываются и продолжают валидироваться старым human-readable contract.

Historical Review Contract v2 machine reports тоже остаются валидной immutable history и могут участвовать в historical/progress inspection.

Writer новых STEP REVIEW всегда добавляет `finding_contract: 3` и machine `schemaVersion: 3`.

FIX намеренно требует свежий v3 report. Это не позволяет старому v2 finding без `evidenceBasis` обойти Evidence Gate после обновления Harness.

## Fail-closed проверки

Validator `review_contract.py` для v3 дополнительно проверяет:

- наличие и JSON-синтаксис machine section;
- exact agreement `finding_contract` ↔ machine `schemaVersion`;
- supported fields/enums;
- id sequence `F-001...`;
- обязательный непустой evidence;
- корректный `evidenceBasis`;
- non-empty preconditions для inferred finding;
- только `verification.outcome=confirmed`;
- deterministic fingerprint;
- отсутствие duplicate fingerprints;
- совпадение количества human и machine findings;
- совпадение `Severity` / `Category` между обеими формами;
- прежние verdict composition rules PASS/FAIL/BLOCKED.

Self-test отдельно доказывает:

- stable fingerprint при rename/repair rewording;
- изменение fingerprint при factual change;
- rejection finding без `evidenceBasis`;
- rejection inferred finding без preconditions;
- rejection invalidated hypothesis;
- чтение historical v2 machine report.

Подробная политика и PEM/Vite example: [`EVIDENCE_GATE.md`](EVIDENCE_GATE.md).

---

# Side-effect recovery contract validator

## Файл / Файлы

- `.harness/tools/side_effect_recovery.py`
- `.harness/tools/side-effect-recovery-self-test.py`
- persistence boundary: `.harness/tools/execution_status.py`

## Роль

Проверяет bounded internal checkpoint для mutation-команд. Contract не разрешает command transitions и не выполняет mutation; он валидирует version/kind/phase/attempt/proof и запрещает oversized или secret-like proof metadata.

## Что проверяет

- contract version;
- известный canonical kind `git_commit|git_push|provider_pr|harness_update|file_write`;
- legacy `github_pr` принимается только для чтения/завершения уже сохранённого PR recovery checkpoint; новые PR checkpoints используют `provider_pr`;
- monotonic phases одной attempt;
- новая attempt начинается с `prepared`;
- proof — JSON object не более 8 KiB;
- credential/token/password/secret-like keys не сохраняются;
- checkpoint восстанавливается из execution-status после process restart.

## Self-test

~~~bash
python3 .harness/tools/side-effect-recovery-self-test.py
~~~

Synthetic fault injection покрывает crash before side effect, unknown outcome, crash after applied side effect и crash between observation/completion checkpoint.

Runtime reconciliation Git/provider подробно описан в [`SIDE_EFFECT_RECOVERY.md`](SIDE_EFFECT_RECOVERY.md).


---

# Adaptive repair-cycle comparator

## Файл / Файлы

- `.harness/tools/repair_cycle.py`
- `.harness/tools/repair-cycle-self-test.py`

## Роль

Сравнивает два consecutive current Review Contract v3 report по stable fingerprints, `reviewed_revision`, `contract_basis`, `verification_basis` и optional factual `verification_status`. Historical v2 остаётся валидной history, но adaptive FIX telemetry требует свежие evidence-gated v3 reports. Возвращает bounded telemetry и conservative stop decision `continue|NO_PROGRESS|REPEATED_FINDINGS|REGRESSION`.

## Self-test

```bash
python3 .harness/tools/repair-cycle-self-test.py
```

Self-test покрывает progress, no-progress, repeated findings, higher-severity regression, worsening factual Verification status, historical report без status и scope-change guard. Resolver-level применение stored telemetry покрывается `execution-self-test.py`.

Политика описана в [`ADAPTIVE_REPAIR_STOPPING.md`](ADAPTIVE_REPAIR_STOPPING.md).

Generic long-running detector реализован в `.harness/tools/progress_guard.py`; regression suite `.harness/tools/progress-guard-self-test.py` покрывает STAGNATION/CYCLE/DRIFT, activity-only false-positive guard, execution-groups fingerprint и suppression FIX↔REVIEW. Политика: [`PROGRESS_GUARD.md`](PROGRESS_GUARD.md). Execution-state schema дополнительно валидирует каждый persisted progress sample и `lastDelta` fail-closed: command/STEP/operation, fingerprints, metrics, counters и classification не могут восстанавливаться из malformed defaults.

Cross-process integration suite `.harness/tools/reliable-orchestration-fault-self-test.py` проверяет совместную работу state authority, Intent Basis и Progress Guard через реальные process boundaries: crash после durable snapshot, `STEP RUN` resume/stagnation после потери response и concurrent stale completion против current invocation.


---

# Runtime adapter conformance / scripted orchestration

## Файл / Файлы

- `.harness/tools/runtime_adapter_conformance.py`
- `.harness/tools/scripted_runtime.py`
- `.harness/tools/orchestration-harness-self-test.py`

## Роль

Общая deterministic conformance suite для declared runtime adapters и test-only ScriptedRuntime с exact event sequence/fault injection. Recovery tests ведут exact ordered journal side-effect applications, поэтому duplicate mutation при resume не может быть скрыта дедупликацией identity. Сеть, API key и real Claude/Codex process не требуются.

## Self-test

```bash
python3 .harness/tools/orchestration-harness-self-test.py
```

Test автоматически входит в `run-self-tests.py`. Real-runtime integration вынесена за deterministic CI boundary. Подробнее: [`DETERMINISTIC_TEST_HARNESS.md`](DETERMINISTIC_TEST_HARNESS.md).


---

# Completion / Convergence Gate

## Файл / Файлы

- CLI: `.harness/tools/completion-gate.py`
- engine: `.harness/tools/completion_gate.py`
- regression: `.harness/tools/completion-gate-self-test.py`

## Роль

Deterministic precheck перед semantic convergence judgement STEP. Gate не
повторяет code review: он проверяет, можно ли вообще оценивать полноту на
текущем contract/evidence basis.

## Когда использовать

- внутри `STEP REVIEW` до semantic completion judgement;
- при диагностике REVIEW PASS, который не закрыл STEP;
- при проверке stale/missing Verification evidence.

## Что проверяет

- machine-discoverable Acceptance criteria;
- generated Verification status;
- совпадение current Verification contract hash с basis evidence;
- совпадение current product/worktree subject revision с revision, на которой
  запускалась Verification; сам STEP Evidence исключается из subject revision,
  поэтому запись generated evidence не делает proof stale;
- current Ready/prerequisite contract;
- structured completion result `PASS | FAIL | BLOCKED`.

## CLI

```bash
python3 .harness/tools/completion-gate.py STEP-024 --json
```

## Exit codes

- `0` — deterministic precheck PASS;
- `1` — BLOCKED/stale/missing prerequisite;
- `2` — argparse error.

## Граница ответственности

Deterministic gate не решает, действительно ли implementation/evidence
семантически покрывают criterion. Это делает reviewer один раз. Writer затем
нормализует completion findings, сохраняет их в immutable REVIEW report и
использует существующий FIX/BLOCKED routing без второго lifecycle.


---

# STEP Execution Groups

## Файл / Файлы

- engine: `.harness/tools/execution_groups.py`;
- CLI: `.harness/tools/execution-groups.py`;
- regression: `.harness/tools/execution-groups-self-test.py`.

## Роль

Валидирует optional machine-readable DAG внутри STEP Implementation plan и строит deterministic sequential scheduling projection.

## Что проверяет

- stable group IDs и exact schema;
- покрытие каждого numbered Implementation plan step ровно одной group;
- unknown/self dependencies и cycles;
- repository-relative explicit mutation prefixes;
- обязательные group verification responsibilities;
- overlap mutation surface у независимых `parallel=true` groups.

`parallel=true` не запускает concurrent agents. В v1 это capability metadata; implementer следует `topologicalOrder` последовательно.

## CLI

```bash
python3 .harness/tools/execution-groups.py STEP-024 --json
```

## Exit codes

- `0` — graph отсутствует либо валиден, projection построена;
- `1` — malformed/unsafe graph или STEP нельзя прочитать;
- `2` — argparse error.

Подробная schema и conflict semantics: [`EXECUTION_GROUPS.md`](EXECUTION_GROUPS.md).


---

# Planning impact / evolution analysis

## Файл / Файлы

- engine: `.harness/tools/impact_analysis.py`;
- CLI: `.harness/tools/impact-analysis.py`;
- regression: `.harness/tools/impact-analysis-self-test.py`;
- authoritative fingerprint source: `.harness/tools/planning_contract.py → planning_context_basis / planning_context_components`.

## Роль

Объясняет, какой canonical planning component сделал Ready plan stale, и показывает affected STEP surface после изменения REQ/ADR/STEP/OQ/PRN/architecture reference. Tool не создаёт второй freshness engine: окончательное решение fresh/stale по-прежнему определяется `planning_context_basis`.

## CLI

```bash
python3 .harness/tools/impact-analysis.py --step STEP-018 --json
python3 .harness/tools/impact-analysis.py --changed REQ-007 --json
python3 .harness/tools/impact-analysis.py --changed ADR-012 --changed REQ-007 --json
```

`--step` и `--changed` взаимоисключающие.

## Что проверяет / возвращает

- current Ready basis против stored `plan.context_basis`;
- per-component fingerprints, сохранённые при Ready stamp;
- exact cause `added | removed | changed`;
- affected STEP и remediation `STEP PLAN STEP-NNN`;
- superseding ADR propagation через `superseded_by`;
- legacy Ready plan без component fingerprints остаётся fail-safe stale с generic `PLANNING_CONTEXT changed`.

Impact analysis read-only: downstream artifacts, reviews и completed history не переписываются.

### Semantic Blast Radius validator

Файлы:

- engine: `.harness/tools/semantic_blast_radius.py`;
- CLI: `.harness/tools/semantic-blast-radius.py`;
- regression: `.harness/tools/semantic-blast-radius-self-test.py`.

Preflight возвращает deterministic trigger из STEP `risk_flags`, exact repository revision и explicit downstream STEP surface из existing impact analysis:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-024 --phase plan --json
python3 .harness/tools/semantic-blast-radius.py STEP-024 --phase review --json
```

Validation mode дополнительно принимает Context Contract, validated grounding и semantic payload. Validator revalidates grounding, enforce-ит общий context budget, provenance evidence paths и 1–2 critical hypotheses. Semantic `PASS` возможен только при `proven` critical proofs, чьи commands реально присутствуют в STEP Verification и имеют fresh generated PASS evidence на current subject revision. Aggregate status `MANUAL_REQUIRED` допустим, если pending manual checks не являются proof этих hypotheses; существующие completion/review gates всё равно обязаны закрыть manual checks отдельно.

### Decision Archaeology validator

Файлы:

- engine: `.harness/tools/decision_archaeology.py`;
- CLI: `.harness/tools/decision-archaeology.py`;
- regression: `.harness/tools/decision-archaeology-self-test.py`.

Preflight фиксирует exact repository revision, concrete target path и bounded Git history target-файла. При existing Context Contract current revision обязан совпадать с его `repositoryRevision`.

```bash
python3 .harness/tools/decision-archaeology.py \
  --target src/provider/retry.py \
  --scope simple \
  --json
```

Validation mode принимает semantic archaeology payload и optional Context Contract. Validator проверяет:

- `documented | inference` claim boundary;
- `high | medium | low` confidence;
- repository-local artifact/commit provenance;
- commit evidence только из bounded target history;
- timestamped evidence map;
- supplied issue/PR/docs evidence как explicit `supplied-not-locally-verifiable`, не как local proof;
- explicit conflicts и gaps;
- stale-ADR diagnostic assessments;
- expansion/history/claim/source budgets.

`PASS` запрещён, если есть inference без historical evidence. Такая inference допустима только как `low` confidence + explicit gap + `INCONCLUSIVE`. Conversation/transcript не является supported evidence category.

Подробная semantic policy: [`DECISION_ARCHAEOLOGY.md`](DECISION_ARCHAEOLOGY.md).

## Exit codes

- `0` — запрос корректно вычислен, даже если найден stale plan;
- `1` — canonical context нельзя безопасно прочитать/разрешить;
- `2` — argparse error.

Подробная lifecycle policy: [`EVOLUTION_SEMANTICS.md`](EVOLUTION_SEMANTICS.md).


---

# Release Qualification entrypoint

## Файл / Файлы

- `.harness/tools/release-qualification.py`
- `.harness/tools/release-qualification-self-test.py`

## Роль

Canonical deterministic entrypoint release-level проверки exact candidate checkout. Он не заменяет Harness Integrity: release orchestrator вызывает один и тот же executable в platform/runtime lanes и агрегирует результат с downstream/stress gates.

## CLI

```bash
python3 .harness/tools/release-qualification.py \
  --lane current \
  --expect-sha '<exact-candidate-sha>' \
  --expected-python 3.13 \
  --json
```

`--lane` обязателен:

- `current` — validator + полный discoverable self-test suite;
- `minimum` — тот же core contract строго на Python 3.11;
- `windows` — validator + targeted Windows-specific boundaries.

`--expect-sha` обязателен и должен совпадать с фактическим `git rev-parse HEAD`. `--expected-python` опционально закрепляет exact major.minor runtime caller-а.

## Exit codes

- `0` — PASS;
- `1` — qualification gate FAIL либо checkout был мутирован во время qualification;
- `2` — BLOCKED до gates: SHA/runtime/platform mismatch, dirty checkout или недоступный Git state.

## Fail-closed свойства

- evidence всегда относится к exact repository revision;
- dirty checkout не квалифицируется;
- после gates повторно проверяется tracked/untracked state;
- stdout/stderr в compact JSON представлены hash + byte count, полный вывод остаётся job log;
- Windows lane нельзя случайно запустить на POSIX;
- minimum lane нельзя засчитать не на Python 3.11.

Подробный release contract: [`RELEASE_QUALIFICATION.md`](RELEASE_QUALIFICATION.md).


---

# Initialized Upgrade Qualification

## Файл / Файлы

- `.harness/tools/release-upgrade-qualification.py`
- `.harness/tools/release-upgrade-qualification-self-test.py`

## Роль

Проверяет upgrade already initialized downstream baseline до exact release-prepared candidate SHA. Работает только с local checkouts и disposable clones; network/private authentication принадлежит external release workflow.

## CLI

```bash
python3 .harness/tools/release-upgrade-qualification.py \
  --baseline-project /path/to/release-canary \
  --baseline-sha '<exact-baseline-sha>' \
  --candidate-source /path/to/harness-candidate \
  --candidate-sha '<exact-candidate-sha>' \
  --json
```

## PASS contract

- exact clean baseline/candidate inputs;
- candidate tree имеет согласованные release lock + update graph;
- previous stable → candidate выполняет реальный UPDATE, не первичный NO_UPDATE;
- reload boundaries разрешаются bounded repeats;
- pending project schema мигрирует deterministic owner-ом;
- STATUS/DOCTOR/validator/full self-tests PASS;
- Accepted ADR, INIT reports и canary project-owned customization сохранены;
- повторный APPLY возвращает реальный `NO_UPDATE` без repository mutation;
- source baseline/candidate host checkouts остаются неизменными.

Подробно: [`INITIALIZED_UPGRADE_QUALIFICATION.md`](INITIALIZED_UPGRADE_QUALIFICATION.md).


---

# Bounded Stress Suite

## Файл / Файлы

- `.harness/stress-tests.json`
- `.harness/tools/run-stress-tests.py`
- `.harness/tools/run-stress-tests-self-test.py`

## Роль

Отдельный runner для intermittent concurrency/process/locking/cleanup regressions. Первый scenario — regression #256 concurrent authority fixture cleanup.

## CLI

```bash
python3 .harness/tools/run-stress-tests.py --iterations 5
python3 .harness/tools/run-stress-tests.py --json
```

Без `--iterations` используется release default из manifest: 20.

Runner запускает каждый manifest scenario ровно один раз с bounded iteration count, не делает retry-on-failure, завершает process tree при timeout и сохраняет diagnostic hashes/byte counts/tails для failed scenario.

Release Qualification/current всегда использует 20 iterations. Обычный PR CI использует explicit lightweight budget.
