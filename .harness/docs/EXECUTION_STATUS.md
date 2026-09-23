# Execution Status

Execution Status — локальный crash-safe слой, который фиксирует фактическое выполнение **всех** canonical Harness-команд между session/runtime interruptions.

Исключение: `HARNESS RESUME` — управляющая команда над уже существующим состоянием выполнения. Она не создаёт новое корневое выполнение и работает только тогда, когда существует ровно одна безопасная точка продолжения.

Он не добавляет новых пользовательских команд и не создаёт вторую state machine.

```text
Command Transition System (CTS)
→ какие переходы допустимы внутри одной execution sequence

Execution Status
→ какая команда фактически была запущена и успела ли завершиться

Execution Resolver
→ какую уже существующую command продолжить или выполнить следующей
```

## Фиксированный путь

Во всём проекте используется один файл:

```text
.harness/local/execution/execution-status.json
```

Per-STEP файлы запрещены.

Каталог `.harness/local/` исключён из Git. Execution Status является operational state, а не product evidence.

Все read-modify-write операции сериализуются advisory lock-файлом `.harness/local/execution/execution-status.lock`. На Unix используется `flock`, на Windows — `msvcrt.locking`; lock освобождается ОС при завершении процесса. Atomic `os.replace` сохраняет целостность JSON, а lock отдельно предотвращает lost update между параллельными sessions/subagents.

## Execution record

Каждый явный запуск пользователя создаёт независимую execution record.

Пример single command:

```json
{
  "executionId": "exec-...",
  "mode": "single",
  "requestedCommand": "STEP PLAN STEP-001",
  "rootCommand": "STEP PLAN STEP-001",
  "sequence": [
    "STEP PLAN STEP-001"
  ],
  "status": "running",
  "current": {
    "command": "STEP PLAN STEP-001",
    "status": "running",
    "result": null,
    "attempt": 1
  }
}
```

Файл может одновременно хранить несколько execution records. Поэтому запуск новой независимой команды не уничтожает сведения об interrupted execution.

## Internal modes

`mode` — внутренняя классификация уже существующего пользовательского ввода, а не новый command layer.

### `single`

Пользователь ввёл одну команду:

```text
STEP PLAN STEP-001
```

После её completion Harness останавливается. CTS не запускает автоматически `STEP IMPLEMENT`.

### `chain`

Пользователь явно ввёл chain:

```text
GIT CHECK > COMMIT > PUSH > PR
```

Вся sequence структурно валидируется до первого segment. После completion текущего segment следующий запускается только если:

1. он присутствует в исходной sequence;
2. CTS содержит edge;
3. result текущего segment входит в `onPreviousResult`;
4. runtime preconditions edge выполнены.

### `orchestration`

Пользователь ввёл существующую orchestration command:

```text
STEP RUN STEP-001
```

Root execution остаётся `STEP RUN STEP-001`, а `current.command` может временно указывать на дочернюю canonical command:

```text
STEP PLAN STEP-001
STEP IMPLEMENT STEP-001
STEP REVIEW STEP-001
STEP FIX STEP-001
```

Если конкретный STEP Type выполняется внутри RUN без отдельной canonical child command, current остаётся `STEP RUN STEP-NNN`. После interruption повторяется сам RUN.

## CTS не является глобальным порядком всех действий пользователя

Это принципиальное правило.

Две отдельные команды:

```text
STEP PLAN STEP-001
<execution завершена>

GIT COMMIT
```

являются двумя независимыми executions.

Harness **не требует** edge:

```text
STEP PLAN → GIT COMMIT
```

Такого перехода не существует и он не нужен.

CTS проверяет переходы только:

- внутри explicit chain;
- внутри orchestration одной root command.

## Status и result

Execution и current command используют:

```text
running
complete
blocked
```

Command result:

```text
SUCCESS
PASS
FAIL
BLOCKED
```

### `running`

Completion не доказан.

После новой session:

```text
RESUME current.command
```

