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
3. До semantic convergence judgement запусти `python3 .harness/tools/completion-gate.py STEP-NNN --json`. Если STEP Verification содержит `- product: FEATURE-*`, generated Verification PASS уже обязан включать валидированное real-product observation: current qualified driver bytes, current feature-map/source basis и evidence files из `.harness/local/product-verification/**`. Stale/broken driver или stale feature map являются evidence blocker и не могут быть переинтерпретированы reviewer-ом. Это deterministic precheck текущего Verification evidence/contract basis и Ready prerequisites. `BLOCKED` не переинтерпретируй reasoning-ом.
   Если Ready plan содержит `plan.execution_groups`, также прочитай `python3 .harness/tools/execution-groups.py STEP-NNN --json`: проверь implementation/evidence относительно group `mutationPaths` и `verificationResponsibilities`. Это не второй code review и не разрешение parallel execution.
   Затем выполни `python3 .harness/tools/semantic-blast-radius.py STEP-NNN --phase review --json`. Если `required=true`, повторно используй validated grounding на exact reviewed revision и запусти core capability `semantic-blast-radius`. REVIEW `pass` запрещён, пока blast-radius validator не вернул `PASS`: critical hypotheses должны иметь `proven` proof через реально существующие STEP Verification commands и fresh generated Verification PASS. `INCONCLUSIVE` из-за missing/stale executable proof — evidence finding, а не safety PASS. Blast proof проверяет fresh PASS **exact proof commands**; unrelated pending manual Verification checks остаются отдельным blocker существующего completion gate и не считаются закрытыми blast-radius capability.
4. Перед lead semantic code-review проверь optional High-Rigor Interrogate:
   ```bash
   python3 .harness/tools/high-rigor.py --mode interrogate --phase review --step STEP-NNN --json
   ```
   Если preflight вернул `RUN`, internal `high-rigor` обязан дать configured independent readonly reviewers **один exact review surface + intent + rubric**, сохранить consensus и disagreements и затем вернуть validated lead synthesis. Interrogate не заменяет Completion Gate, Semantic Blast Radius или mandatory security/test reviewers; consensus не является proof. `DEGRADED` раскрой в rationale/evidence и продолжай только ordinary review gates. При `SKIP` fan-out не выполняй.
5. Независимый lead reviewer сверяет task/REQ/ADR/OQ/architecture refs/Implementation plan и applicable active Project Principles с реализацией и tests. Правила повторно берутся из canonical `sources.principles`, а не из памяти prompt/session. Нарушение blocking PRN без explicit approved deviation — material finding; advisory PRN само по себе не превращай в blocker. Если Interrogate выполнялся, используй его consensus/disagreement map как adversarial input, но categorization/verdict остаются ответственностью lead reviewer. Material означает, что finding меняет observable implementation behaviour, нарушает Accepted ADR/REQ/STEP contract, создаёт security/correctness/regression risk или оставляет обязательный acceptance/prerequisite без доказуемого owner/path. Wording/style/clarity notes без такого эффекта не являются findings: помести их в rationale.
   Перед тем как превратить новую reviewer-derived идею в finding, примени **Evidence Gate**:
   - прямое доказанное нарушение REQ/ADR/STEP/PRN может использовать `evidenceBasis.kind=contract`;
   - уже воспроизведённый defect — `kind=reproduced`;
   - новый придуманный reviewer-ом failure/security scenario сначала является только hypothesis с `kind=inferred`;
   - для inferred hypothesis перечисли необходимые preconditions и проверь их по реальному repository/runtime state;
   - если практичен маленький решающий эксперимент, сначала выполни самый дешёвый falsification check: HTTP request, проверка mount/route/config, минимальный function call или существующий test;
   - actively пытайся опровергнуть собственную гипотезу, а не только найти ей подтверждение;
   - framework capability сама по себе не доказывает project reachability;
   - для security scenario нужен project-specific reachable path от entry point/trust boundary до asset/effect;
   - invalidated/unverified hypothesis **не является finding**, не должна запускать FIX и не требует отдельного durable artifact; при полезности кратко упомяни её в rationale;
   - не требуй regression test до подтверждения inferred scenario и не расширяй подтверждённый defect на экзотические adjacent cases без отдельного contract/evidence.
   Если STEP Acceptance содержит measurable performance claim либо Evidence Gate подтвердил performance finding, подключи internal `benchmark-methodology`. Проверь raw benchmark evidence deterministic tool-ом `.harness/tools/benchmark-methodology.py`: exact command/environment/revision, correctness counts, repeated samples, work proof, observed variation, bottleneck/sanity/end-to-end relevance. Один/два run или effect внутри observed variation дают `INCONCLUSIVE`, а не regression/improvement finding. Если performance Acceptance зависит от claim, reviewer не может выдать PASS при `INCONCLUSIVE`; `microbenchmark-only` evidence не доказывает end-to-end claim.
   Сделай один полный semantic code-review проход exact revision и собери все material **evidence-gated** findings; completion не является вторым code review.
