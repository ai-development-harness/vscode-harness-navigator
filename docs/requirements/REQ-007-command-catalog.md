---
schema: 1
id: REQ-007
priority: high
source: brief
steps:
  - STEP-006
  - STEP-007
  - STEP-015
adrs:
  - ADR-003
  - ADR-004
---

# REQ-007 — Read-only каталог Harness-команд

## Requirement

Расширение должно отображать и искать полный read-only каталог canonical Harness-команд из текущего command graph, объяснять команды и позволять скопировать их текст.

## Rationale

Справка должна следовать реальному protocol surface после обновления Harness и не должна быть command launcher.

## Acceptance

- Command Catalog строится из `.harness/command-transitions.json`, отображает известные и будущие команды поддерживаемой schema и группирует их по domain.
- Commands View и Find Command используют canonical syntax, локализованное краткое description/fallback и graph metadata в tooltip.
- Copy Command копирует template с корректными placeholder; из context конкретного STEP допускается фактический STEP ID.
- Изменение command graph обновляет каталог без перезапуска Extension Host; schema error не ломает Artifact Navigator.
