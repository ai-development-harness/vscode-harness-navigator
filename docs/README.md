# Документация проекта

После `PROJECT INIT` этот каталог становится project knowledge base.

## Продуктовые документы

- `PROJECT.md` — назначение, пользователи, границы, цели и ограничения проекта.
- `requirements/REQ-NNN-*.md` — канонические продуктовые требования.
- `requirements/SPEC.md` — index projection REQ.
- `requirements/STATUS.md` — lifecycle projection REQ.
- `architecture.md` — текущий архитектурный baseline.
- `adr/` — immutable history устойчивых архитектурных решений.
- `development.md` — команды, environments, testing/build conventions после появления кода.
- `OPEN_QUESTIONS.md` — нерешённые вопросы, которые нельзя молча угадывать.
- `GLOSSARY.md` — продуктовые/доменные термины конкретного проекта.
- `skills/` — provenance/registry дополнительных project/technology skills.

## Документация Harness

Документация самого AI Development Harness находится отдельно от project knowledge base — в [`.harness/docs/`](../.harness/docs/README.md).

Начни с:

- [`.harness/docs/README.md`](../.harness/docs/README.md) — оглавление;
- [`.harness/docs/DOCUMENT_MODEL.md`](../.harness/docs/DOCUMENT_MODEL.md) — связи REQ/ADR/STEP/PLAN/STATUS/Evidence/Review;
- [`.harness/docs/GLOSSARY.md`](../.harness/docs/GLOSSARY.md) — определения терминов Harness.

Product-specific subsystem docs добавляются по мере появления устойчивых подсистем. Не создавай десятки пустых файлов во время INIT без необходимости.
