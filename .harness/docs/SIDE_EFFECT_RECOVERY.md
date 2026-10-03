# Side-effect recovery

## Назначение

Side-effect recovery — внутренний recovery contract для mutation-команд, у которых повтор после crash может создать второй внешний эффект.

Он **не является** новой command state machine:

- допустимые переходы команд по-прежнему определяет только CTS;
- execution state хранит текущую/возобновляемую invocation;
- side-effect checkpoint хранит bounded proof одной mutation attempt;
- canonical project artifacts не заменяются local operational state.

## Фазы

Внутри одной mutation attempt используются фазы:

~~~text
prepared
→ side_effect_started
→ side_effect_observed
→ postconditions_verified
~~~

`prepared` означает: deterministic inputs уже зафиксированы, но внешний side effect ещё не должен считаться начавшимся.

`side_effect_started` означает: mutation boundary пересечён, outcome после crash может быть неизвестен.

`side_effect_observed` означает: внешний факт уже прочитан обратно из Git/provider.

`postconditions_verified` означает: внешний факт соответствует подготовленному exact intent.

## Где хранится proof

Checkpoint хранится в active record:

~~~text
.harness/local/execution/execution-status.json
  executions[].current.context.sideEffect
~~~

Contract version: `1`.

Proof:

- ограничен 8 KiB compact UTF-8 JSON;
- проходит schema validation при чтении execution state;
- не содержит credential/token/password/secret-like keys;
- не является append-only log;
- удаляется естественным bounded lifecycle execution state после terminal completion.

Новый unbounded event journal не вводится.

## Recovery decision

После restart mutation executor сначала наблюдает внешний факт и классифицирует состояние:

- **ALREADY_APPLIED** — intended side effect уже доказан; повтор запрещён, command завершается через recovery;
- **SAFE_RETRY** — наблюдаемое состояние всё ещё равно pre-side-effect baseline; разрешена новая attempt;
- **AMBIGUOUS** — состояние отличается и от baseline, и от intended result; command блокируется с `SIDE_EFFECT_RECOVERY_AMBIGUOUS`.

Chat history, сообщение модели или старый stdout не являются proof.

## GIT COMMIT

До `git commit` checkpoint фиксирует HEAD до mutation, branch, staged tree и уникальный reflog marker.

После crash executor ищет commit по marker и проверяет exact HEAD, branch, parent и committed tree. Если marker доказывает созданный commit и postconditions совпадают, второй commit не создаётся. Если marker не найден, но repository state остался на исходном HEAD/branch, разрешается retry. Если HEAD/branch изменились и outcome нельзя доказать, recovery блокируется.

## GIT PUSH

До push фиксируются exact local HEAD, configured remote, branch, live remote HEAD до mutation и `afterPush` policy result.

После crash используется live `git ls-remote`, а не только local remote-tracking ref:

- remote HEAD == intended local HEAD → push уже состоялся;
- remote HEAD == baseline → безопасный retry;
- любое третье значение → `SIDE_EFFECT_RECOVERY_AMBIGUOUS`.

Force push по-прежнему запрещён Git policy/preflight.

## GIT PR

Side-effect kind для новых execution — provider-neutral `provider_pr`: один и тот же recovery contract применяется к GitHub/`gh` и Gitea/`tea`. Legacy `github_pr` остаётся валидным только для чтения и завершения checkpoint, созданного до переименования; kind внутри активного lifecycle не мигрируется.

До provider create фиксируются head repository (если известен), head branch, base branch и published head SHA.

После interruption executor сначала делает exact provider query:

- один matching open PR с теми же head/base/head SHA → reuse/recovery;
- ни одного → можно создать;
- больше одного или checkpoint больше не соответствует текущему revision → `SIDE_EFFECT_RECOVERY_AMBIGUOUS`.

Provider object id/URL сохраняются после наблюдения.

## HARNESS UPDATE APPLY

Updater **не переводится** на этот lightweight checkpoint engine.

`HARNESS UPDATE APPLY` уже имеет собственный transactional journal с snapshot/rollback/recovery, потому что операция затрагивает набор файлов, lock state и update report. Это более сильная transaction boundary. Общая семантика та же: после interruption сначала recovery/reconciliation, затем продолжение. Implementation остаётся updater-specific.

## File/report writers

Для будущих writers используется тот же contract: `kind=file_write`, deterministic target identity/path/hash в proof, atomic write или exact post-write readback. Duplicate/non-identical output должен завершаться BLOCKED. Сам contract не делает произвольные file writes автоматически.

## Reason codes

- `SIDE_EFFECT_CHECKPOINT_INVALID`;
- `SIDE_EFFECT_CHECKPOINT_WRITE_FAILED`;
- `SIDE_EFFECT_RECOVERY_PROBE_FAILED`;
- `SIDE_EFFECT_RECOVERY_AMBIGUOUS`.

Command-specific postcondition codes (`COMMIT_POSTCONDITION_FAILED`, `PUSH_POSTCONDITION_FAILED`, `PR_POSTCONDITION_FAILED`) сохраняются для доказанного execution failure после наблюдаемого side effect.

## Архитектурное решение

Отдельный project ADR не создаётся намеренно: `docs/adr/**` — project-owned artifact surface шаблона, а не maintainer-history Harness core.

Решение core зафиксировано здесь:

1. schema v2 execution state остаётся bounded;
2. side-effect checkpoint — optional contract active command;
3. CTS не меняется;
4. UPDATE journal не дублируется;
5. provider/repository facts имеют приоритет над runtime/model memory.
