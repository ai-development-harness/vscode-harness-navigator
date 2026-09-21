---
schema: 1
id: REQ-005
priority: high
source: brief
steps:
  - STEP-005
  - STEP-007
adrs:
  - ADR-002
  - ADR-004
---

# REQ-005 — Навигация по Harness ID

## Requirement

Расширение должно распознавать существующие STEP, REQ, ADR и OQ ID в Harness-aware Markdown-файлах и предоставлять стандартные navigation-функции VS Code. Harness-aware file — canonical artifact, configured projection, Markdown в configured project knowledge/planning path, `.harness/**/*.md` или другой Markdown внутри того же Harness workspace; Markdown вне Harness workspace не получает Harness semantic functionality.

## Rationale

Harness ID должен восприниматься разработчиком как символ исходного кода: его можно открыть, исследовать и вставить без поиска файла вручную.

## Acceptance

- Definition, Peek Definition, Ctrl/Cmd+Click и document links открывают canonical artifact для известного ID.
- Hover локализованно показывает title и релевантные metadata; неизвестный ID не приводит к сбою.
- Completion по prefixes `STEP-`, `REQ-`, `ADR-`, `OQ-` фильтрует индекс, показывает ID/title/details и вставляет только canonical ID.
- ID подсвечиваются совместимо с темами VS Code без фиксированной палитры и не ухудшают Markdown highlighting.
- Navigation, completion, highlighting, references и diagnostics применяются только в определённой области Harness-aware files.
