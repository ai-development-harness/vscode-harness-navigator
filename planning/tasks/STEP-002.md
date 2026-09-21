---
schema: 1
id: STEP-002
status: planned
type: implementation
priority: high
phase: project-model
depends_on:
  - STEP-001
requirements:
  - REQ-001
  - REQ-002
  - REQ-008
adrs:
  - ADR-001
architecture_refs:
  - "docs/architecture.md#system-context"
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#security-boundaries"
risk_flags:
  - architecture
  - security-sensitive
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-002 — Определение проекта и чтение manifest

## Goal

Реализовать изолированное определение Harness workspace root, compatibility states и manifest-driven configuration.

## Context

Artifact parsing допустим только после доказуемого валидного manifest. При этом обычная папка, пустой проект и project-level incompatibility имеют разный UX.

## Scope

- Реализовать detection и manifest service для каждого workspace root.
- Проверить minimum release 0.6.0, поддерживаемую schema и configured paths.
- Implement containment validation для каждого resolved configured path относительно owning workspace root.
- Создать typed states для non-Harness, invalid, unsupported и valid empty project.
- Добавить command `Harness: Show Diagnostics` для details project detection state и стабильную taxonomy producer ошибок этого слоя.
- Покрыть detection и manifest cases tests.

## Mutation policy

### Allowed

- Source и tests слоя Harness detection/manifest.
- Локализованные messages и diagnostics, принадлежащие этому слою.

### Conditional

- Изменения базовой activation wiring, если это минимально нужно для регистрации project state.

### Forbidden

- Hardcoded fallback artifact paths, legacy parsing, auto migration/update Harness.
- Чтение за границами workspace по configured path, Git history, запуск tools Harness или mutation workspace.

## Out of scope

- Parsing STEP, REQ, ADR, OQ и построение views.
- Command graph и navigation providers.

## Acceptance criteria

- Каждый workspace root определяется по `.harness/manifest.yaml` и получает отдельное typed состояние.
- Версия ниже 0.6.0, malformed manifest и unsupported schema дают локализуемые диагностируемые состояния без legacy fallback.
- Все будущие artifact paths доступны только из успешно прочитанного manifest.
- Absolute, traversal и symlink configured path за пределами owning workspace root не читаются и формируют configuration blocker.
- `Harness: Show Diagnostics` раскрывает details detection/configuration state, используя stable categories этого слоя.
- Unit и integration tests наблюдаемо проверяют ordinary, invalid, unsupported и valid empty workspace.
- Tests проверяют containment для normal, absolute, traversal и symlink configured path.

## Verification

- Реальные `typecheck`, `lint` и targeted tests STEP-002.
- Extension Host integration scenario для нескольких workspace roots.
- Targeted containment and diagnostics command tests.

## Deliverables

- Detection/manifest services, project state model, localized diagnostics и tests.

## Implementation plan

Заполняется командой `STEP PLAN STEP-002`.

## Evidence

—

## Blocker / Failure reason

—
