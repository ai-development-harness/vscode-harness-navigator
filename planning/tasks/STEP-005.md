---
schema: 1
id: STEP-005
status: planned
type: implementation
priority: high
phase: ide-navigation
depends_on:
  - STEP-003
requirements:
  - REQ-001
  - REQ-005
  - REQ-006
  - REQ-008
adrs:
  - ADR-002
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#data-state-model"
  - "docs/architecture.md#reliability-observability"
risk_flags:
  - performance-critical
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-005 — Навигация, references и relations Harness ID

## Goal

Реализовать standard VS Code navigation и relations flows для Harness ID на основе общих Artifact и Reference indexes.

## Context

Navigator должен дать ID поведение IDE symbol, но не обходить workspace повторно и не применять semantic behavior за пределами Harness-aware files.

## Scope

- Definition, document link, hover, completion, reference и semantic highlighting providers.
- Relations service, backlinks, Show Relations и Find All References entry points.
- Theme-compatible rendering and diagnostics unknown IDs в области classifier.
- Unit/integration tests navigation, completion, references, relations, hover and highlighting.

## Mutation policy

### Allowed

- Source, tests, command contributions и localized strings navigation/relations providers.

### Conditional

- Минимальные extensions shared index interfaces для required range and metadata lookups.

### Forbidden

- Повторный scan workspace при hover/completion/references, fixed RGB styles и semantic processing outside Harness-aware files.
- Автоматическое изменение Markdown или Harness configuration.

## Out of scope

- Artifact/focus tree UI and command catalog UI.
- Command execution, graph visualisation and WebView details panel.

## Acceptance criteria

- Known Harness ID в Harness-aware file поддерживает definition, peek, Ctrl/Cmd+Click, document links, localized hover и completion, вставляющий только canonical ID.
- Theme-compatible highlighting не ухудшает Markdown syntax highlighting; unknown IDs не приводят к exception.
- Relations и backlinks показывают кликабельные outgoing/incoming artifacts из общих indexes.
- Standard Find All References и UI entry points возвращают shared Reference Index results без erroneous inclusion canonical definition.

## Verification

- Реальные `typecheck`, `lint` и targeted unit tests providers/relations.
- Extension Host integration tests definition, hover, completion, references and diagnostics in RU/EN.

## Deliverables

- Navigation/highlighting providers, relations service, reference commands, localized UX and tests.

## Implementation plan

Заполняется командой `STEP PLAN STEP-005`.

## Evidence

—

## Blocker / Failure reason

—
