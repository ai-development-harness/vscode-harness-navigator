---
name: review-step
description: Run an independent read-only review of an exact repository revision, compose deterministic specialized reviewers, and persist a validated immutable report.
---
# review-step

Используй для `STEP REVIEW STEP-NNN`. Human-readable findings/evidence/verdict rationale пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; protocol headings/keys/enums не локализуй.

1. До reasoning запусти deterministic integrity gate и убедись, что STEP имеет current Ready plan:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
2. Используй только phase `context`, уже возвращённый canonical dispatcher handoff. Прочитай `readPaths` + relevant diff/code/tests. `deterministic.specializedReviewGate` содержит exact gate, а `deterministic.repositoryRevision` — exact revision. Повторно `step-context.py`/gates не вызывай и revision вручную не восстанавливай. Модель может добавить reviewer, но не убрать required.
3. Независимый reviewer сверяет task/REQ/ADR/OQ/architecture refs/Implementation plan с реализацией и tests. Сделай полный semantic проход exact revision и собери material findings.
4. Верни structured payload:
   - `verdict: pass|fail|blocked`;
   - `findings[]`: `title/severity/category/location/scenario/impact/fixDirection`;
   - `verificationObservations`;
   - `rationale`;
   - `specializedReviews.security/tests` только для реально выполненных specialized reviews: `status + evidence`.
5. Categories:
   - `implementation` — реализация/тест не соответствует непротиворечивому contract;
   - `evidence` — acceptance недостаточно доказан;
   - `contract` — STEP/REQ/ADR/dependency/Acceptance противоречив или требует отсутствующего решения.
6. Routing:
   - `pass` — findings нет;
   - `fail` — implementation/evidence findings, исправимые внутри scope;
   - `blocked` — contract defect/missing prerequisite либо blocking evidence condition.
7. Не создавай review Markdown/frontmatter, timestamp, revision или gate metadata вручную. Передай JSON в:

   ```bash
   python3 .harness/tools/semantic-writer.py step-review STEP-NNN --payload-file '<local-json-or->'
   ```

   Writer сам повторно вычисляет exact repository revision и specialized gate, требует результаты всех mandatory reviewers, создаёт immutable report через exclusive reservation и проверяет его canonical validator-ом.
   Execution result бери только из `completionResult` writer-а (`PASS|FAIL|BLOCKED`); не вычисляй verdict второй раз после записи report.
   Для semantic PASS writer сам выполняет lifecycle close `status → completed`, доказывает type-specific completion proof и синхронизирует projections. Если proof недостаточен, PASS report остаётся immutable evidence, STEP не закрывается, а `completionResult=BLOCKED`.
8. Product code не исправляй. При BLOCKED укажи corrective STEP/RESEARCH/ADR в semantic finding/rationale; contract defect не маршрутизируй в FAIL→FIX.

Crash recovery доверяет только schema-valid writer report для той же exact repository revision.
