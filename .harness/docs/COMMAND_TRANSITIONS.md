# Command transitions

Этот документ описывает **Command Transition System (CTS)** AI Development Harness — детерминированную систему допустимых переходов между каноническими командами с условиями результата и runtime guards.

Команда в CTS является action/transition request, а не состоянием. Состояние определяется repository/runtime facts. Поэтому термин «Command State Machine» допустим только как упрощённая аналогия; каноническое название модели — **Command Transition System**.

CTS не определяет, успела ли конкретная command завершиться до session/runtime interruption. Это фиксирует [`EXECUTION_STATUS.md`](EXECUTION_STATUS.md) в одном local `execution-status.json`.

CTS также **не задаёт глобальный порядок всех команд пользователя**. Edge требуется только внутри одной explicit chain или orchestration execution. Две отдельные invocations, например завершённый `STEP PLAN STEP-001` и последующий отдельный `GIT COMMIT`, являются независимыми executions и не требуют cross-domain edge.

Machine-readable source of truth:

```text
.harness/command-transitions.json
```

Человекочитаемая таблица ниже должна полностью соответствовать этому JSON. Harness Integrity проверяет соответствие автоматически.

## Зачем существует отдельный transition graph

Синтаксически корректные команды не обязательно образуют корректную цепочку.

Например, обе команды существуют:

```text
GIT PR
GIT COMMIT
```

но цепочка:

```text
GIT PR > COMMIT
```

структурно невозможна.

Harness не должен выводить это из здравого смысла, Git semantics или поведения конкретного агента. Отсутствие edge `GIT PR → GIT COMMIT` в canonical transition graph означает `INVALID_CHAIN`.

## Порядок обработки команды

Каноническая команда проходит строго следующие стадии:

```text
1. tokenize
      ↓
2. normalize
      ↓
3. transition-table
      ↓
4. runtime-preconditions
      ↓
5. dispatch
```

Этот порядок зафиксирован и в `.harness/command-transitions.json`.

### 1. Tokenize

Строка разбивается на chain segments только по отдельному оператору:

```text
A > B
```

### 2. Normalize

До проверки graph разрешаются только механические преобразования:

- первый segment обязан иметь explicit DOMAIN;
- DOMAIN наследуется последующими shorthand-сегментами;
- STEP target наследуется внутри STEP chain;
- `HARNESS UPDATE CHECK ... > APPLY` нормализует `APPLY` в `HARNESS UPDATE APPLY`;
- explicit target последующего segment не может отличаться от первого.

На этой стадии не читаются project state, Git state, review verdict или skill instructions.

### 3. Transition table

После normalization каждый segment обязан существовать в table.

Для каждой соседней пары:

```text
A > B
```

должен существовать explicit edge:

```text
A → B
```

Если edge отсутствует, результат:

```text
INVALID_CHAIN
```

и **ни один segment не выполняется**.

Это правило применяется до skill routing, repository mutation и command-specific interpretation.

### 4. Runtime preconditions

Некоторые structurally valid edges имеют дополнительные условия.

Примеры:

- `GIT CHECK → GIT PUSH` требует `git-push-ready`;
- `GIT CHECK → GIT PR` требует `git-pr-ready`;
- `STEP REVIEW → STEP FIX` выполняется только при результате review `FAIL`;
- внутри chain `HARNESS UPDATE CHECK → HARNESS UPDATE APPLY` требуется matching target/route; standalone APPLY выполняет собственный fresh deterministic preflight.

Отсутствие runtime precondition не превращает цепочку в `INVALID_CHAIN`. Структура остаётся валидной, но исполнение может завершиться `BLOCKED` или остановить оставшиеся segments.

### 5. Dispatch

Только после успешной structural validation Harness выбирает соответствующий skill/runtime role и начинает command semantics.

## Result model

### `INVALID_CHAIN`

Структура command chain отсутствует в transition graph.

Ничего не выполняется.

### `BLOCKED`

Структура допустима, но текущее состояние проекта/runtime/Git не удовлетворяет runtime precondition.

