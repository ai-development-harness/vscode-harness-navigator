---
schema: 1
id: ADR-001
status: accepted
date: 2026-09-21
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-001
  - REQ-002
  - REQ-003
steps:
  - STEP-001
  - STEP-002
  - STEP-003
  - STEP-007
---

# ADR-001 — Read-only граница и Harness как источник истины

## Context

Navigator нужен для работы с проектами Harness, но не должен конкурировать с их protocol layer и canonical documents.

## Problem

Запуск команд или собственное сохранение состояния из IDE создадут второй управляющий контур и риск расхождения с Harness.

## Decision

Расширение только читает manifest, configured artifacts, projections и command graph. Оно не запускает процессы, не изменяет документы или execution state и не хранит независимое persistent состояние проекта.

## Alternatives considered

### Command launcher и редактор артефактов

Отклонено для MVP: это расширяет доверенную границу до runtime/orchestration и конфликтует с назначением навигатора.

### Hardcoded локальная модель путей и статусов

Отклонено: такая модель быстро расходится с configured Harness project.

## Consequences

UI может предоставлять только derived read-only возможности и clipboard copy. Все paths и lifecycle semantics должны быть явно прочитаны из Harness files.

## Security implications

Отсутствие command dispatch, shell и document mutation сокращает привилегии расширения и предотвращает неявное выполнение текста workspace.

## Data / migration implications

Migration отсутствует: расширение не пишет project data и не поддерживает legacy format эвристически.

## Compatibility / operational implications

Неизвестный или неподдерживаемый manifest/schema даёт явное состояние incompatibility, а не fallback к стандартным путям.
