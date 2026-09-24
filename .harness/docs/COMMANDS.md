# Команды Harness

Команды — стабильный человеко-машинный интерфейс. Каноническая форма начинается с явного namespace: `<DOMAIN> <ACTION> ...`. Подробный синтаксис и chain operator `>` описаны в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md).

Допустимость переходов и routing команд определяется **только** machine-readable graph `.harness/command-transitions.json`. Обычный runtime передаёт raw command в `.harness/tools/harness-dispatch.py`: dispatcher выполняет structural gate/execution/continuation и возвращает deterministic result либо exact semantic skill handoff. `validate-command.py` остаётся read-only диагностическим structural gate.

State transitions выполнения описаны в `.harness/docs/EXECUTION_PROTOCOL.md`.

Для STEP target допускается пользовательский shorthand `NNN` (не менее трёх цифр). Structural parser до dispatch нормализует его в canonical `STEP-NNN`, поэтому `STEP RUN 024` и `STEP RUN STEP-024` адресуют один и тот же STEP. В durable state/docs сохраняется canonical форма.

Поле `documentation` каждой команды в CTS указывает на стабильный explicit anchor вида `.harness/docs/COMMANDS.md#command-<domain>-<operation>`. Эти anchors являются частью protocol contract и не зависят от алгоритма генерации Markdown slug.

Старые ненеймспейсные формы не являются каноническими alias. Локальные пользовательские alias-команды можно добавить только явно в `AGENTS.local.md`; они читаются после `AGENTS.md`.

## Цепочки

Для разрешённых команд одной области можно не повторять namespace:

```text
GIT CHECK > COMMIT > PUSH > PR
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
HARNESS UPDATE CHECK TO vX.X.X > APPLY
```

Вся цепочка сначала нормализуется и проверяется по `.harness/command-transitions.json`. Отсутствующий edge означает `INVALID_CHAIN` и ноль выполненных сегментов. После structural PASS дальнейшее выполнение определяется `onPreviousResult` и `runtimePreconditions` конкретного edge. Полные правила — в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md) и [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md).

<a id="command-harness-help"></a>
## `HARNESS HELP`

Read-only deterministic справка по command surface. Команда читает metadata непосредственно из `.harness/command-transitions.json` и выводит команды, сгруппированные по domain, с кратким описанием и ссылкой на документацию:

```bash
python3 .harness/tools/harness-help.py
```

Отдельный вручную поддерживаемый список команд для HELP не допускается: CTS registry остаётся единым machine-readable source of truth.

<a id="command-harness-status"></a>
## `HARNESS STATUS`

Read-only operational snapshot: Harness release/generation, project initialization, Git branch/worktree, unresolved executions и GitHub PR capability.

```bash
python3 .harness/tools/harness-ux.py status --json
```

<a id="command-harness-resume"></a>
## `HARNESS RESUME`

Продолжает единственное незавершённое выполнение, которое можно безопасно возобновить. Если таких выполнений нет — возвращает `BLOCKED/NO_RESUMABLE_EXECUTION`; если их несколько — `BLOCKED/MULTIPLE_RESUMABLE_EXECUTIONS`.

```bash
python3 .harness/tools/harness-ux.py resume --json
```

Команда не создаёт новое корневое выполнение: она возвращает идентификатор, корневую команду и точную команду продолжения уже существующего выполнения.

<a id="command-harness-doctor"></a>
## `HARNESS DOCTOR`

Deterministic диагностика required core dependencies, repository/protocol health и optional capabilities.

```bash
python3 .harness/tools/harness-ux.py doctor --json
```

Codex/Claude и `gh` являются capability-specific: их отсутствие само по себе не делает общий Doctor `BLOCKED`.

<a id="command-harness-config"></a>
## `HARNESS CONFIG`

Read-only effective manifest/Git/update configuration с указанием source files.

```bash
python3 .harness/tools/harness-ux.py config --json
```

<a id="command-project-init"></a>
## `PROJECT INIT`

