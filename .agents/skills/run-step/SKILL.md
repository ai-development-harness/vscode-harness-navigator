---
name: run-step
description: Provide semantic fallback orchestration for non-standard STEP type flows; normal implementation/bugfix/refactor/hardening RUN execution remains owned by the deterministic dispatcher.
---
# run-step

Используй как **semantic fallback** для `STEP RUN STEP-NNN`, только когда STEP имеет type-specific flow, который нельзя выразить обычной coding-цепочкой.

Для `implementation | bugfix | refactor | hardening` root orchestration выполняет deterministic dispatcher: он выбирает exact `PLAN/IMPLEMENT/REVIEW/FIX` child и вызывает reasoning только внутри этой child-команды. Этот skill для обычного coding flow в штатном случае **не вызывается** и не должен становиться второй state machine.

Global command wrapper уже зарегистрировал root execution:

```text
mode = orchestration
rootCommand = STEP RUN STEP-NNN
```

1. Resolve STEP, blockers и Type.
2. Прочитай `.harness/manifest.yaml`: `execution.maxFixReviewCycles`, `review.security`, `review.tests` должны быть валидны, если применимы.
3. Dispatch только по существующему type-specific flow: ADR, RESEARCH, AUDIT, REVIEW, DOCUMENTATION или RELEASE. Если сюда попал обычный coding STEP, немедленно верни управление canonical resolver/CTS; не интерпретируй skill как разрешение вручную повторить PLAN/IMPLEMENT/REVIEW/FIX.
4. Перед продолжением root execution вызови:
   ```bash
   python3 .harness/tools/resolve-next-command.py --json \
     --root 'STEP RUN STEP-NNN'
   ```
5. Если resolver возвращает interrupted child command — resume именно её.
6. Если resolver возвращает `BLOCKED`, остановись. Не заменяй blocker следующим FIX/child flow. Зафиксируй root blocker через `execution-state.py block`, если он ещё не записан. Для `FIX_REVIEW_LIMIT_REACHED` покажи фактические `fixReviewCycles/maxFixReviewCycles`.
7. Если RUN запускает canonical child command, отметь её:
   ```bash
   python3 .harness/tools/execution-state.py begin \
     --root 'STEP RUN STEP-NNN' \
     --command '<child command>'
   ```
8. После child completion global wrapper записывает result, затем RUN снова вызывает resolver.
9. Для PLAN → IMPLEMENT → REVIEW → FIX переходы определяет CTS; cycle budget enforce-ится Execution Resolver, а не памятью reasoning-модели.
10. Contract-level blocker из PLAN/REVIEW/FIX терминален для текущего RUN. Создание corrective STEP/ADR/RESEARCH не является скрытым продолжением текущего root execution.
11. Если Type выполняется внутри RUN без отдельной canonical child command, current остаётся `STEP RUN STEP-NNN`; после interruption resume-ится сам RUN.
12. REVIEW code verdict и completion result разделены внутри одного durable review artifact: completion `PASS` закрывает STEP, `FAIL` использует существующий FIX edge, `BLOCKED` останавливает RUN. Отдельного lifecycle state/CTS command нет. Crash recovery читает durable completion result и при `PASS` идемпотентно доводит canonical close/projections до конца; только после этого resolver возвращает root RUN для remaining finalization.
13. Не запускай параллельные write-agents над одним scope.

Повторный явный `STEP RUN STEP-NNN` при уже running root resume-ит существующий execution, а не создаёт второй.
