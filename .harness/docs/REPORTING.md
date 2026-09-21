# Completion Reports

Каждая команда должна завершаться коротким, но пригодным для следующего действия отчётом.

## PROJECT INIT

- project name/summary;
- созданные REQ/ADR/STEP и их количество;
- ключевые архитектурные решения;
- unresolved OPEN_QUESTIONS;
- roadmap phases и critical dependencies;
- рекомендуемый agent profile;
- requirements/roadmap semantic review reports + deterministic consistency result;
- следующая команда.

## ADD / PLAN / IMPLEMENT / FIX

- STEP;
- изменённые canonical artifacts;
- blockers/risks;
- verification result, если применимо;
- следующая команда.

## REVIEW

- schema-valid report path;
- exact reviewed revision;
- verdict;
- blocking findings по severity/category;
- deterministic specialized-review requirements/results;
- следующая команда (`FIX`, blocker action или next step).

## RECONCILE / RELEASE CHECK

- report path;
- найденный drift/blockers;
- созданные corrective STEP;
- verdict/следующее действие.

Не вставляй в completion report длинный пересказ task/REQ/ADR. Durable details уже находятся в repository artifacts.

## GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT SYNC

- current branch/upstream;
- Harness validation result;
- suspicious/unrelated files or blockers;
- для GIT COMMIT: hash, subject, included files, verification/traceability;
- для GIT PUSH: remote branch, push result, ahead/behind state;
- для `GIT PR`: URL либо точный blocker;
- следующая безопасная команда.

Не скрывай partial success: например, если push прошёл, а PR создать не удалось, сообщи оба результата отдельно.
