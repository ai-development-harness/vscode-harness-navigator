# Project Principles

Project Principle (`PRN-NNN`) — project-owned долгоживущий инженерный инвариант, который применяется ко множеству будущих решений и может блокировать PLAN/REVIEW.

## PRN, ADR и REQ

- **REQ** — что должна делать система или какой observable product outcome обязателен.
- **ADR** — какое конкретное архитектурное решение принято и почему.
- **PRN** — какое project-wide инженерное правило обязаны соблюдать многие будущие решения.

### Это Project Principle

```text
PRN-004
Все изменения публичного API должны сохранять backward compatibility
в пределах поддерживаемого migration window.
```

Правило действует на множество будущих решений и участвует в PLAN/REVIEW.

### Это ADR, а не Principle

```text
ADR-012
Для transactional persistence использовать PostgreSQL.
```

Это конкретный architecture choice с rationale/consequences.

### Это REQ, а не Principle

```text
REQ-031
Пользователь может экспортировать свои данные в JSON.
```

Это product behavior и Acceptance.

### Это обычная инструкция, а не Principle

```text
Python-код форматируется Black.
```

Coding-style preference не превращается в PRN без material project-wide engineering invariant.

## Contract

Principles хранятся в configured `sources.principles` (по умолчанию `docs/principles`). Это project-owned surface; `AGENTS.md` не является вторым storage rules.

```yaml
schema: 1
id: PRN-004
status: active
severity: blocking
scope: project
superseded_by: null
requirements: []
adrs: []
```

Обязательные sections: `Rule`, `Rationale`, `Applies to`, `Exceptions / approved deviation`.
Statuses: `active | superseded | deprecated`. Severity: `blocking | advisory`.

Deterministic validation проверяет stable/unique ID, schema/lifecycle, существование referenced REQ/ADR, supersession target и обязательные sections.

## Enforcement

- `PROJECT INIT` создаёт PRN только для действительно global engineering constraints.
- `STEP PLAN` определяет applicability semantic-оценкой; applicable blocking PRN требует compliance или explicit approved deviation.
- `STEP REVIEW` повторно читает canonical `sources.principles`, а не полагается на память prompt/session.
- `PROJECT RECONCILE` учитывает violations и obsolete references.
- `RELEASE CHECK` блокирует unresolved applicable violation blocking principle.
- Advisory PRN сам по себе не blocker.

Applicability/violation — semantic judgement. Schema, IDs, refs, lifecycle и freshness — deterministic.

## Planning freshness

Все active blocking principles входят в `planning_context_basis`. Для `scope: project` используется conservative freshness: изменение blocking PRN stale-ит Ready plans и требует нового `STEP PLAN`.

## Governance

Blocking principle нельзя менять побочным эффектом обычного FIX. `superseded` обязан указывать `superseded_by`; `deprecated` больше не применяется. Approved deviation должна быть explicit и traceable.

## Проверяемый lifecycle

Synthetic regression фиксирует:

```text
PRN active + STEP
→ incompatible PLAN = BLOCKED
→ corrected PLAN = PASS
→ REVIEW читает тот же canonical PRN
→ compatible implementation = PASS
→ PRN changes
→ planning_context_basis changes
```

Regression доказывает wiring/repository semantics; semantic judgement остаётся обязанностью модели.
