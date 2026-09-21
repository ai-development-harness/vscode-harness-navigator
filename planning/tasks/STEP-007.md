---
schema: 1
id: STEP-007
status: planned
type: implementation
priority: high
phase: integration-quality
depends_on:
  - STEP-004
  - STEP-005
  - STEP-006
requirements:
  - REQ-001
  - REQ-002
  - REQ-003
  - REQ-004
  - REQ-005
  - REQ-006
  - REQ-007
  - REQ-008
  - REQ-009
  - REQ-010
adrs:
  - ADR-001
  - ADR-002
  - ADR-003
  - ADR-004
architecture_refs:
  - "docs/architecture.md#основные-потоки"
  - "docs/architecture.md#reliability-observability"
  - "docs/architecture.md#deployment-runtime-assumptions"
risk_flags:
  - release-critical
  - security-sensitive
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-007 — Интеграция MVP и release proof

## Goal

Свести реализованные подсистемы в проверяемый локальный MVP, закрыть cross-cutting integration gaps и подготовить фактические package/release evidence.

## Context

Функции в независимых STEP требуют целостной проверки multi-root lifecycle, watcher refresh, localization, performance boundary and packaged extension behavior.

## Scope

- Интеграционные tests всех обязательных MVP flows, cross-root isolation, `Harness: Refresh` и `Harness: Show Diagnostics`.
- Проверка watch-driven refresh artifact/projection/manifest/command graph, summary/status bar и diagnostics resilience.
- Проверка offline/no-shell/no-mutation boundary на фактическом extension path.
- End-to-end проверка containment configured paths и complete stable diagnostics taxonomy.
- Production bundling/package inspection and documentation of real developer/release commands.

## Mutation policy

### Allowed

- Интеграционный source/wiring, tests, test fixtures, package configuration и development/release documentation, необходимые для MVP proof.

### Conditional

- Узкие corrective changes ownership ранее реализованных components только при подтверждённом integration defect.

### Forbidden

- Новые post-MVP product capabilities, WebView, AI/network integrations или расширение mutation boundary.

## Out of scope

- Новые REQ/architectural contracts и product features после утверждённого MVP.
- Автоматический publication, Git commit, push или release.

## Acceptance criteria

- Integration tests покрывают all required detection states, views, providers, command catalog/copy, diagnostics, watchers, multi-root and RU/EN behavior.
- Реальный packaged extension работает offline, не запускает shell/Harness tools, не требует GitHub auth и не изменяет Harness artifacts.
- Status Bar/summary reflect derived counts, watcher refresh works without Extension Host restart, and `node_modules` is not scanned.
- `Harness: Refresh` восстанавливает current workspace derived state, а `Harness: Show Diagnostics` показывает stable taxonomy для detection, artifacts, projections и command graph; configured path за границей root не читается.
- All real project quality gates, bundling and package inspection pass; final MVP gaps are either fixed in scope or recorded as blocker.

## Verification

- Полный набор фактически существующих `typecheck`, `lint`, unit/integration `test`, `build` и `package` commands.
- Изолированный Extension Host MVP smoke suite и inspection generated package archive.

## Deliverables

- Интеграционные tests/fixtures, minimum integration fixes, package evidence and updated development/release documentation.

## Implementation plan

Заполняется командой `STEP PLAN STEP-007`.

## Evidence

—

## Blocker / Failure reason

—