Однократный bootstrap из configured `sources.localBrief`. Создаёт schema-v1 project knowledge base и initial roadmap, но не production code. INIT сохраняет два immutable semantic reports — requirements и roadmap — с exact deterministic basis, пересобирает projections и завершается только через `finalize-project-init.py`. Ручное `project.initialized: true` не является валидным completion.

<a id="command-step-add"></a>
## `STEP ADD: <описание>`

Преобразует короткую человеческую задачу в корректный новый STEP:

- ищет дубликаты/пересечения;
- выбирает следующий стабильный ID;
- классифицирует machine `type`/`priority`/`phase` и closed-set `risk_flags`;
- связывает существующие REQ/ADR;
- создаёт новый REQ только при появлении нового продуктового контракта;
- не выдумывает ADR; при необходимости создаёт prerequisite ADR/RESEARCH STEP;
- вычисляет dependencies;
- формирует Goal/Context/Scope/Mutation policy/Out of scope/Acceptance/Verification/Deliverables;
- обновляет canonical traceability и пересобирает deterministic projections;
- возвращает `STEP PLAN STEP-NNN`.

Production code не меняется.

<a id="command-step-list"></a>
## `STEP LIST`

Read-only список canonical STEP: ID, title, lifecycle status, priority, type, phase, plan status и path.

```bash
python3 .harness/tools/harness-ux.py step-list --json
```

<a id="command-step-show"></a>
## `STEP SHOW STEP-NNN`

Read-only snapshot одного STEP. Общий CTS принимает также shorthand `NNN`. Показывает metadata, plan, dependencies/statuses, REQ/ADR/risk flags, latest valid review и связанные unresolved executions.

```bash
python3 .harness/tools/harness-ux.py step-show --step STEP-024 --json
```

<a id="command-skill-find"></a>
## `SKILL FIND: <описание>`

Ищет подходящие Agent Skills/repository skills на GitHub и в доступном web, инспектирует содержимое и сохраняет schema-v1 shortlist в configured `protocol.skillSearchDirectory`. Максимальное число кандидатов задаёт `skills.search.maxResults` (1–10). Ничего не устанавливает. Для каждого кандидата возвращает exact source/path/link, fit, limitations, license/provenance и safety notes.

Следующий шаг: `SKILL INSTALL: #N` либо `SKILL CREATE: <описание>`.

<a id="command-skill-install"></a>
## `SKILL INSTALL: <source | #N>`

После явного выбора пользователя повторно инспектирует сторонний skill, не выполняя его scripts, блокирует high-risk варианты, затем устанавливает bundle в `.agents/skills/`, фиксирует `UPSTREAM.md`, обновляет `docs/skills/REGISTRY.md` и generated `SKILL-ROUTING` block `AGENTS.md`. `#N` resolve-ится из последнего durable search report, а не из chat history.

<a id="command-skill-create"></a>
## `SKILL CREATE: <описание>`

Создаёт project-native skill, если готового подходящего варианта нет. Основан на project conventions и актуальной авторитетной документации, регистрируется в Registry и routing block. Не дублирует core harness protocol.

<a id="command-github-generate-templates"></a>
## `GITHUB GENERATE TEMPLATES`

Изучает актуальные technologies/tooling/CI/project conventions и полностью пересоздаёт managed GitHub Issue Forms и Pull Request template. Работает на любом этапе; существующие target files заменяются, чтобы пользователь увидел изменение в обычном diff. Язык берётся из `language.githubTemplates`. Подробнее: `GITHUB_TEMPLATES.md`.

<a id="command-project-quick-fix"></a>
## `PROJECT QUICK FIX: <описание>`

Выполняет маленькую low-risk правку без создания STEP/REQ/ADR. Разрешён только для micro-change без изменения product/API/data/security/architecture/dependencies. Если scope оказался больше — команда прекращается и предлагает `STEP ADD:`. Если пользователь уже исправил мелочь вручную, можно сразу использовать `GIT CHECK > COMMIT` или отдельные `GIT CHECK` и `GIT COMMIT`. Подробнее: `QUICK_CHANGES.md`.

<a id="command-step-plan"></a>
## `STEP PLAN STEP-NNN`

