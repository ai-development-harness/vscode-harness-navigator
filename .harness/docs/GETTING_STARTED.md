# Начало работы

## Требования

- Git — обязательный repository executable;
- Python 3.11+ — обязательный runtime deterministic Harness tooling;
- Codex **или** Claude Code — один runtime для agent-session; оба одновременно не требуются;
- GitHub CLI `gh` — optional: нужен только для `GIT PR` / `GIT PR FINISH` и должен быть авторизован.

Harness не зависит от product runtime будущего проекта. Отсутствующий `gh` не блокирует Harness/Git workflow целиком, а только GitHub Pull Request capability.

Полный dependency contract: [`DEPENDENCIES.md`](DEPENDENCIES.md).

## 1. Создай repository из template

Предпочтительно GitHub **Use this template**.

Template содержит update lock и protocol metadata. Не удаляй их при bootstrap: Harness self-update использует immutable releases как BASE.

## 2. Подготовь local brief

Configured path берётся из:

```text
.harness/manifest.yaml → sources.localBrief
```

Default template использует:

```bash
cp PROJECT_BRIEF.example.md PROJECT_BRIEF.local.md
```

Файл local-only и не должен попадать в Git.

## 3. Настрой язык и paths при необходимости

До INIT можно изменить project-configurable значения manifest:

- `language.*`;
- `sources.*`;
- `protocol.*`;
- `execution.maxFixReviewCycles`;
- `review.security/tests`;
- `skills.search.maxResults`.

Specialized language key может отсутствовать: тогда реально используется `language.default`.

Если меняешь layout, core tooling обязан работать с новым configured path без дополнительного hidden default.

## 4. Открой repository в runtime

### Codex

Использует:

- `AGENTS.md`;
- `.codex/config.toml`;
- `.codex/agents/*.toml`.

### Claude Code

Использует:

- `CLAUDE.md` → `AGENTS.md`;
- `.claude/settings.json`;
- `.claude/agents/*.md`.

Canonical skills общие:

```text
.agents/skills/
```

Runtime adapter не является вторым source of truth protocol semantics.

## 5. При необходимости обнови Harness до INIT

```text
HARNESS UPDATE CHECK
HARNESS UPDATE APPLY
```

Update-specific paths разрешаются так:

```text
manifest.repository.harnessUpdatePolicy
        ↓
harness-update.toml
        ├── source.update_manifest
        ├── state.lock_file
        └── state.report_directory
```

Pre-INIT update меняет protocol layer, но не выполняет PROJECT INIT и не создаёт product knowledge.

После update inspect diff и при необходимости:

```text
GIT CHECK > COMMIT
```

## 6. Выполни PROJECT INIT

```text
PROJECT INIT
```

Initializer должен:

1. прочитать configured local brief и доступные references;
2. создать project overview;
3. создать canonical schema-v1 REQ;
4. создать минимальный architecture baseline;
5. создать ADR только для устойчивых решений;
6. создать canonical OQ для существенных неизвестных;
7. выполнить independent requirements semantic review и сохранить immutable INIT report с exact basis;
8. создать canonical schema-v1 STEP roadmap;
9. заполнить explicit dependencies, `architecture_refs`, `risk_flags`, mutation policy, acceptance и verification;
10. выполнить independent roadmap semantic review и сохранить второй immutable INIT report;
11. обеспечить REQ↔STEP и ADR↔STEP traceability;
12. пересобрать tracked projections через `sync-projections.py`;
13. запустить `validate.py --mode manual`;
14. завершить bootstrap только через:
    ```bash
    python3 .harness/tools/finalize-project-init.py --name '<project-name>'
    ```
15. не создавать production code.

Ручное `project.initialized=true` не является валидным INIT completion.

## 7. Что проверить после INIT

Проверь прежде всего:

- нет ли выдуманных требований;
- все ли material uncertainties представлены OQ/prerequisite work;
- нет ли лишних ADR;
- верны ли dependencies;
- явно ли ограничен Mutation policy;
- наблюдаемы ли Acceptance criteria;
- реально ли Verification доказывает Acceptance;
- есть ли два PASS INIT reports для текущих bases;
- проходит ли Harness validator.

Projection-файлы руками корректировать не нужно: drift должен ловиться deterministic tooling.

Полезные команды:

```text
PROJECT STATUS
STEP NEXT
```

## 8. STEP workflow

Новая задача:

```text
STEP ADD: <описание>
```

Planning:

```text
STEP PLAN STEP-001
```

Каждый PLAN проходит independent planning-review. Только matching semantic PASS + exact `context_basis` + `plan_content_hash` позволяют сделать plan Ready.

Реализация:

```text
STEP IMPLEMENT STEP-001
```

Review:

```text
STEP REVIEW STEP-001
```

Полный orchestration:

```text
STEP RUN STEP-001
```

Crash/session restart продолжает существующую execution через `.harness/local/execution/execution-status.json`.

## 9. REVIEW semantics

Перед review Harness детерминированно выбирает минимально обязательные specialized reviewers:

```bash
python3 .harness/tools/review_gates.py STEP-001 --json
```

`review.security/tests=auto` не означает «решает модель»: preselector использует risk flags, STEP type и factual changed surface.

Review report относится к exact repository revision:

- clean tree → `git_head`;
- dirty tree → `git_head + worktree_hash`.

Product/config mutation после report инвалидирует crash-recovery proof.

## 10. Harness update существующего проекта

`HARNESS UPDATE APPLY` не переписывает project-owned active documents/templates.

Если после update validator сообщает migration pending:

```text
PROJECT RECONCILE
```

RECONCILE идемпотентно мигрирует active schema, Accepted ADR, OQ и project-owned templates, затем пересобирает projections. Historical immutable reports не переписываются.

До завершения required migration strict commit/CI gate остаётся закрыт.

## 11. Git workflow

Bootstrap/project changes фиксируются обычными Harness Git-командами:

```text
GIT CHECK > COMMIT > PUSH
```

Git policy берётся из configured `repository.gitPolicy`.

Harness Integrity CI проверяет protocol/repository hygiene; product CI появляется только после фактического выбора product tooling.

## 12. Runtime profiles

Tracked runtime configs можно настраивать:

```text
.codex/config.toml
.codex/agents/*.toml
.claude/settings.json
.claude/agents/*.md
```

Они относятся к shared update surface и сохраняются через 3-way merge.

Model/effort не заменяют deterministic/semantic gates.

## Local overrides

Общие local instructions:

```bash
cp AGENTS.local.example.md AGENTS.local.md
```

`AGENTS.local.md` читается последним и исключён из Git.

Claude-specific private settings/instructions можно хранить в runtime-specific local files согласно Claude Code semantics.
