# Optional High-Rigor modes: Arena и Interrogate

## Зачем

Один сильный agent обычно дешевле и быстрее нескольких. Поэтому high-rigor не
является default.

Он нужен там, где стоимость неправильного shape/вердикта существенно выше
дополнительного fan-out:

- крупный ADR;
- public API;
- migration / compatibility;
- security-sensitive architecture;
- distributed/concurrent state;
- high-risk refactor;
- спорный review finding.

## Policy

`.harness/manifest.yaml`:

```yaml
highRigor:
  arena: explicit
  interrogate: explicit
  seats: 3
  maxSeats: 5
  maxInputCharsPerSeat: 80000
  maxOutputCharsPerSeat: 24000
  maxTotalChars: 400000
```

Modes:

| Policy | Без запроса | Явный запрос | Risk condition |
|---|---|---|---|
| `disabled` | SKIP | SKIP | SKIP |
| `explicit` | SKIP | RUN | SKIP |
| `risk` | RUN только при risk | RUN | RUN |

Risk activation использует только machine-readable STEP `risk_flags`. Model
не может объявить обычную задачу high-risk по ощущению.

High-risk closed set:

- security-sensitive;
- data-migration;
- destructive;
- public-api;
- architecture;
- concurrency;
- external-integration;
- performance-critical;
- release-critical.

Arena применим к `plan|architecture`, Interrogate — к `review|audit`.

## Почему core не хранит список моделей

Model names и availability меняются быстрее protocol. Canonical Harness задаёт:

- number of seats;
- independence;
- exact inputs;
- rubric;
- result trace;
- degradation semantics;
- budgets.

Runtime adapter выбирает конкретные models/effort нативным способом.

Это сохраняет одинаковую semantic модель для Codex/Claude и не заставляет
Harness имитировать provider-specific model registries.

## Arena

```text
exact contract
    ↓
shared rubric
    ↓
candidate A ─┐
candidate B ─┼─ independent outputs
candidate C ─┘
    ↓
independent judge
    ↓
base selection
    ↓
coherent graft/synthesis
    ↓
normal Harness verification
```

PASS требует минимум 2 completed candidates и отдельного completed judge.
Configured candidate seat count всё равно должен быть представлен в trace:
failed/unsupported seat нельзя молча удалить.

## Interrogate

```text
intent + exact review surface
          ↓
       shared rubric
          ↓
reviewer A / B / C independently
          ↓
consensus + disagreement map
          ↓
lead judgment
          ↓
ordinary Review Contract verdict
```

Consensus finding требует минимум двух independent completed reviewers.

Lone finding не удаляется: lead может перенести его в `actOn|consider|noted|dismissed`.

## Traceability

Transient run files:

```text
.harness/local/high-rigor/<run-id>/
```

Validator читает exact UTF-8 files и recompute-ит:

- SHA-256;
- chars;
- bytes.

Для каждого participant сохраняются:

- seat id / role;
- runtime;
- independent session execution id;
- requested model;
- actual model;
- fallback reason;
- status;
- exact input/rubric/output hashes and sizes.

Так «все reviewers видели одно и то же» является проверяемым фактом, а не
заявлением модели.

## DEGRADED

High-rigor может завершиться `DEGRADED`, например:

- model fallback;
- failed seat;
- unsupported seat;
- меньше двух completed independent candidates/reviewers;
- Arena judge unavailable.

DEGRADED не означает обычный workflow failure. Он означает, что дополнительный
high-rigor quality bar не был полностью получен.

Caller обязан раскрыть degradation. Нельзя подписывать такой run как PASS.

## Budgets

Измеряются Unicode chars, а не provider-specific tokens:

- `maxInputCharsPerSeat`;
- `maxOutputCharsPerSeat`;
- `maxTotalChars`.

Это runtime-neutral и воспроизводимо.

Seats имеют отдельный hard limit; disagreement не даёт права автоматически
увеличивать fan-out.

## Safety boundary

High-rigor — semantic quality multiplier, а не authority.

Ни Arena, ни Interrogate не заменяют deterministic Harness gates. Final trace
всегда содержит:

```text
deterministicGatesReplaced = false
```

Arena не разрешает нескольким candidates писать в один shared target.
Interrogate reviewers read-only.

## Local vs canonical

Полные candidate/reviewer outputs остаются local diagnostic material.

Durable PLAN/ADR/REVIEW сохраняет один coherent итог. Если fan-out materially
изменил решение, human-readable rationale/evidence может указать run id,
PASS/DEGRADED и существенный disagreement.

Local outputs не становятся canonical project truth.
