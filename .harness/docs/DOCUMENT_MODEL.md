# Модель документов и traceability

AI Development Harness хранит долгоживущий контекст проекта в репозитории. Главная цель модели — не позволить одному Markdown-файлу одновременно быть требованиями, roadmap, архитектурой, operational state и отчётом.

Все **active machine-readable project documents** используют YAML frontmatter `schema: 1`. Machine keys и enum values являются частью protocol и не локализуются. Человекочитаемый Markdown использует `language.documentation` с fallback на `language.default`.

## Configured paths вместо скрытой topology

Canonical/project paths задаются в `.harness/manifest.yaml`.

Основные поля:

- `sources.localBrief` — локальный вход bootstrap;
- `sources.projectOverview` — нормализованное описание проекта;
- `sources.requirements` — canonical REQ + requirements projections;
- `sources.adrDirectory` — canonical ADR;
- `sources.architecture` — architecture baseline;
- `sources.openQuestions` — canonical OQ;
- `sources.openQuestionsIndex` — projection OQ;
- `sources.roadmap` / `sources.status` — STEP projections;
- `protocol.taskDirectory` — canonical STEP;
- `protocol.reviewDirectory` — implementation review reports;
- `protocol.planningReviewDirectory` — semantic planning-review reports;
- `protocol.initReviewDirectory` — INIT semantic-review reports;
- `protocol.auditDirectory`, `protocol.releaseDirectory`, `protocol.skillSearchDirectory` — durable reports соответствующих workflows.

Default layout template использует `docs/**` и `planning/**`, но core tools и skills обязаны читать configured paths, а не считать defaults вторым source of truth.

## Canonical active documents

### Requirement — REQ-NNN

Canonical REQ хранит:

- `schema: 1`;
- `id`;
- `priority`;
- `source`;
- обратные связи `steps` и `adrs`;
- sections `Requirement`, `Rationale`, `Acceptance`.

REQ описывает требуемый результат, а не implementation detail.

### ADR — ADR-NNN

Canonical ADR хранит stable decision history:

- `status: proposed | accepted | superseded | rejected`;
- deciders/date;
- supersession links;
- reverse traceability в REQ/STEP;
- context/problem/decision/alternatives/consequences;
- security/data/compatibility implications.

Accepted ADR не переписывается как mutable config. Изменение решения оформляется новым ADR/supersession.

### STEP — STEP-NNN

Canonical STEP хранится в configured `protocol.taskDirectory`.

Frontmatter:

- `status: planned | in_progress | blocked | completed | deferred | cancelled`;
- `type: implementation | bugfix | refactor | research | adr | audit | review | hardening | documentation | release`;
- `priority: critical | high | medium | low`;
- `phase`;
- strict refs `depends_on`, `requirements`, `adrs`, `architecture_refs`;
- closed-set `risk_flags`;
- `plan` metadata.

Body содержит Goal/Context/Scope/Mutation policy/Out of scope/Acceptance/Verification/Deliverables/Implementation plan/Evidence/Blocker.

ID имеют минимум три цифры без искусственного верхнего предела: `STEP-001`, `STEP-1000`.

### Open Question — OQ-NNN

Неопределённость — отдельный canonical document, а не свободный блок в общем index-файле.

OQ хранит:

- `status: open | resolved | deferred`;
- `affects`: существующие STEP/REQ/ADR либо `PROJECT`;
- timestamps;
- Context;
- Decision needed;
- Resolution.

`open` OQ блокирует executable STEP, если `affects` пересекает STEP/linked REQ/ADR. `PROJECT` используется как INIT-level blocker.

## Projections

Projection — tracked deterministic representation canonical state, но **не** второй источник истины.

Детерминированно генерируются:

- requirements `SPEC.md`;
- requirements `STATUS.md`;
- configured roadmap;
- configured project status;
- configured Open Questions index.

Команда:

```bash
python3 .harness/tools/sync-projections.py
```

Validation требует byte-for-byte совпадения projection с вычисленным результатом. Поэтому агент не должен вручную «синхронизировать статус» в этих файлах.

Projection derivation работает fail-closed: malformed canonical REQ/STEP, недоступный completion proof или ошибка вычисления relevant OQ не превращаются в правдоподобный `planned`/«—». `sync-projections.py` возвращает `BLOCKED`, а validator — `projection derivation failed`, пока canonical state не станет доказуемым.

Requirement lifecycle status выводится из canonical REQ + STEP completion proofs. Он не хранится в canonical REQ.

## Planning contract

`STEP PLAN` разделяет два fingerprints:

### context_basis

SHA-256 canonical planning context:

- STEP contract;
- linked REQ;
- linked ADR;
- type-specific completion proof прямых dependencies;
- только explicit `architecture_refs` — document/anchor, относящиеся к STEP;
- relevant canonical OQ.

Изменение нерелевантного architecture section не должно делать plan stale.

### content_hash

SHA-256 нормализованного текста `Implementation plan`.

Это отдельный fingerprint: изменение самого плана должно инвалидировать Ready даже при неизменном product contract.

### planning-review

Каждый PLAN проходит отдельный independent semantic review. Durable report хранит exact `context_basis` + `plan_content_hash`.

Только matching `verdict: pass` разрешает `stamp-plan`, который записывает:

- `plan.status: ready`;
- revision;
- context/content hashes;
- reviewed report;
- timestamp.

## Completion proofs dependencies

`status: completed` сам по себе не является достаточным доказательством prerequisite.

