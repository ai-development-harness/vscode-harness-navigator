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

Если причина текущего решения неочевидна, Accepted ADR может быть stale, либо есть competing explanations из code/history — до выбора нового architecture direction вызови внутренний read-only capability `decision-archaeology` на конкретном target path. Он обязан отделить documented rationale от inference, сохранить conflicts/gaps и вернуть bounded evidence map. Conversation/session memory не является historical evidence. Validated findings преврати в `Preserve / Change / Avoid / Risk` constraints; unresolved historical ambiguity => OQ/RESEARCH/BLOCKED, а не догадка.

## Эволюция решения

Если Accepted ADR остаётся применим — ссылайся на него, не создавай дубликат.

Для крупного/дорогого architecture choice проверь optional Arena через `python3 .harness/tools/high-rigor.py --mode arena --phase architecture [--step STEP-NNN] --json`. При `RUN` candidates получают один exact decision contract/rubric, отдельный judge выбирает base, а synthesis сохраняет disagreements. Arena не принимает ADR сама и не заменяет Decision Archaeology/Semantic Blast Radius. `DEGRADED` раскрывай как недополученный дополнительный quality signal, а не как blocker/approval сам по себе.

Если durable contract меняется, сначала используй deterministic blast-radius preflight текущего STEP (если STEP context доступен). При material risk flags Semantic Blast Radius обязателен до утверждения safety/compatibility claim: explicit linked impact остаётся за impact-analysis, implicit consumers/contracts — hypotheses с evidence/proof. Неподтверждённый critical assumption не маскируй ADR prose.

Если durable contract меняется:

1. не переписывай старый Accepted ADR;
2. создай новый ADR с Context/Problem/Decision/Alternatives/Consequences и релевантными security/data/compatibility implications;
3. явно укажи `Supersedes`/связь со старым решением;
4. обнови traceability с затронутыми STEP/REQ;
5. если решение ещё не принято и без него нельзя планировать/реализовывать — оставь работу BLOCKED через OQ/RESEARCH/ADR prerequisite, а не угадывай архитектуру внутри implementation.
