---
schema: 1
id: REQ-001
priority: high
source: brief
steps:
  - STEP-001
  - STEP-002
  - STEP-003
  - STEP-004
  - STEP-005
  - STEP-006
  - STEP-007
adrs:
  - ADR-001
  - ADR-004
---

# REQ-001 — Read-only граница и источник истины

## Requirement

Расширение должно быть локальным навигационным и информационным слоем: оно читает существующие файлы Harness, не создаёт альтернативную модель состояния и не изменяет артефакты Harness автоматически.

## Rationale

Разработчик должен доверять canonical документам и протоколу Harness; IDE-удобство не должно получить полномочия runtime или orchestration.

## Acceptance

- Расширение не запускает Harness-команды, агентов, shell-команды, Python tools или terminal.
- Расширение не изменяет STEP, REQ, ADR, OQ, projections, manifest или execution state; копирование команды ограничено clipboard.
- Данные артефактов, связей и статусов берутся из configured Harness files, а не из отдельного persistent state.
