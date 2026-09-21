---
schema: 1
id: STEP-003
status: planned
type: implementation
priority: high
phase: project-model
depends_on:
  - STEP-002
requirements:
  - REQ-001
  - REQ-003
  - REQ-008
  - REQ-009
adrs:
  - ADR-001
  - ADR-002
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

# STEP-003 — Парсинг артефактов и общие индексы

## Goal

Построить read-only parsing STEP, REQ, ADR и OQ, requirements status reader, Artifact Index и Reference Index с инкрементальным обновлением.

## Context

Все UI и navigation consumers должны получать один согласованный project model. Ошибочный документ не должен блокировать корректные артефакты, а manifest blocker уже изолирован STEP-002.

## Scope

- Typed parsers canonical artifacts и requirements status projection.
- Artifact Index с metadata, status и relations; Reference Index для Harness-aware files.
- Classifier точной области Harness-aware files и FileSystemWatcher invalidation/update paths.
- Diagnostics classification для recoverable artifact errors.
- Producer categories `ArtifactDirectoryMissing`, `ArtifactParseError`, `DuplicateArtifactId`, `InvalidArtifactReference` и `ProjectionReadError` для общего diagnostics flow.
- Command `Harness: Refresh` для controlled rebuild derived state текущего workspace без canonical mutation.
- Unit tests parsing, indexes, relations, status reader, aware-file classifier и incremental update.

## Mutation policy

### Allowed

- Source и tests parser/index/watcher/diagnostics layers.
- Локальные derived in-memory structures Extension Host.

### Conditional

- Минимальные shared types или activation registration, необходимые index lifecycle.

### Forbidden

- Persistent cache в workspace, изменение canonical Harness files или повторный full scan на каждый provider lookup.
- Views, command catalog и navigation UI beyond interfaces, нужные индексам.

## Out of scope

- Tree/Quick Pick presentation и command graph parsing.
- Реализация specific definition/hover/completion/reference providers.

## Acceptance criteria

- Корректные configured STEP, REQ, ADR и OQ представлены одним Artifact Index с ID, title, kind, status, file, metadata и relations.
- REQ lifecycle берётся из requirements status projection; отсутствие artifacts остаётся normal empty state.
- Reference Index и classifier покрывают ровно canonical artifacts, configured projections, project knowledge/planning Markdown, `.harness/**/*.md` и additional Markdown внутри Harness workspace, исключая Markdown вне него.
- Duplicate IDs, parse errors, invalid H1, identity mismatch и invalid reference диагностируются, не ломая корректные artifacts.
- Watcher инкрементально обновляет затронутые derived data без обхода `node_modules`.
- `Harness: Refresh` восстанавливает derived state после пропущенного watcher event без изменения Harness files.

## Verification

- Реальные `typecheck`, `lint` и targeted unit tests parser/index/watcher.
- Integration scenario: изменение одного artifact обновляет индекс без перезапуска Extension Host.
- Targeted tests refresh command и stable artifact/projection diagnostics categories.

## Deliverables

- Artifact parsers, status reader, Artifact/Reference Indexes, classifier, watcher core, diagnostics core и tests.

## Implementation plan

Заполняется командой `STEP PLAN STEP-003`.

## Evidence

—

## Blocker / Failure reason

—