### `NOT_EXECUTED`

Segment структурно допустим, но execution до него не дошёл из-за результата предыдущего segment.

### `PASS` / `SUCCESS` / `FAIL`

Результат выполненной команды. Edge сам определяет, при каком результате разрешён переход дальше.

Это особенно важно для review:

```text
STEP REVIEW STEP-024 > FIX > REVIEW
```

Edge `REVIEW → FIX` разрешён именно при `FAIL`. Поэтому `FAIL` здесь не является универсальным «остановить chain» — transition graph определяет допустимый следующий шаг.

## Полная таблица команд и переходов

Отсутствие перехода в таблице означает запрет. Никаких implicit edges нет.

<!-- COMMAND-TRANSITIONS:START -->
| Command | Chain segment | Allowed next | Transition condition |
|---|:---:|---|---|
| `PROJECT INIT` | no | — | standalone-only |
| `PROJECT STATUS` | no | — | standalone-only |
| `PROJECT RECONCILE` | no | — | standalone-only |
| `PROJECT QUICK FIX:` | no | — | standalone-only |
| `STEP ADD:` | no | — | standalone-only |
| `STEP NEXT` | no | — | standalone-only |
| `STEP PLAN STEP-NNN` | yes | STEP IMPLEMENT | IMPLEMENT: result=SUCCESS; pre=— |
| `STEP IMPLEMENT STEP-NNN` | yes | STEP REVIEW | REVIEW: result=SUCCESS; pre=— |
| `STEP REVIEW STEP-NNN` | yes | STEP FIX | FIX: result=FAIL; pre=— |
| `STEP FIX STEP-NNN` | yes | STEP REVIEW | REVIEW: result=SUCCESS; pre=— |
| `STEP RUN STEP-NNN` | no | — | standalone-only |
| `STEP AUDIT STEP-NNN` | no | — | standalone-only |
| `SKILL FIND:` | no | — | standalone-only |
| `SKILL INSTALL:` | no | — | standalone-only |
| `SKILL CREATE:` | no | — | standalone-only |
| `GITHUB GENERATE TEMPLATES` | no | — | standalone-only |
| `RELEASE CHECK` | no | — | standalone-only |
| `HARNESS UPDATE CHECK` | yes | HARNESS UPDATE APPLY | UPDATE APPLY: result=PASS; pre=matching-update-target-and-route |
| `HARNESS UPDATE APPLY` | yes | — | terminal chain segment |
| `GIT CHECK` | yes | GIT COMMIT<br>GIT PUSH<br>GIT PR | COMMIT: result=PASS; pre=—<br>PUSH: result=PASS; pre=git-push-ready<br>PR: result=PASS; pre=git-pr-ready |
| `GIT COMMIT` | yes | GIT PUSH | PUSH: result=SUCCESS; pre=— |
| `GIT PUSH` | yes | GIT PR | PR: result=SUCCESS; pre=— |
| `GIT PR` | yes | — | terminal chain segment |
| `GIT SYNC` | no | — | standalone-only |
<!-- COMMAND-TRANSITIONS:END -->

## Как читать таблицу

### Chain segment = no

Команда может выполняться отдельно, но никогда не входит в chain.

Например:

```text
PROJECT INIT
STEP RUN STEP-024
GIT SYNC
```

### Chain segment = yes, Allowed next = —

Команда может быть последним segment цепочки, но после неё нет допустимого перехода.

Например:

```text
GIT PR
HARNESS UPDATE APPLY
```

### Runtime condition

`result=...` — результат предыдущего segment, при котором edge активируется.

`pre=...` — runtime precondition, который проверяется после structural validation.

## Примеры

### Валидная Git chain

```text
GIT CHECK > COMMIT > PUSH > PR
```

Нормализация:

```text
GIT CHECK
GIT COMMIT
GIT PUSH
GIT PR
```

Все три edges существуют.

### Структурно валидный shortcut с runtime precondition

```text
GIT CHECK > PUSH
```

Edge существует, поэтому chain структурно валидна.

