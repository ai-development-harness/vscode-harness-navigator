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

Особенность: целостное legacy migration-pending состояние после Harness update может быть выдано warning, чтобы пользователь смог выполнить `PROJECT RECONCILE`.

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
- changed Git paths;
- security-sensitive path patterns;
- test/code surface patterns;
- clean-tree fallback.

Clean-tree fallback fail-closed требует security + tests, потому что один последний commit не доказывает полный implementation surface STEP.

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
- перед `GIT SYNC`.

## CLI

```bash
python3 .harness/tools/git-preflight.py \
  check|commit|push|pr|sync \
  [--json] \
  [--commit-type <type>] \
  [--slug <slug>]
```

### Аргументы

- action — `check`, `commit`, `push`, `pr`, `sync`;
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
- ff-only sync;
- Harness validator перед mutation, если это требует policy.

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
- completion proofs;
- relevant OQ blockers;
- `plan.context_basis`;
- `plan.content_hash`;
- matching planning-review PASS;
- INIT review basis.

Semantic качество плана static validator не оценивает — его подтверждает independent planning-review.

---

# 11. Machine-readable Markdown document contract

## Файл

`.harness/tools/document_contract.py`

## Роль

Низкоуровневый parser/validator schema-v1 Markdown documents.

Прямого CLI нет.

## Основные функции

- ограниченный YAML frontmatter parsing;
- `##` section parsing;
- duplicate section detection;
- H1 extraction;
- schema/kind checks;
- mandatory non-empty sections;
- unresolved placeholder detection;
- stable/content hashes;
- durable report timestamp identity;
- atomic UTF-8 writes.

Все более высокоуровневые validators должны использовать этот module вместо собственных несовместимых Markdown/YAML parsers.

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
- reviewed repository revision;
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

Project templates принадлежат проекту после INIT, поэтому их mutation выполняет explicit reconciliation flow, а не silent self-update.

---

# 15. Execution Status schema validator

## Файл

`.harness/tools/execution_status.py`

## Роль

Модуль в целом управляет crash-safe local execution state; validation-часть представлена `validate_status()`.

Прямого validator CLI нет.

## Что проверяет `validate_status()`

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

# 17. Self-tests валидаторов

Self-tests проверяют implementation самих gates на synthetic repositories/fixtures:

```bash
python3 .harness/tools/command-references-self-test.py
python3 .harness/tools/execution-self-test.py
python3 .harness/tools/planning-contract-self-test.py
python3 .harness/tools/report-contract-self-test.py
python3 .harness/tools/repository-hardening-self-test.py
python3 .harness/tools/git-policy-self-test.py
python3 .harness/tools/git-preflight-self-test.py
python3 .harness/tools/harness-config-self-test.py
python3 .harness/tools/harness-update-self-test.py
python3 .harness/tools/update-migration-self-test.py
```

Self-test PASS означает, что validator/gate выдержал известные positive/negative regressions. Он **не заменяет** запуск валидатора на текущем repository state.

---

# 18. Рекомендуемые последовательности

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
