# Глоссарий проекта

Этот файл предназначен для **доменных и продуктовых терминов конкретного проекта** и заполняется/обновляется после `PROJECT INIT`.

Термины самого AI Development Harness (`REQ`, `ADR`, `STEP`, `Evidence`, `Projection`, `Drift`, `Gate` и т. п.) определены отдельно:

- [`.harness/docs/GLOSSARY.md`](../.harness/docs/GLOSSARY.md)

Добавляй сюда термин только если его единое значение важно для требований, архитектуры, UX или реализации конкретного продукта.

| Термин | Определение | Связанные REQ/ADR | Примечание |
|---|---|---|---|
| Harness-aware file | Markdown-файл в текущем Harness workspace, в котором Navigator применяет semantic navigation: canonical artifact, configured projection, project knowledge/planning Markdown, `.harness/**/*.md` или другой Markdown этого workspace. | REQ-005 | Markdown вне Harness workspace исключён. |
| Artifact Index | Read-only in-memory индекс canonical STEP, REQ, ADR и OQ с metadata, status и relations. | REQ-003, ADR-002 | Единственный источник artifact data для consumers расширения. |
| Reference Index | Read-only in-memory индекс упоминаний Harness ID в Harness-aware files. | REQ-006, ADR-002 | Используется для backlinks, references, diagnostics и navigation. |
| Command Catalog | Read-only derived каталог canonical Harness-команд из command graph. | REQ-007, ADR-003 | Не запускает команды. |
