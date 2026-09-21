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
2. Получи минимально обязательные specialized reviewers:
   ```bash
   python3 .harness/tools/review_gates.py STEP-NNN --json
   ```
   `auto` определяется детерминированно по risk flags, STEP type и factual changed surface; `always` обязателен всегда. Canonical workflow REVIEW выполняется до Git publication. Если worktree уже clean после внешних/manual commits и exact implementation baseline недоступен, preselector помечает `surfaceMode=clean-tree-fallback` и fail-closed требует security + tests вместо доверия только последнему commit. Модель может добавить reviewer, но не убрать обязательный. Сохрани из результата exact `basis` и список `required` — это durable proof решения preselector.
3. Получи точную revision:
   ```bash
   python3 .harness/tools/planning-state.py review-revision
   ```
   Для dirty tree report фиксирует `git_head + worktree_hash`; для clean tree достаточно `git_head`.
4. Независимый reviewer сверяет task/REQ/ADR/OQ/architecture refs/Implementation plan с реализацией и tests. Сделай полный проход текущей revision и собери все material findings.
5. Categories:
   - `implementation` — реализация/тест не соответствует непротиворечивому contract;
   - `evidence` — acceptance недостаточно доказан;
   - `contract` — сам STEP/REQ/ADR/dependency/Acceptance противоречив или требует отсутствующего решения.
6. Routing:
   - `pass` — findings нет;
   - `fail` — есть implementation/evidence findings, исправимые внутри scope;
   - `blocked` — есть contract defect/missing prerequisite/stale planning context либо blocking evidence condition, которую нельзя безопасно исправить внутри текущего STEP.
7. Создай новый immutable schema-v1 report `REVIEW-<UTC timestamp>.md` в configured `protocol.reviewDirectory/STEP-NNN/`. Каждый finding обязан иметь Severity, Category, Location, Scenario, Impact, Fix direction. В `specialized_reviews.gate_basis` и `specialized_reviews.required` запиши exact значения preselector; статусы security/tests обязаны им соответствовать. Для выполненного specialized review заполни `security_evidence` / `tests_evidence` конкретной краткой сводкой или ссылкой на реально существующее durable evidence. Это evidence reference/summary, а не автоматически доверенный filesystem path.
8. До completion проверь report:
   ```bash
   python3 .harness/tools/review_contract.py --file '<report-path>' --current-revision
   ```
   Невалидный report нельзя использовать как verdict.
9. Product code не исправляй. При BLOCKED укажи corrective STEP/RESEARCH/ADR; не отправляй contract defect в FAIL→FIX.

Crash recovery доверяет только schema-valid report для той же exact repository revision.
