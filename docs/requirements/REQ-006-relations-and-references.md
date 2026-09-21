---
schema: 1
id: REQ-006
priority: high
source: brief
steps:
  - STEP-005
  - STEP-007
adrs:
  - ADR-002
---

# REQ-006 — Связи и поиск упоминаний

## Requirement

Расширение должно строить единый Reference Index для Harness-aware файлов и показывать outgoing relations, backlinks и стандартный Find All References.

## Rationale

Связи REQ, STEP, ADR и OQ являются центральной частью документной модели Harness и должны быть доступны из IDE без повторного обхода workspace на каждый запрос.

## Acceptance

- Show Relations показывает кликабельные requirement, ADR, dependency и incoming связи артефакта.
- Backlinks и Find All References используют один Reference Index и возвращают упоминания из Harness-aware файлов.
- Find All References доступен из обычного интерфейса редактора, tree/context menu и relations flow.
- Canonical definition не ошибочно включается как обычное reference, если это противоречит стандартному VS Code UX.
