# Authoritative State Ownership

Этот документ фиксирует trust/ownership boundary AI Development Harness для
canonical control-plane state. Его главный invariant:

> semantic runtime предлагает результат; Harness проверяет authoritative state и
> только deterministic boundary имеет право зафиксировать canonical transition.

Исследовательская мотивация:

- Global Coherence: When Every Agent Is Right and the Team Is Still Wrong —
  https://arxiv.org/abs/2610.02036
- ABSENTIA: Detecting Broken Access Control Vulnerabilities in Web Applications —
  https://arxiv.org/abs/2610.00977

Reference-и являются источниками архитектурных идей, а не внешними protocol
dependencies.

## Machine-readable authority contract

Глобальный versioned contract хранится в:

```text
.harness/command-transitions.json → authorityContract
```

Canonical schema v1:

```json
{
  "schemaVersion": 1,
  "semanticResult": "proposal",
  "executionStateCommit": "dispatcher",
  "transitionCommit": "dispatcher",
  "canonicalArtifactCommit": "deterministic-writer",
  "sideEffectCommit": "deterministic-action"
}
```

`command_transitions.py` проверяет этот объект как closed contract. Его
удаление, частичное изменение или неизвестное значение делает CTS invalid до
dispatch первой команды.

## Proposal → validation → commit

Semantic command проходит границу:

```text
semantic runtime
  │
  │ structured proposal
  ▼
deterministic Harness boundary
  │
  ├─ current execution / executionId
  ├─ current command expectation
  ├─ repository / context / revision facts
  ├─ command-specific prerequisite
  └─ postcondition
  │
  ▼
canonical commit
```

Слово `SUCCESS`/ `PASS` в ответе модели само по себе не является proof.

## State ownership matrix

| Surface | Authority | Роль semantic runtime |
|---|---|---|
| CTS syntax/transitions | `command-transitions.json` + dispatcher | не выбирает и не commit-ит edge |
| `execution-status.json` | execution layer / dispatcher | не пишет напрямую |
| execution completion | dispatcher | возвращает proposal, связанный с `executionId` |
| Ready plan stamp | canonical planning writer | предлагает plan/planning-review payload |
| STEP REVIEW report | canonical review writer | предлагает structured verdict/findings |
| Completion result | completion gate/writer | предлагает coverage/findings |
| generated Evidence | deterministic verification/writer | не подделывает machine PASS |
| Git/provider side effects | `git-action.py` / recovery layer | формирует только semantic metadata там, где это разрешено |
| Harness update transaction | updater/recovery engine | не commit-ит update state |
| product code/config внутри STEP scope | implementer | разрешённая semantic mutation |
| REQ/ADR/OQ/STEP semantic evolution | canonical artifact workflow | предлагает изменение в owning artifact |

Последние две строки принципиальны: Harness не превращает все product writes в
centralized generic action service. Authority contract защищает protocol/control
state, а не запрещает implementer выполнять task-scoped инженерную работу.

## Execution-bound semantic completion

Каждый semantic handoff содержит:

```json
{
  "executionId": "exec-...",
  "authority": {
    "semanticResult": "proposal",
    "executionStateCommit": "dispatcher",
    "transitionCommit": "dispatcher",
    "canonicalArtifactCommit": "deterministic-writer",
    "sideEffectCommit": "deterministic-action",
    "completionBinding": "executionId"
  }
}
```

Canonical completion обязан вернуть тот же `executionId`:

```bash
python3 .harness/tools/harness-dispatch.py complete \
  --root '<root command>' \
  --command '<current command>' \
  --execution-id '<executionId from handoff>' \
  --result <SUCCESS|PASS|FAIL|BLOCKED>
```

Если между handoff и **commit point** completion уже появилась новая invocation
того же `rootCommand`, старый result получает:

```text
BLOCKED / STALE_SEMANTIC_RESULT
```

Проверка повторяется внутри той же execution-state transaction, которая меняет
`current.status/result`. Ранняя dispatcher-проверка является только fast-path
и не считается authority proof. Это закрывает ABA/TOCTOU-гонку, где одинаковые
`rootCommand` и `current.command` выглядят валидно, хотя result принадлежит
старому run.

## Canonical writers

Semantic payload не должен вручную имитировать durable artifact:

- plan/planning-review записывает planning writer;
- STEP REVIEW записывает review writer с stamped expectation;
- Completion Gate записывает/валидирует completion proof;
- generated Verification Evidence создаёт verification layer;
- projections пересобираются deterministic sync tooling.

Writer обязан повторно проверить current basis/revision/expectation перед commit.
Stale payload не становится valid только потому, что его Markdown/JSON
синтаксически корректен.

## Side effects

Внешний side effect не считается выполненным по model output. Для Git/provider
mutation действует отдельный contract из
[`SIDE_EFFECT_RECOVERY.md`](SIDE_EFFECT_RECOVERY.md):

```text
semantic intent
  → deterministic preflight
  → exact mechanical action
  → observed postcondition
  → recovery checkpoint
```

После interruption reconciliation использует observed provider/repository facts,
а не память модели.

## Multi-agent / execution groups

Execution groups не получают отдельного права менять global lifecycle. Несколько
semantic workers могут работать только в разрешённых mutation surfaces. STEP
lifecycle, execution state, completion и transition commit остаются
сериализованными canonical Harness boundaries.

Conflict/mutation semantics execution groups описаны в
[`EXECUTION_GROUPS.md`](EXECUTION_GROUPS.md).

## Fail-closed rules

Harness обязан блокировать:

- completion без exact `executionId`;
- completion от stale `executionId`, если уже существует новая running invocation;
- semantic result для не-current command;
- STEP REVIEW payload без matching stamped expectation;
- deterministic PASS без требуемой postcondition;
- попытку продолжить `BLOCKED` execution reasoning-ом.
- semantic resume, если durable Intent Basis больше не совпадает с current canonical contract; runtime не имеет права "обновить intent" из chat history. См. [`INTENT_RESUME.md`](INTENT_RESUME.md).

## Не является security sandbox

Authority contract защищает от случайного/stale orchestration behavior при
использовании canonical tools. Он не защищает от malicious runtime или
пользователя, который сознательно редактирует local state/files и обходит
Harness tools. Полная граница описана в
[`THREAT_MODEL.md`](THREAT_MODEL.md).

## Regression coverage

Минимальный набор отрицательных проверок:

1. удалённый/изменённый `authorityContract` → invalid CTS;
2. stale `executionId` → `STALE_SEMANTIC_RESULT`;
3. completion чужой current command → `COMMAND_NOT_CURRENT`;
4. semantic GIT COMMIT SUCCESS без repository postcondition не открывает PUSH;
5. stale review expectation/revision не создаёт trusted review artifact.

Связанный implementation issue:
https://github.com/ai-development-harness/ai-development-harness-template/issues/202
