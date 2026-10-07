# Semantic Blast Radius

Semantic Blast Radius — conditional read-only capability поверх deterministic impact analysis и Codebase Grounding.

```text
STEP risk flags + explicit dependencies
            ↓
 deterministic preflight
            ↓
 validated codebase grounding
            ↓
 semantic implicit-impact hypotheses
            ↓
 deterministic payload/proof validation
            ↓
       PLAN / REVIEW
```

## Что остаётся deterministic

`.harness/tools/impact_analysis.py` остаётся source of truth для explicit artifact/dependency impact. Semantic capability не дублирует его и не объявляет inferred consumer канонической dependency.

Preflight также фиксирует exact repository revision, STEP risk flags и current Verification state.

## Trigger

Capability required, если canonical STEP содержит хотя бы один material risk flag кроме `none`:

- `security-sensitive`;
- `data-migration`;
- `destructive`;
- `public-api`;
- `architecture`;
- `concurrency`;
- `external-integration`;
- `performance-critical`;
- `release-critical`.

`risk_flags: [none]` означает low-risk fast path: semantic blast-radius автоматически не запускается.

## Semantic output

Модель формулирует hypotheses только о неявных effects:

- implicit behavior/data/API contracts;
- indirect consumers;
- compatibility/migration;
- shared state/concurrency;
- runtime/operational assumptions;
- proof/test surface.

Deterministic facts возвращаются validator-ом отдельно и не копируются в semantic input как model claims.

Каждый hypothesis связан с concrete `affectedBehavior`, evidence paths и proof state.

## Proof rule

Required analysis выделяет 1–2 critical hypotheses.

На PLAN future proof может быть `planned`; такой result остаётся `INCONCLUSIVE`, пока obligation не доказан. Planner обязан включить proof surface в Verification/Implementation plan. Даже PLAN не может получить PASS по self-report: exact proof command должна иметь fresh generated PASS evidence для current subject revision.

На REVIEW `PASS` требует для каждой critical hypothesis:

- `proof.status=proven`;
- `proof.kind=verification-command`;
- command существует в current STEP Verification;
- exact proof command имеет fresh generated PASS evidence для current contract/subject revision.

Aggregate Verification может при этом быть `MANUAL_REQUIRED`, если в STEP есть unrelated manual checks: это не обесценивает уже полученное executable proof конкретной critical hypothesis. Manual checks по-прежнему обязательны через существующий completion/review flow и не считаются выполненными blast-radius validator-ом.

Если proof отсутствует, unavailable или stale, blast-radius не может вернуть PASS.

## Bounded context

Blast radius повторно использует тот же Context Contract и validated Codebase Grounding. Дополнительные expansions разрешены только explicit reason.

Общий budget grounding + blast expansions использует те же границы:

| Scope | Max expansion files | Max expansion chars |
|---|---:|---:|
| `simple` | 6 | 60 000 |
| `complex` | 16 | 160 000 |

То есть blast-radius не получает второй независимый budget поверх grounding.

## CLI

Preflight:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-024 --phase plan --json
python3 .harness/tools/semantic-blast-radius.py STEP-024 --phase review --json
```

Validation:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-024 \
  --phase review \
  --context-file .harness/local/context.json \
  --grounding-file .harness/local/grounding.json \
  --payload-file .harness/local/blast-radius.json \
  --json
```

Local JSON files are transient handoff only; they are forbidden tracked artifacts.

## Result boundary

Validated result separates:

- `deterministic` — risk flags, explicit affected STEP surface, revision, Verification facts;
- `hypotheses` — semantic possible risks;
- `provenObservations` — semantic conclusions tied to inspected evidence;
- `testSurfaces` — concrete safety proof obligations.

Semantic hypothesis is not a canonical dependency/ADR/REQ. Durable contract changes still route through ADR/REQ/OQ/STEP.
