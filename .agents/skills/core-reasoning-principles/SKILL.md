---
name: core-reasoning-principles
description: Route only applicable Harness-owned CRP leaves from the Context Contract; keep them separate from project-owned PRN engineering principles.
---
# core-reasoning-principles

Это internal routing capability, не пользовательская команда.

## Namespace boundary

- `CRP-NNN` — Harness-owned **Core Reasoning Principle**: как агент должен рассуждать/организовывать работу.
- `PRN-NNN` — project-owned **Project Principle**: инженерный инвариант конкретного проекта.

CRP не входит в project traceability, не stale-ит Ready plan как PRN и не может заменить REQ/ADR/PRN.

## Progressive disclosure

Canonical dispatcher/context resolver уже возвращает:

```text
context.contextContract.coreReasoningPrinciples
```

Читай **только перечисленные leaf paths**. Не сканируй весь каталог `leaves/` и не загружай все CRP «на всякий случай».

Каждый leaf короткий и содержит:

- Trigger / applicability;
- Rationale;
- Actionable pattern.

Если CRP описывает правило, которое можно надёжно сделать deterministic validator/gate/tool, предпочитай structural enforcement. Prose principle не имеет права ослаблять existing deterministic policy.

## Runtime neutrality

Selection происходит до runtime adapter и зависит только от canonical STEP/Context facts. Codex/Claude получают один и тот же набор CRP для одинакового role/STEP/revision.
