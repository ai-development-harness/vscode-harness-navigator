---
schema: 1
id: REQ-004
priority: high
source: brief
steps:
  - STEP-004
  - STEP-007
adrs:
  - ADR-004
---

# REQ-004 — Нативные views артефактов и фокуса

## Requirement

Расширение должно предоставить нативные Tree Views для Harness Artifacts и Harness Focus с управлением сортировкой, фильтрацией и открытием canonical Markdown-файлов.

## Rationale

Разработчику нужен быстрый обзор артефактов и того, что требует внимания, без WebView и ручного поиска по каталогам.

## Acceptance

- Artifacts View показывает группы STEP, REQ, ADR, OQ и для каждого элемента ID, title и status через стандартные VS Code Tree View API.
- Доступны независимые sort order по предусмотренным полям, фильтрация по status/type/priority и phase для STEP, а также clear filters; настройки сохраняются в workspace settings.
- Click и context actions открывают или раскрывают canonical файл и позволяют скопировать ID либо relative path.
- `Harness: Go to Artifact` открывает Quick Pick со всеми известными STEP, REQ, ADR и OQ, fuzzy-ищет по ID, title и kind и открывает выбранный canonical Markdown-файл.
- Focus View показывает активные, заблокированные STEP и открытые OQ, но не назначает следующий STEP.
