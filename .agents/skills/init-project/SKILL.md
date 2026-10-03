---
name: init-project
description: Bootstrap a new repository from the configured local brief into a durable, versioned project knowledge base and initial roadmap.
---
# init-project

Используй для `PROJECT INIT`. Project docs, REQ/ADR/STEP/OQ и human-readable INIT review prose пиши на `language.documentation` с fallback на `language.default`; structural headings и machine schema сохраняй protocol-stable.

1. Прочитай `.harness/manifest.yaml`. Все project paths бери из `sources.*` / `protocol.*`; не подменяй configurable path canonical default-ом. Язык human-readable content бери через `language.<domain>` с fallback на `language.default`. Если `project.initialized=true`, остановись и предложи `PROJECT RECONCILE`.
2. Прочитай configured `sources.localBrief`; после общих repository instructions также прочитай `AGENTS.local.md`, если он существует.
3. Изучи доступные референсы. Недоступный источник не заменяй предположением.
4. Создай draft active documents в schema v1 с YAML frontmatter:
   - configured project overview;
   - canonical REQ в `sources.requirements`;
   - минимальный architecture baseline;
   - canonical OQ в `sources.openQuestions`;
   - ADR в `sources.adrDirectory` только для устойчивых решений;
   - PRN в `sources.principles` только для действительно project-wide инженерных инвариантов; preference/coding style не превращай в principle;
   - STEP в `protocol.taskDirectory`.
   Machine keys/enums frontmatter всегда protocol-English и не локализуются.
5. Удали pre-init `REQ-001-template.md`, когда появились реальные требования. Не редактируй projection-файлы вручную.
6. До requirements review выполни Requirements Quality Gate: систематически проверь применимые functional/data/UX/NFR/integration/acceptance dimensions. Сначала ищи ответ в уже существующих REQ/ADR/OQ/architecture/codebase. Сформируй schema-v1 payload и проверь его через `python3 .harness/tools/requirements-quality.py --payload-file '<local-json-or->'`. Blocking ambiguity => targeted user question; ответ обязательно сохрани в canonical REQ/ADR/OQ/STEP и повтори gate. Non-blocking stylistic warnings не блокируют INIT.
7. До roadmap передай candidate requirements отдельному `reviewer` agent/session, отличному от initializer, и выполни semantic requirements review по `requirements-review`. Получи точный basis:
   ```bash
   python3 .harness/tools/planning-state.py init-basis requirements
   ```
   Сохрани immutable schema-v1 report `INIT-REVIEW-<UTC timestamp>.md` в configured `protocol.initReviewDirectory` по template с `reviewer_role: reviewer`. PASS обязан ссылаться на текущий basis. Если остаётся существенное contradiction/missing decision — создай canonical OQ с `affects: PROJECT` либо prerequisite work и верни BLOCKED.
8. Перед roadmap проверь candidate Project Principles: создавай PRN только для global cross-cutting engineering invariant, применимого к множеству будущих решений. Product behavior оставляй в REQ, конкретный architecture choice — в ADR, coding-style preference — в обычных project instructions. Applicable blocking PRN нельзя обходить без explicit approved deviation.
9. Перед roadmap выполни architecture completeness pass по подтверждённым brief/REQ/Accepted ADR: системные boundaries/ownership, persistence/migrations/compatibility, API/protocol contracts, security/trust boundaries, async/state/concurrency, extension/integration contracts, observability/recovery и deployment/update constraints. Неприменимые измерения не выдумывай. Material missing durable decision оформи как ADR prerequisite или OPEN OQ с `affects: PROJECT`; не прячь неизвестность в будущий STEP.
10. Для architecture-sensitive baseline передай requirements + architecture context отдельному read-only `architect` agent/session. Его задача — найти hidden coupling, incompatible boundary и missing durable decision до roadmap. Material unresolved issue => BLOCKED.
11. Построй canonical STEP roadmap по dependencies. Для каждого STEP заполни strict frontmatter refs, `architecture_refs`, `risk_flags`, contract sections и mutation policy. `plan.status=not_planned`.
12. Передай candidate roadmap отдельному `reviewer` agent/session и выполни независимый roadmap consistency review: REQ↔REQ, REQ↔ADR, STEP↔REQ, contract↔Acceptance, ownership, dependencies/completion prerequisites, architecture refs, OQ и Verification. Получи basis:
   ```bash
   python3 .harness/tools/planning-state.py init-basis roadmap
   ```
   Сохрани второй immutable INIT report с `stage: roadmap`.
13. Обеспечь двустороннюю traceability REQ↔STEP и ADR↔STEP. Project-level OPEN OQ нельзя обходить.
14. Пересобери tracked projections:
    ```bash
    python3 .harness/tools/sync-projections.py
    ```
15. Обнови generated project blocks README/AGENTS и другие разрешённые INIT artifacts. После **всех** candidate mutations запусти:
    ```bash
    python3 .harness/tools/validate.py --mode manual
    ```
16. Только после PASS atomically заверши INIT:
    ```bash
    python3 .harness/tools/finalize-project-init.py --name '<project-name>'
    ```
    Нельзя вручную выставлять `project.initialized=true`: finalizer повторно проверяет projections, active schema, оба semantic PASS report и INIT postconditions.
17. Не создавай production code. Product-specific CI проектируй отдельным STEP после появления реального tooling.

Если semantic review после одного исправляющего прохода всё ещё BLOCKED, заверши INIT как BLOCKED. Не запускай внутренний бесконечный цикл.
