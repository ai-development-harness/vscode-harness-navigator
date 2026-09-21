---
name: reconcile-project
description: Idempotently migrate active project schema, detect cross-repository drift and create corrective work without silently changing production code.
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

1. Сравни code/config/migrations/tests с REQ, Accepted ADR, architecture refs, STEP, evidence и review reports.
2. Запусти:
   ```bash
   python3 .harness/tools/check-command-references.py --json
   ```
   Paths берутся из manifest через общий config layer.
3. Production code не исправляй. Однозначный projection/command-syntax drift можно синхронизировать.
4. Пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
5. Выполни полный deterministic gate:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
6. Substantive gaps превращай в corrective STEP. Итоговый reconcile/audit report сохраняй в configured `protocol.auditDirectory` с YAML frontmatter `schema: 1`.

Нельзя заявлять «drift отсутствует», пока migration/check-command-references/validator не выполнены либо их BLOCKED состояние не раскрыто в Evidence.
