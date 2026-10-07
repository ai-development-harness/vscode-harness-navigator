---
name: structural-enforcement
description: Convert repeated structured Harness corrections into the strongest feasible enforcement proposal, with recurrence proof, regression fixture requirements, and no silent architecture mutation.
---
# structural-enforcement

Это **внутренняя capability**, не пользовательская команда.

Используй её, когда structured Harness evidence показывает повторяющийся класс ошибки, либо когда человек **явно** попросил структурно закрепить даже один конкретный случай.

## Evidence boundary

Основной deterministic источник — Review Contract v3 evidence-gated findings:

```bash
python3 .harness/tools/structural-enforcement.py --step STEP-NNN --json
```

Tool агрегирует exact `category + fingerprint` и дедуплицирует повторные reports одной reviewed revision.

Дополнительные structured events можно передать через `--evidence-file`:

- `repair_stop`;
- `progress_stop`;
- `audit_finding`;
- `reconcile_finding`;
- `validator_failure`;
- `durable_decision`.

Chat, transcript и session memory не являются source kinds и не могут использоваться как primary evidence.

Legacy review prose не реконструируй в machine findings. Historical v1/v2 reports не используй для recurrence: они предшествуют Evidence Gate и учитываются только как skipped legacy metric.

## Recurrence rule

По умолчанию:

```text
1 factual occurrence → не recurring
2+ distinct factual occurrences → recurring
```

Два REVIEW report-а той же finding fingerprint на той же `reviewed_revision` считаются **одним** occurrence.

`--explicit-single` разрешён только если пользователь в текущем запросе явно требует structuralization одного случая. Агент не включает этот flag по собственной инициативе.

## Enforcement ladder

Выбирай **первый feasible уровень**:

1. `architecture-ownership` — убрать ошибочный путь ownership/API архитектурой;
2. `schema-type` — сделать invalid state невыразимым schema/type contract;
3. `validator-lint` — deterministic validator/lint с actionable error;
4. `regression-test` — behavioral regression guard;
5. `durable-instruction` — только irreducible judgement.

Для выбранного уровня proposal обязан объяснить, почему **каждый более сильный** уровень неприменим.

Нельзя выбирать instruction только потому, что она быстрее.

## Proposal contract

Semantic payload:

```json
{
  "schemaVersion": 1,
  "status": "PASS",
  "classKey": "review:implementation:sha256:...",
  "recurringErrorClass": "Direct writes bypass the canonical state owner.",
  "mechanism": {
    "kind": "validator-lint",
    "rationale": "The wrong write path is syntactically detectable.",
    "higherLevelsRejected": [
      {
        "kind": "architecture-ownership",
        "reason": "Ownership is already singular and correct."
      },
      {
        "kind": "schema-type",
        "reason": "The language boundary cannot encode this file-path rule."
      }
    ]
  },
  "candidateScope": ["src", "tests/regressions"],
  "proof": {
    "fixture": "tests/regressions/direct-write.txt",
    "command": ["python3", "tools/check-owner.py"],
    "oldMistakeExpectedFailure": "Old direct-write example must fail.",
    "correctedStateExpectedPass": "Owner-mediated example must pass."
  },
  "evidenceIds": ["sha256:...", "sha256:..."],
  "gaps": []
}
```

Проверка:

```bash
python3 .harness/tools/structural-enforcement.py \
  --step STEP-NNN \
  --payload-file .harness/local/structural-enforcement/proposal.json \
  --json
```

## Regression proof

Для любого deterministic mechanism (`architecture-ownership`, `schema-type`, `validator-lint`, `regression-test`) proposal обязан содержать negative regression fixture contract:

- candidate fixture path;
- exact command argv;
- ожидаемое падение на старой ошибке;
- ожидаемый PASS на исправленном состоянии.

После реализации повтори validation с `--implemented`. Тогда fixture обязан реально существовать как regular repository file:

```bash
python3 .harness/tools/structural-enforcement.py \
  --step STEP-NNN \
  --payload-file .harness/local/structural-enforcement/proposal.json \
  --implemented \
  --json
```

Сам tool command не исполняет: фактический regression command должен быть частью canonical STEP Verification/CI.

## Architecture safety

`architecture-ownership` требует explicit `decisionRoute`:

- `architecture-change`;
- `ADR`;
- `OQ/RESEARCH`.

Validated result всегда возвращает:

```text
automaticMutationAllowed = false
```

Capability не создаёт/не переписывает ADR и не меняет production code сама.

## Workflow routing

### STEP FIX

Перед очередным repair выполни deterministic scan текущего STEP. Если current finding class уже recurring:

- не делай ещё один локальный patch автоматически;
- сформируй strongest-feasible proposal;
- если выбранный mechanism выходит за Scope/Mutation policy текущего STEP — BLOCKED + corrective STEP/ADR/RESEARCH;
- если mechanism допустим в текущем STEP — implement it вместе с regression fixture и проверь `--implemented`.

### PROJECT RECONCILE

Project-wide scan:

```bash
python3 .harness/tools/structural-enforcement.py --json
```

Recurring classes должны попасть в reconcile classification как candidate systemic corrective work. Один occurrence без explicit human request не повышай до recurring pattern.

### AUDIT

Audit может передать уже structured audit finding через `--evidence-file`. Не конвертируй audit prose в class key reasoning-ом.

## Запреты

- не использовать transcript/chat как evidence;
- не считать duplicate report той же revision вторым occurrence;
- не выбирать weaker ladder level без причин по всем stronger levels;
- не создавать deterministic rule без regression fixture contract;
- не считать proposal доказательством того, что check реально выполнен;
- не менять architecture автоматически;
- не добавлять prose rule поверх уже достаточного deterministic enforcement.
