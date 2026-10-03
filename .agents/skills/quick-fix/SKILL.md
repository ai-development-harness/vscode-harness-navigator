---
name: quick-fix
description: Handle semantically low-risk micro-changes without creating STEP/REQ/ADR when no product, architecture, data, API or security contract changes.
---
# quick-fix

Используй для `PROJECT QUICK FIX: <описание>`.

## Когда допустимо

PROJECT QUICK FIX подходит только для изменения с низким semantic risk, которое одновременно:

- не меняет product behavior/contract;
- не меняет public API/schema/persistence/security/permissions;
- не вводит новую dependency/technology;
- не требует отдельного архитектурного решения;
- не нуждается в traceability через REQ/STEP/ADR;
- можно проверить пропорциональными локальными gates.

Критерий — **смысл и риск, а не число строк/файлов**. Любая правка, меняющая REQ behavior intent, ADR decision/rationale, STEP Scope/Acceptance, OQ resolution или Project Principle, **не является QUICK FIX**, даже если это одна строка. Механическая generated/formatting правка может затронуть много файлов и оставаться QUICK FIX, а однострочное изменение authorization/API behavior QUICK FIX уже не является.

Примеры: typo, пунктуация, безопасная правка комментария/документа, локальное formatting, механическое изменение без semantic effect, очевидная корректировка текста без изменения смысла.

## Выполнение

1. Прочитай `AGENTS.md`, затем `AGENTS.local.md`, если существует.
2. Убедись, что запрос соответствует критериям PROJECT QUICK FIX. Если изменение затрагивает behavior/API/data/security/architecture/dependency либо требует нетривиального design choice — остановись и предложи `STEP ADD: ...`.
3. Используй `mechanic` или минимально подходящего write-agent; QUICK FIX не должен становиться способом обойти reasoning, необходимый для реального product change.
4. Меняй только минимально необходимый semantic scope, даже если механически затронуто несколько файлов.
5. Не создавай/не обновляй REQ, ADR, STEP, PLAN, STATUS только ради мелкой правки.
6. Запусти пропорциональные проверки: format/targeted test/validator там, где они реально нужны.
7. Если по ходу выяснилось, что правка перестала быть low-risk, остановись до дальнейшего расширения scope и предложи `STEP ADD: ...`.
8. Верни краткий diff-summary и рекомендуй `GIT COMMIT`.

Если пользователь уже вручную сделал такую правку, отдельный PROJECT QUICK FIX не нужен: `GIT CHECK`/`GIT COMMIT` могут принять её как micro-change без STEP после проверки тех же критериев.