Если publishable local commit отсутствует или Git state не позволяет push:

```text
BLOCKED
```

но не `INVALID_CHAIN`.

### Обратный порядок

```text
GIT PR > COMMIT
```

Edge отсутствует:

```text
GIT PR -X-> GIT COMMIT
```

Результат:

```text
INVALID_CHAIN
0 commands executed
```

### Условный STEP transition

```text
STEP REVIEW STEP-024 > FIX > REVIEW
```

Structural graph:

```text
REVIEW --FAIL--> FIX --SUCCESS--> REVIEW
```

Если первый review = PASS:

```text
✓ STEP REVIEW STEP-024 — PASS
○ STEP FIX STEP-024 — NOT_EXECUTED
○ STEP REVIEW STEP-024 — NOT_EXECUTED
```

### Cross-domain

```text
STEP RUN STEP-024 > GIT COMMIT
```

Отклоняется при normalization/transition validation. Cross-domain edges в graph отсутствуют.

## Runtime preconditions

Имена runtime preconditions в graph — стабильные protocol identifiers.

### `git-push-ready`

После `GIT CHECK` текущее состояние должно допускать `GIT PUSH`: существует локальное publishable состояние, нет blocking divergence/policy violation, а push не требует запрещённой destructive операции.

### `git-pr-ready`

После `GIT CHECK` branch должна уже быть опубликована в состоянии, пригодном для `GIT PR`. Наличие unpublished local commit делает shortcut `GIT CHECK → GIT PR` blocked; для нового commit нужен путь через `GIT PUSH`.

### `matching-update-target-and-route`

Для chain `HARNESS UPDATE CHECK > APPLY` APPLY использует target/route предшествующего PASS CHECK. Standalone `HARNESS UPDATE APPLY [TO <tag>]` не требует durable CHECK state: update engine заново валидирует current Harness и выполняет read-only preflight до mutation.

## Structural error codes

`validate-command.py` использует стабильные structural codes:

| Code | Значение |
|---|---|
| `EMPTY_COMMAND` | Команда пуста |
| `EMPTY_SEGMENT` | В chain есть пустой segment |
| `MISSING_DOMAIN` | Первый segment не содержит explicit DOMAIN |
| `UNKNOWN_DOMAIN` | DOMAIN не существует в transition graph |
| `UNKNOWN_OPERATION` | Operation не существует в выбранном DOMAIN |
| `MISSING_TARGET` | Для команды отсутствует обязательный target |
| `INVALID_TARGET_SYNTAX` | Target записан в неподдерживаемой форме |
| `TARGET_MISMATCH` | Target изменён/введён позднее внутри chain |
| `INVALID_INPUT_SYNTAX` | Free-form input не отделён двоеточием |
| `MISSING_INPUT` | Обязательный free-form input пуст |
| `UNEXPECTED_ARGUMENTS` | У команды появились неразрешённые аргументы |
| `DOMAIN_MISMATCH` | Внутри chain явно указан другой DOMAIN |
| `CHAIN_NOT_ALLOWED` | DOMAIN или command разрешены только standalone |
| `INVALID_CHAIN` | Для соседней пары нет explicit transition edge |
| `INVALID_TRANSITION_TABLE` | Сам machine-readable graph не прошёл integrity validation |

Успешные structural results:

- `VALID_COMMAND` — одна canonical command;
- `VALID_CHAIN` — вся цепочка существует в graph.

Runtime `BLOCKED`, `PASS`, `SUCCESS`, `FAIL` и `NOT_EXECUTED` относятся уже к execution layer и не подменяют structural codes.

## Deterministic preflight

Перед интерпретацией canonical command Harness выполняет:

```bash
python3 .harness/tools/validate-command.py --json -- 'GIT CHECK > COMMIT > PUSH > PR'
```

Для валидной команды tool возвращает normalized segments и metadata каждого edge.

Для невалидной — ненулевой exit code и стабильный error code.

Этот tool проверяет **только command structure**. Он не заменяет Git checks, STEP preconditions, review verdicts, Harness update checks или другие runtime gates.
