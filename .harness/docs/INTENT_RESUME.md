# Intent-aware Resume

Intent-aware resume дополняет механический execution cursor проверкой того, что
semantic contract, в рамках которого была начата STEP-команда, **не изменился**
после interruption.

Главное различие:

```text
Execution State
→ где остановилось выполнение

Intent Basis
→ тот же ли semantic STEP/REQ/ADR/plan contract разрешает продолжение
```

Механизм не создаёт отдельный belief store, не копирует REQ/ADR/STEP и не
использует chat transcript как source of truth.

## References

Архитектурная мотивация:

- Durable Execution Is Not Durable Reasoning:
  https://behzat.ai/blog/durable-execution-is-not-durable-reasoning-checkpointing-agent-state-without-losing-intent
- Progression-of-States:
  https://arxiv.org/abs/2610.01415
- Inference Institute discussion:
  https://inference.institute/research/give-long-running-agents-a-working-account-of-the-task/

Эти материалы являются design references, а не runtime dependencies Harness.

## Scope v1

Intent Basis обязателен для semantic STEP-команд:

```text
STEP PLAN STEP-NNN
STEP IMPLEMENT STEP-NNN
STEP REVIEW STEP-NNN
STEP FIX STEP-NNN
```

Это команды, где session/runtime interruption может отделить начало semantic
работы от её продолжения.

Другие namespaces не получают искусственный intent snapshot без canonical
task-contract source.

## Storage

Snapshot хранится внутри active execution:

```text
.harness/local/execution/execution-status.json
  → executions[]
    → current.context.intentBasis
```

Он local-only, bounded и не является project evidence.

Schema v1:

```json
{
  "schemaVersion": 1,
  "stepId": "STEP-042",
  "command": "STEP IMPLEMENT STEP-042",
  "operation": "IMPLEMENT",
  "contextBasis": "sha256:...",
  "contextComponents": [
    "STEP@STEP-042=sha256:...",
    "REQ@REQ-007=sha256:...",
    "ADR@ADR-003=sha256:..."
  ],
  "planContentRequired": true,
  "planContentHash": "sha256:...",
  "planRevision": 4,
  "capturedAt": "2026-10-05T10:00:00+00:00"
}
```

Serialized snapshot имеет hard limit **16 KiB**.

## Почему нет отдельного obligations hash

Harness уже имеет два authoritative fingerprints.

### `planning_context_basis()`

Schema-v4 basis включает:

- semantic STEP contract;
- linked REQ;
- linked ADR;
- dependency STEP contracts;
- explicit architecture refs;
- relevant OQ;
- active blocking Project Principles.

То есть изменение goal/scope/Acceptance/REQ/architecture/principle уже меняет
этот basis.

### `plan_content_hash()`

Для Ready plan hash включает:

- Implementation plan;
- canonical `plan.execution_groups`, если они есть.

Поэтому изменение execution-group DAG, mutation surface или verification
responsibilities автоматически stale-ит IMPLEMENT/REVIEW/FIX resume.

Отдельный `obligationsHash` дублировал бы те же semantic inputs и создал бы
второй staleness engine.

## PLAN отличается от IMPLEMENT/REVIEW/FIX

`STEP PLAN` **создаёт/изменяет Implementation plan как output**. Поэтому его
Intent Basis фиксирует planning context, но не связывает resume с
`planContentHash`.

Иначе нормальный сценарий:

```text
PLAN started
→ model wrote draft Implementation plan
→ process crash
→ resume
```

ошибочно считался бы stale из-за собственного output команды.

Для `IMPLEMENT/REVIEW/FIX` Ready plan является входным contract, поэтому
`planContentHash` обязателен.

## Resume algorithm

```text
load active execution
  ↓
read stored Intent Basis
  ↓
recompute current canonical fingerprints
  ↓
compare
  ├─ equal → RESUME
  └─ changed → BLOCKED + reasonCode + remediation
```

Snapshot при resume **не пересчитывается и не перезаписывается**. Иначе stale
intent невозможно было бы обнаружить.

Unrelated code/files, terminal review reports, Evidence и
`.harness/local/**` не входят в planning basis и сами по себе не блокируют
resume.

## Blocker taxonomy

### `INTENT_BASIS_STALE`

