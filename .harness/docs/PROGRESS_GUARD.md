# Progress Guard

Progress Guard — bounded deterministic guard для long-running STEP execution.
Он отвечает на вопрос:

> изменилось ли authoritative состояние задачи так, что execution действительно
> продвинулось, либо runtime повторяет ту же работу?

Guard не является scheduler-ом, не создаёт новый STEP lifecycle и не хранит
transcript/belief history.

## References

Архитектурная мотивация:

- Progression-of-States — https://arxiv.org/abs/2610.01415
- Give long-running agents a working account of the task —
  https://inference.institute/research/give-long-running-agents-a-working-account-of-the-task/
- Global Coherence — https://arxiv.org/abs/2610.02036

References не являются runtime dependencies.

## Scope v1

Guard применяется к semantic STEP nodes:

```text
STEP PLAN STEP-NNN
STEP IMPLEMENT STEP-NNN
STEP REVIEW STEP-NNN
STEP FIX STEP-NNN
```

Он особенно полезен внутри `STEP RUN` и при resume interrupted semantic
command.

## Два независимых сигнала

### Material progress

Material fingerprint строится из уже существующих canonical contracts:

- STEP lifecycle status;
- schema-v4 planning context basis;
- Implementation plan hash;
- execution-groups graph hash;
- Acceptance criteria hash;
- Evidence hash как material-change signal без автоматического направления;
- type-specific completion proof;
- Completion Gate deterministic precheck;
- Verification freshness/status;
- structured Review Contract v2/v3 finding fingerprints;
- Completion Convergence findings.

Новые project-owned artifacts для этого не создаются.

### Repository activity

Activity signal отделён от material progress и по возможности ограничен
machine-readable mutation surface:

- `PLAN/REVIEW` не получают product-file activity signal;
- `IMPLEMENT/FIX` при наличии `plan.execution_groups` используют union их
  validated `mutationPaths`;
- STEP без execution groups сохраняет conservative whole-repository fallback,
  потому что prose Mutation policy пока не является строгим path contract.

Это разделение намеренное:

```text
repository changed
≠
acceptance/completion progressed
```

Но и обратное правило важно:

```text
repository changed
→ нельзя объявлять STAGNATION только потому,
  что Acceptance/Evidence ещё не обновлены
```

Поэтому `ACTIVITY_ONLY` не является blocker-ом. Это защищает длинный IMPLEMENT,
который может менять несколько файлов между checkpoint/resume.

## Execution groups

`plan.execution_groups` входят в progress material через отдельный canonical
fingerprint.

Progress Guard **не хранит current group cursor** и не исполняет DAG. В v1
execution groups остаются planning/conflict contract из
[`EXECUTION_GROUPS.md`](EXECUTION_GROUPS.md).

Если в будущем появится authoritative group runtime state, он может стать ещё
одним progress input только после отдельного contract change.

## Bounded telemetry

В active execution хранится:

```text
execution.progressTelemetry
```

Schema v1 содержит:

- максимум 8 compact samples;
- `unchangedResumes`;
- `driftStreak`;
- только последний factual delta;
- текущий `stopDecision`.

Это не event log. Полный material snapshot в execution-status не копируется:
sample хранит fingerprints и компактные metrics.

## Sampling points

### Fresh semantic node

При старте semantic STEP node сохраняется initial sample.

### Actual resume

При фактическом повторном запуске той же interrupted command снимается новый
sample и сравнивается с предыдущим.

Read-only `HARNESS STATUS` sample/counter **не добавляет**.

### Semantic transition

При переходе к следующему semantic node сохраняется новый sample. Это позволяет
обнаружить bounded exact cycle, если execution вернулась к уже наблюдавшемуся
authoritative progress state.

## STAGNATION

`EXECUTION_STAGNATION` возникает после двух последовательных actual resume
attempts без:

- material progress;
- repository activity.

Пример:

