---
name: add-plan-step
description: Convert a short user request into a versioned, traceable, dependency-aware STEP and regenerate deterministic projections.
---
# add-plan-step

Используй для `STEP ADD: ...`.

- Сначала semantic duplicate/overlap search по canonical STEP/REQ.
- ID = следующий после максимального когда-либо использованного; формат `STEP-001+`, верхнего предела нет, дырки не переиспользуются.
- Создай STEP schema v1 в configured `protocol.taskDirectory` по **проектному `TEMPLATE.md`** в этом каталоге; именно template + `planning_contract` являются структурным контрактом, не копируй структуру STEP из памяти.
- Machine frontmatter:
  - `status: planned`;
  - protocol-English `type` / `priority`;
  - `phase`;
  - strict lists `depends_on`, `requirements`, `adrs`, `architecture_refs`, `risk_flags`;
  - optional `adr_outputs` — точные ADR IDs результатов только для `type: adr`, объявленные до создания ADR; внешние ADR остаются в `adrs` входами (#360);
  - optional `architecture_outputs` — точное подмножество `architecture_refs`, которое STEP должен изменить как результат; объяви до PLAN, сохрани остальные refs входами (#360);
  - `plan.status: not_planned`.
- Новый REQ создавай только для нового product contract в configured `sources.requirements`; обновляй двустороннюю REQ↔STEP traceability.
- Durable decision → ADR/RESEARCH prerequisite. Обновляй ADR↔STEP traceability.
- Существенная неопределённость → отдельный canonical OQ schema v1 в configured `sources.openQuestions`; `affects` обязан ссылаться на существующие IDs либо `PROJECT`.
- Заполни Goal, Context, Scope, Mutation policy (Allowed/Conditional/Forbidden), Out of scope, Acceptance criteria, Verification, Deliverables.
- Все ADR и архитектурные refs, изменяемые как результаты, перечисли явно в `Deliverables` через canonical ID/path/anchor. Входные ссылки оставь в Context/`adrs`/`architecture_refs`; не обозначай их как результаты. До handoff запусти `python3 .harness/tools/planning-state.py output-contract STEP-NNN`; при `OUTPUT_DECLARATIONS_REQUIRED` исправь контракт создаваемого STEP и повтори gate. Dispatcher также проверяет новые STEP перед успешным завершением ADD.
- Перед handoff выполни Requirements Quality Gate по новому STEP и owning artifacts. Сначала ищи ответ в linked REQ/ADR/OQ/architecture/codebase; затем проверь schema-v1 semantic payload через `python3 .harness/tools/requirements-quality.py --payload-file '<local-json-or->'`. Blocking ambiguity нельзя превращать в executable STEP: задай только material targeted question, сохрани ответ в canonical owner и повтори gate. Non-blocking stylistic warning не блокирует STEP ADD.
- После quality PASS проверь linked contracts, ownership, dependencies, architecture refs и OQ. Не маскируй overlap новым STEP.
- Не редактируй PLAN/STATUS/requirements STATUS/OQ index вручную. Пересобери:
  ```bash
  python3 .harness/tools/sync-projections.py
  python3 .harness/tools/validate.py --mode manual
  ```
- Production code не меняй.
- Только непротиворечивый unblocked STEP получает handoff `STEP PLAN STEP-NNN`.
