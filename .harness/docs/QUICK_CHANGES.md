# Мелкие изменения без STEP

Не каждое изменение заслуживает отдельного `STEP-NNN`. Harness различает **traceable work** и **micro-change**.

## Когда STEP не нужен

Можно обойтись без STEP, если изменение мало, локально и не меняет продуктовый или технический контракт. Типичные примеры:

- исправить опечатку или пунктуацию;
- поправить комментарий без изменения поведения;
- исправить очевидную формулировку в документации без изменения требования;
- локально отформатировать файл;
- поправить незначительный текст fixture/test description, не меняя сценарий.

В таких случаях нет смысла создавать REQ/ADR/STEP/PLAN/STATUS и искусственную evidence-цепочку. Историей изменения остаётся Git commit.

## Два варианта

### Агент делает правку

```text
PROJECT QUICK FIX: исправь опечатку «авторизция» в форме входа
```

Агент проверяет, что изменение действительно micro-change, выполняет его и предлагает `GIT COMMIT`.

### Пользователь уже исправил вручную

Просто выполни:

```text
GIT CHECK
GIT COMMIT
```

`GIT COMMIT` обязан проверить diff. Если изменение соответствует micro-change policy, отсутствие STEP допустимо.

## Когда PROJECT QUICK FIX запрещён

Создай `STEP ADD:` вместо PROJECT QUICK FIX, если изменение затрагивает хотя бы одно из следующего:

- поведение продукта;
- API/public contract;
- database/schema/migrations;
- auth/security/permissions/secrets;
- dependency или новый technology/tool;
- architecture boundary;
- существенную test strategy;
- несколько модулей/несвязанных файлов;
- requirement/acceptance criteria;
- риск регрессии, который требует отдельного review/evidence.

Если во время PROJECT QUICK FIX выяснилось, что scope больше ожидаемого, агент **не расширяет его молча**: он останавливается и предлагает `STEP ADD: ...`.

## Commit message

Для micro-change обычно подходят `docs`, `fix`, `style`, `test` или `chore` — по фактическому diff. `Traceability` в commit body может быть `N/A: PROJECT QUICK FIX`.
