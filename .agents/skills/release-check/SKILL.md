---
name: release-check
description: Evaluate the repository's actual release model, execute only real project readiness gates, and persist a READY/BLOCKED report backed by evidence.
---
# release-check

Используй для `RELEASE CHECK`.

Human-readable release-check report пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; release notes как отдельный артефакт используют `language.releaseNotes`.

## Release model

1. Сначала определи фактическую release model из repository: package/build/deploy artifacts, CI, environments, migrations, versioning, rollback/update mechanics и release documentation.
2. Не выдумывай обязательные gates, которых в проекте нет, и не считай optional tooling mandatory только потому, что оно типично для похожих проектов.
3. Получи `python3 .harness/tools/traceability-coverage.py --json` и используй `releaseRelevant` REQ как deterministic coverage input для фактического release scope. Затем проверь unresolved critical/high findings, release-critical REQ/STEP, applicable active Project Principles, actual build/test/type/lint/package/deploy gates, migrations/upgrades/rollback, security и docs/release notes там, где они реально применимы. Release-relevant uncovered/stale evidence и unresolved applicable `blocking` PRN блокируют release; `advisory` PRN сам по себе не является release blocker.

## Verdict

- `READY` допустим только если все **реально обязательные** release gates, найденные в repository/policy, выполнены и имеют достаточное evidence.
- `BLOCKED` — есть failed mandatory gate, unresolved release-critical blocker либо обязательный gate нельзя доказать имеющимся evidence.
- Не подменяй неизвестный/непроверенный обязательный gate предположением о PASS.
- Не блокируй release за отсутствие несуществующего project gate.

## Report

Подготовь semantic JSON: `target` (точный `TO <tag>`, если указан), `verdict: "ready"|"blocked"` и sections из configured `protocol.releaseDirectory/TEMPLATE.md`. Не конструируй самостоятельно YAML, H1, UTC или имя `RELEASE-<UTC>.md`. Правила и пример: `.harness/docs/REPORTING.md`.

```bash
python3 .harness/tools/semantic-writer.py release-report --execution-id '<executionId>' --payload-file '<local-json-or->'
```

Только writer `PASS` разрешает предложить `complete SUCCESS`: dispatcher перепроверит отчёт текущей execution. **`verdict: blocked` означает реальную неготовность релиза, но может быть корректным завершённым отчётом проверки**; это не технический failure writer. При неверной schema/непроверенных данных сообщи `BLOCKED`, не выдумывай READY.
