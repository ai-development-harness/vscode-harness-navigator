---
name: plan-step
description: Produce, independently review, fingerprint and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`. Используй `context.contextContract` как минимальный runtime-neutral набор artifacts/sections; legacy `readPaths` остаётся compatibility surface и не означает «прочитать файл целиком». Дополнительный context загружай только через explicit expansion с material reason; `.harness/tools/**` не входит в normal semantic context. Human-readable prose Implementation plan и planning-review пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; protocol headings/keys не локализуй.

Execution Status ведёт global wrapper. Active legacy schema после Harness update является blocker: сначала `PROJECT RECONCILE`.

## Phase A — requirements quality / clarification

До consistency reasoning выполни Requirements Quality Gate по STEP и linked owning artifacts. Сначала получи ответ из existing REQ/ADR/OQ/architecture/codebase; не спрашивай то, что уже зафиксировано. Верни schema-v1 quality payload и проверь его через:

```bash
python3 .harness/tools/requirements-quality.py --payload-file '<local-json-or->'
```

`NEEDS_INPUT`/`BLOCKED` с blocking finding останавливает PLAN до targeted user input или canonical prerequisite. Ответ пользователя сохрани в соответствующий REQ/ADR/OQ/STEP и запусти gate повторно. Не оставляй решение только в chat/session state. Warning-only PASS продолжает planning.

## Phase B — deterministic + semantic contract validation

1. Запусти:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
2. Используй только `context`, уже возвращённый canonical dispatcher handoff: `context.contextContract.required` задаёт exact artifacts/sections, а deterministic facts остаются в том же handoff. Повторно `step-context.py`/resolver не вызывай. Не preload-ь unrelated docs/REQ/ADR; затем исследуй только действительно relevant code/tests/config. Completion dependency для PLAN не вычисляй.
3. Проверь semantic consistency:
   - Goal/Scope/Out of scope/Mutation policy согласованы;
   - Acceptance следует из REQ/ADR и не требует forbidden mutation;
   - Verification реально доказывает Acceptance;
   - linked REQ совместимы;
   - dependencies достаточны;
   - ownership не конфликтует с соседними STEP;
   - architecture prerequisite имеет explicit ref;
   - OPEN OQ/TBD не блокирует решение.
4. Прочитай active Project Principles из configured `sources.principles` и semantic-оценкой определи применимость к этому STEP. Applicable `blocking` PRN без explicit approved deviation является blocker до Ready plan; `advisory` PRN сам по себе не блокирует. Active blocking principles входят в deterministic planning basis, поэтому изменение правила stale-ит Ready plan.
5. Verification contract оформляй machine-executable: `- command: \`...\`` для автоматизируемой проверки; `- manual: ...` только для действительно semantic/visual проверки. Shell operators/pipes не используй — сложную проверку вынеси в repository script.
6. Contract conflict, missing prerequisite/decision или impossible acceptance => `BLOCKED`. Не расширяй contract догадкой.

## Phase C — architecture completeness pass

До формирования Implementation plan явно проверь применимые архитектурные измерения. Это semantic gate, а не checklist ради checklist: неприменимые пункты не создают искусственных требований.

- module/service/bounded-context boundaries и ownership;
- data model, persistence, migrations, rollback и backward compatibility;
- public/internal API, protocol/schema compatibility;
- authn/authz, trust boundaries, tenant/user scoping и data exposure;
- async/event/state-machine/concurrency semantics;
- extension/plugin/integration boundaries;
- indexing/search/cache consistency;
- observability, failure modes и recovery behavior;
- deployment/update/config compatibility;
- cross-cutting constraints из linked REQ/ADR/architecture baseline.

Если STEP затрагивает cross-module/service boundary, persistence schema/migration, public API/protocol, security boundary, distributed/async state, extension/plugin contract или critical compatibility, передай canonical PLAN context отдельному read-only `architect` agent/session. Architect не строит implementation plan: он adversarially ищет missing decision, hidden coupling, incompatible boundary и ADR/OQ/prerequisite. Material unresolved issue => `BLOCKED`.

Architecture-sensitive решение нельзя прятать внутрь Implementation plan. Если durable decision ещё не принят, останови PLAN через ADR/OQ/prerequisite вместо того, чтобы выбирать архитектуру по ходу реализации.

## Phase D — semantic plan payload

Не редактируй STEP/frontmatter вручную. Сформируй только semantic JSON:

- `implementationPlan` — непустой массив шагов;
- каждый шаг: `title`, непустой `actions[]`, optional `files[]`, `tests[]`, `risks[]`;
- `verification` — массив `{"kind":"command|manual","value":"..."}`;
- optional `executionGroups` — machine-readable DAG поверх 1-based элементов `implementationPlan`. Добавляй groups только когда декомпозиция действительно полезна и conflict boundary можно выразить явно. Каждая group содержит `id`, human-readable `title`, `steps[]`, `dependsOn[]`, non-empty `mutationPaths[]`, non-empty `verificationResponsibilities[]`, `parallel`. Если groups заданы, они покрывают каждый implementation step ровно один раз. `parallel=true` допустим только для кандидата с доказуемо непересекающимся declared mutation surface; это **не** команда на запуск concurrent agents.

Сохрани payload только под `.harness/local/**` либо передай через stdin и вызови:

```bash
python3 .harness/tools/semantic-writer.py plan-draft STEP-NNN --payload-file '<local-json-or->'
```

Writer сам заменяет только `## Implementation plan` / `## Verification`, переводит plan в `draft`, валидирует Verification и возвращает exact context/content fingerprints.

## Phase E — independent planning-review payload

Передай persisted draft отдельному `reviewer` agent/session, отличному от planner и от architect, если тот привлекался. Planning reviewer выполняет adversarial pass и обязан проверить:

- покрывает ли plan все material architecture impacts;
- не скрыто ли новое durable architecture decision без ADR/OQ/prerequisite;
- учтены ли migration/rollback/failure/recovery/compatibility paths, когда они применимы;
- не появляется ли hidden ownership conflict или новая cross-STEP dependency;
- действительно ли Verification доказывает Acceptance;
- не основан ли план на недоказанном предположении о соседней подсистеме.
- если persisted draft содержит `plan.execution_groups`, прочитай canonical projection через `execution-groups.py STEP-NNN --json` и проверь, что group purpose соответствует связанным plan steps, declared `mutationPaths` достаточно консервативны, `verificationResponsibilities` реально проверяют group outcome, а `parallel=true` не основан только на разных filenames. Deterministic отсутствие overlap — необходимое, но не достаточное semantic доказательство независимости.

Reviewer возвращает только:

```json
{"verdict":"pass|blocked","findings":[],"rationale":"..."}
```

Не создавай planning-review Markdown/frontmatter вручную. Передай payload в:

```bash
python3 .harness/tools/semantic-writer.py planning-review STEP-NNN --payload-file '<local-json-or->'
```

Writer сам вычисляет current `context_basis` / `plan_content_hash`, резервирует immutable `PLAN-REVIEW-<timestamp>.md`, валидирует report и при PASS вызывает canonical Ready stamp. BLOCKED report остаётся durable evidence, plan не становится Ready.

После writer завершай execution только значением `completionResult` из его JSON; для PASS planning review это `SUCCESS`, для blocker — `BLOCKED`. Не переинтерпретируй verdict. Изменение Implementation plan/upstream semantic input позже по-прежнему stale-ит Ready fingerprints. Production code не меняй.
