# Context Contracts / Progressive Disclosure

Context Contract определяет **минимальный task-local context** для semantic роли.
Contract строится до runtime adapter и поэтому одинаков для Codex и Claude:
provider может отличаться способом чтения файла, но не semantic selection.

## Roles

- `planner`: STEP contract, linked REQ/ADR, dependency contract, relevant OQ,
  architecture refs и compact projections active Project Principles;
- `implementer`: implementation-facing STEP sections, Acceptance/Verification,
  governing ADR и dependency evidence;
- `reviewer`: reviewed STEP contract + Implementation plan/Evidence, linked
  acceptance/decisions, OQ, principles и review-relevant context.

Planner, implementer и reviewer получают **разные manifests** для одного STEP.

## Required context

Resolver возвращает не «прочитай файл целиком», а section-level projection:

```json
{
  "artifact": "REQ-007",
  "path": "docs/requirements/REQ-007-example.md",
  "sections": ["Requirement", "Acceptance"]
}
```

Architecture refs используют exact anchor. OQ `Resolution` добавляется только
если section существует; canonical required `Context/Decision needed` остаются
fail-closed.

Contract также содержит:

- canonical `command`;
- exact `repositoryRevision`;
- `runtimeNeutral=true`;
- `coreReasoningPrinciples[]` — только applicable Harness-owned `CRP-NNN` leaf refs;
- tokenizer-neutral metrics `artifactCount`, `sectionCount`,
  `corePrincipleCount`, `corePrincipleChars`, `manifestChars`,
  `fullRepositoryPreload=false`.

## Запуск

```bash
python3 .harness/tools/context-contract.py STEP-024 --role planner --json
python3 .harness/tools/context-contract.py STEP-024 --role implementer --json
python3 .harness/tools/context-contract.py STEP-024 --role reviewer --json
```

Canonical `step-context.py` включает соответствующий contract в
`context.contextContract`. Legacy `readPaths` остаётся compatibility surface,
но больше не означает обязанность загружать artifact целиком.

## Runtime neutrality

У resolver **нет runtime/provider input**. Для одинаковых
`STEP + role + repository revision` semantic selection одинаков для Codex и
Claude. Adapter может физически читать ranges/sections разным способом, но не
меняет список required artifacts/sections.

## Principles

Здесь существуют **две разные namespaces**.

Project Principle `PRN-NNN` — project-owned engineering invariant. Его applicability остаётся semantic judgement. Чтобы deterministic resolver не пропустил project-wide blocking rule, planner/reviewer получают compact section projections active PRN: `Rule / Applies to / Exceptions / approved deviation`. Полный PRN не preload-ится.

Core Reasoning Principle `CRP-NNN` — Harness-owned leaf о способе reasoning/execution. Для CRP deterministic selector использует только machine facts STEP/Context и добавляет в `coreReasoningPrinciples[]` только applicable leaf paths. Model не получает весь CRP catalog. CRP не входит в `required`, не участвует в project traceability и не stale-ит Ready plan как PRN.

Подробности: [`CORE_REASONING_PRINCIPLES.md`](CORE_REASONING_PRINCIPLES.md).

## Optional / expanded context

Дополнительный context разрешён только с явной причиной:

```bash
python3 .harness/tools/context-contract.py \
  --expand src/integrations/provider.ts \
  --reason 'integration boundary discovered' --json
```

Expansion fail-closed:

- пустая reason запрещена;
- path обязан оставаться внутри repository;
- файл обязан существовать;
- `.harness/tools/**` не входит в normal semantic context.

Expansion не изменяет canonical links и не превращается в unrestricted
full-repository preload.

## Forbidden / unnecessary context

Common PLAN/IMPLEMENT/REVIEW не должен автоматически загружать:

- `.harness/tools/**`;
- unrelated `docs/**`, REQ, ADR или STEP;
- unrelated `.agents/skills/**`; из Core Reasoning Principles читаются только exact paths из `coreReasoningPrinciples[]`, conditionally invoked core capability разрешён только явным workflow trigger;
- весь repository «на всякий случай».

Python source остаётся подробно прокомментированным; token economy достигается
тем, что semantic role получает output tool, а не implementation tool.

## Codebase Grounding

Architecture-sensitive PLAN/AUDIT может условно вызвать core capability `codebase-grounding`. Она использует existing Context Contract как base context, а дополнительные code/tests/config paths получает только через explicit expansions. Для `simple` scope разрешено максимум 6 expansion files / 60 000 chars, для `complex` — 16 / 160 000. Deterministic validator `.harness/tools/codebase-grounding.py` сверяет revision, expansion safety, budget и evidence paths. Подробности: [`CODEBASE_GROUNDING.md`](CODEBASE_GROUNDING.md).

Capability не добавляет новую пользовательскую команду и не превращает semantic inference в authority.

## Semantic Blast Radius

High-risk PLAN/REVIEW может условно вызвать `semantic-blast-radius` после validated Codebase Grounding. Capability не получает отдельный второй context budget: grounding + blast expansions совместно обязаны укладываться в тот же `simple|complex` limit. Explicit dependency impact берётся из deterministic `impact-analysis`, semantic layer работает только с implicit behavior/contracts. Подробности: [`SEMANTIC_BLAST_RADIUS.md`](SEMANTIC_BLAST_RADIUS.md).

## Decision Archaeology

Когда architecture-change/reconcile нужен historical rationale, internal `decision-archaeology` может переиспользовать existing Context Contract как highest-priority canonical evidence set. Concrete target path вне Context Contract считается expansion и расходует тот же bounded budget; дополнительные files требуют explicit reason. Git target history ограничен отдельно, а external issue/PR/docs sources допускаются только как supplied evidence и не становятся repository-local proof. Подробности: [`DECISION_ARCHAEOLOGY.md`](DECISION_ARCHAEOLOGY.md).

## Fail-closed semantics

Missing linked artifact, unreadable/malformed required artifact, missing
обязательная section, invalid repository path или недоступный Git revision
возвращают BLOCKED/error. Resolver **не** переключается на «прочитать весь repo».

Synthetic regression доказывает:

```text
same STEP
├── planner manifest != reviewer manifest
├── Codex selection == Claude selection
├── unrelated REQ/ADR/docs absent
├── required section projection only
├── CRP namespace isolated from project PRN
├── ordinary phase receives only applicable CRP leaves, not full catalog
├── missing linked REQ → BLOCKED
└── explicit expansion requires reason
```
