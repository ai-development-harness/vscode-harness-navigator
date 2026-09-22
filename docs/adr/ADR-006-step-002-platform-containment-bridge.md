---
schema: 1
id: ADR-006
status: accepted
date: 2026-09-22
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-002
steps:
  - STEP-002
  - STEP-009
---

# ADR-006 — Прямой platform-scoped contract для STEP-002

## Context

ADR-005 зафиксировал platform-scoped containment guarantee во время corrective
STEP-008. Его immutable history связывает это решение только с STEP-008. Однако
актуальный implementation plan STEP-002 обязан получать полную архитектурную
норму через прямую machine-readable связь: planning context fingerprint не
включает транзитивные ADR references.

## Problem

Нужно сделать применимый к STEP-002 containment contract прямым входом
`context_basis`, сохранив historical text, status и links ADR-005 без изменения
или ложного supersession.

## Decision

STEP-002 использует этот ADR как полный direct architecture contract чтения
`.harness/manifest.yaml`:

1. На всех platform до чтения действуют portable pre-open `realpath`/containment
   check и post-open identity check по `dev`/`ino`. Static symlink за пределы
   workspace и подмена финального path component на symlink блокируются.
2. Canonical re-derivation уже открытого descriptor для защиты от гонки на
   промежуточном ancestor доступна и обязательна на Linux через `/proc/self/fd`.
3. На platform без такой re-derivation корректный project достигает `valid`;
   принимается только остаточный риск конкурентной подмены промежуточного
   ancestor в момент открытия. Отсутствие этой capability само по себе не даёт
   `configurationBlocked`.
4. Native addon для полного non-Linux parity не добавляется.

Это bridge decision не supersede-ит ADR-005 и не меняет его threat model,
alternatives, compatibility guarantee или исторические reverse links. ADR-005
остаётся первоначальным immutable source решения; ADR-006 — самостоятельной
нормой, напрямую применяемой STEP-002.

## Alternatives considered

### Переписать ADR-005

Отклонено: accepted ADR является immutable history; изменение его links или
supersession metadata задним числом нарушило бы project governance.

### Связать STEP-002 с ADR-005 только через текст ADR-006

Отклонено: planning fingerprint STEP-002 хеширует только direct `adrs`, поэтому
транзитивная ссылка не дала бы проверяемого architecture input.

### Новый ADR с supersession ADR-005

Отклонено: решение и его guarantees не меняются, а reciprocal supersession
потребовал бы запрещённой mutation accepted ADR-005.

## Consequences

STEP-002 получает прямую двустороннюю связь с ADR-006 и может быть перепланирован
против полного неизменяемого contract. ADR-005 не изменяется; product behavior,
package topology и production code не меняются.

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
