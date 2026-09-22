---
schema: 1
id: REQ-008
priority: medium
source: brief
steps:
  - STEP-001
  - STEP-002
  - STEP-003
  - STEP-004
  - STEP-005
  - STEP-006
  - STEP-007
  - STEP-008
adrs:
  - ADR-004
---

# REQ-008 — Локализация и диагностируемая деградация

## Requirement

Все пользовательские элементы расширения должны быть доступны на русском и английском, а errors должны быть классифицированы и безопасно отражены в VS Code.

## Rationale

Понятные localized states позволяют различать нормальное отсутствие данных, recoverable document issue и blocker проекта, не скрывая проблему и не ломая Extension Host.

## Acceptance

- Локализованы views, commands, menus, notifications, errors, empty states, placeholders, diagnostics, tooltips, settings и descriptions; fallback locale — English.
- Canonical IDs, enums, filenames, API keys и Harness-команды не локализуются, а business logic работает независимо от locale.
- Recoverable artifact problems не отключают другие корректные функции, а project-level blocker не допускает индексацию на предположениях.
- Минимальная стабильная taxonomy включает `NotHarnessProject`, `InvalidManifest`, `UnsupportedHarnessVersion`, `UnsupportedSchema`, `ArtifactDirectoryMissing`, `ArtifactParseError`, `DuplicateArtifactId`, `InvalidArtifactReference`, `ProjectionReadError`, `CommandGraphReadError`, `CommandGraphUnsupportedSchema` и `UnexpectedInternalError`.
- `Harness: Show Diagnostics` показывает пользователю технические details текущего состояния; необработанные исключения не ломают Extension Host, а технические сведения также доступны через Output Channel `Harness Navigator`.
