---
schema: 1
id: REQ-003
priority: high
source: brief
steps:
  - STEP-003
  - STEP-007
adrs:
  - ADR-001
  - ADR-002
---

# REQ-003 — Индексация артефактов и статусов

## Requirement

Расширение должно read-only парсить canonical STEP, REQ, ADR и OQ, строить единый Artifact Index и отображать статусы согласно модели Harness.

## Rationale

Навигация и UI должны опираться на одну согласованную модель документов, а не на разрозненный parsing в каждом компоненте.

## Acceptance

- Index содержит ID, title, kind, status, file, metadata и outgoing/incoming relations для корректных STEP, REQ, ADR и OQ.
- Для REQ lifecycle status читается из requirements status projection Harness; не создаётся альтернативный lifecycle.
- Отсутствие артефактов является normal empty state, а ошибка одного файла не исключает остальные корректные возможности.
- Duplicate ID, отсутствующий H1, несоответствие ID и файла, parse errors и неизвестные references классифицируются для diagnostics.
