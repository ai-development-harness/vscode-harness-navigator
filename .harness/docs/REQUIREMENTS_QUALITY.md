# Requirements Quality Gate

Requirements Quality Gate отвечает на вопрос **«достаточно ли определён contract для планирования и реализации?»**. Он не заменяет planning consistency и implementation review.

## Место в pipeline

```text
structural validation
→ requirements-quality / clarification
→ planning consistency
→ architecture completeness
→ implementation
→ review
```

Gate обязателен для `PROJECT INIT`, `STEP ADD` и `STEP PLAN`.

## Разделение ответственности

Semantic agent ищет ambiguity и оценивает materiality. Детерминированный `.harness/tools/requirements-quality.py` валидирует machine-readable payload и не разрешает runtime adapters по-разному интерпретировать status/severity/owner.

Проверяются только применимые dimensions:

- functional scope, actors, states;
- data identity/lifecycle/ownership/concurrency;
- UX states и destructive flows;
- performance/reliability/recovery/observability/security/privacy;
- integration failure/retry/timeout/versioning;
- measurable acceptance, placeholders, hidden assumptions и terminology conflicts.

## Question policy

Вопрос задаётся только когда ответ materially меняет architecture, scope, tests или acceptance. До вопроса агент обязан искать ответ в linked REQ/ADR/OQ/STEP, architecture и relevant codebase.

За один pass нужно задавать минимальный набор highest-impact вопросов. Non-blocking stylistic finding не останавливает flow.

## Machine-readable result

```json
{
  "schemaVersion": 1,
  "status": "NEEDS_INPUT",
  "quality": {
    "completeness": "pass",
    "clarity": "pass",
    "measurability": "fail",
    "scenarioCoverage": "pass"
  },
  "findings": [
    {
      "code": "AMBIGUOUS_RECOVERY_POLICY",
      "severity": "blocking",
      "owner": "REQ-014",
      "question": "Какой recovery behavior обязателен после timeout?",
      "rationale": "Ответ меняет acceptance и retry semantics.",
      "sourceRefs": ["REQ-014#Reliability"]
    }
  ]
}
```

Status:

- `PASS` — blocking ambiguity нет; warnings допустимы.
- `NEEDS_INPUT` — требуется targeted user input.
- `BLOCKED` — продолжение невозможно до canonical prerequisite/owner resolution.

Owner всегда `PROJECT` или canonical `REQ-NNN` / `ADR-NNN` / `OQ-NNN` / `STEP-NNN`.

Проверка transport payload:

```bash
python3 .harness/tools/requirements-quality.py --payload-file result.json
```

## Persistence

Ответ пользователя нельзя оставлять только в chat/runtime state:

| Класс решения | Canonical owner |
|---|---|
| product behavior | REQ |
| architecture decision | ADR |
| unresolved decision | OQ |
| task-local scope / acceptance | STEP |

После записи ответа gate запускается повторно. Агент сначала читает canonical owner, поэтому уже зафиксированный ответ не должен запрашиваться снова.

## Отличие от соседних gates

- **Requirements Quality**: достаточно ли определено?
- **Planning Consistency**: согласованы ли уже определённые contracts?
- **Architecture Completeness**: учтены ли применимые cross-cutting impacts?
- **Implementation Review**: соответствует ли фактическая реализация contract?
