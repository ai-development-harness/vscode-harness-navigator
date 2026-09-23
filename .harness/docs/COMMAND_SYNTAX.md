# Синтаксис команд Harness

Этот документ определяет каноническую форму пользовательских команд и сокращённый синтаксис последовательного выполнения.

## 1. Каноническая форма

Команда начинается с явной области:

```text
<DOMAIN> <OPERATION...> [TARGET] [: free-form input]
```

`OPERATION` может состоять из нескольких слов, например в `HARNESS UPDATE CHECK` или `PROJECT QUICK FIX`.

Канонические области:

- `PROJECT` — lifecycle и maintenance конкретного проекта;
- `STEP` — работа с STEP;
- `SKILL` — поиск, установка и создание repository skills;
- `GITHUB` — GitHub collaboration artifacts;
- `RELEASE` — release gates;
- `HARNESS` — lifecycle самого Harness;
- `GIT` — локальная история и публикация Git.

Примеры:

```text
PROJECT INIT
PROJECT STATUS
PROJECT RECONCILE
PROJECT QUICK FIX: исправить опечатку в README

STEP ADD: добавить экспорт отчётов
STEP LIST
STEP SHOW STEP-NNN
# пример: STEP SHOW STEP-024
STEP NEXT
STEP PLAN STEP-024
STEP IMPLEMENT STEP-024
STEP REVIEW STEP-024
STEP FIX STEP-024
STEP RUN STEP-024
STEP AUDIT STEP-024

SKILL FIND: accessibility review
SKILL INSTALL: #2
SKILL CREATE: проверка миграций

GITHUB GENERATE TEMPLATES

RELEASE CHECK

HARNESS HELP
HARNESS STATUS
HARNESS RESUME
HARNESS DOCTOR
HARNESS CONFIG
HARNESS UPDATE CHECK
HARNESS UPDATE CHECK TO vX.X.X
HARNESS UPDATE APPLY
HARNESS UPDATE APPLY TO vX.X.X

GIT CHECK
GIT COMMIT
GIT COMMIT: обновить документацию Harness
GIT PUSH
GIT PR
GIT PR FINISH
GIT SYNC
```

Для STEP target разрешена сокращённая пользовательская форма только из цифр:

```text
STEP RUN 024
STEP PLAN 024 > IMPLEMENT > REVIEW
```

До transition checks она нормализуется в canonical `STEP-024`. Формы короче трёх цифр и произвольные suffix/prefix не принимаются.

Старые ненеймспейсные формы не являются каноническими alias. Если пользователь хочет локальный alias, он задаётся явно в `AGENTS.local.md`.

## 2. Цепочки

Оператор `>` как отдельный token, окружённый пробелами, означает последовательное выполнение нескольких команд одной области:

```text
<FULL COMMAND> > <ACTION> > <ACTION>
```

Первый сегмент всегда содержит явный DOMAIN. Последующие сегменты могут не повторять тот же DOMAIN.

Примеры:

```text
GIT CHECK > COMMIT > PUSH > PR

STEP PLAN STEP-024 > IMPLEMENT > REVIEW

HARNESS UPDATE CHECK TO vX.X.X > APPLY
```

Полные повторные формы той же области также допустимы, но сокращённая запись предпочтительнее:

```text
GIT CHECK > GIT COMMIT > GIT PUSH
```

эквивалентна:

```text
GIT CHECK > COMMIT > PUSH
```

## 3. Structural validation до интерпретации

Machine-readable source of truth для command surface и переходов:

```text
.harness/command-transitions.json
```

Полная документация матрицы:

```text
.harness/docs/COMMAND_TRANSITIONS.md
```

Canonical command сначала проходит deterministic preflight:

```bash
python3 .harness/tools/validate-command.py --json -- '<raw canonical command>'
```

Порядок обработки фиксирован:

```text
tokenize
→ normalize
→ transition-table
→ runtime-preconditions
→ dispatch
```

До успешного шага `transition-table` запрещены skill routing, command-specific interpretation и mutation.

Если команда или chain структурно невалидны:

- ни один segment не выполняется;
- working tree / Git / Harness artifacts не меняются;
- пользователь получает стабильный structural error code.

Это предотвращает ситуацию, когда первая mutation уже произошла, а ошибка в последнем segment обнаружилась только после неё.

## 4. Наследование области

Внутри цепочки DOMAIN наследуется от первого сегмента. Для семейства `HARNESS UPDATE` также наследуется префикс `UPDATE`, поэтому `> APPLY` означает `HARNESS UPDATE APPLY`.

Например:

```text
GIT CHECK > COMMIT > PUSH > PR
```

означает:

```text
GIT CHECK
GIT COMMIT
GIT PUSH
GIT PR
```

Указание другого DOMAIN после `>` запрещено.

Невалидно:

```text
STEP RUN STEP-024 > GIT COMMIT
```

Для перехода между областями пользователь запускает отдельную команду/цепочку.

## 5. Наследование target

### STEP

После первого explicit STEP target он фиксируется для всей STEP-цепочки.

```text
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
```

означает работу только с `STEP-024`.

Эквивалент:

```text
STEP PLAN STEP-024
STEP IMPLEMENT STEP-024
STEP REVIEW STEP-024
```

Если последующий сегмент указывает другой STEP, вся цепочка невалидна и ничего не выполняется.

### HARNESS UPDATE

Explicit target `TO <tag>` наследуется внутри update chain:

```text
HARNESS UPDATE CHECK TO vX.X.X > APPLY
```

означает:

```text
HARNESS UPDATE CHECK TO vX.X.X
HARNESS UPDATE APPLY TO vX.X.X
```

Указание другого target в `APPLY` делает цепочку невалидной.

### GIT

