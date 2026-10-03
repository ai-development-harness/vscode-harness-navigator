---
name: documentation-sync
description: Synchronize documentation and traceability from verified implementation while preserving accepted product and architecture contracts as authoritative.
---
# documentation-sync

Обновляй только затронутые docs после подтверждённой реализации.

## Source hierarchy

- Фактические code/tests/evidence подтверждают **что реализовано**.
- Canonical REQ определяют **какое product/system behavior требуется**.
- Accepted ADR/architecture определяют **какие durable решения обязательны**.
- STEP/review/evidence определяют traceability и состояние конкретной работы.

Не «синхронизируй документацию под код», если реализация расходится с Accepted REQ/ADR. Такое расхождение — finding/corrective work либо отдельное решение об изменении contract, а не основание молча переписать requirement/ADR.

## Workflow

1. Все project paths бери из manifest.
2. Определи только реально затронутую документацию и traceability.
3. Не придумывай API/behavior, которых нельзя доказать code/tests/evidence или accepted contract.
4. Обновляй relevant subsystem docs и разрешённую canonical traceability. Accepted ADR immutable; изменение durable decision оформляется через новый ADR.
5. Не редактируй PLAN/STATUS/requirements SPEC+STATUS/Open Questions index вручную.
6. Пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
7. Для механической части используй `docs` agent; semantic conflict между implementation и contract не поручай ему «исправить текстом».
