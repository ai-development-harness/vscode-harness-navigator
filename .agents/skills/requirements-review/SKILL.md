---
name: requirements-review
description: Review requirements for clarity, testability, duplication, conflicts and traceability without turning implementation details into product contracts.
---
# requirements-review

Human-readable review prose пиши на `.harness/manifest.yaml → language.documentation` с fallback на `language.default`; machine schema не локализуй.

Проверяй canonical REQ из configured `sources.requirements` как единый набор product/system contracts, а не по одному файлу в изоляции. `SPEC.md` и `STATUS.md` внутри configured requirements directory — deterministic projections, не competing source requirement definition. Canonical Open Questions бери из `sources.openQuestions`; `sources.openQuestionsIndex` — projection.

Обязательная semantic review должна искать:

- дубликаты, overlap и взаимоисключающие требования;
- противоречия Acceptance между REQ;
- неявные обязательства из project constraints/architecture, которым не соответствует ни один REQ;
- requirement, который нельзя наблюдаемо проверить;
- конфликт REQ с Accepted ADR или architecture baseline;
- конфликт linked REQ с Goal/Scope/Out of scope/Acceptance конкретного STEP;
- конкурирующее ownership одной и той же mutation между STEP без dependency/границы;
- missing dependency, если один STEP фактически требует результата другого;
- OPEN question/TBD, без решения которого нельзя честно сформировать executable STEP.

Новый REQ нужен только когда меняется требуемое поведение/качество продукта или обязательный system contract. Технический refactor/bug correction может ссылаться на existing REQ или быть purely corrective task.

Результат review классифицируй:

- `PASS` — contracts достаточно согласованы для следующей planning phase;
- `BLOCKED` — есть semantic contradiction, missing decision/prerequisite или непроверяемый contract; не маскируй это implementation details.

Не исправляй неоднозначность догадкой. Для отсутствующего решения используй OPEN_QUESTION либо prerequisite RESEARCH/ADR STEP.
