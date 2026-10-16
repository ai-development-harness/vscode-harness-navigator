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

## Консервативная предварительная оценка последствий (#287)

Существующая команда `impact-analysis.py --changed` по-прежнему показывает
прямые затронутые STEP. Для **прогноза транзитивного влияния** добавлен
неизменяющий проект режим:

```bash
python3 .harness/tools/impact-analysis.py --changed REQ-001 --preview --json
python3 .harness/tools/impact-analysis.py --changed ADR-002 --preview --json
```

В `steps[]` перечислены все известные STEP, включая незатронутые; каждый
получает `decision`, `dependencyPath`, причины, текущее состояние плана
и решения по review/verification/completion evidence. `affected[]` содержит
только STEP, связанные с указанными изменениями. Старые проблемы
других, несвязанных STEP не скрываются, но вынесены в
`preExistingConcerns[]`, чтобы не раздувать текущую область работ.
Такие независимые предупреждения больше не устанавливают общий
`status=BLOCKED`: этот статус возвращается только для неопределённости
в затронутой цепочке либо при недоступном источнике изменения.
Результат основан на canonical
связях REQ/ADR/OQ/PRN/STEP из planning snapshot, `depends_on` и
существующей `plan_staleness()`, **не на истории переписки с моделью**.

| Решение | Что означает | Дальнейшее действие |
| --- | --- | --- |
| `preserved` | Указанное изменение не затрагивает STEP через известные зависимости | Ничего сбрасывать не нужно; обычные freshness gates продолжают действовать |
| `revalidate` | У upstream STEP есть изменения, но собственный plan basis ещё не доказан устаревшим | Перепроверить зависимости и текущие review/verification evidence |
| `invalidated` | План STEP уже имеет несовпадение canonical planning basis | Отложить пересоздание плана до выбора STEP командой `STEP NEXT`; начать `STEP RUN`, который выполнит новый PLAN + REVIEW перед IMPLEMENT |
| `ambiguous` | Цикл, отсутствующий dependency или ошибка чтения/контракта не дают доказать безопасность | Сначала исправить/разобрать граф зависимостей; автоматически не продолжать |

Например:

```text
REQ-001 изменился
  └── STEP-001: invalidated  (прямой REQ)
         └── STEP-006: revalidate  (зависимость STEP-001)
                └── STEP-007: revalidate  (зависимость STEP-006)

STEP-002: preserved (нет связи)
```

**Важные ограничения.** Это dry-run прогноз, а не разрешение повторно
использовать старый PASS/DONE. Исторические reports, STEP statuses и
`execution-status.json` не переписываются. Даже `preserved` не обходит
действующую проверку current revision, Review Contract, Verification и
Completion Gate. Автоматический selective replay и повторное исполнение
Git push/PR/других side effects в эту задачу **не входят**.

Прогноз консервативный: явная транзитивная зависимость может требовать
перепроверки даже без фактического изменения поведения (ложноположительный
результат). Неучтённые неявные связи между модулями не выявляются одним
`depends_on`; для них уже предусмотрен `semantic-blast-radius` и
формализация missing links в canonical REQ/ADR/STEP. Никаких новых
пользовательских обязательств при переключении Claude Code ↔ Codex нет.

## Проверка зависимостей новой работы (#295, #355)

`--preview` остаётся read-only. На execution boundary используются существующие
Ready plan, Verification и completion proof:

- Completed prerequisite подтверждается собственной принятой историей. Текущие
  REQ/ADR/OQ/STEP/PRN не пересматривают его прежний PASS.
- `dependency_completion_basis` нового REVIEW фиксирует фактические proofs,
  доступные при этой новой проверке. Metadata не дописывается в старые отчёты.
- `verification_context_basis()` новой работы содержит proofs её прямых
  prerequisites отдельно от Ready plan. PLAN разрешено готовить до их завершения,
  а IMPLEMENT и Verification требуют сохранного принятого результата.
- Missing/corrupt PASS, отсутствие Evidence, Verification FAIL или незавершённый
  прямой prerequisite дают `VERIFICATION_DEPENDENCY_UNPROVEN` до новых проверок.
- Смена собственного contract/source или прямого proof во время активной работы
  требует актуальных PLAN/Verification/REVIEW этой новой работы. Прежние completed
  STEP и их исторические Evidence при этом не переоткрываются.

Пример: изменение REQ-001 после completed STEP-001/002 сохраняет их принятие.
Новый STEP-003 планируется по сегодняшним требованиям и использует сохранный
результат своего прямого completed prerequisite, без повторной приёмки предков.

## Semantic blast radius

Deterministic impact analysis отвечает только за **explicit** canonical links/fingerprints. Для STEP с material `risk_flags` planner/reviewer дополнительно запускает internal `semantic-blast-radius`: explicit impact остаётся immutable fact, а model judgement используется только для implicit API/data/behavior contracts, indirect consumers, compatibility/concurrency/runtime assumptions и необходимого proof surface.

Semantic hypothesis не добавляется автоматически в dependency graph. Если hypothesis выявляет реальный durable contract/dependency gap, его нужно оформить через canonical ADR/REQ/OQ/STEP, после чего deterministic impact analysis увидит новую explicit связь.

На REVIEW отсутствие fresh executable proof для critical hypothesis не превращается в PASS.

## Flow forward

```text
REQ / STEP / ADR / OQ / PRN changes
→ current planning basis differs from Ready basis
→ affected active plan becomes stale
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
→ re-plan affected active STEP
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
- `planRemediation: null` (нет массовой команды по списку);
- `deferredPlanRemediation: STEP PLAN STEP-NNN` (diagnostic, не рекомендация выполнить сейчас);
- `planRefreshPolicy: when-selected-by-STEP-NEXT`.

Пример:

```text
STEP-018
Plan: STALE
Cause: REQ-007 changed
Action now: defer
When selected: STEP NEXT → STEP RUN STEP-018 → new PLAN + independent REVIEW
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

## Завершённый STEP — исторический факт

`step_completion_proof()` и compatibility wrapper
`historical_completion_projection_proof()` проверяют сохранность принятого
результата: собственные Evidence, generated Verification и trusted immutable
PASS REVIEW, либо предусмотренный type-specific proof. Старые reports без
поздней metadata сохраняются без изменений. Superseded ADR остаётся принятым
историческим решением.

Завершённый STEP не сравнивается с сегодняшним REQ/ADR/PRN/architecture context,
не пересчитывает dependency basis старого REVIEW и не обходит нынешний
`depends_on`. Изменение этих входов после приёмки не отменяет прошлое завершение
и не требует повторного PLAN/IMPLEMENT/Verification/REVIEW. Новые proof artifacts
и дополнительные команды для этого не нужны. Read-only диагностика плана
возвращает `status: historical`, `action: null`; сегодняшние OQ, статусы ADR
и переименование architecture anchor не блокируют исторический Ready plan.

Новая работа проверяет собственные текущие требования, архитектуру, Ready plan,
Verification и независимый REVIEW. Её прямые completed prerequisites должны иметь
сохранный completion proof; за этим историческим узлом обход останавливается.
Missing/повреждённый REVIEW, отсутствие Evidence или generated Verification FAIL
у прямого prerequisite остаются BLOCKED. Незавершённые зависимости, отсутствующие
STEP и циклы активного графа не становятся допустимыми. Общий schema validator
продолжает проверять структурную целостность ссылок и графа.

Реальный defect старой реализации получает отдельную corrective задачу.
Несовпадение historical fingerprint само по себе таким defect не является.
