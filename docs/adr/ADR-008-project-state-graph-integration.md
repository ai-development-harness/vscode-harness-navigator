---
schema: 1
id: ADR-008
status: accepted
date: 2026-10-03
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-001
  - REQ-002
  - REQ-004
  - REQ-008
  - REQ-009
  - REQ-011
steps:
  - STEP-018
---

# ADR-008 — Узкая интеграция Project State API и dependency Graph

## Context

ADR-001 и ADR-004 закрепили read-only Navigator без process execution и WebView. Harness 0.10.3+ предоставляет deterministic Project State API как canonical summary, graph и insights, а интерактивный dependency graph требует presentation, которую Tree View не покрывает.

## Problem

Нужно получить graph без второго parser/analytics контура и не превратить Navigator в Harness runtime или универсальный executor repository tools.

## Decision

Для trusted Harness 0.10.3+ workspace Extension Host может запускать только fixed `.harness/tools/project-state.py --json` без shell, с canonical root cwd, bounded output, timeout, cancellation и lifecycle cleanup. Он валидирует schemaVersion 1 tolerant к новым optional fields, создаёт typed presentation model и передаёт его изолированному theme-aware WebView dependency graph.

Это узкое дополнение к ADR-001 и ADR-004, а не их полное supersession: mutation Harness artifacts, network, telemetry, commands, dispatcher, agents, terminal и произвольные `.harness/tools/*.py` остаются запрещены. WebView не имеет filesystem/process access, не парсит artifacts и не вычисляет canonical semantics. ArtifactIndex не является fallback для graph.

## Alternatives considered

### Повторный parser и graph analytics в Navigator

Отклонено: он расходится с protocol state и повторно реализует lifecycle, relations и dependency analysis Harness.

### Нативный Tree View вместо graph

Отклонено: Tree View не обеспечивает layout, интерактивные edges, selection/focus и graph filters требуемого flow.

### Произвольный launcher Harness tools

Отклонено: это нарушает read-only navigation boundary и открывает недопустимую trust boundary.

## Consequences

Минимальная совместимая версия Harness повышается до 0.10.3. Project State API becomes the only canonical graph source; unavailable or invalid API yields diagnostics, not legacy behavior. Snapshot state and process ownership are isolated per workspace root.

## Security implications

Repository-provided Python runs only in trusted workspace and only through the fixed non-shell entry point. User-controlled text is never interpolated into command execution. Output is treated as untrusted data, size-bounded and fail-safe parsed; WebView receives presentation data only.

## Data / migration implications

Migration project data отсутствует. Navigator не пишет artifacts или persistent graph state.

## Compatibility / operational implications

Harness 0.6.x–0.10.2 становится unsupported. `integrity: degraded` остаётся отображаемым state; MISSING references и API diagnostics сохраняют provenance вместо скрытия проблем.
