# STEP Execution Groups

`executionGroups` — optional machine-readable dependency graph поверх обычного `Implementation plan`. Он не создаёт новый STEP lifecycle, новый CTS state или новый обязательный artifact layer.

Первая версия намеренно **не запускает parallel subagents автоматически**. Harness сначала валидирует dependency/conflict model; implementer исполняет groups последовательно в deterministic topological order.

## Когда создавать groups

Planner добавляет groups только если STEP достаточно крупный и независимые work streams можно описать без догадок. Для маленького STEP или неясного conflict boundary `executionGroups` нужно опустить.

## Schema

```json
{
  "implementationPlan": [
    {"title":"Backend","actions":["..."]},
    {"title":"UI","actions":["..."]},
    {"title":"Integration","actions":["..."]}
  ],
  "executionGroups": [
    {"id":"backend","title":"Backend contract","steps":[1],"dependsOn":[],"mutationPaths":["src/api"],"verificationResponsibilities":["Run API unit tests"],"parallel":true},
    {"id":"ui","title":"UI implementation","steps":[2],"dependsOn":[],"mutationPaths":["src/ui"],"verificationResponsibilities":["Run UI tests"],"parallel":true},
    {"id":"integration","title":"Integration","steps":[3],"dependsOn":["backend","ui"],"mutationPaths":["tests/integration"],"verificationResponsibilities":["Run integration suite"],"parallel":false}
  ],
  "verification": []
}
```

### Поля group

- `id` — stable ID внутри plan revision, формат `[a-z][a-z0-9-]{0,63}`;
- `title` — human-readable purpose;
- `steps[]` — 1-based номера `### N.` элементов canonical Implementation plan;
- `dependsOn[]` — hard dependencies по group ID;
- `mutationPaths[]` — non-empty repository-relative path prefixes, задающие exclusive mutation/conflict surface; glob syntax не поддерживается;
- `verificationResponsibilities[]` — non-empty group-local проверки/обязанности; они не заменяют canonical STEP `## Verification`;
- `parallel` — capability flag. `true` означает только потенциальную независимость при выполненных dependencies.

Если `executionGroups` заданы, **каждый** numbered implementation step обязан принадлежать ровно одной group. Частичный graph запрещён: sequential projection не имеет права терять работу.

## Canonical persistence

Semantic planner payload использует массив `executionGroups[]`. В STEP frontmatter Harness хранит ту же модель как restricted-YAML-compatible mapping `plan.execution_groups.<id>`, потому что canonical YAML subset намеренно запрещает list-of-maps.

Пример persisted формы:

```yaml
plan:
  execution_groups:
    backend:
      title: Backend contract
      steps:
        - 1
      dependsOn: []
      mutationPaths:
        - src/api
      verificationResponsibilities:
        - Run API unit tests
      parallel: true
```

CLI/PROJECT STATE обратно публикуют normalized list; storage encoding не является отдельной semantic schema.

`step-context.py` также публикует normalized groups в `step.plan.executionGroups`, поэтому implementer/reviewer получают group contract через canonical dispatcher handoff, а не повторно парсят frontmatter.

## Conflict safety

Harness отклоняет две независимые `parallel=true` groups, если их declared mutation prefixes пересекаются (`src/api` и `src/api/schema`, одинаковый path или `.`). Если одна group зависит от другой, overlap допустим: DAG уже запрещает их одновременное выполнение.

Разные filenames сами по себе не доказывают semantic independence. Planner должен ставить `parallel=true` только когда явный conflict boundary достаточен; при сомнении group остаётся `parallel=false`.

## Deterministic validation

Validator запрещает duplicate/invalid IDs, unknown/self dependencies, cycles, out-of-range/duplicate step refs, неполное покрытие plan, malformed mutation surface/responsibilities и overlap независимых parallel candidates.

## Projection и sequential execution

```bash
python3 .harness/tools/execution-groups.py STEP-024 --json
```

Result содержит `groups`, stable `topologicalOrder`, `dependencyLayers` и `parallelCandidates`.

Implementer v1 идёт **последовательно** по `topologicalOrder` и не начинает group до её `dependsOn`. Automatic multi-agent parallel execution — отдельный follow-up.

## Freshness

Canonical groups сохраняются в `plan.execution_groups` и входят в `plan_content_hash`. Изменение dependency graph, mutation surface, purpose или verification responsibilities делает Ready plan stale и требует нового planning review.

Для STEP без groups сохраняется прежняя hash semantics и sequential behavior.

## UI / Navigator

PROJECT STATE публикует `metadata.executionGroups`; клиент может показать group DAG, dependencies, mutation surface и parallel candidates, не вычисляя их из prose.
