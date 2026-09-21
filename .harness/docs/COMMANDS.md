# Команды Harness

Команды — стабильный человеко-машинный интерфейс. Каноническая форма начинается с явного namespace: `<DOMAIN> <ACTION> ...`. Подробный синтаксис и chain operator `>` описаны в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md).

Допустимость переходов между командами определяется **только** machine-readable graph `.harness/command-transitions.json`. Полная человекочитаемая матрица — [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md). До skill routing canonical command проходит deterministic `.harness/tools/validate-command.py`.

State transitions выполнения описаны в `.harness/docs/EXECUTION_PROTOCOL.md`.

Старые ненеймспейсные формы не являются каноническими alias. Локальные пользовательские alias-команды можно добавить только явно в `AGENTS.local.md`; они читаются после `AGENTS.md`.

## Цепочки

Для разрешённых команд одной области можно не повторять namespace:

```text
GIT CHECK > COMMIT > PUSH > PR
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
HARNESS UPDATE CHECK TO vX.X.X > APPLY
```

Вся цепочка сначала нормализуется и проверяется по `.harness/command-transitions.json`. Отсутствующий edge означает `INVALID_CHAIN` и ноль выполненных сегментов. После structural PASS дальнейшее выполнение определяется `onPreviousResult` и `runtimePreconditions` конкретного edge. Полные правила — в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md) и [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md).

## `PROJECT INIT`

Однократный bootstrap из configured `sources.localBrief`. Создаёт schema-v1 project knowledge base и initial roadmap, но не production code. INIT сохраняет два immutable semantic reports — requirements и roadmap — с exact deterministic basis, пересобирает projections и завершается только через `finalize-project-init.py`. Ручное `project.initialized: true` не является валидным completion.

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

## `SKILL FIND: <описание>`

Ищет подходящие Agent Skills/repository skills на GitHub и в доступном web, инспектирует содержимое и сохраняет schema-v1 shortlist в configured `protocol.skillSearchDirectory`. Максимальное число кандидатов задаёт `skills.search.maxResults` (1–10). Ничего не устанавливает. Для каждого кандидата возвращает exact source/path/link, fit, limitations, license/provenance и safety notes.

Следующий шаг: `SKILL INSTALL: #N` либо `SKILL CREATE: <описание>`.

## `SKILL INSTALL: <source | #N>`

После явного выбора пользователя повторно инспектирует сторонний skill, не выполняя его scripts, блокирует high-risk варианты, затем устанавливает bundle в `.agents/skills/`, фиксирует `UPSTREAM.md`, обновляет `docs/skills/REGISTRY.md` и generated `SKILL-ROUTING` block `AGENTS.md`. `#N` resolve-ится из последнего durable search report, а не из chat history.

## `SKILL CREATE: <описание>`

Создаёт project-native skill, если готового подходящего варианта нет. Основан на project conventions и актуальной авторитетной документации, регистрируется в Registry и routing block. Не дублирует core harness protocol.

## `GITHUB GENERATE TEMPLATES`

Изучает актуальные technologies/tooling/CI/project conventions и полностью пересоздаёт managed GitHub Issue Forms и Pull Request template. Работает на любом этапе; существующие target files заменяются, чтобы пользователь увидел изменение в обычном diff. Язык берётся из `language.githubTemplates`. Подробнее: `GITHUB_TEMPLATES.md`.

## `PROJECT QUICK FIX: <описание>`

Выполняет маленькую low-risk правку без создания STEP/REQ/ADR. Разрешён только для micro-change без изменения product/API/data/security/architecture/dependencies. Если scope оказался больше — команда прекращается и предлагает `STEP ADD:`. Если пользователь уже исправил мелочь вручную, можно сразу использовать `GIT CHECK > COMMIT` или отдельные `GIT CHECK` и `GIT COMMIT`. Подробнее: `QUICK_CHANGES.md`.

## `STEP PLAN STEP-NNN`

Сначала валидирует task contract, type-specific dependency proofs, linked REQ/ADR, explicit `architecture_refs` и relevant OQ. После draft Implementation plan обязательный independent planning-review сохраняет exact `context_basis` и отдельный `plan_content_hash`. Только matching PASS позволяет `stamp-plan` выставить `plan.status=ready`. Изменение plan body или relevant upstream input делает plan stale без повторного reasoning.

## `STEP IMPLEMENT STEP-NNN`

Реализует только current Ready plan в пределах task contract. При первой product mutation ставит canonical `status: in_progress`, добавляет/обновляет tests и запускает verification. `status: completed` недопустим до schema-valid independent review PASS и type-specific completion proof.

## `STEP REVIEW STEP-NNN`

Независимая проверка exact repository revision. Перед reasoning deterministic preselector вычисляет обязательные security/test reviewers по `review.security/tests`, risk flags, STEP type и factual changed surface. Immutable schema-v1 report содержит `git_head` и при dirty tree `worktree_hash`, structured findings и specialized review metadata. `FAIL` разрешён только для implementation/evidence defects; contract defect → `BLOCKED`. Crash recovery доверяет только schema-valid report для той же revision.

## `STEP FIX STEP-NNN`

Исправляет подтверждённые findings последнего применимого FAIL review. Не расширяет scope. После FIX следующая команда — `STEP REVIEW STEP-NNN`.

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

