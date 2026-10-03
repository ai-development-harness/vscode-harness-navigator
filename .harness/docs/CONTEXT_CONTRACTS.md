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
- tokenizer-neutral metrics `artifactCount`, `sectionCount`,
  `manifestChars`, `fullRepositoryPreload=false`.

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

Applicability Project Principle — semantic judgement. Чтобы deterministic
resolver не угадывал applicability и не пропустил project-wide blocking rule,
planner/reviewer получают compact section projections active PRN:
`Rule / Applies to / Exceptions / approved deviation`. Полный PRN не preload-ится.

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
- unrelated `.agents/skills/**`;
- весь repository «на всякий случай».

Python source остаётся подробно прокомментированным; token economy достигается
тем, что semantic role получает output tool, а не implementation tool.

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
├── missing linked REQ → BLOCKED
└── explicit expansion requires reason
```
