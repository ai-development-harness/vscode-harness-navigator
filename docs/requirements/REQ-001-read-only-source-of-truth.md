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
  - STEP-018
adrs:
  - ADR-001
  - ADR-004
  - ADR-008
---

# REQ-001 — Read-only граница и источник истины

## Requirement

Расширение должно быть локальным навигационным и информационным слоем: оно не изменяет артефакты Harness и не создаёт альтернативную семантическую модель состояния. Единственное исключение из запрета запуска процессов — fixed read-only Project State API `.harness/tools/project-state.py --json` для Harness 0.10.3+ по контракту ADR-008.

## Rationale

Разработчик должен доверять canonical документам и протоколу Harness; IDE-удобство не должно получить полномочия runtime или orchestration.

## Acceptance

- Расширение не запускает Harness-команды, dispatcher, агентов, пользовательские shell-команды, terminal или произвольные Python tools; допускается только ограниченный ADR-008 запуск Project State API без shell для чтения snapshot.
- Расширение не изменяет STEP, REQ, ADR, OQ, projections, manifest или execution state; копирование команды ограничено clipboard.
- Данные артефактов, связей и статусов берутся из configured Harness files или canonical Project State API, а не из отдельного persistent state.
