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
2. Используй только phase `context`, уже возвращённый canonical dispatcher handoff. `context.contextContract.required` задаёт минимальные artifact sections; затем прочитай exact diff/code/tests, необходимые для review. Не preload-ь unrelated docs/REQ/ADR. Дополнительный context требует explicit expansion reason. Legacy `readPaths` остаётся compatibility surface и не означает чтение файла целиком. `deterministic.specializedReviewGate` содержит exact gate, а `deterministic.repositoryRevision` — exact revision. Повторно `step-context.py`/resolver/gates не вызывай и revision вручную не восстанавливай. Модель может добавить reviewer, но не убрать required.
   `deterministic.implementationBaseline` — durable proof HEAD до первой product mutation. При валидном proof gate использует `surfaceMode=implementation-baseline` и проверяет полный `baseline..HEAD + current worktree`; rename/copy учитываются по source и destination path, это работает после нескольких commit, push/PR и restart. Если proof отсутствует/недоступен/non-ancestor, gate явно использует `clean-tree-fallback` и fail-closed требует `security` + `tests`. Harness-owned `.harness/local/**` и `REVIEW-*.md` не меняют surface/basis.
3. До semantic convergence judgement запусти `python3 .harness/tools/completion-gate.py STEP-NNN --json`. Это deterministic precheck текущего Verification evidence/contract basis и Ready prerequisites. `BLOCKED` не переинтерпретируй reasoning-ом.
   Если Ready plan содержит `plan.execution_groups`, также прочитай `python3 .harness/tools/execution-groups.py STEP-NNN --json`: проверь implementation/evidence относительно group `mutationPaths` и `verificationResponsibilities`. Это не второй code review и не разрешение parallel execution.
4. Независимый reviewer сверяет task/REQ/ADR/OQ/architecture refs/Implementation plan и applicable active Project Principles с реализацией и tests. Правила повторно берутся из canonical `sources.principles`, а не из памяти prompt/session. Нарушение blocking PRN без explicit approved deviation — material finding; advisory PRN само по себе не превращай в blocker. Сделай один полный semantic code-review проход exact revision и собери material findings; completion не является вторым code review.
5. Верни structured payload Review Contract v2:
   - `verdict: pass|fail|blocked`;
   - `findings[]` — полный factual contract:
     - `title`, `severity`, `category`;
     - `location: {path, line|null}`;
     - `scenario: {given, when, then}`;
     - `expected`, `observed`, `impact`;
     - `repair: {direction, admissibleAlternatives[]}`;
     - `constraints[]`, `evidence[]`;
   - `verificationObservations`;
   - `rationale`;
   - `specializedReviews.security/tests` только для реально выполненных specialized reviews: `status + evidence`;
   - при `verdict: pass` обязательно добавь `completion`:
     - `disposition: pass|fix|blocked`;
     - `coverage[]` — exact criteria из `## Acceptance criteria`, status `covered|missing`, evidence;
     - `assertions.requirementObligations / plannedScope / specializedObligations` — `covered|missing|not_applicable` + evidence;
     - `findings[]` — structured `kind / criterion|null / message`; `id=COMP-NNN` и route writer присваивает детерминированно.
     `fix` допустим только для missing work внутри текущего scope; contract/prerequisite gap → `blocked`. Out-of-scope obligations не добавляй.

   `id` и `fingerprint` модель не придумывает: writer присваивает `F-NNN` и вычисляет stable `sha256:` fingerprint из factual identity finding. Title/prose formatting и repair wording не участвуют в identity, поэтому повтор того же дефекта после FIX распознаётся детерминированно.
6. Categories:
   - `implementation` — реализация/тест не соответствует непротиворечивому contract;
   - `evidence` — acceptance недостаточно доказан;
   - `contract` — STEP/REQ/ADR/dependency/Acceptance противоречив или требует отсутствующего решения.
7. Routing:
   - `pass` — findings нет;
   - `fail` — implementation/evidence findings, исправимые внутри scope;
   - `blocked` — contract defect/missing prerequisite либо blocking evidence condition.
8. Не создавай review Markdown//frontmatter, timestamp, revision или gate metadata вручную. Передай JSON в:

   ```bash
   python3 .harness/tools/semantic-writer.py step-review STEP-NNN --payload-file '<local-json-or->'
   ```

   Dispatcher до reasoning сохраняет exact repository revision + gate basis в active execution. Writer повторно вычисляет factual revision/gate и **отказывается создавать report**, если они отличаются от stamped expectation; модель не передаёт и не выбирает expected revision. После совпадения writer требует результаты mandatory reviewers, создаёт immutable report через exclusive reservation и проверяет его canonical validator-ом.
   Writer сохраняет findings дважды в одном immutable report: human-readable `## Findings` и canonical `## Machine-readable findings` (Review Contract v2). Validator сверяет обе формы; malformed/duplicate/fingerprint-mismatch fail-closed.
   Execution result бери только из `completionResult` writer-а (`PASS|FAIL|BLOCKED`); не вычисляй verdict второй раз после записи report.
   Для semantic PASS writer сам выполняет lifecycle close `status → completed`, доказывает type-specific completion proof и синхронизирует projections. Если proof недостаточен, PASS report остаётся immutable evidence, STEP не закрывается, а `completionResult=BLOCKED`.
9. Product code не исправляй. При BLOCKED укажи corrective STEP/RESEARCH/ADR в semantic finding/rationale; contract defect не маршрутизируй в FAIL→FIX.

Crash recovery доверяет только schema-valid writer report для той же exact repository revision.
