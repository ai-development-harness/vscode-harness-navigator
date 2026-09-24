---
schema: 1
id: ADR-003
status: accepted
date: 2026-09-21
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-007
steps:
  - STEP-006
  - STEP-007
  - STEP-015
---

# ADR-003 — Command Catalog строится из command graph

## Context

Harness release определяет canonical command surface в machine-readable `.harness/command-transitions.json`.

## Problem

Ручной список команд в расширении может устареть после Harness update и скрыть команды будущей версии.

## Decision

Command Catalog извлекает domain, canonical syntax, target, input и chain metadata из supported command graph schema. Локализованные short descriptions являются только presentation layer и имеют fallback для незнакомых команд.

## Alternatives considered

### Вручную поддерживаемый список canonical commands

Отклонено: он не является источником истины и требует синхронных релизов.

### Parsing только COMMANDS.md

Отклонено: Markdown не является machine-readable contract для полного каталога.

## Consequences

Commands View обновляется watcher-ом command graph; неизвестная schema показывает локальную диагностируемую ошибку без отключения артефактной навигации.

## Security implications

Каталог остаётся read-only и копирует текст только в clipboard; command graph не рассматривается как инструкция к выполнению.

## Data / migration implications

Данные каталога derived и не сохраняются в workspace.

## Compatibility / operational implications

Поддерживаемые schema могут показать неизвестные команды; неподдерживаемые schema не должны интерпретироваться эвристически.