```text
IMPLEMENT sample A
→ crash
→ resume: A       # tolerated
→ crash
→ resume: A       # BLOCKED / EXECUTION_STAGNATION
```

Blocker содержит:

- число unchanged attempts;
- changed/unchanged metrics;
- STEP/command;
- remediation.

## CYCLE

`EXECUTION_CYCLE` означает, что bounded execution path вернулась к **тому же semantic command** и exact комбинации material + activity fingerprint после промежуточных semantic nodes. Одинаковый project state на обычном переходе между разными фазами (`IMPLEMENT → REVIEW`) cycle-ом не считается.

Пример:

```text
state A
→ semantic node B
→ state A
```

Cycle detection не реконструирует trajectory из transcript: используется только
ring последних восьми samples.

## DRIFT

`EXECUTION_DRIFT` — conservative v1 detection repeated factual worsening:

- completion reasons увеличиваются;
- Completion Gate blockers увеличиваются;
- Verification status ухудшается;
- finding surface увеличивается, включая первое появление material findings;
- completion proof откатывается.

Один negative delta не блокирует execution. Требуются два последовательных
worsening resume deltas.

Это ограничение снижает false positives во время промежуточной implementation
работы.

## FIX ↔ REVIEW

Generic Progress Guard **не конкурирует** с
[`ADAPTIVE_REPAIR_STOPPING.md`](ADAPTIVE_REPAIR_STOPPING.md).

Для FIX и последующего REVIEW:

- progress samples можно хранить для diagnostics;
- generic STAGNATION/CYCLE/DRIFT stop decision подавляется;
- authoritative stop policy остаётся у #153:
  `NO_PROGRESS | REPEATED_FINDINGS | REGRESSION | FIX_REVIEW_LIMIT_REACHED`.

Так один и тот же repair loop не получает две разные taxonomy.

## Intent-aware resume

[`INTENT_RESUME.md`](INTENT_RESUME.md) выполняется раньше Progress Guard.

Разделение:

- Intent Basis: тот ли semantic contract сейчас действует?
- Progress Guard: продвигается ли execution внутри всё ещё действующего contract?

Если intent stale, generic progress classification не используется.

## Blocker taxonomy

```text
EXECUTION_STAGNATION
EXECUTION_CYCLE
EXECUTION_DRIFT
```

Все blocker-ы сохраняются в `blockedBy` и доступны через resolver,
`HARNESS STATUS` и `HARNESS RESUME`.

Canonical remediation v1:

```text
STEP PLAN STEP-NNN
```

Это безопасная re-entry point. Если причина лежит в REQ/ADR/OQ, дальнейшая
маршрутизация выполняется evolution semantics, а не Progress Guard.

## Snapshot unavailable

Progress detection не является prerequisite для **fresh** legacy/diagnostic
invocation. Если canonical progress snapshot невозможно вычислить, execution
может продолжить существующий workflow, а `progressTelemetryError` хранит
bounded diagnostic.

Это отличается от Intent Basis: отсутствие исходного intent proof делает resume
unsafe и потому fail-closed.

## False-positive policy

Guard специально **не** блокирует:

- один no-op resume;
- scoped repository activity без material completion delta;
- single long model call;
- normal FIX↔REVIEW repair loop;
- read-only STATUS/inspection;
- unrelated transcript/history changes.

## Regression coverage

`.harness/tools/progress-guard-self-test.py` покрывает:

- material progress;
- repeated no-op resume;
- activity-only false-positive guard;
- exact cycle;
- repeated drift;
- FIX↔REVIEW suppression;
- execution-groups fingerprint;
- real execution-state persistence;
- bounded sample ring;
- strict persisted sample/lastDelta schema;
- Evidence reword/update не маскирует Verification regression;
- unrelated PLAN activity и activity вне execution-group mutationPaths не
  сбрасывают stagnation.

Implementation issue:
https://github.com/ai-development-harness/ai-development-harness-template/issues/204