6. Верни structured payload Review Contract v3:
   - `verdict: pass|fail|blocked`;
   - `findings[]` — полный factual contract:
     - `title`, `severity`, `category`;
     - `location: {path, line|null}`;
     - `scenario: {given, when, then}`;
     - `expected`, `observed`, `impact`;
     - `repair: {direction, admissibleAlternatives[]}`;
     - `constraints[]`, обязательный непустой `evidence[]`;
     - обязательный `evidenceBasis`:
       - `kind: contract|reproduced|inferred`;
       - `source` — конкретный contract/reproducer/hypothesis origin;
       - `preconditions[]` — для `inferred` минимум одна реально проверенная предпосылка;
       - `verification: {method, result, outcome: confirmed}`.
       Writer принимает только `outcome=confirmed`; invalidated hypothesis в `findings[]` передавать запрещено.
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
7. Categories:
   - `implementation` — реализация/тест не соответствует непротиворечивому contract;
   - `evidence` — acceptance недостаточно доказан;
   - `contract` — STEP/REQ/ADR/dependency/Acceptance противоречив или требует отсутствующего решения.
8. Routing:
   - `pass` — findings нет;
   - `fail` — implementation/evidence findings, исправимые внутри scope;
   - `blocked` — contract defect/missing prerequisite либо blocking evidence condition.
9. Не создавай review Markdown//frontmatter, timestamp, revision или gate metadata вручную. Передай JSON в:

   ```bash
   python3 .harness/tools/semantic-writer.py step-review STEP-NNN --payload-file '<local-json-or->'
   ```

   Dispatcher до reasoning сохраняет exact repository revision + gate basis в active execution. Writer повторно вычисляет factual revision/gate и **отказывается создавать report**, если они отличаются от stamped expectation; модель не передаёт и не выбирает expected revision. После совпадения writer требует результаты mandatory reviewers, создаёт immutable report через exclusive reservation и проверяет его canonical validator-ом.
   Writer сохраняет findings дважды в одном immutable report: human-readable `## Findings` и canonical `## Machine-readable findings` (Review Contract v3). Validator сверяет обе формы; malformed/duplicate/fingerprint-mismatch fail-closed.
   Execution result бери только из `completionResult` writer-а (`PASS|FAIL|BLOCKED`); не вычисляй verdict второй раз после записи report.
   Для semantic PASS writer сам выполняет lifecycle close `status → completed`, доказывает type-specific completion proof и синхронизирует projections. Если proof недостаточен, PASS report остаётся immutable evidence, STEP не закрывается, а `completionResult=BLOCKED`.
10. Product code не исправляй. При BLOCKED укажи corrective STEP/RESEARCH/ADR в semantic finding/rationale; contract defect не маршрутизируй в FAIL→FIX.

Crash recovery доверяет только schema-valid writer report для той же exact repository revision.
