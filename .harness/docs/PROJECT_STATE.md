# Project State API

`project-state.py` — read-only deterministic projection состояния Harness-проекта для UI, VSCode Navigator и других клиентов.

## Назначение

Tool собирает единый machine-readable snapshot из canonical repository artifacts:

- REQ;
- ADR;
- STEP;
- OQ;
- immutable implementation REVIEW;
- доступных repository skills.

Он **не вызывает LLM**, не изменяет repository и не определяет визуальный layout. Клиент получает данные и сам выбирает radial graph, dependency view, таблицу или другую визуализацию.

## Запуск

Из корня Harness-проекта:

```bash
python3 .harness/tools/project-state.py --json
```

Для тестов/интеграций можно явно передать root:

```bash
python3 .harness/tools/project-state.py --root /path/to/project --json
```

Без `--json` выводится короткая человекочитаемая сводка.

## Контракт JSON

Корневые поля schema v1:

- `schemaVersion` — версия API;
- `status` — удалось ли построить snapshot; успешный результат имеет `PASS`;
- `integrity` — `ok` или `degraded`; degraded означает, что snapshot построен, но обнаружены проблемы связности/истории;
- `project` — имя, initialized-state и версия Harness;
- `summary` — агрегаты;
- `graph.nodes` — узлы;
- `graph.edges` — нормализованные связи;
- `insights` — вычислимые blockers/coverage/dependency facts;
- `diagnostics` — machine-readable anomalies;
- `sources` — manifest-resolved canonical directories.

### summary

`summary.artifacts` считает canonical project artifacts REQ/ADR/STEP/OQ. REVIEW history и skills вынесены отдельно в `summary.reviews` и `summary.skills`, чтобы protocol infrastructure не раздувал счётчик проектных артефактов.

Также доступны:

- `relationships`;
- `byType`;
- `byStatus`;
- `blockers`;
- `missingReferences`;
- `invalidReviews`;
- `relationshipCoveragePercent`.

### nodes

Узел имеет стабильный `id`, `type`, `title`, `status`, canonical `path` и небольшой `metadata` object.

Типы schema v1:

- `PROJECT`;
- `REQ`;
- `ADR`;
- `STEP`;
- `OQ`;
- `REVIEW`;
- `SKILL`;
- `MISSING` — synthetic node для битой ссылки.

REQ lifecycle status выводится детерминированно из связанных STEP и completion proof, а не придумывается клиентом.

Для STEP node `metadata.executionGroups` содержит canonical optional execution-group DAG текущего plan: IDs, `steps`, `dependsOn`, declared `mutationPaths`, `verificationResponsibilities` и `parallel`. Клиент не должен восстанавливать group graph из prose Implementation plan.

Evolution/freshness metadata для STEP:

- `planFreshness: fresh | stale | not_ready | blocked | invalid`;
- `planStaleCauses[]` — deterministic component causes из того же planning context, например `REQ@REQ-007 changed`;
- `planRemediation` — exact next action, обычно `STEP PLAN STEP-NNN`.

Эти поля объясняют staleness, но не меняют lifecycle STEP и не создают отдельный state machine.

### edges

Связи нормализованы независимо от того, с какой стороны artifact их объявил:

- `implemented_by`: REQ → STEP;
- `addresses`: ADR → REQ;
- `governs`: ADR → STEP;
- `depends_on`: STEP → STEP dependency;
- `affects`: OQ → target;
- `reviews`: REVIEW → STEP.

`declaredBy` показывает, какие canonical artifacts объявили связь. Если reciprocal metadata существует с обеих сторон, остаётся один edge с двумя declarations.

## Диагностика

Битая ссылка не исчезает из графа. Tool создаёт `MISSING:<ID>` node и добавляет `MISSING_REFERENCE` diagnostic, поэтому Navigator может визуально показать разрыв.

Malformed canonical Markdown/frontmatter блокирует построение snapshot и возвращает:

```json
{"schemaVersion":1,"status":"BLOCKED","error":"..."}
```

Невалидный immutable review не становится REVIEW node, но отражается в `diagnostics` и переводит `integrity` в `degraded`.

## Dependency analytics

Tool вычисляет только факты, для которых не требуется semantic judgement:

- dependency cycles;
- самую длинную STEP dependency-chain;
- downstream impact заблокированного STEP;
- requirements без implementing STEP;
- isolated core artifacts;
- relationship coverage.

Поле `longestChain` намеренно не называется «critical path»: без duration/schedule данных это была бы неверная семантика.

## Интеграция с Navigator

Рекомендуемый flow:

```text
repository
  ↓
project-state.py --json
  ↓
parse schemaVersion
  ↓
client-side graph/layout
  ↓
filters / selection / navigation
```

Navigator не должен повторно парсить REQ/ADR/STEP/OQ для построения обзорного графа. Canonical parsing и нормализация связей принадлежат Harness tool.

Schema v1 не содержит timestamp генерации: одинаковое repository state даёт стабильный payload, удобный для cache/diff.
