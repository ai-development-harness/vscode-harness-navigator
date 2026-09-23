# Структура репозитория

Harness разделяет control plane, runtime adapters, project knowledge и planning/history.

## Ownership важнее физического пути

Базовое разделение:

```text
.harness/**      → Harness control plane / local operational state
.agents/**       → runtime-neutral skills
.codex/**        → Codex adapter
.claude/**       → Claude Code adapter
docs/**          → default project knowledge layout
planning/**      → default project planning/history layout
```

Но project topology **не определяется этими default paths**. Canonical project locations берутся из `.harness/manifest.yaml → sources.* / protocol.*`.

Внутри `.harness/**` ownership тоже неоднороден:

- `harness_owned` — core protocol/tooling/docs;
- `shared` — например manifest/runtime configs, где нужен 3-way merge;
- `.harness/local/**` — untracked operational state.

## Default layout template

```text
.
├── README.md
├── AGENTS.md
├── CLAUDE.md
├── PROJECT_BRIEF.example.md
├── .harness/
│   ├── manifest.yaml
│   ├── harness.lock.json
│   ├── harness-update-graph.json
│   ├── command-transitions.json
│   ├── reasoning-boundaries.json        # generated projection
│   ├── harness-update.toml
│   ├── harness-policy.toml
│   ├── git-policy.toml
│   ├── docs/
│   │   ├── README.md
│   │   ├── VALIDATORS.md
│   │   ├── REASONING_BOUNDARIES.md      # generated table/diagrams
│   │   └── ...
│   ├── tools/
│   │   ├── harness_config.py
│   │   ├── document_contract.py
│   │   ├── planning_contract.py
│   │   ├── review_contract.py
│   │   ├── review_gates.py
│   │   ├── reasoning_boundaries.py
│   │   ├── project_integrity.py
│   │   ├── project_migration.py
│   │   ├── projection_contract.py
│   │   ├── template_contract.py
│   │   ├── validate.py
│   │   ├── execution_status.py
│   │   └── ...
│   └── local/
│       └── execution/execution-status.json
├── .agents/skills/
├── .codex/
├── .claude/
├── docs/
│   ├── PROJECT.md
│   ├── architecture.md
│   ├── OPEN_QUESTIONS.md              # projection
│   ├── open-questions/
│   │   ├── OQ-NNN-*.md                # canonical
│   │   └── TEMPLATE.md
│   ├── requirements/
│   │   ├── REQ-NNN-*.md               # canonical
│   │   ├── SPEC.md                     # deterministic projection
│   │   ├── STATUS.md                   # deterministic projection
│   │   └── TEMPLATE.md
│   ├── adr/
│   │   ├── ADR-NNN-*.md
│   │   └── TEMPLATE.md
│   └── skills/REGISTRY.md
├── planning/
│   ├── PLAN.md                         # deterministic projection
│   ├── STATUS.md                       # deterministic projection
│   ├── tasks/
│   │   ├── STEP-NNN.md
│   │   └── TEMPLATE.md
│   ├── reviews/
│   │   └── STEP-NNN/REVIEW-*.md
│   ├── plan-reviews/
│   │   └── STEP-NNN/PLAN-REVIEW-*.md
│   ├── init-reviews/
│   │   └── INIT-REVIEW-*.md
│   ├── audits/
│   ├── releases/
│   ├── harness-updates/
│   └── skill-searches/
└── .github/
```

Это **defaults нового template**, а не hard-coded runtime topology.

## Manifest-driven project topology

Примеры:

```yaml
sources:
  requirements: spec/requirements
  adrDirectory: spec/decisions
  architecture: spec/architecture.md
  openQuestions: spec/questions
  openQuestionsIndex: spec/QUESTIONS.md
  roadmap: work/ROADMAP.md
  status: work/STATUS.md

protocol:
  taskDirectory: work/tasks
  reviewDirectory: work/reviews
  planningReviewDirectory: work/plan-reviews
```

После такой настройки core validators, execution recovery, projections и skills должны работать через эти paths. Default `docs/**`/`planning/**` не остаются скрытым вторым registry.

## Project-owned templates

Colocated `TEMPLATE.md` рядом с STEP/REQ/ADR/OQ/report directories остаются project-owned:

- HARNESS UPDATE не перезаписывает их напрямую;
- protocol-owned canonical definitions находятся в Harness tooling;
- `PROJECT RECONCILE` refreshes project templates при schema migration.

Это сохраняет ownership boundary существующих проектов и одновременно обеспечивает обновляемую schema.

## Active documents vs immutable history

Active mutable contracts:

- STEP;
- REQ;
- current ADR status/history document;
- OQ;
- current project/architecture docs.

Immutable reports:

- implementation reviews;
- planning reviews;
- INIT reviews;
- completed audit/migration/update reports.

Schema migration меняет active documents/templates, но не переписывает historical immutable reports задним числом.

## Control plane update paths

Manifest знает только путь к update policy:

```text
repository.harnessUpdatePolicy
```

Update-specific topology живёт в самой policy:

```toml
[source]
update_manifest = ".harness/harness-update-graph.json"

[state]
lock_file = ".harness/harness.lock.json"
report_directory = "planning/harness-updates"
```

Updater и validators обязаны читать эти значения, а не дублировать их hardcoded constants.

## Runtime adapters

`.codex/**` и `.claude/**` адаптируют один protocol к конкретным runtimes. Они не определяют отдельные STEP/REQ/ADR semantics.

Tracked model/effort settings — shared config: Harness update сохраняет project-specific настройки через 3-way merge.

## Projections

Tracked projections генерируются из canonical state:

```bash
python3 .harness/tools/sync-projections.py
```

Validator сравнивает ожидаемое и фактическое содержимое. Projection drift — integrity defect, а не новый источник истины.

## Local state

Единственный Execution Status:

```text
.harness/local/execution/execution-status.json
```

Он untracked, crash-safe и может содержать несколько independent execution records. Это operational recovery, а не audit/product evidence.

## Self-update boundary

Self-updater:

- использует ownership policy;
- не трогает unknown/project-owned paths;
- читает BASE/THEIRS только из immutable release tags;
- обновляет shared files через 3-way merge;
- после schema-changing release оставляет project-owned migration `PROJECT RECONCILE`.

Product implementation directories специально отсутствуют из template и появляются только по фактическим STEP.
