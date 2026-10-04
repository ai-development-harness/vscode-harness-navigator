---
schema: 1
id: REQ-011
priority: high
source: brief
steps:
  - STEP-018
  - STEP-019
adrs:
  - ADR-008
---

# REQ-011 — Граф зависимостей из Project State API

## Requirement

Navigator должен показывать интерактивный read-only граф связей Harness-проекта только из локального deterministic Project State API Harness 0.10.3+ и предоставлять безопасную навигацию по его canonical данным.

## Rationale

Разработчику нужен единый обзор зависимостей, lifecycle facts и нарушенных ссылок без дублирования parser, normalization и analytics Harness в extension.

## Acceptance

- `Harness: Show Dependency Graph`, Harness View и `Show in Dependency Graph` для STEP/REQ/ADR/OQ открывают полный graph; context action фокусирует выбранный artifact.
- Extension Host без shell получает `.harness/tools/project-state.py --json`, валидирует schemaVersion 1 tolerant к неизвестным optional fields и передаёт WebView только typed presentation model. WebView не читает workspace, не запускает процессы, не парсит artifacts и не получает произвольный Extension Host API.
- Graph представляет PROJECT, REQ, ADR, STEP, OQ, REVIEW, SKILL и MISSING; canonical relations `implemented_by`, `addresses`, `governs`, `depends_on`, `affects`, `reviews`, provenance `declaredBy`, MISSING nodes и diagnostics без создания reciprocal duplicates.
- Graph показывает ordinary artifacts, blocked STEP, MISSING nodes, selection, relations и members dependency cycles с VS Code theme variables; поддерживает node/details selection, open canonical artifact, related-node selection, full-graph return, fit-to-viewport, filters node type/status/relation type и режим `STEP dependencies` только с STEP/`depends_on`.
- Details STEP показывает предоставленные API status, priority, phase, plan freshness, stale causes, remediation command, REQ/ADR, dependencies и downstream impact. `insights.dependency.longestChain` называется только `Longest dependency chain` / `Самая длинная цепочка зависимостей`; Navigator не выводит Critical Path, lifecycle, blockers или следующий STEP самостоятельно.
- `integrity: degraded` отображается вместе с diagnostics и не блокирует graph. `BLOCKED`, malformed JSON, unsupported schema, timeout, oversized output, missing Python/tool или process error отображают localized Project State error без ArtifactIndex fallback.
- В untrusted workspace API не запускается. Для trusted root invocation имеет fixed executable/argv, canonical cwd, timeout, stdout/stderr limits, cancellation и cleanup child process on deactivation; concurrent process на один root не допускается.
- Snapshot cache, explicit refresh, invalidation, debounce и stale-request cancellation изолированы per workspace root; file changes корректно обновляют graph без restart. Работа остаётся offline и локализованной RU/EN.
- Unit и Extension Host integration tests покрывают process boundary, schema/graph semantics, errors, filters, STEP mode, multi-root, command/context opening, refresh, degraded/MISSING/cycles/BLOCKED, Workspace Trust и RU/EN.
