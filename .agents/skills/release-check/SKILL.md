---
name: release-check
description: Run a project-specific production/release readiness gate and persist blockers/evidence in a release report.
---
# release-check

Используй для `RELEASE CHECK`. Human-readable release-check report пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; release notes как отдельный артефакт используют `language.releaseNotes`. Определи фактическую release model из repo. Проверь unresolved critical/high findings, release-critical REQ/STEP, actual build/test/type/lint/package/deploy gates, migrations/upgrades/rollback, security and docs/release notes where applicable. Создай schema-v1 report `RELEASE-YYYYMMDDTHHMMSSZ.md` в configured `protocol.releaseDirectory`. Verdict READY/BLOCKED. До завершения проверь конкретный файл через `python3 .harness/tools/report_contract.py --file '<report-path>' --kind release_check`. Не выдумывай gates, которых нет в проекте.
