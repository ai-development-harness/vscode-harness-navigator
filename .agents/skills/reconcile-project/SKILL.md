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
4. Запусти deterministic coverage и включи findings в reconcile classification:
   ```bash
   python3 .harness/tools/traceability-coverage.py --json
   python3 .harness/tools/check-command-references.py --json
   ```
   Uncovered REQ, stale evidence, invalid refs и non-exempt orphan STEP нельзя скрывать за semantic summary. Paths берутся из manifest через общий config layer.
5. Production code не исправляй. Не переписывай REQ/ADR под фактический код только ради устранения расхождения: accepted product/architecture contract остаётся authority, пока отдельное решение явно его не меняет.
6. Однозначный projection/command-syntax drift можно синхронизировать. Пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
7. Выполни полный deterministic gate:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
8. Substantive gaps превращай в corrective STEP. Итоговый reconcile/audit report сохраняй в configured `protocol.auditDirectory` с YAML frontmatter `schema: 1`.

Нельзя заявлять «drift отсутствует», пока migration/check-command-references/validator не выполнены либо их BLOCKED состояние не раскрыто в Evidence.