Минимальный proof зависит от STEP type:

- implementation/bugfix/refactor/hardening/documentation/release — Evidence + schema-valid PASS review;
- research — completed + durable Evidence/Deliverables;
- adr — completed + Evidence + linked ADR в `accepted`;
- audit/review — completed + durable Evidence.

Proof fingerprint входит в planning basis direct dependent STEP.

## Implementation review

STEP REVIEW создаёт immutable schema-v1 report `REVIEW-<UTC timestamp>.md`. Planning/INIT semantic reports аналогично используют `PLAN-REVIEW-<UTC timestamp>.md` и `INIT-REVIEW-<UTC timestamp>.md`; sortable canonical names определяют deterministic history order. Для schema-v1 durable reports timestamp в filename и `created_at` обязаны обозначать один и тот же whole-second UTC instant. Поэтому report нельзя сделать «новее» только будущим filename при старом metadata timestamp. Existing durable report path immutable и не может быть перезаписан вместо создания нового. STEP не хранит отдельный mutable `review.latest_*` cache: latest state выводится из immutable review history, чтобы запись результата review не меняла только что проверенную revision.

Report обязан содержать:

- `step_id`;
- `verdict: pass | fail | blocked`;
- exact reviewed revision;
- specialized review metadata: persisted `gate_basis`, exact список `required`, результаты security/tests и concrete `*_evidence` summary/reference для реально выполненного specialized review. Preselector включает factual changed paths и режим поверхности; если review запускается уже на clean tree без exact implementation baseline, он fail-closed требует security + tests, а не считает последний commit полным STEP diff;
- structured findings.

Reviewed revision:

- clean tree — `git_head`;
- dirty tree — `git_head + worktree_hash`.

Из worktree fingerprint исключаются `.harness/local/**` и только **новый report-shaped implementation review**, который STEP REVIEW создаёт после snapshot. Весь configured review directory не является trust/ignore boundary: изменение, удаление или rename уже существующего immutable report остаётся частью exact revision и отдельно блокируется immutability gate. Git path классифицируется лексически, без разыменования symlink target; durable review/report artifacts сами не могут быть symlink. Product/config changes после review fingerprint изменяют и делают crash-recovery proof неприменимым.

Finding categories:

- `implementation`;
- `evidence`;
- `contract`.

`fail` допускает только implementation/evidence findings внутри STEP scope. Contract defect обязан маршрутизироваться в `blocked`.

## INIT semantic evidence

PROJECT INIT сохраняет два immutable semantic reports:

1. `stage: requirements`;
2. `stage: roadmap`.

Каждый PASS относится к exact deterministic basis текущих candidate documents.

После всех mutations INIT:

1. regenerates projections;
2. запускает validator;
3. вызывает `finalize-project-init.py`.

Ручное выставление `project.initialized=true` не является валидным завершением INIT.

## Migration active documents

HARNESS UPDATE меняет protocol layer, но не получает право молча переписывать project-owned REQ/ADR/STEP/templates.

Если release меняет project document schema:

```text
HARNESS UPDATE APPLY
        ↓
project schema migration pending
        ↓
PROJECT RECONCILE
```

`PROJECT RECONCILE` запускает идемпотентную migration:

- legacy STEP/REQ/ADR/OQ → schema v1;
- monolithic REQ/OQ → canonical files;
- Accepted ADR сохраняет смысл/status;
- старый Ready plan без durable semantic proof становится draft;
- project-owned templates обновляются из protocol-owned definitions;
- projections пересобираются;
- historical immutable review/audit/update reports не переписываются; legacy implementation reviews получают `path + content hash` pin в migration report, поэтому могут участвовать в completion proof без retroactive rewrite и любое последующее изменение обнаруживается.

Повтор migration без изменений — настоящий no-op.

## Traceability

Минимальные двусторонние связи:

```text
REQ ↔ STEP
ADR ↔ STEP
OQ → STEP / REQ / ADR / PROJECT
STEP → dependency STEP completion proof
STEP → Evidence
STEP → planning-review
STEP → implementation review
```

Static validator проверяет существование refs и reverse REQ/ADR↔STEP links. Semantic reviewer проверяет смысловую непротиворечивость.

## Source-of-truth hierarchy

Разные слои отвечают на разные вопросы:

1. factual code/config/migrations/tests — что существует сейчас;
2. Accepted ADR — какие устойчивые решения обязательны;
3. architecture baseline — актуальная архитектурная модель;
4. REQ — что проект обязан обеспечивать;
5. STEP — scope конкретной работы;
6. immutable semantic/review reports — что было независимо доказано для конкретного fingerprint/revision;
7. deterministic projections — навигация/сводка canonical state;
8. brief/chat/заметки — входной контекст.

Code не «побеждает» Accepted ADR автоматически. Несоответствие — architecture drift и требует явного reconciliation.

## Durable handoff

Harness не требует chat history для продолжения:

```text
STEP ADD
  → canonical contract

STEP PLAN
  → implementation plan
  → independent planning-review
  → Ready fingerprints

STEP IMPLEMENT
  → code/tests
  → Evidence

STEP REVIEW
  → immutable exact-revision report

STEP FIX
  → fixes only confirmed implementation/evidence findings

PROJECT RECONCILE
  → migration/projection sync/audit/corrective STEP
```

Operational `.harness/local/execution/execution-status.json` помогает пережить crash/session restart, но не заменяет canonical documents и immutable proof artifacts.
