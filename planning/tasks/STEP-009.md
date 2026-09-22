---
schema: 1
id: STEP-009
status: completed
type: adr
priority: high
phase: architecture-governance
depends_on:
  - STEP-008
requirements:
  - REQ-002
adrs:
  - ADR-006
architecture_refs:
  - "docs/architecture.md#security-boundaries"
risk_flags:
  - architecture
  - security-sensitive
plan:
  status: ready
  revision: 2
  context_basis: sha256:79c382a1b193b3c701fe9d0f6a3aa2e03a9a6e90e0edfc179157663763ab23af
  content_hash: sha256:ef2017b467a777869546c1082b2f4b26171c56888b5eb0caf9dd48452461afb6
  reviewed_report: planning/plan-reviews/STEP-009/PLAN-REVIEW-20260922T062352Z.md
  planned_at: 2026-09-22T06:24:46+00:00
---

# STEP-009 — Bridge ADR для traceability STEP-002 и platform containment

## Goal

Устранить traceability-разрыв между текущей реализацией STEP-002 и platform-scoped
containment decision, не переписывая immutable accepted ADR-005.

## Context

Corrective STEP-008 завершил реализацию ADR-005 и закрыл F-009/F-010 для
STEP-002. Однако новый актуальный план STEP-002 обязан опираться на это
architecture decision, тогда как `ADR-005.steps` исторически ограничен STEP-008.
Добавление STEP-002 в accepted ADR-005 изменило бы immutable decision history, а
отсутствие direct ADR связи не включает решение в `context_basis` planning review.

## Scope

- Подготовить отдельный ADR-bridge, который самостоятельно фиксирует действующую
  platform-scoped норму containment и делает её применение к STEP-002 explicit и
  двусторонне проверяемым, не изменяя текст ADR-005.
- Связать новый ADR с REQ-002, STEP-002 и этим ADR STEP; обновить REQ↔STEP/ADR
  traceability и релевантный architecture index только deterministic projections или
  canonical источники, которые действительно владеют этими связями.
- Обновить STEP-002 так, чтобы его последующий plan ссылался на новый accepted ADR,
  а не на несвязанную historical запись ADR-005.

## Mutation policy

### Allowed

- Новый canonical ADR, STEP/REQ traceability и минимальная синхронизация architecture
  documentation, нужная для отображения нового решения.
- `planning/tasks/STEP-002.md` только в объёме machine traceability, required
  architecture reference и блока, необходимого для честного re-plan.

### Conditional

- Изменение `docs/architecture.md` только для списка/ссылки на новый accepted ADR,
  без изменения security boundary или поведения containment.

### Forbidden

- Любое изменение текста, status, reverse links или supersession metadata accepted ADR-005.
- Изменение production-кода, tests, package configuration, REQ-002 Acceptance или
  platform-scoped security guarantee.
- Подмена нового ADR неформальной ссылкой, ручная правка projections или объявление
  STEP-002 ready/completed без нового matching planning-review и independent STEP review.

## Out of scope

- Реализация native addon, изменение portability/containment поведения или новые
  product requirements.
- Повторная реализация либо review findings STEP-008.

## Acceptance criteria

- Новый ADR schema-v1 имеет собственный immutable decision record, ссылается на REQ-002,
  STEP-002 и STEP-009 и нормативно фиксирует portable containment checks, Linux-only
  ancestor-race protection, non-Linux residual risk и отказ от native addon. Эта норма
  достаточна для STEP-002 без транзитивного чтения ADR-005; ADR-005 остаётся неизменным
  historical source решения.
- STEP-002 получает двусторонне проверяемую ссылку на новый accepted ADR; его planning
  context включает architecture decision, необходимое для platform-scoped containment.
- REQ-002 и architecture documentation согласованы с canonical links; projections
  детерминированно пересобраны и validator проходит без traceability errors.
- ADR-005 остаётся byte-for-byte неизменным.

## Verification

- Сравнение content hash ADR-005 до/после и `git diff --check`.
- `python3 .harness/tools/sync-projections.py --check`.
- `python3 .harness/tools/validate.py --mode manual`.
- Независимый review ADR STEP с проверкой REQ↔ADR↔STEP traceability и absence of
  production changes.

## Deliverables

