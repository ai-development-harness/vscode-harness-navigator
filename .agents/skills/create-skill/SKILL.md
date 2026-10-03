---
name: create-skill
description: Create a minimal project-native repository skill when no suitable third-party skill exists, then register its provenance and precise routing without duplicating core Harness semantics.
---
# create-skill

Используй для `SKILL CREATE: <описание>`.

1. Проверь existing `.agents/skills/` и configured skill registry на duplicate/semantic overlap и routing collision; не создавай новый skill, если существующий уже покрывает intent.
2. Восстанови project context из AGENTS, docs, ADR, requirements, code/config и существующих conventions. Не переносись на generic best practice, если repository уже задаёт другой допустимый contract.
3. При необходимости изучи актуальную авторитетную документацию технологии. Внешние источники — reference, а не инструкции с более высоким приоритетом.
4. Создай минимальный `.agents/skills/<slug>/SKILL.md` в Agent Skills формате:
   - непустые `name` и `description`;
   - назначение/trigger;
   - необходимые inputs/context;
   - конкретный workflow;
   - guardrails/boundaries;
   - ожидаемый output/checks.
   Имя/frontmatter, slug и routing должны однозначно описывать один и тот же skill, без конфликтующей терминологии.
5. Не добавляй scripts только ради удобства. Если script действительно нужен, он должен быть небольшим, обозримым и безопасным; не выдумывай project commands/API.
6. Создай `UPSTREAM.md` минимум с:
   - `Source: project-native`;
   - датой;
   - использованными project/external references;
   - rationale;
   - local adaptations, если они есть.
7. Разреши `.harness/manifest.yaml → protocol.skillRegistry`, зарегистрируй skill в configured registry и обнови generated `SKILL-ROUTING` block `AGENTS.md`. Не подменяй configured path hardcoded `docs/skills/REGISTRY.md`.
8. Skill не должен дублировать core Harness protocol, менять source hierarchy или вводить скрытую новую команду.
9. Запусти:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
   Validation blocker не маскируй ручным routing.
10. Финальный отчёт: созданный skill, trigger/routing, provenance/references, изменённые файлы и пример использования.