Повтор должен иметь resume-semantics: сначала проверить уже существующие artifacts/diff/state и не дублировать side effects вслепую.

### `complete`

Команда доказанно завершена.

- для `single` execution автоматического продолжения нет;
- для `chain` resolver проверяет следующий segment исходной sequence через CTS;
- для `STEP RUN` resolver проверяет допустимый CTS transition дочерней команды или возвращает root RUN для orchestration tail.

### `blocked`

Автоматическое продолжение запрещено до устранения blocker.

## Запись состояния

После structural validation, но до command-specific dispatch:

```bash
python3 .harness/tools/execution-state.py start \
  --command 'GIT CHECK > COMMIT > PUSH > PR'
```

Файл обновляется через:

```text
temporary file
→ flush
→ fsync
→ os.replace
```

Partial JSON после process crash не считается нормальным состоянием.

## Child/next command внутри одной execution

Для explicit chain или `STEP RUN`:

```bash
python3 .harness/tools/execution-state.py begin \
  --root 'STEP RUN STEP-001' \
  --command 'STEP IMPLEMENT STEP-001'
```

После завершения:

```bash
python3 .harness/tools/execution-state.py complete \
  --root 'STEP RUN STEP-001' \
  --command 'STEP IMPLEMENT STEP-001' \
  --result SUCCESS
```

Следующая command определяется resolver/CTS, а не chat history.

## Resolver

Для конкретного root execution:

```bash
python3 .harness/tools/resolve-next-command.py --json \
  --root 'STEP RUN STEP-001'
```

Без `--root`:

```bash
python3 .harness/tools/resolve-next-command.py --json
```

возвращаются все unresolved executions.

Это важно, потому что пользователь может осознанно выполнить новую независимую команду поверх старого interrupted execution.

## Пример: interrupted STEP RUN + отдельный Git check

```text
STEP RUN STEP-001
  ✓ PLAN
  ↯ IMPLEMENT
```

State:

```text
exec-001
root    = STEP RUN STEP-001
current = STEP IMPLEMENT STEP-001
status  = running
```

Затем пользователь отдельно выполняет:

```text
GIT CHECK
```

Добавляется новая execution:

```text
exec-002
root    = GIT CHECK
current = GIT CHECK
status  = complete
```

`exec-001` не перезаписывается. Resolver по root RUN по-прежнему возвращает:

```text
RESUME STEP IMPLEMENT STEP-001
```

## Пример: manual PLAN, затем manual COMMIT

```text
STEP PLAN STEP-001
```

после completion заканчивает свою single execution.

Следующий ввод:

```text
GIT COMMIT
```

создаёт новую single execution. Это валидный workflow; CTS edge между командами не требуется.

## Пример: explicit conditional STEP chain

```text
STEP REVIEW STEP-001 > FIX > REVIEW
```

Если первый REVIEW = FAIL:

```text
REVIEW --FAIL--> FIX
```

и chain продолжается.

Если первый REVIEW = PASS:

```text
FIX    = NOT_EXECUTED
REVIEW = NOT_EXECUTED
root execution = complete
```

## Пример: Harness update между sessions

Single command:

```text
HARNESS UPDATE CHECK TO vX.X.X
```

успешно завершилась и записана как `PASS`.

Если следующая завершённая execution всё ещё этот CHECK, новая session может проверить handoff:

```bash
python3 .harness/tools/execution-state.py find \
  --command 'HARNESS UPDATE CHECK TO vX.X.X' \
  --result PASS \
  --latest
```

и `HARNESS UPDATE APPLY TO vX.X.X` не обязан повторять CHECK.

Если после CHECK завершалась другая execution, old CHECK считается stale для mutation и APPLY выполняет fresh CHECK.

Explicit chain:

```text
HARNESS UPDATE CHECK TO vX.X.X > APPLY
```

хранит оба segment в одной root sequence и после interruption продолжает APPLY внутри той же execution.

## FIX → REVIEW budget

