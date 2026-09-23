# Git workflow Harness

Harness отделяет разработку от публикации изменений. `STEP IMPLEMENT` / `STEP REVIEW` не создают commits автоматически. Git-операции выполняются явными командами области `GIT` и управляются policy по `.harness/manifest.yaml → repository.gitPolicy`.

GitHub CLI `gh` не является dependency всего Git workflow: `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT SYNC` используют обычный Git. Установленный и авторизованный `gh` требуется только для текущей GitHub Pull Request capability — `GIT PR` и `GIT PR FINISH`. Подробнее: [`DEPENDENCIES.md`](DEPENDENCIES.md).

## Команды

```text
GIT CHECK
GIT COMMIT
GIT COMMIT: <необязательная подсказка>
GIT PUSH
GIT PR
GIT PR FINISH
GIT SYNC

# shorthand-цепочка
GIT CHECK > COMMIT > PUSH > PR
```

## Deterministic Git preflight

Safety-critical Git decisions вынесены в dependency-free tool:

```bash
python3 .harness/tools/git-preflight.py check --json
python3 .harness/tools/git-preflight.py commit --json --commit-type feat --slug user-search
python3 .harness/tools/git-preflight.py push --json
python3 .harness/tools/git-preflight.py pr --json
python3 .harness/tools/git-preflight.py sync --json
```

Tool не создаёт commit, не выполняет push, не открывает PR и не делает fast-forward. Он возвращает `PASS/BLOCKED` и exact mutation plan. Исключение — configured `git fetch`: fetch разрешён как operational refresh remote refs и не меняет working tree.

LLM/agent по-прежнему отвечает за semantic decisions — например, является ли diff одним logical change и какой commit type соответствует фактическому изменению. Но protected branch, remote divergence, publish state, force prohibition, clean-worktree requirement, PR base/tool и ff-only safety больше не интерпретируются вручную.

### `GIT CHECK`

Read-only preflight через `git-preflight.py check`: branch/protection/upstream, staged/unstaged/untracked, configured remotes/base и Harness integrity. Semantic оценку подозрительных/unrelated файлов и предполагаемого commit type/scope делает agent по фактическому diff.

### `GIT COMMIT`

`GIT COMMIT`:

- проверяет Harness и staged/worktree;
- не включает секреты, local brief, build/cache мусор;
- выявляет unrelated changes;
- после staging запускает deterministic `commit` preflight;
- при protected `auto-create` использует exact `details.requiredBranch`, затем повторяет gate;
- формирует подробный Conventional Commit message;
- только после `PASS` создаёт **локальный commit**.

Message строится по `.gitmessage`:

```text
feat(auth): добавь ротацию refresh-токенов

Контекст:
- Исключает повторное использование отозванной сессии.

Изменения:
- Добавлена ротация refresh token.
- Повторное использование старого token отзывает цепочку сессии.

Проверки:
- yarn test auth — PASS
- yarn typecheck — PASS

Traceability:
- STEP-024
- REQ-017
- ADR-006
```

Если diff содержит две независимые задачи, предпочтительны два commits, а не один общий `chore`.

### Branch policy

Default:

```text
main + feat  → feature/<slug>
main + fix   → bugfix/<slug>
main + docs  → docs/<slug>
main + chore → chore/<slug>
```

Это меняется через:

```toml
[branch]
when_on_protected = "auto-create" # auto-create | stay | block
```

Первый commit пустого template repo может остаться в `main` благодаря `allow_initial_commit_on_protected=true`. Для обычного commit на protected branch deterministic gate возвращает `PROTECTED_BRANCH_REQUIRES_NEW_BRANCH` либо `PROTECTED_BRANCH_COMMIT_BLOCKED` согласно policy.

### `GIT PUSH`

`GIT PUSH` сначала запускает `git-preflight.py push`. Tool использует только configured `push.remote`, при необходимости делает fetch, повторно запускает Harness validator, считает exact ahead/behind и формирует non-force `mutationPlan.argv`. Только `PASS` разрешает публикацию. По умолчанию:

```toml
[pull_request]
after_push = "create-if-missing"
```

Поэтому после push агент проверяет наличие PR и создаёт его при отсутствии. Чтобы только отправлять ветку:

```toml
[pull_request]
after_push = "never"
```

