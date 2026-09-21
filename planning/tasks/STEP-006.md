---
schema: 1
id: STEP-006
status: planned
type: implementation
priority: high
phase: commands-ui
depends_on:
  - STEP-002
requirements:
  - REQ-001
  - REQ-007
  - REQ-008
adrs:
  - ADR-003
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#security-boundaries"
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

# STEP-006 — Каталог и справка Harness-команд

## Goal

Реализовать read-only Command Catalog, Harness Commands View, Find Command и безопасное Copy Command.

## Context

Command graph является machine-readable source of truth, а UI должен оставаться справкой, которая не dispatches commands.

## Scope

- Parser supported command graph schema и typed Command Catalog.
- Producer categories `CommandGraphReadError` и `CommandGraphUnsupportedSchema` для общего diagnostics flow.
- Commands Tree View by domain, descriptions/fallback, tooltips and Find Command Quick Pick.
- Copy canonical command templates to clipboard, включая STEP context substitution.
- Watch command graph and tests supported/unsupported schema, unknown future command and copy behavior.

## Mutation policy

### Allowed

- Source, tests, extension contributions и localized strings command catalog UI.

### Conditional

- Минимальные project-state subscriptions, необходимые для isolated command graph refresh per workspace root.

### Forbidden

- Ручной canonical command list как source of truth, command dispatch to terminal/agent/runtime и parsing commands from Markdown as contract.

## Out of scope

- Artifact parsing, reference navigation и command-chain helper.
- Изменение command graph или Harness project files.

## Acceptance criteria

- Catalog derives canonical syntax, domain, input/target and chain metadata from `.harness/command-transitions.json`.
- Commands View и Find Command показывают known и future commands supported schema, short localized description/fallback и graph-based tooltip.
- Copy Command places correct template or STEP-specific command only in clipboard and never executes it.
- Command graph change refreshes catalog without Extension Host restart; unsupported graph schema isolates its error from Artifact Navigator.
- Command graph read/schema failures имеют stable diagnostics categories и доступны через общий diagnostics flow.

## Verification

- Реальные `typecheck`, `lint` и targeted unit tests graph/catalog/copy.
- Extension Host integration scenarios for Commands View, Find Command, Copy Command and graph change.

## Deliverables

- Command graph service, Command Catalog, commands view/actions, watcher subscription, localized descriptions and tests.

## Implementation plan

Заполняется командой `STEP PLAN STEP-006`.

## Evidence

—

## Blocker / Failure reason

—
