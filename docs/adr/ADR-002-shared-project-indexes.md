---
schema: 1
id: ADR-002
status: accepted
date: 2026-09-21
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-003
  - REQ-005
  - REQ-006
  - REQ-009
  - REQ-010
steps:
  - STEP-003
  - STEP-005
  - STEP-007
---

# ADR-002 — Общие Artifact и Reference indexes

## Context

Views, navigation providers, diagnostics и relations используют одни и те же Harness documents и ссылки.

## Problem

Независимый parsing в каждом consumer создаст неодинаковые результаты, лишнее scanning workspace и медленную интерактивность.

## Decision

Расширение строит на каждый workspace root общий read-only Artifact Index и Reference Index в памяти. Все consumers получают данные из этих индексов, которые watcher обновляет инкрементально.

## Alternatives considered

### Независимый parsing в каждом provider

Отклонено: дублирует логику, ухудшает latency и создаёт drift между UI и navigation.

### Persistent cache артефактов в workspace

Отклонено: нарушает read-only boundary и создаёт альтернативный source of truth.

## Consequences

Нужны чёткие typed parser interfaces, invalidation rules и изоляция errors одного документа. Lookup по ID и references становится быстрым и единообразным.

## Security implications

Индексы не исполняют содержимое файлов и существуют только в памяти Extension Host.

## Data / migration implications

Project data не мигрируются и не кэшируются на диске.

## Compatibility / operational implications

Корректность depends on configured paths и watcher coverage; project-level manifest blocker останавливает создание index.