Сначала валидирует semantic task/dependency contracts, linked REQ/ADR, explicit `architecture_refs` и relevant OQ. Завершение dependencies для PLAN не требуется. Planner возвращает structured Implementation plan/Verification payload, а `semantic-writer.py` сам рендерит STEP draft. Independent reviewer также возвращает только structured verdict/findings/rationale; writer вычисляет exact schema-v4 `context_basis`/`plan_content_hash`, создаёт immutable planning-review и при PASS выполняет Ready stamp. Reverse traceability/priority/phase/completion state dependency не stale-ят plan; изменение semantic input — stale-ит.

<a id="command-step-implement"></a>
## `STEP IMPLEMENT STEP-NNN`

Реализует только current Ready plan в пределах task contract. До semantic handoff execution layer детерминированно применяет `step-implement-ready` и фиксирует durable `implementationBaseline` — текущий Git HEAD до первой product mutation. Baseline хранится в `execution-status.json`, переживает restart и не сдвигается при повторном IMPLEMENT активной `in_progress` lifecycle. При первой product mutation ставит canonical `status: in_progress` и добавляет/обновляет tests. При попытке завершить IMPLEMENT как `SUCCESS` dispatcher сам запускает machine-executable `## Verification` через `verification.py`, пишет generated Evidence и разрешает completion только после PASS; manual checks остаются явной semantic boundary. `status: completed` недопустим до schema-valid independent review PASS и type-specific completion proof.

<a id="command-step-review"></a>
## `STEP REVIEW STEP-NNN`

Независимая проверка exact repository revision. Перед reasoning dispatcher штампует в active execution exact `repositoryRevision` и `gateBasis`, а deterministic preselector вычисляет обязательные security/test reviewers. Reviewer возвращает structured verdict/findings/observations; `semantic-writer.py` принимает verdict только пока текущие revision/gate совпадают со stamped expectation, после чего создаёт immutable report. При PASS writer дополнительно переводит STEP в `completed` только если type-specific completion proof полностью доказан, затем синхронизирует projections; иначе report остаётся PASS, но execution получает BLOCKED и STEP не закрывается. Crash recovery принимает либо exact current-revision report, либо строгий post-review proof `new PASS report + completed STEP + completion proof`.

`STEP REVIEW` поддерживает post-commit и multi-commit сценарии. При валидном durable baseline preselector строит exact surface как `baseline..HEAD + staged/unstaged/untracked product paths` и возвращает `surfaceMode=implementation-baseline`; поэтому security/test classification видит весь STEP diff, а не только последний commit. `.harness/local/**` и новый `REVIEW-*.md` исключаются из surface. Если baseline отсутствует, недоступен или не является ancestor текущего HEAD, Harness не угадывает diff: переключается в `clean-tree-fallback`, сохраняет diagnostic paths и fail-closed требует `security + tests`.

<a id="command-step-fix"></a>
## `STEP FIX STEP-NNN`

Исправляет подтверждённые findings последнего применимого FAIL review. Не расширяет scope. `SUCCESS` проходит тот же deterministic Verification gate, что и IMPLEMENT; factual FAIL остаётся внутри FIX, `MANUAL_REQUIRED` требует только перечисленных manual checks. После PASS Verification следующая команда — `STEP REVIEW STEP-NNN`.

<a id="command-step-run"></a>
## `STEP RUN STEP-NNN`

Автоматический orchestrated flow:

```text
PLAN (если актуального плана нет)
 → IMPLEMENT
 → deterministic verification
 → REVIEW
 → [security/test review по review.* policy]
 → FIX ↔ REVIEW (лимит из `execution.maxFixReviewCycles`, допустимо 1–5)
 → CLOSE
```

Для обычных coding STEP (`implementation | bugfix | refactor | hardening`) сам root-orchestration выполняет dispatcher без отдельного model turn: deterministic resolver выбирает `PLAN/IMPLEMENT/REVIEW/FIX`, а reasoning вызывается только внутри соответствующих semantic child-команд. Для type-specific flows (`research | adr | audit | review | documentation | release`) сохраняется semantic `run-step` fallback.

При blocker или исчерпании циклов orchestration останавливается и не маскирует failure. Лимит `execution.maxFixReviewCycles` enforce-ится Execution Resolver детерминированно и сохраняется между sessions.

