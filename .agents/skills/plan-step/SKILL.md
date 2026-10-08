---
name: plan-step
description: Produce, independently review, fingerprint and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`. Используй `context.contextContract` как минимальный runtime-neutral набор artifacts/sections; legacy `readPaths` остаётся compatibility surface и не означает «прочитать файл целиком». Дополнительный context загружай только через explicit expansion с material reason; `.harness/tools/**` не входит в normal semantic context. Human-readable prose Implementation plan и planning-review пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; protocol headings/keys не локализуй.

Если `context.contextReuse.status=REUSE_CANDIDATE`, используй summary как только навигационную подсказку к прежним подтверждённым источникам. Точные source hashes уже проверены Core; не перечитывай их целиком без нового вопроса, но спорные предпосылки перепроверяй из source of truth. При `STALE/MISSING` не доверяй прежнему reasoning. Результат значимого bounded grounding можешь зафиксировать через `context-reuse.py record` с явными source paths и коротким summary (не в transcript). Отвергнутые гипотезы можно сохранить там же только с concrete falsification evidence, чтобы другой агент не исследовал их заново при неизменных источниках. Эти заметки не являются grounds для PASS/BLOCKED.

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
   python3 .harness/tools/gate-reuse.py
   ```
2. Используй только `context`, уже возвращённый canonical dispatcher handoff: `context.contextContract.required` задаёт exact artifacts/sections, а deterministic facts остаются в том же handoff. Если `context.contextContract.coreReasoningPrinciples` непуст, прочитай **только** перечисленные `path` leaves и примени их к reasoning; не сканируй каталог CRP. `CRP-NNN` — Harness-owned reasoning rule и не является project `PRN-NNN`; Project Principles по-прежнему приходят отдельными canonical artifacts. Повторно `step-context.py`/resolver не вызывай. Не preload-ь unrelated docs/REQ/ADR; затем исследуй только действительно relevant code/tests/config. Completion dependency для PLAN не вычисляй.
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
5. Verification contract оформляй machine-executable: `- command: \`...\`` для автоматизируемой проверки; `- manual: ...` только для действительно semantic/visual проверки; `- product: FEATURE-*` для Acceptance, которое нужно доказать через реальную пользовательскую поверхность project-owned Verification Driver. `product` допустим только если `.agents/skills/verify-product/SKILL.md` и `docs/verification/feature-map.json` существуют, driver qualified, а feature entry связывает exact REQ/STEP Acceptance. Shell operators/pipes не используй — сложную проверку вынеси в repository script.
   Если Acceptance содержит измеримый performance claim, performance optimization является целью STEP или пользователь явно требует benchmark, подключи internal `benchmark-methodology`. До измерения зафиксируй metric/unit/direction/scope и minimum material effect, exact baseline/candidate command + measurement-relevant environment, correctness counters/work proof, repeated-run strategy, bottleneck/sanity-limit и end-to-end relevance. В PLAN не выдумывай samples: запланируй benchmark execution как Verification и последующую deterministic проверку через `.harness/tools/benchmark-methodology.py`. `INCONCLUSIVE` не доказывает performance Acceptance.
6. Contract conflict, missing prerequisite/decision или impossible acceptance => `BLOCKED`. Не расширяй contract догадкой.

## Phase C — architecture completeness pass

До architecture completeness оцени, нужна ли bounded mental model существующей реализации. Если ownership/state responsibility неочевидны, есть cross-module/service/API/integration boundary, shared async/concurrent state или plan зависит от runtime/data flow нескольких слоёв — вызови внутренний core capability `codebase-grounding` на **том же** `context.contextContract` из dispatcher handoff. Не запускай новый resolver. Используй validated structured grounding payload как read-only input для planner/architect; capability не строит plan и не принимает architecture decision. Для локального low-risk изменения в одном очевидном модуле отдельный grounding pass не нужен.

Затем запусти deterministic blast-radius preflight:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-NNN --phase plan --json
```

Если `required=true`, validated Codebase Grounding становится обязательным input для внутреннего core capability `semantic-blast-radius`. Он обязан отделить deterministic explicit impact от semantic hypotheses и выделить 1–2 critical safety assumptions. `INCONCLUSIVE` на PLAN допустим только как explicit proof obligation: каждый unresolved critical assumption перенеси в `Verification`/Implementation plan как concrete command/check до Ready. Не выдавай persuasive prose за proof и не запускай capability автоматически при `risk_flags: [none]`.

До формирования Implementation plan явно проверь применимые архитектурные измерения. Это semantic gate, а не checklist ради checklist: неприменимые пункты не создают искусственных требований.

**Evidence Gate действует уже на стадии PLAN.** Новый security/failure/edge scenario без explicit REQ/ADR/STEP/PRN или reproduced project evidence сначала является hypothesis. Semantic Blast Radius/architect/reviewer могут сохранить такую hypothesis только как bounded proof/falsification obligation: concrete check в Verification/plan, который подтвердит или опровергнет необходимые preconditions. До confirmation запрещено превращать hypothesis в production mutation, regression/security test, hardening, ADR/OQ/prerequisite или planning blocker. Framework/platform capability сама по себе не является project-specific evidence. Invalidated hypothesis отбрасывается; confirmed scenario может влиять на plan только в пределах contract.

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

После grounding/blast-radius/architect pass проверь optional High-Rigor Arena:

```bash
python3 .harness/tools/high-rigor.py --mode arena --phase plan --step STEP-NNN --json
```

Если preflight вернул `RUN`, используй internal `high-rigor`: все candidates получают один exact compact PLAN/decision contract и один rubric, пишут в отдельные local outputs, затем отдельный readonly judge оценивает candidates. Validated Arena synthesis — дополнительный planning input, но не заменяет Requirements Quality, Semantic Blast Radius, architect pass или independent planning-review. `DEGRADED` явно зафиксируй в planning rationale/handoff и продолжай только обычными существующими gates; не называй его high-rigor PASS. При `SKIP` никаких fan-out agents не создавай.

## Phase D — semantic plan payload

Не редактируй STEP/frontmatter вручную. Сформируй только semantic JSON:

- `implementationPlan` — непустой массив шагов;
- каждый шаг: `title`, непустой `actions[]`, optional `files[]`, `tests[]`, `risks[]`; production action и новый regression/security test должны быть traceable к explicit contract, reproduced defect или confirmed project-specific scenario; unverified hypothesis допустима только как bounded proof/falsification obligation, а не как mutation/test/hardening;
- `verification` — массив `{"kind":"command|manual|product","value":"..."}`; для `product` value — canonical `FEATURE-*` из `docs/verification/feature-map.json`;
- optional `executionGroups` — machine-readable DAG поверх 1-based элементов `implementationPlan`. Добавляй groups только когда декомпозиция действительно полезна и conflict boundary можно выразить явно. Каждая group содержит `id`, human-readable `title`, `steps[]`, `dependsOn[]`, non-empty `mutationPaths[]`, non-empty `verificationResponsibilities[]`, `parallel`. Если groups заданы, они покрывают каждый implementation step ровно один раз. `parallel=true` допустим только для кандидата с доказуемо непересекающимся declared mutation surface; это **не** команда на запуск concurrent agents.

Сохрани payload только под `.harness/local/**` либо передай через stdin и вызови:

```bash
python3 .harness/tools/semantic-writer.py plan-draft STEP-NNN --payload-file '<local-json-or->'
```

Writer сам заменяет только `## Implementation plan` / `## Verification`, переводит plan в `draft`, валидирует Verification и возвращает exact context/content fingerprints.

## Phase E — independent planning-review payload

Передай persisted draft отдельному `reviewer` agent/session, отличному от planner и от architect, если тот привлекался. Если Semantic Blast Radius был required, передай reviewer также его **validated result** как phase-local evidence, чтобы reviewer мог сопоставить unresolved critical proof obligations с persisted Verification/plan. Planning reviewer выполняет adversarial pass и обязан проверить:

- покрывает ли plan все material architecture impacts;
- не скрыто ли новое durable architecture decision без ADR/OQ/prerequisite;
- учтены ли migration/rollback/failure/recovery/compatibility paths, когда они применимы;
- не появляется ли hidden ownership conflict или новая cross-STEP dependency;
- действительно ли Verification доказывает Acceptance;
- для STEP с material risk flags выполнен ли required Semantic Blast Radius и перенесены ли все unresolved critical proof obligations из PLAN result в Verification/plan;
- не основан ли plan на недоказанном предположении о соседней подсистеме;
- не превратил ли planner/architect/Semantic Blast Radius unverified hypothesis в production work, regression/security test, hardening, ADR/OQ/prerequisite или blocker вместо bounded proof/falsification obligation;
- любой новый reviewer-derived security/failure scenario сначала проходит Evidence Gate: preconditions → cheapest practical falsification → confirmed либо discard. Неподтверждённая hypothesis сама по себе не может BLOCK-ировать PLAN.
- если persisted draft содержит `plan.execution_groups`, прочитай canonical projection через `execution-groups.py STEP-NNN --json` и проверь, что group purpose соответствует связанным plan steps, declared `mutationPaths` достаточно консервативны, `verificationResponsibilities` реально проверяют group outcome, а `parallel=true` не основан только на разных filenames. Deterministic отсутствие overlap — необходимое, но не достаточное semantic доказательство независимости.

Reviewer возвращает только material findings, которые меняют допустимость или содержание реализации. Material finding — это минимум одно из: plan приводит к иному observable implementation behaviour; противоречит Accepted ADR/REQ/STEP contract; оставляет обязательный acceptance/verification/prerequisite без владельца или доказуемого пути выполнения. Wording/style/clarity notes, не меняющие эти свойства, помещай только в `rationale` и не превращай в blocker.

Для `type: adr` planning-review проверяет адекватность плана принятия/фиксации решения, prerequisites, ownership, compatibility и Verification. Сам authored ADR не является вторым объектом full editorial review на каждом PLAN round; формулировки ADR блокируют PLAN только если создают material contradiction/ambiguity по определению выше. ADR остаётся частью context fingerprint, чтобы смысловое изменение корректно stale-ило Ready plan.

Если привлекаешь reviewer/architect/specialized subagent, brief обязан явно сказать: читать только repository files из выданного context; не читать outputs/transcripts/temp files других agents; не ждать и не polling-ить другие reviewers; вернуть свой результат сразу после собственного pass. Параллельные specialized reviewers независимы.

Reviewer возвращает только:

```json
{"verdict":"pass|blocked","findings":[],"rationale":"..."}
```

Не создавай planning-review Markdown/frontmatter вручную. Передай payload в:

```bash
python3 .harness/tools/semantic-writer.py planning-review STEP-NNN --payload-file '<local-json-or->'
```

Writer сам вычисляет current `context_basis` / `plan_content_hash`, резервирует immutable `PLAN-REVIEW-<timestamp>.md`, валидирует report и при PASS вызывает canonical Ready stamp. BLOCKED report остаётся durable evidence, plan не становится Ready. Количество durable planning-review rounds внутри текущей active `STEP PLAN` execution ограничено `.harness/manifest.yaml → execution.maxPlanReviewCycles`; historical reports прошлых explicit PLAN invocations budget новой execution не расходуют. При `PLAN_REVIEW_LIMIT_REACHED` не запускай очередной auto-fix/re-PLAN. Остановись и передай пользователю оставшиеся findings.

После writer завершай execution только значением `completionResult` из его JSON; для PASS planning review это `SUCCESS`, для blocker — `BLOCKED`. Не переинтерпретируй verdict. Изменение Implementation plan/upstream semantic input позже по-прежнему stale-ит Ready fingerprints. Production code не меняй.
