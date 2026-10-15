---
name: reconcile-project
description: Idempotently migrate active project schema, detect repository-wide drift across code and canonical artifacts, and create corrective work without silently changing production code.
---
# reconcile-project

Используй для `PROJECT RECONCILE` после успешного `PROJECT INIT`.

Если `project.initialized=false`, обычный reconcile неприменим: handoff → `PROJECT INIT`. Исключение — pre-init legacy adoption прямо перед INIT, если update protocol явно требует schema migration.

## Schema migration first

После Harness update сначала детерминированно проверь active schema:

```bash
python3 .harness/tools/migrate-project-schema.py --check --json
```

Если `MIGRATION_REQUIRED`, выполни:

```bash
python3 .harness/tools/migrate-project-schema.py --json
```

Migration:

- идемпотентно переводит active STEP/REQ/ADR и canonical OQ на schema v1;
- мигрирует Accepted ADR как schema change без изменения решения;
- разбивает legacy monolithic requirements/OQ;
- не переписывает immutable historical review/audit reports; legacy review history hash-pin-ится migration report-ом, чтобы оставаться доверенным и обнаруживать последующую mutation;
- синхронизирует project-owned templates/projections;
- сохраняет versioned migration report в configured `protocol.auditDirectory`.

Старый Ready plan без durable planning-review мигрируется в draft и требует нового `STEP PLAN`.

## Reconcile

1. Сравни code/config/migrations/tests с canonical REQ, Accepted ADR, active Project Principles, architecture refs, STEP, evidence и schema-valid review reports. Цель — найти **repository-wide cross-artifact drift**, а не сравнивать разные repositories.
2. Для stale/changed contracts используй `python3 .harness/tools/impact-analysis.py --step STEP-NNN --json` или `--changed ARTIFACT-ID --json`; не пересчитывай staleness reasoning-ом.
3. Классифицируй найденное по canonical owner:
   - deterministic projection/command-syntax drift, который можно безопасно пересобрать;
   - substantive product/contract drift, требующий corrective STEP;
   - missing/obsolete architecture decision, требующий ADR/RESEARCH;
   - active blocking principle violation, malformed principle semantics или active reference на superseded/deprecated PRN;
   - evidence gap, который нельзя объявлять исправленным без соответствующей проверки.
4. Если material drift нельзя честно классифицировать без historical intent — например code расходится с Accepted ADR, но похоже на намеренную прошлую эволюцию — используй internal `decision-archaeology` на одном concrete target path. Canonical ADR/REQ/PRN/architecture evidence проверяй раньше Git/issues; conversation/transcript не используй. `possibly-stale` ADR — diagnostic finding, не permission переписать ADR. Ambiguous history => RESEARCH/OQ/BLOCKED, а не автоматический выбор intent.
5. Запусти deterministic coverage и recurring-correction scan, затем включи findings в reconcile classification:
   ```bash
   python3 .harness/tools/traceability-coverage.py --json
   python3 .harness/tools/check-command-references.py --json
   python3 .harness/tools/structural-enforcement.py --json
   ```
   Uncovered REQ, stale evidence, invalid refs и non-exempt orphan STEP нельзя скрывать за semantic summary. Recurring classes из Review Contract v2 routes в systemic corrective proposal; один occurrence без explicit human request не является recurring. Paths берутся из manifest через общий config layer.
6. Production code не исправляй. Не переписывай REQ/ADR под фактический код только ради устранения расхождения: accepted product/architecture contract остаётся authority, пока отдельное решение явно его не меняет.
7. Однозначный projection/command-syntax drift можно синхронизировать. Пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
8. Выполни полный deterministic gate:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
9. Substantive gaps превращай в corrective STEP. Итоговый audit report обязателен даже при отсутствии drift. Модель передаёт только **semantic payload** с `scope: "project"` и секциями из configured audit `TEMPLATE.md`, включая конкретные находки, evidence и corrective actions. Канонические `schema/kind/mode/created_at`, H1 и имя файла **не создавай вручную**. Пример payload и правила секций: `.harness/docs/REPORTING.md`.
10. Передай payload в deterministic writer с **точным** `executionId` текущего handoff:
    ```bash
    python3 .harness/tools/semantic-writer.py audit-report --execution-id '<executionId>' --payload-file '<local-json-or->'
    ```
    Writer сам использует configured `protocol.auditDirectory/TEMPLATE.md`, создаёт immutable `AUDIT-<UTC>.md`, проверяет `report_contract.py` и сохраняет execution-bound receipt. При `BLOCKED` не отправляй `complete SUCCESS`. При `PASS` передай штатному dispatcher `SUCCESS` именно для этой execution: Core перепроверит receipt, SHA-256 и scope до terminal success. Найденный drift — **содержимое валидного аудита**, не ошибка schema: его нельзя скрывать и не нужно выдавать за отсутствие отчёта.

Нельзя заявлять «drift отсутствует», пока migration/check-command-references/validator не выполнены либо их BLOCKED состояние не раскрыто в Evidence.