Для GitHub PR Harness предпочитает `gh`. Если CLI недоступен/не авторизован, push не объявляется неуспешным, но PR creation показывается как отдельный blocker.

### `GIT PR`

`GIT PR` можно вызвать отдельно. Перед provider action обязательный `git-preflight.py pr` доказывает, что exact local HEAD опубликован, configured base существует, preferred tool доступен и body template остаётся внутри repository. После `PASS` агент не создаёт duplicate PR при `reuse_existing=true` и заполняет traceability/verification из repository evidence. Default template — `.github/pull_request_template.md`.

### `GIT PR FINISH`

После merge Pull Request команда завершает локальный lifecycle feature branch.

```bash
python3 .harness/tools/git-preflight.py pr-finish --json
```

PASS требует чистое рабочее дерево, состояние provider `MERGED`, совпадение текущего локального HEAD с GitHub `headRefOid`, согласованный local PR state и существующую return branch без local-ahead/divergence. Это позволяет безопасно завершать как обычный merge, так и squash/rebase merge.

После PASS выполняй exact ordered `mutationPlan.steps`: switch → optional ff-only sync → удаление локальной PR-ветки. При сохранённом Git ancestry используется `git branch -d`; после squash/rebase merge — `git update-ref -d <ref> <verified-head-oid>`, где old OID обязан совпадать с подтверждённым GitHub `headRefOid`. `git branch -D`, удаление удалённой ветки, reset/rebase запрещены. Local-only `.harness/local/git/pr-state.json` удаляется только после полностью успешного FINISH.

### `GIT SYNC`

Default `GIT SYNC` через `git-preflight.py sync` делает fetch + ahead/behind report. Для автоматического безопасного fast-forward:

```toml
[sync]
mode = "ff-only"
```

В `ff-only` tool выдаёт exact `git merge --ff-only <remote>/<branch>` только для clean behind-only state. Local-ahead/diverged/dirty state блокируется. Merge/rebase конфликтующей истории автоматически не выполняются.

## Цепочка публикации

Для обычной последовательной публикации допустим shorthand:

```text
GIT CHECK > COMMIT > PUSH > PR
```

Он эквивалентен четырём отдельным canonical commands той же области. Structural validity определяется не этим prose-описанием, а `.harness/command-transitions.json`; полная матрица находится в [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md). Для Git graph соответствует publication flow `CHECK → COMMIT → PUSH → PR` с дополнительными explicit shortcut edges из таблицы. Обратный/неразрешённый порядок отклоняется как `INVALID_CHAIN` до любых действий. После structural PASS runtime conditions каждого edge проверяются отдельно. Уже созданный commit не откатывается автоматически, если последующий push или PR оказался blocked.

Cross-domain chain запрещён: `STEP RUN STEP-NNN > GIT COMMIT` не является допустимой командой. Полная семантика — в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md).

## Safety defaults

Harness никогда по умолчанию не выполняет:

- `git push --force` / `--force-with-lease`;
- `git reset --hard`;
- `git clean -fd`;
- автоматический merge/rebase;
- commit amend;
- staging подозрительных/несвязанных файлов.

Перед Git mutation запускается соответствующий deterministic preflight; commit/push gates при policy requirement вызывают тот же `.harness/tools/validate.py --mode commit`, который используется Harness workflow. CI отдельно прогоняет synthetic Git preflight regression и fail-closed Git-policy regression.

## Что настраивать

Главный файл разрешается через `.harness/manifest.yaml → repository.gitPolicy`; default template path — `.harness/git-policy.toml`.

Чаще всего меняются:

- `language.commitMessages` в manifest;
- `commit.stage_mode`;
- `branch.when_on_protected`;
- `branch.name_pattern` и prefixes;
- `push.remote`;
- `push.allow_protected`;
- `pull_request.after_push`;
- `pull_request.draft`;
- `sync.mode`.

## Мелкие изменения без STEP

Для typo/formatting/другого подтверждённого micro-change STEP не обязателен. Если пользователь уже внёс правку, достаточно `GIT CHECK > COMMIT` либо тех же команд по отдельности. Git operator обязан проверить, что diff действительно не меняет behavior/API/data/security/architecture/dependencies. Подробности: [`QUICK_CHANGES.md`](QUICK_CHANGES.md).

Язык commit message берётся из `.harness/manifest.yaml` → `language.commitMessages`.
