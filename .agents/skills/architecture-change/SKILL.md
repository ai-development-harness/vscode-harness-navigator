---
name: architecture-change
description: Evaluate whether a change requires an ADR and safely evolve durable architecture contracts without rewriting history.
---
# architecture-change

Применяй, когда STEP имеет `architecture`/`public-api`/major data boundary или planner выявил durable decision. Сначала проверь существующие Accepted ADR. Если контракт меняется — новый ADR с Context/Problem/Decision/Alternatives/Consequences/security/data/compatibility и `Supersedes`. Не создавай ADR для локальной implementation detail. Не переписывай старый Accepted ADR.