Git-цепочка не имеет отдельного target; каждый сегмент работает с текущим repository/branch context согласно `.harness/git-policy.toml`.

## 6. Разрешённые цепочки

Цепочки поддерживаются только там, где сокращение не скрывает обязательное пользовательское решение.

### GIT

В chain участвуют только фазы publication pipeline:

```text
GIT CHECK
GIT COMMIT
GIT PUSH
GIT PR
```

`GIT SYNC` остаётся самостоятельной командой.

Пример обычной публикации:

```text
GIT CHECK > COMMIT > PUSH > PR
```

### STEP

Для ручного управления стадиями допустимы:

```text
STEP PLAN STEP-NNN
STEP IMPLEMENT STEP-NNN
STEP REVIEW STEP-NNN
STEP FIX STEP-NNN
```

Пример:

```text
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
```

`STEP RUN STEP-NNN` уже является orchestration-командой и не используется как сегмент цепочки.

`STEP AUDIT STEP-NNN` является самостоятельной audit-командой и не объединяется с mutation flow.

### HARNESS UPDATE

Поддерживается только безопасная пара:

```text
HARNESS UPDATE CHECK [TO <tag>] > APPLY
```

В chain `CHECK > APPLY` сегмент APPLY требует PASS matching CHECK для того же target/route. Standalone `HARNESS UPDATE APPLY [TO <tag>]` допустим и обязан выполнить fresh deterministic validation/preflight самостоятельно.

### Не поддерживаются

Цепочки не используются для:

- `PROJECT` — lifecycle-команды должны оставаться явными;
- `SKILL` — после поиска выбор кандидата должен оставаться отдельным пользовательским решением;
- `GITHUB` — генерация templates является самостоятельной mutation;
- `RELEASE` — release check является самостоятельным gate.

## 7. Переходы между командами

Допустимые переходы **не определяются этим документом**.

Их единственный machine-readable источник:

```text
.harness/command-transitions.json
```

Человекочитаемая полная таблица:

```text
.harness/docs/COMMAND_TRANSITIONS.md
```

Правило закрытого мира:

> Если explicit edge `A → B` отсутствует в transition graph, переход запрещён.

Поэтому существование обеих команд по отдельности не делает их допустимой цепочкой.

Например:

```text
GIT PR > COMMIT
```

даёт `INVALID_CHAIN` до выполнения `GIT PR`, потому что edge `GIT PR → GIT COMMIT` отсутствует.

## 8. Выполнение structurally valid edge

После structural PASS runtime использует metadata edge:

```text
onPreviousResult
runtimePreconditions
```

Следующий segment выполняется только если:

1. существует соответствующий edge;
2. фактический result предыдущей команды входит в `onPreviousResult`;
3. выполнены `runtimePreconditions` edge.

Если edge структурно существует, но runtime precondition не выполнена, это `BLOCKED`, а не `INVALID_CHAIN`.

Если result предыдущего segment не активирует edge, оставшиеся segments = `NOT_EXECUTED`.

Важно: `FAIL` не является универсальной остановкой. Например transition graph разрешает `STEP REVIEW → STEP FIX` именно при review result `FAIL`.

## 9. Независимые executions

CTS и chain syntax не запрещают пользователю после завершения одной команды вызвать любую другую structurally valid standalone command.

Например:

```text
STEP PLAN STEP-001
```

завершилась, после чего пользователь отдельно вызывает:

```text
GIT COMMIT
```

Это две независимые root executions. Переход `STEP PLAN → GIT COMMIT` не ищется и не требуется.

Cross-domain prohibition относится только к **одной строке chain**, например `STEP PLAN STEP-001 > GIT COMMIT`.

Execution tracking описан в [`EXECUTION_STATUS.md`](EXECUTION_STATUS.md).

## 10. Цепочка не является транзакцией

Успешно выполненные mutation не откатываются автоматически при ошибке следующего сегмента.

Например, если:

```text
GIT COMMIT
```

успешно создал commit, а `GIT PUSH` затем оказался BLOCKED, Harness сохраняет локальный commit и сообщает partial result.

Automatic rollback, reset, amend, merge/rebase или force push из chain semantics запрещены.

## 11. Safety boundary STEP → GIT

Harness намеренно не поддерживает:

```text
STEP RUN STEP-024 > GIT COMMIT > GIT PUSH
```

После работы над STEP пользователь получает возможность отдельно посмотреть diff/evidence/review и только затем запускает Git-команду или Git-цепочку:

```text
STEP RUN STEP-024
```

затем:

```text
GIT CHECK > COMMIT > PUSH > PR
```

Эта граница является частью protocol safety, а не ограничением parser implementation.


## 12. Drift ссылок на команды в project-owned документах

После изменения command surface старые project-owned документы не считаются автоматически мигрированными только потому, что protocol layer уже обновлён. Для `PROJECT RECONCILE` предусмотрена отдельная deterministic проверка:

```bash
python3 .harness/tools/check-command-references.py --json
```

Основные project paths, canonical Open Questions и taskDirectory checker берёт через единый manifest config layer, поэтому нестандартный layout не теряется. Дополнительно проверяются `README.md` и live subsystem Markdown под default `docs/**`; configured `sources.adrDirectory` исключается как decision history независимо от фактического пути. Harness documentation находится отдельно в `.harness/docs/**` и в project-doc scan не входит.

Исторические артефакты намеренно не переписываются и не входят в deterministic scope: immutable review/audit/release/update/search reports и ADR history могут сохранять синтаксис, который был корректен в момент создания записи.

Finding этой проверки означает необходимость reconciliation, а не автоматическую mutation: `PROJECT RECONCILE` обязан отразить его в audit report и отличить реальный stale reference от намеренной исторической цитаты.
