# Structured Reflection

Structured Reflection — optional post-work learning pass over **durable Harness evidence**.

Цель не «запомнить чат», а найти урок, который стоит закрепить в структуре проекта/Core.

```text
structured evidence
      ↓
trigger worth the model cost?
      ↓
semantic lesson
      ↓
exactly one primary target
      ↓
immutable reflection report
      ↓
обычный Harness workflow при принятии proposal
```

## Evidence sources

Closed set:

```text
review_finding
repair_stop
progress_stop
completion_outcome
audit_finding
reconcile_finding
verification_failure
git_evidence
durable_decision
validator_failure
```

`transcript`, `chat`, `session memory` отсутствуют в contract.

Каждый event содержит stable `id`, `classKey`, `occurrenceId`, `fingerprint`, summary и path к существующему durable repository artifact. Local temporary files не принимаются как evidence.

## Recurrence

Recurrence считается по distinct `occurrenceId` внутри одного `classKey`:

```text
тот же finding + та же reviewed revision + два источника → 1 occurrence
тот же class + другая revision/STEP                 → 2 occurrences
```

По умолчанию rule/skill proposal требует 2+ occurrences. Явный текущий запрос человека может разрешить structuralization одного случая.

## Primary target

Каждый lesson выбирает максимум один target:

| Target | Scope | Пример |
|---|---|---|
| `core-tool-gate-validator` | core | нарушение можно детерминированно запретить |
| `core-reasoning-principle` | core | irreducible reasoning guidance |
| `core-skill` | core | повторяемый Harness semantic workflow |
| `project-principle` | project | cross-cutting project rule |
| `project-skill` | project | project-specific repeated workflow |
| `adr-req-oq-gap` | project | отсутствует owning decision/contract |
| `no-action` | none | one-off / уже покрыто существующим механизмом |

Нельзя одновременно предложить «добавить validator и PRN». Выбирается strongest owning target; secondary context можно описать в rationale.

## Duplicate detection

Report хранит stable Lesson fingerprint из class/scope/target/summary. Новый write сканирует предыдущие `REFLECTION-*.md` и блокирует тот же lesson, чтобы reflection не плодил одинаковые TODO.

## Trigger policy

Reflection не запускается автоматически после каждого STEP. Scan рекомендует pass, когда есть recurring class или high-cost signal (`repair_stop`, `progress_stop`, `verification_failure`). Пользователь также может запросить reflection явно.

## Reports

Durable reports:

```text
<protocol.auditDirectory>/reflections/REFLECTION-YYYYMMDDTHHMMSSZ.md
```

Report содержит evidence IDs/paths/fingerprints и semantic proposal. Он immutable и не меняет target artifacts.

## Relationship to Structural Enforcement

`structural-enforcement` отвечает на узкий вопрос: повторяется ли класс ошибки и какой strongest enforcement feasible.

`structured-reflection` шире: после значимой работы классифицирует lessons между Core/project contracts, skills, reasoning rules или `no-action`.

Если lesson — recurring correction, reflection должна переиспользовать existing structural-enforcement facts/proposal, а не изобретать параллельную recurrence semantics.

## Safety

- no transcript source;
- evidence pointer mandatory;
- no automatic mutation;
- one-off не становится rule без explicit human request;
- duplicate lesson blocked;
- project/Core scope explicit;
- accepted proposal реализуется отдельным нормальным STEP/ADR/REQ/PRN/skill change.
