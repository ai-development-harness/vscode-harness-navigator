---
name: git-workflow
description: Safe Git workflow using configured repository policy plus deterministic preflight gates before COMMIT, PUSH, PR and SYNC mutations.
---
# git-workflow

Используй для `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT PR FINISH`, `GIT SYNC` и валидных Git-chain segments.

## Главный принцип

Git policy остаётся в configured `.harness/manifest.yaml → repository.gitPolicy`, но safety-critical решение «можно ли сейчас выполнять mutation» принимает deterministic tool:

```bash
python3 .harness/tools/git-preflight.py check --json
python3 .harness/tools/git-preflight.py commit --json [--commit-type <type>] [--slug <slug>]
python3 .harness/tools/git-preflight.py push --json
python3 .harness/tools/git-preflight.py pr --json
python3 .harness/tools/git-preflight.py sync --json
```

Agent не должен вручную переопределять `PASS/BLOCKED`, protected-branch decision, remote ahead/behind, publish state, PR base/tool или ff-only safety.

Preflight не создаёт commit, не делает push, не открывает PR и не fast-forward-ит branch. Единственная допустимая operational side effect — `git fetch` там, где policy требует актуального remote state.

## Общие правила

1. До mutation изучи фактический diff/status и semantic scope.
2. Не включай unrelated changes.
3. `require_single_logical_change` остаётся semantic обязанностью агента: deterministic tool не угадывает смысл файлов.
4. STEP/REQ/ADR traceability не обязательна для подтверждённого micro-change/PROJECT QUICK FIX.
5. Если diff без STEP меняет behavior/API/data/security/architecture/dependencies — остановись и предложи `STEP ADD:`.
6. Force-push, destructive reset/clean, automatic merge/rebase и amend запрещены без отдельного явного protocol path; обычный Git workflow их не использует.

## GIT CHECK

Запусти:

```bash
python3 .harness/tools/git-preflight.py check --json
```

Покажи branch, protection, upstream, staged/unstaged/untracked, configured remotes/base и Harness validation result. CHECK ничего не stage/commit/push.

## GIT COMMIT

1. Определи фактический logical change по diff.
2. Выбери commit type только из `commit.types`; optional user hint не заменяет diff.
3. Stage согласно `commit.stage_mode`:
   - `staged-only` — не добавлять новые paths к index;
   - `tracked-only` — не stage новые files;
   - `all-safe` — stage только проверенный logical change, без `git add .` вслепую.
4. После staging и непосредственно перед commit запусти:

```bash
python3 .harness/tools/git-preflight.py commit --json \
  --commit-type '<type>' \
  --slug '<short semantic slug>'
```

5. Если `reasonCode=PROTECTED_BRANCH_REQUIRES_NEW_BRANCH`, используй **точный** `details.requiredBranch`, создай branch, затем повтори preflight. Не вычисляй имя повторно вручную.
6. Только `PASS` разрешает `git commit`.
7. Сформируй message по `.gitmessage` и policy:
   - Conventional Commit;
   - subject ≤ `subject_max_length`;
   - body только согласно `require_body`;
   - verification/traceability — согласно policy;
   - при `sign=true` используй Git signing, не отключай его молча.
8. Выполни commit. COMMIT никогда не делает push.

Machine gate детерминированно проверяет Harness validation, empty commit, stage-mode ограничения, protected branch и initial-commit exception. Семантику logical change/message всё ещё обязан проверить агент.

## GIT PUSH

Непосредственно перед push:

```bash
python3 .harness/tools/git-preflight.py push --json
```

Tool:

- использует только configured `push.remote`;
- выполняет fetch, если `fetch_before_push=true`;
- запускает Harness validation, если требуется;
- применяет `require_clean_worktree`;
- проверяет protected branch / initial bootstrap exception;
- считает exact ahead/behind относительно configured remote branch;
- блокирует remote-ahead состояние: при `force=never` безопасного автоматического push поверх неизвестных remote commits нет;
- гарантирует `force=never`;
- формирует `mutationPlan.argv` с `--set-upstream` / tag behavior согласно policy.

Выполняй только план после `PASS`. Не добавляй `--force`, `--force-with-lease` или другой remote.

После успешного push применяй `pull_request.after_push`: `never | ask | create-if-missing`.

## GIT PR

Непосредственно перед PR:

```bash
python3 .harness/tools/git-preflight.py pr --json
```

PASS доказывает:

- current HEAD полностью опубликован в configured push remote;
- configured PR base существует;
- `pull_request.provider` / `preferred_tool` разрешены policy и tool доступен;
- body template существует внутри repository;
- draft/reuse/title flags прочитаны из policy.

Используй `mutationPlan` и policy буквально. Не подменяй provider/tool самостоятельно. Если `reuse_existing=true`, сначала переиспользуй существующий open PR той же head/base.

После успешного создания/переиспользования PR сохрани local-only `.harness/local/git/pr-state.json` schema v1 с полями `pr`, `headBranch`, `baseBranch`, `returnBranch`, `url`. Для `returnBranch` используй предыдущую существующую локальную ветку из истории переключений Git, если она отличается от head; иначе configured/actual PR base. Файл находится под уже ignored `.harness/local/**` и не коммитится. `GIT PR FINISH` дополнительно сверяет текущий локальный HEAD с GitHub `headRefOid`, поэтому squash/rebase merge не требует Git ancestry.

## GIT PR FINISH

1. Запусти `python3 .harness/tools/git-preflight.py pr-finish --json`.
2. При `BLOCKED` остановись и покажи `reasonCode`; не обходи его ручным switch/delete.
3. При PASS выполни каждый `mutationPlan.steps[*].argv` строго по порядку.
4. Не используй `git branch -D`. Для обычного merge deterministic plan использует `git branch -d`; для squash/rebase merge он может вернуть `git update-ref -d <ref> <verified-head-oid>` с обязательным old OID. Не меняй эту команду вручную, не удаляй удалённую ветку и не делай reset/rebase.
5. Если любой step завершился ошибкой, остановись и сохрани local PR state.
6. Только после успеха всех steps и `deleteStateFileAfterSuccess=true` удали указанный `stateFile`.

## GIT SYNC

Запусти:

```bash
python3 .harness/tools/git-preflight.py sync --json
```

Tool сначала fetch-ит только `sync.fetch_remote` и считает ahead/behind.

- `mode=report` → mutation запрещена, только отчёт.
- `mode=ff-only` → tool выдаёт `git merge --ff-only <remote>/<branch>` только для clean behind-only state.
- local-ahead или diverged state блокирует автоматический sync.
- automatic merge/rebase не разрешены.

Выполняй mutation только если `status=PASS` и `mutationPlan.operation` содержит разрешённый ff-only plan.

## Failure policy

Любой `BLOCKED` останавливает текущий Git segment. Не обходи blocker ручной командой с более слабыми параметрами.

Типичные blockers:

- detached HEAD;
- invalid configured Git policy;
- Harness validation failure;
- empty commit при `allow_empty=false`;
- protected-branch commit/push;
- remote missing/ahead;
- dirty worktree при strict push/sync;
- unpublished PR head;
- unavailable configured PR tool;
- missing PR base/template;
- diverged/non-ff sync.

После изменения Git policy или preflight contract обновляй synthetic regression и документацию одновременно.
