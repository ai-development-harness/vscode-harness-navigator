---
name: add-plan-step
description: Convert a short user request into a versioned, traceable, dependency-aware STEP and regenerate deterministic projections.
---
# add-plan-step

Используй для `STEP ADD: ...`.

- Сначала semantic duplicate/overlap search по canonical STEP/REQ.
- ID = следующий после максимального когда-либо использованного; формат `STEP-001+`, верхнего предела нет, дырки не переиспользуются.
- Создай STEP schema v1 в configured `protocol.taskDirectory`.
- Machine frontmatter:
  - `status: planned`;
  - protocol-English `type` / `priority`;
  - `phase`;
  - strict lists `depends_on`, `requirements`, `adrs`, `architecture_refs`, `risk_flags`;
  - `plan.status: not_planned`.
- Новый REQ создавай только для нового product contract в configured `sources.requirements`; обновляй двустороннюю REQ↔STEP traceability.
- Durable decision → ADR/RESEARCH prerequisite. Обновляй ADR↔STEP traceability.
- Существенная неопределённость → отдельный canonical OQ schema v1 в configured `sources.openQuestions`; `affects` обязан ссылаться на существующие IDs либо `PROJECT`.
- Заполни Goal, Context, Scope, Mutation policy (Allowed/Conditional/Forbidden), Out of scope, Acceptance criteria, Verification, Deliverables.
- Перед handoff проверь linked contracts, ownership, dependencies, architecture refs и OQ. Не маскируй overlap новым STEP.
- Не редактируй PLAN/STATUS/requirements STATUS/OQ index вручную. Пересобери:
  ```bash
  python3 .harness/tools/sync-projections.py
  python3 .harness/tools/validate.py --mode manual
  ```
- Production code не меняй.
- Только непротиворечивый unblocked STEP получает handoff `STEP PLAN STEP-NNN`.