При blocker или исчерпании циклов останавливается и не маскирует failure. Лимит `execution.maxFixReviewCycles` enforce-ится Execution Resolver детерминированно и сохраняется между sessions.

## `STEP AUDIT STEP-NNN`

Формальная проверка фактического состояния без production mutation. Подходит для historical reconciliation, architecture/data/security audits. Defects становятся findings/corrective STEP, а не скрытыми исправлениями.

## `PROJECT STATUS`

Проверяет и при необходимости регенерирует projection статусов, показывает blockers, unblocked work и drift indicators. Не пишет product code.

## `STEP NEXT`

Read-only рекомендация следующего **unblocked** шага на основании dependencies, priority, risk и roadmap. Не выбирает просто минимальный номер.

## `PROJECT RECONCILE`

Работает только после успешного `PROJECT INIT` (`.harness/manifest.yaml → project.initialized: true`).

Если проект ещё не инициализирован, команда ничего не меняет, не создаёт audit report/REQ/ADR/STEP и возвращает `PROJECT RECONCILE: NOT_APPLICABLE` с handoff → `PROJECT INIT`.

В инициализированном проекте сначала выполняет idempotent active-schema migration, если она требуется: legacy STEP/REQ/ADR/OQ и project-owned templates переводятся на current schema, старые Ready plans без durable semantic proof становятся draft, immutable historical reports не переписываются. Затем пересобирает projections, сравнивает code/tests/config с REQ/ADR/architecture/STEP/evidence, запускает command-reference check и создаёт audit/corrective work. Не исправляет production code молча.

## `RELEASE CHECK`

Финальный release-oriented review по фактическим проектным gates: unresolved critical/high findings, requirements, migrations, tests/build, security, docs, upgrade/deploy concerns. Создаёт schema-v1 report в configured `protocol.releaseDirectory`.

## `HARNESS UPDATE CHECK [TO <tag>]`

Read-only проверка маршрута Harness update. Manifest задаёт только `repository.harnessUpdatePolicy`; сама policy задаёт `source.update_manifest`, `state.lock_file` и `state.report_directory`. Именно эти configured paths используются как routing/lock/report topology.

Без `TO` конечный target берётся из configured `source.update_manifest.latest`. С `TO <tag>` пользователь задаёт конкретный конечный target. В обоих случаях updater обязан построить допустимую цепочку release hops; существующий immutable tag без route не считается допустимым target.

Команда моделирует весь route hop-by-hop, показывает bridge/reload boundaries, safe changes/conflicts и не меняет working tree, Git refs, lock, STEP, commit, push или PR.

Команда разрешена как до, так и после `PROJECT INIT`: `project.initialized: false` не является blocker для проверки Harness update.

## `HARNESS UPDATE APPLY [TO <tag>]`

Maintenance mutation protocol layer без STEP. Standalone APPLY сам выполняет fresh deterministic validation/preflight; в chain `CHECK > APPLY` переход разрешён только после PASS CHECK для того же target/route.

Команда применяет заранее проверенную цепочку строго hop-by-hop. Каждый hop использует immutable release tags и обычные ownership/3-way rules. Lock обновляется только после postcondition соответствующего hop. Если edge помечен `reloadRequired`, текущий запуск останавливается на достигнутом bridge с `UPDATER_RELOAD_REQUIRED`; после reload повторяется та же команда до исходного конечного target.

Команда разрешена до `PROJECT INIT`. Pre-init update обновляет только protocol layer/lock, не выполняет bootstrap проекта и не переводит `project.initialized` в `true`.

Пример конечного target:

```text
HARNESS UPDATE APPLY TO vX.X.X
```

Updater не выполняет executable migration/install/bootstrap actions из configured update graph или target release, не делает commit/push/PR. Project-owned schema migration после protocol update выполняет `PROJECT RECONCILE`. После неё: inspect diff → `GIT CHECK > COMMIT` либо те же команды отдельно.

## `GIT CHECK`

Read-only Git preflight: проверяет branch/upstream/ahead-behind, staged/unstaged/untracked, Harness integrity, policy и подозрительные файлы. Ничего не stage/commit/push.

## `GIT COMMIT` / `GIT COMMIT: <подсказка>`

Безопасно формирует локальный commit по `.harness/git-policy.toml`: проверяет Harness/diff, исключает unrelated/suspicious files, при необходимости создаёт ветку, stage-ит разрешённые файлы и формирует подробный Conventional Commit message по `.gitmessage`. `GIT COMMIT` никогда не делает push.

## `GIT PUSH`

Проверяет Harness, fetch/divergence и protected-branch policy, затем без force отправляет текущую ветку в configured remote. После успешного push применяет PR-policy: ничего, предложить PR или создать PR при отсутствии.

## `GIT PR`

Создаёт Pull Request для опубликованной ветки либо возвращает существующий PR согласно policy. Использует `.github/pull_request_template.md`, repository evidence и verification; дубликаты не создаёт.

## `GIT SYNC`

Fetch + ahead/behind/divergence. По умолчанию read-only report; при `sync.mode="ff-only"` допускает только безопасный fast-forward чистой рабочей копии. Merge/rebase автоматически не выполняются.
