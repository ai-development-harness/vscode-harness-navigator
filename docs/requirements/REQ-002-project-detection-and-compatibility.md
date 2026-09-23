---
schema: 1
id: REQ-002
priority: high
source: brief
steps:
  - STEP-002
  - STEP-007
  - STEP-008
  - STEP-009
adrs:
  - ADR-001
  - ADR-005
  - ADR-006
  - ADR-007
---

# REQ-002 — Определение Harness-проекта и совместимость

## Requirement

Расширение должно независимо определять состояние каждого workspace root по `.harness/manifest.yaml`, поддерживать Harness 0.6.0+ и получать все artifact paths из manifest.

## Rationale

Workspace может не быть Harness-проектом, быть повреждённым или состоять из нескольких roots с разными releases; безопасное различение состояний необходимо до чтения артефактов.

## Acceptance

- Обычная папка, повреждённый manifest, неподдерживаемый release, неподдерживаемая schema и корректный пустой Harness-проект представлены разными понятными состояниями.
- Версия ниже 0.6.0 не использует legacy parsing, миграцию или обновление и показывает обнаруженную и минимальную версии.
- `protocol.taskDirectory` и все используемые `sources.*` paths читаются из manifest без hardcoded fallback.
- Каждый configured path разрешается относительно owning workspace root и до доступа проходит containment check после resolution; absolute, traversal или symlink path за пределами root не читается и даёт configuration blocker.
- В multi-root workspace каждый root обрабатывается изолированно.
