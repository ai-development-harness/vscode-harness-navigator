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

`git-preflight.py` не создаёт mutation и возвращает `PASS/BLOCKED` + exact plan. Mechanical mutations исполняет `.harness/tools/git-action.py`. `GIT SYNC` и `GIT PR FINISH` dispatcher вызывает напрямую без LLM. `GIT COMMIT` и `GIT PR` сохраняют semantic message/prose boundary. Standalone `GIT PUSH` сохраняет semantic logical-scope check, но PUSH непосредственно после успешного canonical COMMIT в той же explicit chain выполняется deterministic fast-path без второго model turn. Configured `git fetch` разрешён как operational refresh remote refs.

LLM/agent по-прежнему отвечает за semantic decisions — например, является ли diff одним logical change и какой commit type соответствует фактическому изменению. Но protected branch, remote divergence, publish state, force prohibition, clean-worktree requirement, PR base/tool и ff-only safety больше не интерпретируются вручную.

### `GIT CHECK`

Read-only deterministic preflight без model call: dispatcher напрямую запускает `git-preflight.py check` и возвращает branch/protection/upstream, staged/unstaged/untracked, configured remotes/base и Harness integrity. Semantic grouping/logical scope не нужен для CHECK; он выполняется позже только если пользователь действительно переходит к `GIT COMMIT`.

### `GIT COMMIT`

`GIT COMMIT`:

- проверяет Harness и staged/worktree;
- не включает секреты, local brief, build/cache мусор;
- выявляет unrelated changes;
- после semantic staging формирует подробный Conventional Commit message в `.harness/local/git/commit-message.txt`;
- вызывает `git-action.py commit --commit-type ... --slug ... --message-file ...`;
- executor повторяет preflight, при protected `auto-create` создаёт только exact required branch;
- message читается и валидируется один раз Harness-ом, затем exact captured text передаётся `git commit -F -` через stdin; Git не переоткрывает mutable input path;
- только после PASS создаёт **локальный commit** и проверяет новый HEAD.
- после доказанного commit SUCCESS пытается удалить только exact validated `.harness/local/git/commit-message.txt`; symlink path запрещён, при failure message сохраняется для retry, а secondary cleanup failure возвращается warning и не отменяет уже созданный commit.

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

`GIT PUSH` выполняется через `git-action.py push`. Executor запускает `push` preflight, использует только configured `push.remote`, при необходимости делает fetch, повторно запускает Harness validator, исполняет только exact non-force `mutationPlan.argv` и проверяет published HEAD. По умолчанию:

```toml
[pull_request]
after_push = "create-if-missing"
```

Standalone `GIT PUSH` остаётся semantic boundary для проверки logical scope и follow-up: `git-action.py push` возвращает factual `afterPush = never|ask|create-if-missing`, и модель использует именно это поле вместо повторного чтения Git policy. Если PUSH является следующим segment после успешного `GIT COMMIT` в той же chain, logical scope уже проверен COMMIT: перед fast-path dispatcher дополнительно доказывает, что repository HEAD действительно изменился относительно `gitHeadBefore`, и только затем вызывает `git-action.py push` без второго model turn. Одного semantic `SUCCESS` недостаточно. Сама push mutation в обоих случаях полностью deterministic. Чтобы только отправлять ветку:

```toml
[pull_request]
after_push = "never"
```

Для GitHub PR Harness предпочитает `gh`. Если CLI недоступен/не авторизован, push не объявляется неуспешным, но PR creation показывается как отдельный blocker.

### `GIT PR`

`GIT PR` можно вызвать отдельно. Модель формирует только semantic body (и title, если `title_from_commit=false`) в `.harness/local/git/**`, затем вызывает `git-action.py pr`. Executor повторяет preflight, читает semantic input в memory snapshot, ищет exact open head/base PR через configured provider, переиспользует его по policy либо создаёт новый. При create captured body передаётся `gh pr create --body-file -` через stdin, поэтому provider не переоткрывает mutable `pr-body.md`; title также используется как captured string. После этого executor проверяет provider `headRefOid` против exact published HEAD и сам сохраняет `.harness/local/git/pr-state.json`. Только после этих postconditions executor пытается удалить exact validated `pr-body.md` / `pr-title.txt`; symlink paths запрещены, changed/undeletable inputs сохраняются с cleanup warning. Secondary cleanup failure не превращает уже созданный/reused PR в BLOCKED. `pr-state.json` остаётся recovery state до успешного `GIT PR FINISH`. Default body template — `.github/pull_request_template.md`.

### `GIT PR FINISH`

После merge Pull Request команда детерминированно, без semantic skill/model call, завершает локальный lifecycle feature branch.

```bash
python3 .harness/tools/git-preflight.py pr-finish --json
```

PASS требует чистое рабочее дерево, состояние provider `MERGED`, совпадение текущего локального HEAD с GitHub `headRefOid`, согласованный local PR state и существующую return branch без local-ahead/divergence. Это позволяет безопасно завершать как обычный merge, так и squash/rebase merge.

После PASS exact ordered plan исполняет `git-action.py pr-finish`: switch → optional ff-only sync → удаление локальной PR-ветки → postconditions → удаление local PR state. При обычном merge используется `git branch -d`, после squash/rebase — compare-and-swap `git update-ref -d <ref> <verified-head-oid>`. `git branch -D`, удаление remote branch, reset/rebase запрещены.

`GIT PR FINISH` crash-resumable: если session/process оборвался после переключения на `returnBranch`, повторный запуск принимает только recorded `headBranch|returnBranch`, заново сверяет provider `MERGED`, exact `headRefOid` и return-branch relation, после чего выполняет только оставшиеся sync/delete steps. Если feature ref уже удалён, но local PR state остался, повторный запуск завершает только state cleanup.

### `GIT SYNC`

`GIT SYNC` dispatcher выполняет детерминированно, без semantic skill/model call. Default `GIT SYNC` через `git-action.py sync` повторяет preflight и делает fetch + ahead/behind report; при `ff-only` executor сам выполняет разрешённый fast-forward и проверяет HEAD. Для автоматического безопасного fast-forward:

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