<a id="command-step-audit"></a>
## `STEP AUDIT STEP-NNN`

Формальная проверка фактического состояния без production mutation. Подходит для historical reconciliation, architecture/data/security audits. Defects становятся findings/corrective STEP, а не скрытыми исправлениями.

<a id="command-project-status"></a>
## `PROJECT STATUS`

Deterministic команда без model call. Пересобирает tracked projections из canonical state, запускает manual Harness integrity и возвращает structured snapshot: summary по lifecycle, in-progress, blocked, completed и deterministic `STEP NEXT`. Не пишет product code и не интерпретирует project intent.

<a id="command-step-next"></a>
## `STEP NEXT`

Read-only deterministic рекомендация. Сначала продолжает resumable STEP execution, иначе выбирает executable STEP по прозрачному ranking: in-progress перед planned → priority → transitive downstream impact → число explicit risk flags как tie-breaker видимости → canonical roadmap order. Dependency completion не требуется для PLAN, но обязателен для IMPLEMENT. Result содержит exact canonical command и ranking breakdown. Это рекомендация, а не sprint planning.

<a id="command-project-reconcile"></a>
## `PROJECT RECONCILE`

Работает только после успешного `PROJECT INIT` (`.harness/manifest.yaml → project.initialized: true`).

Если проект ещё не инициализирован, команда ничего не меняет, не создаёт audit report/REQ/ADR/STEP и возвращает `PROJECT RECONCILE: NOT_APPLICABLE` с handoff → `PROJECT INIT`.

В инициализированном проекте migration начинается с **read-only preflight всех deterministic hard blockers до первой записи**: immutable review pins, STEP/REQ/ADR parse+identity, duplicate monolithic REQ/OQ IDs и project-owned template conflicts. Только после PASS выполняется idempotent active-schema migration: legacy STEP/REQ/ADR/OQ переводятся на current schema, а project-owned templates получают только missing structural keys/sections с сохранением existing values/prose; non-additive schema/kind/type conflict блокирует RECONCILE без partial mutation. Старые Ready plans без durable semantic proof становятся draft, immutable historical reports не переписываются. Затем пересобирает projections, сравнивает code/tests/config с REQ/ADR/architecture/STEP/evidence, запускает command-reference check и создаёт audit/corrective work. Не исправляет production code молча.

<a id="command-release-check"></a>
## `RELEASE CHECK`

Финальный release-oriented review по фактическим проектным gates: unresolved critical/high findings, requirements, migrations, tests/build, security, docs, upgrade/deploy concerns. Создаёт schema-v1 report в configured `protocol.releaseDirectory`.

<a id="command-harness-update-check"></a>
## `HARNESS UPDATE CHECK [TO <tag>]`

Read-only проверка маршрута Harness update. Manifest задаёт только `repository.harnessUpdatePolicy`; сама policy задаёт `source.update_manifest`, `state.lock_file` и `state.report_directory`. Именно эти configured paths используются как routing/lock/report topology.

Без `TO` конечный target берётся из configured `source.update_manifest.latest`. С `TO <tag>` пользователь задаёт конкретный конечный target. В обоих случаях updater обязан построить допустимую цепочку release hops; существующий immutable tag без route не считается допустимым target.

Dispatcher вызывает deterministic update engine напрямую, без model call. Команда моделирует весь route hop-by-hop, возвращает bridge/reload boundaries, safe changes/conflicts и не меняет working tree, Git refs, lock, STEP, commit, push или PR.

Команда разрешена как до, так и после `PROJECT INIT`: `project.initialized: false` не является blocker для проверки Harness update.

<a id="command-harness-update-apply"></a>
## `HARNESS UPDATE APPLY [TO <tag>]`

Maintenance mutation protocol layer без STEP и без model call. Dispatcher напрямую вызывает deterministic updater. Standalone APPLY сам выполняет fresh deterministic validation/preflight; в chain `CHECK > APPLY` переход разрешён только после PASS CHECK для того же target/route.

