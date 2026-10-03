---
name: architecture-change
description: Decide whether a durable technical change requires an ADR, evolve accepted architecture through explicit superseding decisions, and avoid recording local implementation details as architecture.
---
# architecture-change

Используй, когда STEP/planner затрагивает устойчивое техническое решение, которое должно пережить текущую реализацию.

## Когда ADR обычно нужен

Сначала проверь существующие Accepted ADR и architecture baseline. Новый/заменяющий ADR обычно нужен, если меняется один из durable contracts:

- public API или межмодульный/integration contract;
- persistent data/schema/storage model;
- security/trust/permission boundary;
- ownership/responsibility между подсистемами;
- runtime/deployment/infrastructure boundary;
- dependency/technology choice с существенными долгосрочными последствиями;
- решение, которое дорого или рискованно менять после реализации.

Локальный refactor, имя функции, внутренний helper, очевидная implementation detail или механическая перестановка сами по себе ADR не требуют.

## Эволюция решения

Если Accepted ADR остаётся применим — ссылайся на него, не создавай дубликат.

Если durable contract меняется:

1. не переписывай старый Accepted ADR;
2. создай новый ADR с Context/Problem/Decision/Alternatives/Consequences и релевантными security/data/compatibility implications;
3. явно укажи `Supersedes`/связь со старым решением;
4. обнови traceability с затронутыми STEP/REQ;
5. если решение ещё не принято и без него нельзя планировать/реализовывать — оставь работу BLOCKED через OQ/RESEARCH/ADR prerequisite, а не угадывай архитектуру внутри implementation.
