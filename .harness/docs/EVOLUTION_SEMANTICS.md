# Requirements / Architecture Evolution Semantics

Harness использует flow-forward / flow-back поверх существующих REQ/ADR/OQ/STEP и Project Principles. Отдельного `spec.md` или второго source of truth нет.

## Что менять первым

| Обнаруженное изменение | Canonical owner | Первый шаг |
|---|---|---|
| Изменился intended product behavior | REQ | изменить REQ, затем impact analysis и re-plan affected STEP |
| Изменился долговечный architecture choice | ADR | создать superseding ADR; старый Accepted ADR не переписывать как будто решения не существовало |
| Решение ещё неизвестно | OQ | создать/обновить OQ и BLOCK affected flow |
| Изменился только task-local Scope/Acceptance | STEP | изменить STEP, затем новый `STEP PLAN` |
| Implementation обнаружил невозможность contract | REQ/ADR/OQ/STEP по природе gap | IMPLEMENT → BLOCKED; owning contract не переписывается из implementer |
| Implementation fact не меняет contract | code / Evidence | зафиксировать в code/evidence |
| Project-wide engineering invariant | Project Principle | PRN workflow |
| Опечатка/formatting/non-semantic correction | PROJECT QUICK FIX | только если behavior/architecture/contracts действительно не меняются |

## Единственный freshness mechanism

Authoritative Ready fingerprint остаётся `planning_context_basis` из schema-v4 planning snapshot.

Ready stamp дополнительно сохраняет диагностическую проекцию:

```yaml
plan:
  context_basis: sha256:...
  context_components:
    - REQ@REQ-007=sha256:...
    - ADR@ADR-003=sha256:...
    - STEP@STEP-018=sha256:...
```

`planning_context_components()` строится из **того же snapshot**, поэтому это не независимый staleness engine.

Existing Ready plans, созданные до появления `context_components`, остаются совместимыми: basis mismatch по-прежнему блокирует IMPLEMENT, а причина выводится как generic `PLANNING_CONTEXT changed` до следующего re-plan.

## Deterministic impact analysis

```bash
python3 .harness/tools/impact-analysis.py --step STEP-018 --json
python3 .harness/tools/impact-analysis.py --changed REQ-007 --json
```

Пример stale result:

```json
{
  "schemaVersion": 1,
  "status": "PASS",
  "stepId": "STEP-018",
  "plan": {
    "status": "stale",
    "causes": [
      {"component": "REQ@REQ-007", "change": "changed"}
    ],
    "action": "STEP PLAN STEP-018"
  }
}
```

Impact tool ничего не мутирует.

## Flow forward

```text
REQ / STEP / ADR / OQ / PRN changes
→ current planning basis differs from Ready basis
→ affected plan becomes stale
→ STEP RUN / IMPLEMENT prerequisite blocks stale plan
→ STEP PLAN
→ independent planning review
→ implementation may resume
```

Unrelated STEP сохраняет собственный basis и не блокируется только потому, что изменился соседний artifact.

## Architecture replacement

Accepted ADR не редактируется задним числом так, будто старого решения не было. Новое durable решение создаётся как superseding ADR, а historical ADR получает canonical superseded linkage.

```text
ADR-003 accepted
→ ADR-010 supersedes ADR-003
→ ADR-003 status/superseded_by changes
→ linked planning context becomes stale
→ impact analysis names architecture cause
→ re-plan affected STEP
```

Если active STEP всё ещё ссылается на superseded ADR, RECONCILE классифицирует это как architecture-owner gap.

## Flow back from implementation

Если implementer обнаружил, что approved contract неверен, неполон или требует нового product/architecture decision:

```text
IMPLEMENT
→ contract discovery
→ BLOCKED
→ classify owner
→ reviewable REQ / ADR / OQ / STEP change
→ impact analysis
→ re-plan
```

Запрещён anti-pattern:

```text
silent behavior change in code
→ docs rewritten afterward to justify code
```

Code не становится source of truth автоматически.

## PROJECT STATUS

`PROJECT STATUS` публикует отдельный `stalePlans` surface. Для каждого stale Ready STEP доступны:

- `planFreshness: stale`;
- `planStaleCauses[]`;
- `planRemediation: STEP PLAN STEP-NNN`.

Пример:

```text
STEP-018
Plan: STALE
Cause: REQ-007 changed
Action: STEP PLAN STEP-018
```

Project State API экспортирует те же facts для UI/Navigator.

## PROJECT RECONCILE

RECONCILE классифицирует drift по canonical owner:

- upstream contract changed → downstream plan stale;
- code diverged from active REQ → REQ остаётся authority до explicit decision;
- superseded ADR всё ещё governs active STEP → architecture-owner gap;
- STEP contract изменён после PLAN → task-owner stale plan;
- implementation discovery не promoted в canonical artifact → BLOCKED knowledge gap;
- deterministic projection drift → projection owner, без product-intent reasoning.

RECONCILE не выбирает product intent автоматически.

## PROJECT QUICK FIX

PROJECT QUICK FIX разрешён только для non-semantic correction. Изменение REQ behavior intent, ADR decision/rationale, STEP Scope/Acceptance, OQ resolution или Project Principle не является QUICK FIX независимо от размера diff.

## История

Flow-forward не переписывает прошлое:

- completed STEP не меняется автоматически из-за нового requirement;
- immutable planning-review / implementation-review / audit reports не редактируются;
- superseded ADR сохраняется как historical decision;
- новый current contract создаёт новую planning/evidence/review chain.

## Regression contract

Synthetic regression должен доказывать минимум:

1. linked REQ change → affected Ready STEP stale с exact component cause;
2. `STEP RUN` не входит в IMPLEMENT до re-plan;
3. unrelated Ready STEP остаётся executable;
4. ADR replacement stale-ит linked plan и propagates replacement ID;
5. task-local Scope/Acceptance edit stale-ит собственный STEP component;
6. implementation discovery policy routes to BLOCKED;
7. semantic contract edit не проходит QUICK FIX policy;
8. impact analysis не мутирует immutable historical review.
