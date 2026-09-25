---
schema: 1
id: ADR-004
status: accepted
date: 2026-09-21
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-001
  - REQ-004
  - REQ-005
  - REQ-007
  - REQ-008
  - REQ-009
  - REQ-010
steps:
  - STEP-001
  - STEP-004
  - STEP-005
  - STEP-006
  - STEP-007
  - STEP-016
---

# ADR-004 — Нативный VS Code UI и локальный offline runtime

## Context

MVP должен быть быстрым, доступным для custom themes и не требовать внешних сервисов.

## Problem

WebView, fixed styles и remote integrations увеличивают surface, обходят native IDE UX и противоречат локальному назначению Navigator.

## Decision

Использовать официальный VS Code Extension API: Tree View, Quick Pick, language providers, diagnostics, FileSystemWatcher, ThemeIcon/ThemeColor и стандартную localization system. Runtime работает offline, без telemetry, network, shell или Git history.

## Alternatives considered

### WebView-first dashboard

Отклонено для MVP: нативные Tree Views и providers покрывают нужные flows при меньшей сложности и лучшей theme compatibility.

### Внешний backend или AI service

Отклонено: они не нужны для deterministic local parsing и нарушают offline requirement.

## Consequences

UI остаётся близким к стандартному VS Code. Нужны RU/EN resources, integration tests для providers/views и аккуратная работа с lifecycle disposable subscriptions.

## Security implications

Отсутствуют удалённые запросы и передача содержимого workspace; input обрабатывается локально через parser.

## Data / migration implications

Только workspace settings для sort/filter могут быть persistent; artifacts Harness не меняются.

## Compatibility / operational implications

Extension ориентируется на Node runtime целевого VS Code и production bundling; fixed RGB не используется, чтобы поддерживать custom themes.
