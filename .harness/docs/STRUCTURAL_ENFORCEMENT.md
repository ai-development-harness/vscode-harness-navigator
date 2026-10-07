# Recurring Correction → Structural Enforcement

## Цель

Если один и тот же класс ошибки появляется снова, Harness должен перестать
лечить отдельные симптомы и попробовать сделать ошибочный путь невозможным.

Это feedback loop:

```text
structured correction evidence
          ↓
stable class aggregation
          ↓
recurring? (2+ occurrences)
     ├── no → ordinary local correction
     └── yes
          ↓
strongest feasible enforcement
architecture → schema/type → validator/lint → regression → instruction
          ↓
negative regression proof
```

Internal capability не является новой пользовательской командой.

## Источники evidence

Автоматически читаются только текущие Review Contract v3 evidence-gated machine findings. Historical v1/v2 review history не повышает frequency: эти отчёты появились до обязательного Evidence Gate и учитываются только как skipped legacy metric.

Дополнительный normalized envelope поддерживает:

- repair/progress stop telemetry;
- structured audit/reconcile finding;
- validator failure;
- explicit durable decision.

`repair_stop`, `progress_stop` и `durable_decision` являются corroborating
context и сами по себе не увеличивают frequency. Они не должны дважды считать
то же underlying defect.

Transcript/chat/session memory не поддерживаются.

## Stable class identity

Для Review Contract:

```text
classKey = review:<category>:<finding fingerprint>
```

Occurrence identity включает:

- STEP;
- `reviewed_revision`, если она доступна;
- finding fingerprint.

Поэтому:

```text
same fingerprint + same revision + 3 reports → 1 occurrence
same fingerprint + new revision            → 2 occurrences
```

Threshold v1: **2 distinct factual occurrences**.

## Один случай

Один occurrence не называется recurring pattern автоматически.

Исключение — явный запрос человека структурно закрепить конкретный единичный
случай. Только тогда caller передаёт `--explicit-single`.

Flag не выводится из model judgement.

## Enforcement ladder

| Уровень | Mechanism | Когда выбирать |
|---|---|---|
| 1 | `architecture-ownership` | ошибочный путь можно убрать ownership/API boundary |
| 2 | `schema-type` | invalid state можно сделать невыразимым |
| 3 | `validator-lint` | нарушение имеет надёжный deterministic predicate |
| 4 | `regression-test` | правило лучше доказывается поведением |
| 5 | `durable-instruction` | остаётся irreducible judgement |

Proposal для уровня N обязан содержать причины отказа от всех уровней 1..N-1.

## Regression fixture contract

Любой deterministic enforcement (уровни 1–4) обязан объявить:

- fixture;
- exact command argv;
- ожидаемое failure старой ошибки;
- ожидаемый PASS corrected state.

Proposal validation проверяет contract. `--implemented` дополнительно требует,
чтобы fixture уже существовал как regular repository file.

Tool намеренно **не запускает** произвольный proof command. Execution остаётся
за canonical Verification/CI, где уже существуют timeout, mutation и evidence
guards.

## Architecture boundary

Architecture-level proposal требует route
`architecture-change | ADR | OQ/RESEARCH`.

Capability возвращает `automaticMutationAllowed=false` для любого mechanism.
Она не имеет authority менять ADR/REQ/code.

## Structured supplemental evidence

Envelope:

```json
{
  "schemaVersion": 1,
  "events": [
    {
      "sourceKind": "validator_failure",
      "classKey": "validation:owner-boundary",
      "occurrenceId": "ci:2480",
      "category": "validation",
      "evidenceRef": "ci/run/2480",
      "observedAt": "2026-10-06T10:00:00Z",
      "signal": "owner boundary validation failed"
    }
  ]
}
```

Allowed source kinds closed-set; transcript/chat отсутствуют.

## CLI

Scan STEP:

```bash
python3 .harness/tools/structural-enforcement.py --step STEP-024 --json
```

Project-wide scan:

```bash
python3 .harness/tools/structural-enforcement.py --json
```

Scan with extra structured evidence:

```bash
python3 .harness/tools/structural-enforcement.py \
  --evidence-file .harness/local/structural-enforcement/evidence.json \
  --json
```

Validate proposal:

```bash
python3 .harness/tools/structural-enforcement.py \
  --step STEP-024 \
  --payload-file .harness/local/structural-enforcement/proposal.json \
  --json
```

Post-implementation fixture check:

```bash
python3 .harness/tools/structural-enforcement.py \
  --step STEP-024 \
  --payload-file .harness/local/structural-enforcement/proposal.json \
  --implemented \
  --json
```

## Fail-closed rules

- malformed Review Contract v3 machine findings → BLOCKED;
- class mixes categories → BLOCKED;
- single occurrence + PASS proposal without explicit human override → BLOCKED;
- proposal references evidence from another class → BLOCKED;
- weaker mechanism without reasons for every stronger level → BLOCKED;
- deterministic mechanism without regression proof contract → BLOCKED;
- `--implemented` without existing regular fixture → BLOCKED;
- architecture mechanism without decision route → BLOCKED;
- unknown evidence source kind → BLOCKED.

## Relationship to CRP-001

`CRP-001 Encode lessons in structure` is semantic trigger guidance.
`structural-enforcement` is the machine-checkable feedback-loop contract.

CRP cannot declare recurrence from memory; recurrence comes from this tool.
