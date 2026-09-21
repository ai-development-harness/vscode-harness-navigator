---
schema: 1
id: STEP-004
status: planned
type: implementation
priority: high
phase: workspace-ui
depends_on:
  - STEP-003
requirements:
  - REQ-001
  - REQ-004
  - REQ-008
adrs:
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#основные-потоки"
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-004 — Views артефактов, фокуса и поиск

## Goal

Предоставить нативные Harness Artifacts и Harness Focus Tree Views, пользовательскую сортировку/фильтрацию и `Harness: Go to Artifact`.

## Context

STEP-003 создаёт общий project model; этот STEP преобразует его в standard VS Code UI без нового parsing documents.

## Scope

- Activity Bar container, Artifacts View и Focus View на основе общего Artifact Index.
- Tree items, opening canonical files, context actions, sort/filter workspace settings и clear filters.
- Quick Pick `Harness: Go to Artifact` с fuzzy search ID/title/kind.
- Tests views, actions, sorting/filtering and artifact search.

## Mutation policy

### Allowed

- Source, tests, extension contributions и localized UI strings для artifact/focus/search flows.

### Conditional

- Изменение shared view wiring, если требуется для disposal/refresh subscriptions.

### Forbidden

- WebView, самостоятельный parsing files в provider или выбор следующего STEP за пользователя.
- Изменение Harness artifacts и запуск команд из context menu.

## Out of scope

- Harness Commands View и command catalog.
- Definition, hover, completion, reference и highlighting providers.

## Acceptance criteria

- Artifacts View показывает grouped STEP/REQ/ADR/OQ с ID, title и status через native Tree View API.
- Focus View показывает active/blocked STEP и open OQ, не назначая работу.
- Sort/filter/clear filters соответствуют supported fields и сохраняют workspace preferences.
- `Harness: Go to Artifact` fuzzy-ищет известные artifacts по ID/title/kind и открывает выбранный canonical Markdown file.

## Verification

- Реальные `typecheck`, `lint` и targeted tests views/search.
- Extension Host scenario с artifact selection, filters и empty state.

## Deliverables

- Tree providers/items, artifact search command, sort/filter state, localized UI and tests.

## Implementation plan

Заполняется командой `STEP PLAN STEP-004`.

## Evidence

—

## Blocker / Failure reason

—