Изменился semantic upstream input, например REQ, OQ или blocking Project
Principle.

### `TASK_CONTRACT_CHANGED`

Изменился semantic contract текущего STEP либо dependency STEP.

### `ARCHITECTURE_BASIS_CHANGED`

Изменился linked ADR или explicit architecture reference.

### `PLAN_BASIS_STALE`

Для IMPLEMENT/REVIEW/FIX изменился Implementation plan либо execution-group
graph.

### `INTENT_BASIS_MISSING`

Active execution создана старой версией Harness и не содержит snapshot.
Автоматически «снять basis сейчас» нельзя: это потеряло бы доказательство того,
какой contract был в момент начала работы.

### `INTENT_BASIS_SCHEMA_UNSUPPORTED`

Local state содержит snapshot будущей/неизвестной версии. Envelope остаётся
читаемым, чтобы Harness мог вернуть точный blocker, но semantic resume
fail-closed запрещён.

### `INTENT_BASIS_INVALID` / `INTENT_BASIS_UNAVAILABLE`

Snapshot повреждён либо current canonical basis невозможно безопасно вычислить.

Если fresh semantic start выполняется в legacy/diagnostic fixture с неполным
knowledge graph и exact basis нельзя вычислить, Harness не ломает сам первый
diagnostic invocation: он сохраняет bounded `intentBasisError`. Но после
interruption такой execution **не может быть resumed** — resolver возвращает
`INTENT_BASIS_UNAVAILABLE`, потому что снять новый basis задним числом означало
бы подменить исходный intent текущим состоянием.

## Remediation

Для stale STEP intent canonical remediation:

```text
STEP PLAN STEP-NNN
```

Это не означает, что каждый drift требует нового product design. Команда
повторно строит planning contract на текущем authoritative state; если проблема
на уровне REQ/ADR/OQ, planning/evolution workflow маршрутизирует её к owning
artifact согласно [EVOLUTION_SEMANTICS.md](EVOLUTION_SEMANTICS.md).

## HARNESS STATUS / HARNESS RESUME

Read-only `HARNESS STATUS` может показать stale execution без изменения state.

`HARNESS RESUME` выполняет authoritative comparison. Если intent stale, root
execution переводится в `blocked`, а result сохраняет exact reason/remediation,
например:

```json
{
  "status": "BLOCKED",
  "reasonCode": "ARCHITECTURE_BASIS_CHANGED",
  "rootCommand": "STEP REVIEW STEP-042",
  "remediation": "STEP PLAN STEP-042"
}
```

Повтор exact interrupted command проходит тот же guard и не обходит его новым
runtime/session.

## Interaction with authority contract

[STATE_AUTHORITY.md](STATE_AUTHORITY.md) определяет, что model/runtime только
предлагает semantic result, а Harness владеет execution/transition commit.

Intent-aware resume применяет тот же принцип ко времени:

```text
runtime says "continue"
  ≠
proof that the old intent is still current
```

Только deterministic comparison canonical fingerprints разрешает semantic
handoff после interruption.

## Interaction with side-effect recovery

Intent Basis не заменяет
[SIDE_EFFECT_RECOVERY.md](SIDE_EFFECT_RECOVERY.md).

Разные вопросы:

- Intent Basis: **разрешено ли продолжать ту же semantic задачу?**
- side-effect proof: **какое внешнее действие уже фактически произошло?**

Оба gate должны пройти независимо.

## Compatibility

Execution Status остаётся schema v2. Intent Basis имеет собственную versioned
sub-schema.

Legacy v2 active execution без Intent Basis остаётся читаемой, но intent-aware
STEP resume блокируется как `INTENT_BASIS_MISSING`: безопасной mechanical
migration без исходного snapshot не существует.

Unknown future Intent Basis schema также остаётся читаемой, но не resumable.

## Regression coverage

`.harness/tools/intent-resume-self-test.py` проверяет:

- unchanged resume;
- unrelated repository change;
- linked REQ change;
- ADR/architecture change;
- STEP contract change;
- Ready plan change;
- PLAN output false-positive guard;
- Project Principle change;
- unsupported Intent Basis schema;
- exact `HARNESS RESUME` blocker/remediation;
- explicit repeat той же interrupted command.

Implementation issue:
https://github.com/ai-development-harness/ai-development-harness-template/issues/203
