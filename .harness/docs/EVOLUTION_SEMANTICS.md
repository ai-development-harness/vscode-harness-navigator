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

## Enforcement актуальности завершённых зависимостей (#295)

`--preview` остаётся **только read-only**. Дополнительная защита на
execution boundary переиспользует уже существующие механизмы:

- `step_completion_proof()` проверяет, соответствует ли последний trusted
  REVIEW зафиксированному в нём `contract_basis` текущему semantic snapshot
  REQ/ADR/OQ/STEP/PRN. Новый REVIEW также сохраняет
  `dependency_completion_basis` — отпечатки *фактических upstream completion
  proofs на момент проверки*. Изменение upstream, а затем новый upstream
  REVIEW не делают старый downstream REVIEW действительным вновь.
  Исторические legacy reports не переписываются.
- Если completed STEP зависит от другого STEP, он проверяет актуальность
  его completion proof **транзитивно**. Циклы, отсутствующие зависимости и
  ошибочные документы не превращаются в PASS.
- Для зависимого STEP с современным `contract_basis` в REVIEW теперь обязателен
  `dependency_completion_basis`. Старый REVIEW с первым полем, но без второго,
  не может подтвердить current downstream completion: возвращается
  `completion-dependency-proof-missing`. Это консервативная перепроверка,
  а не изменение исторического отчёта; новый обычный REVIEW создаёт proof.
  Legacy отчёты без `contract_basis` остаются в прежнем migration режиме.
- `verification_context_basis()` содержит hash подтверждённых
  `step_completion_proof` прямых dependencies. Это отдельно от Ready plan:
  PLAN всё ещё разрешено готовить **до** завершения зависимостей.
- При невыполненных/устаревших prerequisites Verification возвращает
  `VERIFICATION_DEPENDENCY_UNPROVEN`, вместо того чтобы запускать новые
  проверки и создавать ложный PASS.
- Когда upstream proof изменится, старое Verification Evidence downstream
  получит `VERIFICATION_CONTEXT_STALE`, пока не будет выполнена новая
  Verification.

**Пример:**

```text
STEP-001 completed (для REQ-001 v1) → STEP-002 completed
                     |
                     └─ REQ-001 изменён до v2

STEP-001: completion-contract-stale
STEP-002: dependency-incomplete:STEP-001
Verification STEP-002: stale или BLOCKED
STEP-003 (несвязанный): остаётся действительным
```

| Ситуация | Что было | Что стало |
| --- | --- | --- |
| Изменение REQ после ранее выполненного REVIEW | Исторический PASS мог использоваться как текущий | Сохранённый `contract_basis` проверяется заново и помечается stale |
| У downstream STEP нет прямой ссылки на изменившийся REQ | Собственный план мог оставаться fresh | Completion chain и Verification пересматривают upstream proof |
| Изменена только административная metadata REQ/STEP | Возможна ненужная повторная работа | Semantic snapshot не включает нерелевантные поля |
| Исторический REVIEW без `contract_basis` | Legacy migration semantics | Сохраняются, без ложного заявления о современном proof |
| Неизвестный dependency/цикл | В сложных сценариях могла теряться причина | Причина сохраняется и не вызывает повторного запуска side effect |

Enforcement не удаляет прежние Evidence/Review, не снимает автоматически
`status: completed`, не запускает Git mutation и не зависит от Claude/Codex.
Исторические завершения остаются историей, но их stale proof не разрешает
новую downstream execution. Для legacy proof без semantic basis следует
использовать существующие миграционные механизмы и обычное REVIEW при
возникновении новых требований; он не получает поддельную историю.

## Semantic blast radius

Deterministic impact analysis отвечает только за **explicit** canonical links/fingerprints. Для STEP с material `risk_flags` planner/reviewer дополнительно запускает internal `semantic-blast-radius`: explicit impact остаётся immutable fact, а model judgement используется только для implicit API/data/behavior contracts, indirect consumers, compatibility/concurrency/runtime assumptions и необходимого proof surface.

Semantic hypothesis не добавляется автоматически в dependency graph. Если hypothesis выявляет реальный durable contract/dependency gap, его нужно оформить через canonical ADR/REQ/OQ/STEP, после чего deterministic impact analysis увидит новую explicit связь.

На REVIEW отсутствие fresh executable proof для critical hypothesis не превращается в PASS.

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

## Совместимость historical REVIEW с новыми dependency proofs

Некоторые проекты завершили зависимые STEP до появления поля
`dependency_completion_basis` в immutable REVIEW. Их исторические отчёты
не переписываются и не превращаются в новый `PASS` по догадке.

У structural validator есть строго ограниченное правило совместимости:
если причина сбоя **только** `completion-dependency-proof-missing` и каждый
затронутый trusted PASS REVIEW принадлежит прежнему формату
(нет `reviewed_subject_content_hash` и `dependency_completion_basis`),
`validate.py` выводит предупреждение вместо ошибки. Это позволяет обновить
существующий инициализированный проект без исправления истории задним числом.

Важно: это **не ослабляет runtime proof**. `step_completion_proof` и
`dependency_completion_failures` продолжат возвращать blocker для
использования такого STEP как подтверждённой актуальной зависимости.
Перед новым зависимым выполнением необходим новый canonical proof/review.

Любое фактическое изменение REQ/ADR/STEP/PRN, устаревший контракт, цикл,
ошибка или отсутствие trusted REVIEW остаются ошибкой validator. Новый REVIEW,
у которого есть `reviewed_subject_content_hash`, но отсутствует обязательная
`dependency_completion_basis`, также не получает historical-исключения.

Точно та же граница применяется к tracked `docs/requirements/STATUS.md`:
исторически завершённые REQ не превращаются в `planned` только из-за
отсутствия более позднего поля в неизменяемом REVIEW. Для таких проекций
восстанавливается прежний completed snapshot/hash, а `STEP NEXT`,
`IMPLEMENT` и транзитивные prerequisites по-прежнему вызывают строгий
`step_completion_proof()`. При реальном изменении upstream contract
проекция устаревает по обычным правилам.

Это различие необходимо при проверке обновления Harness:
**historical validity** не равна **current execution authorization**.
