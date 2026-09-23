---
name: plan-step
description: Produce, independently review, fingerprint and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`. Human-readable prose Implementation plan и planning-review пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; protocol headings/keys не локализуй.

Execution Status ведёт global wrapper. Active legacy schema после Harness update является blocker: сначала `PROJECT RECONCILE`.

## Phase A — deterministic + semantic contract validation

1. Запусти:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
2. Используй только `context`, уже возвращённый canonical dispatcher handoff: `readPaths` + deterministic planning facts. Повторно `step-context.py` не вызывай. Затем исследуй только действительно relevant code/tests/config. Completion dependency для PLAN не вычисляй.
3. Проверь semantic consistency:
   - Goal/Scope/Out of scope/Mutation policy согласованы;
   - Acceptance следует из REQ/ADR и не требует forbidden mutation;
   - Verification реально доказывает Acceptance;
   - linked REQ совместимы;
   - dependencies достаточны;
   - ownership не конфликтует с соседними STEP;
   - architecture prerequisite имеет explicit ref;
   - OPEN OQ/TBD не блокирует решение.
4. Verification contract оформляй machine-executable: `- command: \`...\`` для автоматизируемой проверки; `- manual: ...` только для действительно semantic/visual проверки. Shell operators/pipes не используй — сложную проверку вынеси в repository script.
5. Contract conflict, missing prerequisite/decision или impossible acceptance => `BLOCKED`. Не расширяй contract догадкой.

## Phase B — semantic plan payload

Не редактируй STEP/frontmatter вручную. Сформируй только semantic JSON:

- `implementationPlan` — непустой массив шагов;
- каждый шаг: `title`, непустой `actions[]`, optional `files[]`, `tests[]`, `risks[]`;
- `verification` — массив `{"kind":"command|manual","value":"..."}`.

Сохрани payload только под `.harness/local/**` либо передай через stdin и вызови:

```bash
python3 .harness/tools/semantic-writer.py plan-draft STEP-NNN --payload-file '<local-json-or->'
```

Writer сам заменяет только `## Implementation plan` / `## Verification`, переводит plan в `draft`, валидирует Verification и возвращает exact context/content fingerprints.

## Phase C — independent planning-review payload

Передай persisted draft отдельному `reviewer` agent/session, отличному от planner. Reviewer возвращает только:

```json
{"verdict":"pass|blocked","findings":[],"rationale":"..."}
```

Не создавай planning-review Markdown/frontmatter вручную. Передай payload в:

```bash
python3 .harness/tools/semantic-writer.py planning-review STEP-NNN --payload-file '<local-json-or->'
```

Writer сам вычисляет current `context_basis` / `plan_content_hash`, резервирует immutable `PLAN-REVIEW-<timestamp>.md`, валидирует report и при PASS вызывает canonical Ready stamp. BLOCKED report остаётся durable evidence, plan не становится Ready.

После writer завершай execution только значением `completionResult` из его JSON; для PASS planning review это `SUCCESS`, для blocker — `BLOCKED`. Не переинтерпретируй verdict. Изменение Implementation plan/upstream semantic input позже по-прежнему stale-ит Ready fingerprints. Production code не меняй.
