---
name: git-workflow
description: Provide only semantic Git inputs for COMMIT, PUSH follow-up policy, and PR prose; deterministic tools own Git/provider safety and mutations.
---
# git-workflow

CTS направляет сюда только Git-команды с semantic частью: `GIT COMMIT`, `GIT PUSH`, `GIT PR`. `GIT CHECK`, `GIT SYNC` и `GIT PR FINISH` dispatcher выполняет без LLM.

## Общие semantic обязанности

- Проверь фактический diff и logical scope; unrelated changes не включай.
- Если change без STEP меняет behavior/API/data/security/architecture/dependencies — остановись и предложи `STEP ADD:`.
- Не переопределяй `PASS/BLOCKED`, branch/remote/base/provider/draft/force/ff-only decisions deterministic tools.
- Force-push, destructive reset/clean, automatic merge/rebase и amend не добавляй.

## GIT COMMIT

1. Определи один logical change.
2. Выбери разрешённый commit type и короткий semantic slug.
3. Подготовь staging согласно configured `commit.stage_mode`; не используй `git add .` вслепую.
4. Сформируй commit message по project language/`.gitmessage` и сохрани только в `.harness/local/git/commit-message.txt`.
5. Вызови один mutation boundary:

```bash
python3 .harness/tools/git-action.py commit --json \
  --commit-type '<type>' \
  --slug '<slug>' \
  --message-file .harness/local/git/commit-message.txt
```

Executor сам повторяет commit preflight, при необходимости создаёт exact required branch, проверяет message mechanics, создаёт commit и доказывает изменение HEAD. Ручной `git commit` не выполняй.

## GIT PUSH

После проверки semantic scope вызови:

```bash
python3 .harness/tools/git-action.py push --json
```

Executor сам fetch/preflight-ит configured remote, запрещает force/remote-ahead/protected-branch violations и проверяет remote HEAD postcondition. Не выполняй `git push` вручную.

Используй только возвращённый `afterPush`:

- `never` — закончить;
- `ask` — предложить `GIT PR`, не создавать его скрыто;
- `create-if-missing` — перейти к semantic PR prose только если command flow/policy разрешает продолжение. Provider existence/create проверит PR executor, не модель.

## GIT PR

Подготовь только semantic PR body по repository evidence/template в `.harness/local/git/pr-body.md`. Title-файл нужен только если executor/preflight явно вернул `PR_TITLE_REQUIRED`; тогда создай одно-строчный `.harness/local/git/pr-title.txt`.

Вызови:

```bash
python3 .harness/tools/git-action.py pr --body-file .harness/local/git/pr-body.md --json
```

При требовании title повтори с `--title-file`.

Не вызывай provider CLI вручную (`gh pr create/list/view`, `tea pulls ...`, `tea api ...`), не выбирай head/base/provider/tool/draft и не записывай `pr-state.json` вручную. Executor сам разрешает configured GitHub/Gitea adapter, find/reuse/create-ит exact PR, сверяет provider head OID и сохраняет lifecycle state.

## Failure policy

Любой deterministic `BLOCKED` останавливает segment. Не обходи blocker ручной Git/provider командой с более слабыми параметрами.


## Recovery после interruption

Повторный запуск semantic segment не означает повтор external mutation.

`git-action.py` сохраняет bounded side-effect checkpoint в active execution и перед новой mutation сначала reconciles repository/provider facts:

- COMMIT — reflog marker + HEAD/parent/tree;
- PUSH — live remote branch HEAD;
- PR — exact matching provider object по head/base/head SHA.

Если side effect уже доказан, executor возвращает `SUCCESS` с `recovered: true` и не повторяет mutation. Если исходное состояние не изменилось, разрешается новая попытка. Если outcome неоднозначен, executor возвращает `SIDE_EFFECT_RECOVERY_AMBIGUOUS`.

Не удаляй и не редактируй `.harness/local/execution/execution-status.json` ради retry и не обходи recovery ручным Git/provider CLI.


## Existing PR maintenance

Если пользователь просит разобрать failed CI, review comments, подготовить PR к review или ограниченно следить за уже открытым PR, используй internal `pr-maintenance` для read-only provider facts и semantic classification. Не выполняй mutations из этого capability: исправления возвращаются в обычный STEP/QUICK FIX flow, а публикация — в canonical GIT commands.