- Новый bridge ADR и двусторонние canonical links.
- Обновлённый STEP-002, пригодный к новому semantic planning review после acceptance ADR.
- Deterministic projection/validation evidence.

## Implementation plan

1. **Зафиксировать историческую границу.** Перед любыми изменениями сохранить SHA-256 и
   Git diff baseline `docs/adr/ADR-005-platform-scoped-manifest-containment.md`. Повторно
   проверить, что `ADR-005` остаётся accepted historical decision с `steps: [STEP-008]`;
   не добавлять в него STEP-002, не менять `supersedes`/`superseded_by` и не объявлять его
   superseded. Это сохраняет literal history и устраняет необходимость reciprocal mutation.
2. **Создать самостоятельный ADR-006 bridge.** Добавить schema-v1 `ADR-006` со status
   `accepted`, requirements `[REQ-002]` и steps `[STEP-002, STEP-009]`. Его Decision
   должен сам нормативно перечислить весь contract, необходимый STEP-002: portable pre-open
   realpath/containment и post-open `dev`/`ino` identity checks на всех platform,
   Linux-only canonical re-derivation для ancestor race, допустимый non-Linux residual risk,
   достижимость `valid` и отказ от native addon. Это делает ADR-006 полным direct input
   `context_basis` STEP-002, а не транзитивной ссылкой. ADR-006 подтверждает неизменность
   поведения, threat model, residual risk, alternatives и compatibility guarantee ADR-005,
   но не supersede-ит его и не создаёт reciprocal supersession link.
3. **Восстановить двусторонние связи.** Добавить ADR-006 в `REQ-002.adrs` и подтвердить
   обратную связь `ADR-006.requirements`; добавить ADR-006 в `STEP-002.adrs` и подтвердить
   `ADR-006.steps`. Связать STEP-009 с ADR-006 после его создания. В STEP-002 заменить
   прямую ссылку Implementation plan на ADR-005 ссылкой на ADR-006 с краткой ссылкой на
   сохранённое source decision ADR-005; не менять Goal, Scope, Acceptance, Evidence или
   product behavior.
4. **Синхронизировать canonical architecture references.** Добавить ADR-006 в существующий
   список accepted decisions `docs/architecture.md`, если этот список владеет данной
   навигационной ссылкой; не менять раздел `security-boundaries`. Пересобрать только
   deterministic projections через `sync-projections.py`, затем проверить integrity,
   bidirectional traceability, неизменность ADR-005 и отсутствие production-file changes.
5. **Подготовить handoff.** Записать фактические hashes, команды и результаты в Evidence.
   Не stamp-ить STEP-002: после завершения STEP-009 отдельный `STEP PLAN STEP-002` должен
   получить новый context basis и independent planning-review; затем ему всё ещё нужен
   отдельный independent implementation review.

## Evidence

- `sha256sum docs/adr/ADR-005-platform-scoped-manifest-containment.md` — до и после
  выполнения `d66a84fe0fc712464bc36c9213b9d524e8cceb91cd2d36267f9c04dbe63333df`;
  historical ADR byte-for-byte не изменён.
- Создан `docs/adr/ADR-006-step-002-platform-containment-bridge.md` со status `accepted`;
  его `requirements: [REQ-002]` и `steps: [STEP-002, STEP-009]` reciprocal с REQ/STEP.
- `python3 .harness/tools/sync-projections.py` — exit code 0; обновлены только
  `docs/requirements/STATUS.md`, `planning/PLAN.md`, `planning/STATUS.md`.
- `python3 .harness/tools/validate.py --mode manual` — exit code 0; `HARNESS VALIDATION:
  PASS (216 tracked files checked, mode=manual)`. Существующие warnings касаются stale
  ready context STEP-001/STEP-008, не STEP-009.
- `python3 .harness/tools/sync-projections.py --check` и `git diff --check` — каждый
  exit code 0; projection drift и whitespace errors отсутствуют.
- Независимый planning review
  `planning/plan-reviews/STEP-009/PLAN-REVIEW-20260922T062352Z.md` — `PASS` для exact
  `context_basis` `sha256:79c382a1b193b3c701fe9d0f6a3aa2e03a9a6e90e0edfc179157663763ab23af`
  и `plan_content_hash` `sha256:ef2017b467a777869546c1082b2f4b26171c56888b5eb0caf9dd48452461afb6`.

## Blocker / Failure reason

—
