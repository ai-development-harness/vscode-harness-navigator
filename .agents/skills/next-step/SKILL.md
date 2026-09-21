---
name: next-step
description: Select the next executable project action using dependencies, task state, priority, risk and critical path.
---
# next-step

Используй для `STEP NEXT`. Read-only.

Сначала выполни:

```bash
python3 .harness/tools/resolve-next-command.py --json
```

Resolver возвращает все unresolved executions всех namespaces. Незавершённый STEP-related execution имеет приоритет над стартом нового STEP, но не блокирует явно запрошенные пользователем независимые Git/Project/Harness commands.

Если interrupted STEP execution один — верни его exact resolved command. Если их несколько — выбери один по dependencies/priority/risk/critical path и явно перечисли остальные как незавершённые.

Если STEP-related interrupted execution нет, применяй обычный selection: исключи blocked hard dependencies и completed/cancelled work, учитывай corrective prerequisites и фактическое состояние task.

Верни один основной выбор и точную canonical command.