Для `STEP RUN STEP-NNN` execution record хранит `fixReviewCycles`. Счётчик увеличивается после успешного `FIX → REVIEW` и сохраняется в `.harness/local/execution/execution-status.json`, поэтому restart session не сбрасывает budget.

Когда REVIEW снова возвращает `FAIL` и `fixReviewCycles >= execution.maxFixReviewCycles`, resolver возвращает:

```text
status     = BLOCKED
reasonCode = FIX_REVIEW_LIMIT_REACHED
```

Следующий FIX внутри этого root execution запрещён детерминированно. Это не инструкция reasoning-модели и не soft recommendation.

## Durable recovery proofs

Основное правило остаётся простым:

```text
running
→ resume same command
```

Resolver пропускает повтор дорогой стадии только когда completion можно доказать durable artifact-ом.

### STEP PLAN

PLAN считается доказанно завершённым только когда одновременно истинно:

```text
plan.status = ready
stored context_basis = current context_basis
stored content_hash = current Implementation plan hash
plan.reviewed_report = matching immutable planning-review
planning-review.verdict = pass
planning-review.context_basis = current context_basis
planning-review.plan_content_hash = current content_hash
```

`context_basis` schema v4 включает semantic STEP/dependency contracts, semantic linked REQ/ADR, explicit architecture refs и relevant OQ. Dependency completion state, reverse traceability и scheduling metadata не входят в fingerprint; completion proof проверяется отдельным runtime precondition непосредственно перед IMPLEMENT.

Изменение текста Implementation plan инвалидирует `content_hash` даже при неизменном context.

### STEP REVIEW

При старте REVIEW сохраняется baseline последнего report.

Crash recovery сначала ищет **новый schema-valid immutable report**, который:

- относится к тому же STEP;
- содержит допустимый verdict/finding structure;
- удовлетворяет deterministic specialized-review requirements;
- для FAIL/BLOCKED ссылается на ту же exact repository revision.

Для PASS есть дополнительный строго ограниченный post-review case: structured writer уже мог выполнить lifecycle-only mutation `status → completed` после того, как exact revision была проверена. Тогда recovery требует одновременно новый PASS report относительно baseline, canonical `status: completed` и успешный type-specific completion proof. Без всех трёх условий semantic review повторно не пропускается.

Exact revision:

```text
clean tree → git_head
dirty tree → git_head + worktree_hash
```

Configured review directory и `.harness/local/**` не входят в worktree hash, потому что report/execution state создаются самим workflow. Для каждого changed path fingerprint учитывает Git status/path, stage-0 index `mode + object id`, normalized worktree mode, bytes/symlink target и current submodule HEAD для gitlink. Поэтому chmod executable bit и смена submodule commit инвалидируют старый review proof даже при одинаковых file bytes. Product/config mutation после report меняет fingerprint и запрещает reuse старого verdict.

### GIT COMMIT

При старте сохраняется Git HEAD. Если после crash HEAD изменился и остальные commit postconditions выполнены, resolver может не создавать второй commit вслепую.

Эти proofs не являются execution profiles и не меняют command surface.

## Same root повторно

Если та же root command уже имеет `status=running`, повторный запуск:

```text
STEP RUN STEP-001
```

не создаёт второй активный record. Harness resume-ит существующий execution и увеличивает attempt текущей команды.

Blocked/completed root при явном новом запуске создаёт новую execution.

## История

Файл хранит completed records вместе с unresolved records. Это позволяет использовать безопасные cross-session handoff checks, например UPDATE CHECK → APPLY.

Execution Status не является audit log или product source of truth. Его можно удалить, если пользователь сознательно отказывается от local recovery/history. После удаления Harness обязан опираться на canonical artifacts и безопасно повторять недоказанные команды.

## Главный принцип

```text
explicit user invocation
→ one independent root execution

transition inside that execution
→ CTS

interrupted current command
→ resume same existing command

new independent command
→ new execution record, old interrupted record remains
```
