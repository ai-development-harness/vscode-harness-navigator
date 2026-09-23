---
schema: 1
id: ADR-007
status: accepted
date: 2026-09-23
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-002
steps:
  - STEP-007
---

# ADR-007 — Прямой platform-scoped contract для STEP-007

## Context

ADR-005 зафиксировал platform-scoped containment guarantee, ADR-006 сделал его
прямым входом для STEP-002 и STEP-009. STEP-007 проверяет containment
configured paths end-to-end (traversal, absolute path, static symlink) на
фактическом extension path и packaged-профиле, то есть его security-assert
опираются на ту же норму. Planning context fingerprint STEP-007 хеширует только
direct `adrs`, поэтому транзитивная ссылка через ADR-005/ADR-006 не даёт
проверяемого architecture input.

## Problem

Сделать применимый к STEP-007 containment contract прямым входом
`context_basis`, не изменяя text, status и links ADR-005 и ADR-006.

## Decision

STEP-007 использует этот ADR как полный direct architecture contract чтения
`.harness/manifest.yaml` и configured paths при integration/release proof:

1. На всех platform до чтения действуют portable pre-open `realpath`/containment
   check и post-open identity check по `dev`/`ino`. Абсолютный путь, traversal и
   static symlink за пределы workspace блокируются как configuration blocker;
   подмена финального path component на symlink блокируется.
2. Canonical re-derivation уже открытого descriptor для защиты от гонки на
   промежуточном ancestor доступна и обязательна на Linux через `/proc/self/fd`.
3. На platform без такой re-derivation корректный project достигает `valid`;
   принимается только остаточный риск конкурентной подмены промежуточного
   ancestor в момент открытия. Отсутствие этой capability само по себе не даёт
   `configurationBlocked`.
4. Native addon для полного non-Linux parity не добавляется.
5. Integration proof STEP-007 проверяет только этот контракт и не меняет
   containment readers, кроме узкого corrective по подтверждённому дефекту.

Это bridge decision не supersede-ит ADR-005 и ADR-006 и не меняет их threat
model, alternatives, compatibility guarantee или reverse links. ADR-005
остаётся первоначальным immutable source решения, ADR-006 — нормой для
STEP-002/STEP-009, ADR-007 — самостоятельной нормой, напрямую применяемой
STEP-007.

## Alternatives considered

### Дописать STEP-007 в `steps` ADR-005 и ADR-006

Отклонено: accepted ADR является immutable historical decision record; изменение
его links задним числом нарушает governance (ADR-006, правило 1 README ADR).

### Связать STEP-007 с ADR-005/ADR-006 только через текст

Отклонено: fingerprint хеширует только direct `adrs`, транзитивная ссылка не
даёт проверяемого architecture input.

### Новый ADR с supersession ADR-005/ADR-006

Отклонено: решение и его guarantees не меняются, а reciprocal supersession
потребовал бы запрещённой mutation accepted ADR.

## Consequences

STEP-007 получает прямую двустороннюю связь с ADR-007 и может быть
перепланирован против полного неизменяемого contract. ADR-005 и ADR-006 не
изменяются; product behavior, package topology и production code не меняются.

## Security implications

Portable containment guarantees и Linux-specific ancestor-race protection остаются
обязательными. Explicit non-Linux residual risk ограничен конкурентным локальным
process в узком окне открытия и не расширяет read-only boundary расширения.

## Data / migration implications

Отсутствуют: формат, расположение и lifecycle project data не изменяются.

## Compatibility / operational implications

Расширение остаётся universal VS Code extension. Корректный Harness-project на
macOS/Windows не блокируется только из-за отсутствия descriptor re-derivation;
capability profile остаётся наблюдаемым в tests.
