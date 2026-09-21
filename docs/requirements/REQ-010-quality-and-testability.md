---
schema: 1
id: REQ-010
priority: high
source: brief
steps:
  - STEP-001
  - STEP-007
adrs:
  - ADR-002
  - ADR-004
---

# REQ-010 — Качество реализации и проверяемость

## Requirement

Расширение должно иметь strict TypeScript toolchain и tests, доказывающие parsing/indexing business logic и основные интеграции с VS Code.

## Rationale

Функции навигации и обработки файлов чувствительны к вариантам Harness-документов, поэтому проверяемые контракты необходимы до release.

## Acceptance

- Проект использует strict TypeScript, официальный VS Code Extension API, YAML parser, Yarn, production bundling, ESLint и Prettier с реальными scripts проверки.
- Unit tests покрывают manifest/project detection, artifact/reference indexes, relation indexing, sorting/filtering, requirements status, aware-file classification, completion, reference detection, command graph/catalog и locale-independent logic.
- Integration tests покрывают detection states, views, providers, copy command, diagnostics, watchers, command graph watcher и RU/EN localization.
- Проверки не утверждают реализацию только через mocks helpers вместо наблюдаемого поведения providers и views.
