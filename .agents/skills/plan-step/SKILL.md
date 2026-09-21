---
name: plan-step
description: Produce, independently review, fingerprint and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`. Human-readable prose Implementation plan и planning-review пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; protocol headings/keys не локализуй.

Execution Status ведёт global wrapper. Active legacy schema после Harness update является blocker: сначала `PROJECT RECONCILE`.

## Phase A — deterministic + semantic contract validation

1. Запусти:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
2. Восстанови STEP → type-specific dependency completion proofs → canonical REQ → Accepted ADR → explicit `architecture_refs` → relevant canonical OQ → code/tests/config.
3. Проверь semantic consistency:
   - Goal/Scope/Out of scope/Mutation policy согласованы;
   - Acceptance следует из REQ/ADR и не требует forbidden mutation;
   - Verification реально доказывает Acceptance;
   - linked REQ совместимы;
   - dependencies достаточны;
   - ownership не конфликтует с соседними STEP;
   - architecture prerequisite имеет explicit ref;
   - OPEN OQ/TBD не блокирует решение.
4. Contract conflict, missing prerequisite/decision или impossible acceptance => `BLOCKED`. Не расширяй contract догадкой.

## Phase B — draft implementation plan

1. Запиши содержательный `## Implementation plan`.
2. Пока semantic planning-review не завершён, выставь `plan.status: draft`; не записывай Ready hashes вручную.
3. Получи deterministic fingerprints:
   ```bash
   python3 .harness/tools/planning-state.py plan-context STEP-NNN
   ```
   `contextBasis` включает STEP contract, linked REQ/ADR, explicit architecture refs, relevant OQ и type-specific completion proof прямых dependencies. `planContentHash` отдельно fingerprint-ит сам Implementation plan.

## Phase C — обязательный independent planning-review

Для **каждого** STEP PLAN передай готовый draft отдельному `reviewer` agent/session, отличному от planner, который составлял план. Создай immutable schema-v1 report `PLAN-REVIEW-<UTC timestamp>.md` в configured `protocol.planningReviewDirectory/STEP-NNN/` по template:

- `kind: planning_review`;
- `step_id`;
- `verdict: pass|blocked`;
- точные `context_basis` и `plan_content_hash`;
- `reviewer_role: reviewer` и timestamp.

После любых правок plan/contract fingerprints пересчитай и старый report не переиспользуй.

## Phase D — Ready stamp

Только для matching PASS выполни:

```bash
python3 .harness/tools/execution-state.py stamp-plan STEP-NNN
```

`stamp-plan` сам откажет без matching PASS report и atomically запишет `plan.status=ready`, revision, context basis, content hash, reviewed report и timestamp.

После изменения текста Implementation plan Ready автоматически становится stale по content hash. Изменение relevant upstream context делает stale context basis. Не ставь STEP `in_progress` и не меняй production code.
