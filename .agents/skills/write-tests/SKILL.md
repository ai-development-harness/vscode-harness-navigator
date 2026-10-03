---
name: write-tests
description: Design and implement the smallest reliable set of tests that proves acceptance behavior and regressions at the appropriate level using the project's real test stack.
---
# write-tests

Сначала изучи фактический test framework, project conventions и существующие команды/targets. Не изобретай test command, framework или fixture API.

## Выбор уровня

Выбирай **самый низкий уровень теста, который честно доказывает нужное behavior**:

- unit — чистая локальная логика и изолируемые contracts;
- integration — взаимодействие модулей, persistence, serialization, network/storage adapters и другие реальные boundaries;
- e2e/system — пользовательский/операционный flow, если acceptance зависит именно от сквозной интеграции.

Не заменяй integration/e2e доказательство unit-тестом с моками, если acceptance проверяет реальную boundary.

## Workflow

1. Свяжи тесты с Acceptance criteria, regression scenario или подтверждённым finding.
2. При bugfix по возможности сначала воспроизведи defect failing test на уровне, где он реально проявляется.
3. Добавь positive path и только релевантные negative/edge/concurrency/migration cases; не раздувай suite абстрактным checklist.
4. Используй реальные fixtures/helpers/conventions проекта.
5. Тест должен проверять observable behavior, а не случайную внутреннюю реализацию.
6. Выполни только существующие подходящие test commands/targets либо оставь запуск canonical Verification dispatcher-у, если workflow уже владеет им.
