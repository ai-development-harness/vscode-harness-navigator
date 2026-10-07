# PR Maintenance

`pr-maintenance` — internal capability вокруг уже существующего Pull Request. Она не добавляет новую Git-команду и не меняет authority: commit/push/PR lifecycle остаётся у canonical `GIT` workflow.

## Зачем

После создания PR появляются четыре повторяющихся задачи:

1. понять первопричину упавшего CI;
2. собрать comments/reviews в actionable set;
3. подготовить краткую карту изменений для reviewer;
4. ограниченно перечитать состояние PR, пока идёт CI/review.

Раньше это обычно делалось ad hoc через provider CLI и chat context. Теперь сначала строится exact provider snapshot, затем model output валидируется против него.

## Provider snapshot

```bash
python3 .harness/tools/pr-maintenance.py snapshot --selector feature/foo --pretty
```

Selector может быть branch или PR number. Если selector не указан, используется текущая branch.

Snapshot содержит:

- normalized PR identity/head/base;
- checks/statuses с external IDs, state/conclusion, URL и доступной provider diagnostics;
- issue comments с external IDs;
- submitted reviews с external IDs;
- changed files;
- `snapshotBasis`.

Для GitHub facts читаются через configured `gh`; для Gitea — через configured `tea` API. Если конкретный provider/API не даёт необходимую read capability, Harness возвращает explicit `PR_MAINTENANCE_CAPABILITY_UNAVAILABLE`, а не заменяет факт догадкой модели.

Provider lists bounded до 100 элементов на категорию. Достижение лимита блокирует snapshot как потенциально truncated.

## Semantic validation

Model формирует payload и передаёт его обратно:

```bash
python3 .harness/tools/pr-maintenance.py validate \
  --selector feature/foo \
  --payload-file .harness/local/pr-maintenance/result.json \
  --pretty
```

Tool заново читает provider state. Если `snapshotBasis` изменился — `PR_SNAPSHOT_STALE`.

Это закрывает race:

```text
model прочитал comment #123
→ reviewer добавил ещё comment / CI перезапустился
→ model подготовил действие по старому состоянию
→ validation re-fetch
→ stale basis => BLOCKED
```

## Modes

### `ci-triage`

Ссылаться можно только на failed/pending check facts. За один pass разрешён максимум один `fix`: цель — первая actionable root failure, а не пачка downstream симптомов.

### `feedback`

Каждый current comment/review fact получает `fix | dismiss | clarify`. Duplicate provider fact IDs запрещены; unknown IDs запрещены.

### `reviewability`

Создаётся reviewer guidance: summary, risks, verification и список generated/mechanical paths. Mechanical path обязан реально быть в PR diff.

### `babysit`

Повторное чтение ограничено `refreshCount=0..3`. Capability не polling daemon и не automation scheduler.

## Mutation boundary

Validated semantic output не выполняет mutation.

```text
semantic PR finding
      ↓
normal STEP/FIX/QUICK FIX
      ↓
GIT CHECK / COMMIT / PUSH
      ↓
provider snapshot again
```

Hard invariants:

- no auto-merge;
- no hidden force push;
- no amend/rebase/history rewrite без отдельной explicit policy/approval;
- provider IDs/evidence не заменяются model-generated identifiers;
- `GIT PR FINISH` остаётся единственным deterministic local post-merge lifecycle.

## Idempotence

Одинаковый snapshot + одинаковый semantic payload нормализуются одинаково и ничего не записывают. Повторный запуск после provider change обязан получить новый `snapshotBasis`.
