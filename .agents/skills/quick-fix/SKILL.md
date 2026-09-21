---
name: quick-fix
description: Handle tiny low-risk changes without creating STEP/REQ/ADR when no product, architecture, data, API or security contract changes.
---
# quick-fix

Используй для `PROJECT QUICK FIX: <описание>`.

## Когда допустимо

PROJECT QUICK FIX подходит только для маленького локального изменения, которое одновременно:

- не меняет product behavior/contract;
- не меняет public API/schema/persistence/security/permissions;
- не вводит новую dependency/technology;
- не требует отдельного архитектурного решения;
- не нуждается в traceability через REQ/STEP/ADR;
- можно проверить пропорциональными локальными gates.

Примеры: typo, пунктуация, безопасная правка комментария/документа, локальное formatting, очевидная корректировка текста без изменения смысла.

## Выполнение

1. Прочитай `AGENTS.md`, затем `AGENTS.local.md`, если существует.
2. Убедись, что запрос соответствует критериям PROJECT QUICK FIX. Если нет — остановись и предложи `STEP ADD: ...`.
3. Используй `mechanic` или минимально подходящего write-agent.
4. Меняй только минимально необходимый набор файлов.
5. Не создавай/не обновляй REQ, ADR, STEP, PLAN, STATUS только ради мелкой правки.
6. Запусти пропорциональные проверки: формат/targeted test/validator там, где они реально нужны.
7. Верни краткий diff-summary и рекомендуй `GIT COMMIT`.

Если пользователь уже вручную сделал такую правку, отдельный PROJECT QUICK FIX не нужен: `GIT CHECK`/`GIT COMMIT` могут принять её как micro-change без STEP после проверки критериев.
