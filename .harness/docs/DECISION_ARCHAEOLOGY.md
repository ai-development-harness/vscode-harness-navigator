# Decision Archaeology

Decision Archaeology — read-only semantic capability для ответа на вопрос **почему** существующее architecture/code решение имеет текущую форму.

Она не заменяет:

- Codebase Grounding — что и как работает сейчас;
- Impact Analysis — какие canonical artifacts/STEP явно затронуты;
- Semantic Blast Radius — какие implicit behaviors могут пострадать от изменения.

## Evidence model

Priority:

```text
canonical ADR / REQ / PRN / architecture
                  ↓
        bounded Git target history
                  ↓
     fetched issue / PR / project docs
                  ↓
  optional additional engineering sources
```

Conversation/transcript и session memory не являются evidence.

## Deterministic / semantic boundary

Deterministic layer:

- фиксирует exact `repositoryRevision`;
- разрешает target path;
- собирает bounded commit history target-файла;
- revalidates Context Contract revision;
- валидирует explicit expansions и budgets;
- проверяет, что artifact evidence действительно было доступно capability;
- проверяет, что commit evidence входит в bounded target history;
- добавляет factual timestamps для repository-local evidence;
- structural-валидирует claims/conflicts/gaps.

Semantic layer:

- формулирует competing rationale explanations;
- определяет `documented | inference`;
- выставляет confidence;
- фиксирует conflicts;
- оценивает possible stale ADR;
- формулирует gaps.

Semantic result не меняет canonical artifacts.

## Claim confidence

Каждый claim имеет:

- `basis: documented | inference`;
- `confidence: high | medium | low`;
- evidence list;
- optional uncertainty.

`documented` claim обязан иметь evidence. Repository-local artifact/commit валидируется локально; реально полученный PR/issue/doc source тоже может документировать rationale, но остаётся помечен `supplied-not-locally-verifiable` и не превращается в local proof.

Inference без evidence допустим только как `low` confidence + explicit gap. Такой result не может быть PASS.

## Timestamped evidence map

Validator нормализует evidence:

- artifact → path, artifact kind, timestamp последнего Git commit по path;
- commit → exact SHA, authored timestamp, subject;
- supplied source → runtime-provided ref/title/timestamp с marker `supplied-not-locally-verifiable`.

Это не означает, что последний commit всегда authoritative; timestamp нужен для historical ordering, а не для автоматического выбора «победителя».

## Conflicts

Conflicting supported explanations должны оставаться отдельными claims и связываться `conflicts[]`.

Harness не применяет правило «самый новый источник выигрывает».

## Possible stale ADR

`staleDecisions[]` — diagnostic surface:

- `current`;
- `possibly-stale`;
- `unknown`.

Capability не переписывает status Accepted ADR. Material `possibly-stale` result routes к architecture-change/reconcile и explicit superseding decision.

## Bounded context

| Scope | Expansion files | Expansion chars | Target-history commits | Claims | Supplied evidence |
|---|---:|---:|---:|---:|---:|
| simple | 6 | 60 000 | 12 | 8 | 8 |
| complex | 12 | 120 000 | 24 | 16 | 16 |

Если target не входит в existing Context Contract, он расходует один expansion slot и свои chars.

## CLI

Preflight:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target src/provider/retry.py \
  --scope simple \
  --json
```

With existing Context Contract:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target src/provider/retry.py \
  --scope complex \
  --context-file .harness/local/context.json \
  --json
```

Validate semantic payload:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target src/provider/retry.py \
  --scope complex \
  --context-file .harness/local/context.json \
  --payload-file .harness/local/decision-archaeology.json \
  --json
```

Local handoff JSON остаётся transient `.harness/local/**` и не является canonical source.

## Integration

### Architecture change

Запускай при non-obvious historical rationale, competing explanations или подозрении на stale ADR. Validated findings превращаются в Preserve / Change / Avoid / Risk constraints для нового решения.

### PROJECT RECONCILE

Запускай только для material ambiguity: когда невозможно понять, является расхождение code drift или устаревшим architecture contract. Не используй capability как repository-wide mandatory scan.

## Fail-closed behavior

- arbitrary/out-of-budget expansion → BLOCKED;
- arbitrary commit вне bounded target history → BLOCKED;
- documented claim без evidence → BLOCKED;
- inference без evidence, но с medium/high confidence → BLOCKED;
- inference без evidence и без explicit gap → BLOCKED;
- PASS с ungrounded inference → BLOCKED;
- conflict records с unknown claim IDs → BLOCKED;
- stale ADR assessment без evidence (кроме `unknown`) → BLOCKED.
