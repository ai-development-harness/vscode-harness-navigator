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
   - STEP в `protocol.taskDirectory`.
   Machine keys/enums frontmatter всегда protocol-English и не локализуются.
5. Удали pre-init `REQ-001-template.md`, когда появились реальные требования. Не редактируй projection-файлы вручную.
6. До roadmap передай candidate requirements отдельному `reviewer` agent/session, отличному от initializer, и выполни semantic requirements review по `requirements-review`. Получи точный basis:
   ```bash
   python3 .harness/tools/planning-state.py init-basis requirements
   ```
   Сохрани immutable schema-v1 report `INIT-REVIEW-<UTC timestamp>.md` в configured `protocol.initReviewDirectory` по template с `reviewer_role: reviewer`. PASS обязан ссылаться на текущий basis. Если остаётся существенное contradiction/missing decision — создай canonical OQ с `affects: PROJECT` либо prerequisite work и верни BLOCKED.
7. Построй canonical STEP roadmap по dependencies. Для каждого STEP заполни strict frontmatter refs, `architecture_refs`, `risk_flags`, contract sections и mutation policy. `plan.status=not_planned`.
8. Передай candidate roadmap отдельному `reviewer` agent/session и выполни независимый roadmap consistency review: REQ↔REQ, REQ↔ADR, STEP↔REQ, contract↔Acceptance, ownership, dependencies/completion prerequisites, architecture refs, OQ и Verification. Получи basis:
   ```bash
   python3 .harness/tools/planning-state.py init-basis roadmap
   ```
   Сохрани второй immutable INIT report с `stage: roadmap`.
9. Обеспечь двустороннюю traceability REQ↔STEP и ADR↔STEP. Project-level OPEN OQ нельзя обходить.
10. Пересобери tracked projections:
    ```bash
    python3 .harness/tools/sync-projections.py
    ```
11. Обнови generated project blocks README/AGENTS и другие разрешённые INIT artifacts. После **всех** candidate mutations запусти:
    ```bash
    python3 .harness/tools/validate.py --mode manual
    ```
12. Только после PASS atomically заверши INIT:
    ```bash
    python3 .harness/tools/finalize-project-init.py --name '<project-name>'
    ```
    Нельзя вручную выставлять `project.initialized=true`: finalizer повторно проверяет projections, active schema, оба semantic PASS report и INIT postconditions.
13. Не создавай production code. Product-specific CI проектируй отдельным STEP после появления реального tooling.

Если semantic review после одного исправляющего прохода всё ещё BLOCKED, заверши INIT как BLOCKED. Не запускай внутренний бесконечный цикл.
