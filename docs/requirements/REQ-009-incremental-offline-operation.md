---
schema: 1
id: REQ-009
priority: medium
source: brief
steps:
  - STEP-003
  - STEP-007
  - STEP-018
adrs:
  - ADR-002
  - ADR-004
  - ADR-008
---

# REQ-009 — Incremental и offline работа

## Requirement

Расширение должно работать offline и инкрементально обновлять derived state после изменений workspace без ненужного повторного обхода.

## Rationale

Интерактивные hover, completion и reference lookup должны оставаться быстрыми даже в крупных репозиториях, не добавляя external dependencies.

## Acceptance

- Runtime не выполняет network requests, telemetry, Git history, shell, Harness commands или произвольные Harness tools и не требует GitHub authentication; локальный Project State API допускается только как ограниченное ADR-008 исключение.
- FileSystemWatcher обновляет затронутые artifacts, projections, manifest, Harness-aware files и command graph без перезапуска Extension Host.
- `Harness: Refresh` вручную перезагружает derived state текущего Harness workspace после missed или failed watcher event без mutation canonical files.
- `node_modules` не обходится; hover, completion и references используют in-memory indexes вместо повторного scanning workspace.
- Status Bar и summary отражают derived counts и открывают Harness View, не создавая отдельный dashboard WebView.
- Project State snapshot кэшируется и обновляется по explicit refresh или контролируемому watcher/debounce событию; UI events не запускают tool повторно.
