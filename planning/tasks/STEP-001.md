---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: high
phase: foundation
depends_on: []
requirements:
  - REQ-001
  - REQ-008
  - REQ-010
adrs:
  - ADR-001
  - ADR-004
architecture_refs:
  - "docs/architecture.md#system-context"
  - "docs/architecture.md#deployment-runtime-assumptions"
risk_flags:
  - architecture
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — Базовый каркас расширения и toolchain

## Goal

Создать минимальный production-ready каркас TypeScript VS Code extension с локализацией и проверяемым toolchain без реализации product-функций Navigator.

## Context

В репозитории отсутствует application code и package tooling. Последующие STEP нуждаются в общей extension lifecycle, localization boundary и реальных commands для проверки.

## Scope

- Настроить Yarn-проект, strict TypeScript, официальный VS Code Extension API, production bundling, ESLint и Prettier.
- Создать минимальную activation/deactivation основу, disposable lifecycle и RU/EN localization resources.
- Настроить unit и integration test foundations с реальными scripts lint, typecheck, test, build и package.

## Mutation policy

### Allowed

- Новые source, test, configuration и package files расширения.
- Документация разработки, необходимая фактическому toolchain.

### Conditional

- Минимальные dependencies только после проверки их необходимости для VS Code API, YAML parsing, bundling или tests.

### Forbidden

- Реализация artifact parsing, command catalog, navigation providers или выполнение Harness-команд.
- Сетевые, telemetry, shell или persistent project-state integrations.

## Out of scope

- Полные Views, индексы и language providers.
- Product-specific CI beyond commands, которые реально создаёт этот STEP.

## Acceptance criteria

- TypeScript compile работает в strict mode, а package содержит production bundling, ESLint, Prettier и Yarn scripts для typecheck, lint, test, build и package.
- Extension корректно активируется и освобождает registrations без реализации command execution Harness.
- Пользовательские strings имеют RU и EN resources с English fallback; canonical Harness tokens не локализуются.
- Unit и integration test foundations запускаются реальными project scripts.

## Verification

- Реальные scripts `typecheck`, `lint`, `test`, `build` и `package`, созданные в этом STEP.
- Изолированная проверка Extension Host после появления integration harness.

## Deliverables

- VS Code extension manifest, TypeScript source skeleton, localization resources, test configuration и development documentation.

## Implementation plan

Заполняется командой `STEP PLAN STEP-001`.

## Evidence

—

## Blocker / Failure reason

—