Команда применяет заранее проверенную цепочку строго hop-by-hop. Каждый hop использует immutable release tags и обычные ownership/3-way rules. Lock обновляется только после postcondition соответствующего hop. Если edge помечен `reloadRequired`, текущий запуск останавливается на достигнутом bridge с `UPDATER_RELOAD_REQUIRED`; после reload повторяется та же команда до исходного конечного target.

Команда разрешена до `PROJECT INIT`. Pre-init update не выполняет bootstrap проекта и не переводит `project.initialized` в `true`. При reload-required изменении template contract первый APPLY обновляет protocol layer/lock и останавливается; после reload повтор exact APPLY может детерминированно выровнять только доказанный old-release pre-INIT template baseline. Пользовательская prose/value/schema drift блокирует alignment и не перезаписывается.

Пример конечного target:

```text
HARNESS UPDATE APPLY TO vX.X.X
```

Updater не выполняет executable migration/install/bootstrap actions из configured update graph или target release, не делает commit/push/PR. Deterministic result содержит `nextAction`: `UPDATED → GIT CHECK`, `UPDATER_RELOAD_REQUIRED → reload-and-repeat exact APPLY`. Stable `NO_UPDATE → null`; если `NO_UPDATE` завершил deferred pre-INIT template alignment и вернул `repositoryMutated=true`, dispatcher направляет в `GIT CHECK`. Если GIT gate показывает pending schema migration уже инициализированного проекта, её выполняет `PROJECT RECONCILE` до commit.

<a id="command-git-check"></a>
## `GIT CHECK`

Read-only deterministic Git preflight без model call: dispatcher возвращает branch/upstream, staged/unstaged/untracked, Harness integrity и effective policy facts. Ничего не stage/commit/push; semantic logical-change анализ нужен только при последующем `GIT COMMIT`.

<a id="command-git-commit"></a>
## `GIT COMMIT` / `GIT COMMIT: <подсказка>`

Безопасно формирует локальный commit по `.harness/git-policy.toml`: проверяет Harness/diff, исключает unrelated/suspicious files, при необходимости создаёт ветку, stage-ит разрешённые файлы и формирует подробный Conventional Commit message по `.gitmessage`. `GIT COMMIT` никогда не делает push.

<a id="command-git-push"></a>
## `GIT PUSH`

Проверяет Harness, fetch/divergence и protected-branch policy, затем без force отправляет текущую ветку в configured remote. Standalone `GIT PUSH` сохраняет semantic scope check. В explicit chain, где PUSH непосредственно следует за успешно завершённым canonical `GIT COMMIT`, повторный model turn не нужен: dispatcher сначала доказывает продвижение HEAD относительно durable `gitHeadBefore`, затем вызывает deterministic `git-action.py push` напрямую. Одного заявленного `SUCCESS` для fast-path недостаточно.

<a id="command-git-pr"></a>
## `GIT PR`

Semantic worker готовит только PR prose. `git-action.py pr` детерминированно повторяет preflight, ищет/переиспользует либо создаёт GitHub PR, сверяет exact provider head OID и сам сохраняет local PR lifecycle state. Base/head/provider/draft policy модель не выбирает.

<a id="command-git-pr-finish"></a>
## `GIT PR FINISH`

Standalone post-merge cleanup без model call. Dispatcher напрямую вызывает deterministic executor, который через `git-preflight.py pr-finish` доказывает MERGED state, clean worktree, безопасную return branch и exact удаляемую PR-ветку.

После PASS выполняется exact ordered mutation plan: переключение на сохранённую return branch (при отсутствии local state — на PR base), разрешённый `--ff-only` sync и удаление старой локальной PR-ветки. Force-delete (`-D`), remote branch deletion, reset/rebase запрещены.

После успешного `GIT PR` deterministic executor уже сохраняет local-only `.harness/local/git/pr-state.json`; файл удаляется только после полностью успешного FINISH.

<a id="command-git-sync"></a>
## `GIT SYNC`

Dispatcher выполняет команду без model call: fetch + ahead/behind/divergence через deterministic executor. По умолчанию read-only report; при `sync.mode="ff-only"` допускается только безопасный fast-forward чистой рабочей копии. Merge/rebase автоматически не выполняются.
