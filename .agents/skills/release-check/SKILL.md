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

Создай schema-v1 report `RELEASE-YYYYMMDDTHHMMSSZ.md` в configured `protocol.releaseDirectory`. В report явно свяжи verdict с фактическими gates/evidence и перечисли blockers с required next action.

До завершения проверь конкретный файл:

```bash
python3 .harness/tools/report_contract.py --file '<report-path>' --kind release_check
```
