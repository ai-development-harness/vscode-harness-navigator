# Codebase Grounding

Codebase Grounding — внутренняя read-only semantic capability для восстановления компактной mental model подсистемы до architecture-sensitive planning/audit work.

Она не добавляет новую пользовательскую команду и не заменяет Context Contracts.

```text
canonical STEP / audit target
        ↓
deterministic Harness context
        ↓
bounded codebase grounding
        ↓
validated structured payload
        ↓
planner / architect / auditor
```

## Зачем

Canonical REQ/ADR/STEP объясняют intent и принятые решения, но не всегда достаточно подробно показывают фактический runtime/data flow существующего кода. Прямой переход к plan в такой ситуации создаёт два риска:

- модель строит plan по неверной mental model;
- ради подстраховки загружается слишком большая часть repository.

Grounding закрывает этот разрыв отдельной read-only стадией.

## Authority boundary

Deterministic authority остаётся у Harness:

- canonical paths и artifact links;
- exact repository revision;
- Context Contract required sections;
- context expansion safety;
- measurable context budget validation.

Модель отвечает только за semantic reconstruction:

- flow;
- ownership;
- boundaries;
- interfaces;
- invariants;
- gotchas;
- unknowns.

Grounding payload — proposal/navigation evidence, а не ADR, REQ или implementation plan.

## Trigger policy

Capability включается условно, когда:

- ownership/state responsibility неочевидны;
- есть cross-module/service boundary;
- затронут API/protocol/schema/integration seam;
- есть shared state, async/concurrency lifecycle;
- material plan зависит от понимания runtime/data flow;
- audit проверяет subsystem behavior, а не локальный isolated artifact.

Для low-risk локальной правки в одном очевидном модуле отдельный grounding pass не нужен.

## Context policy

Grounding начинает только с existing `context.contextContract.required` и deterministic facts caller-а.

Дополнительные code/tests/config paths разрешаются только explicit expansion с reason. Full-repository preload запрещён.

Два bounded режима:

| Scope | Max expansion files | Max expansion chars |
|---|---:|---:|
| `simple` | 6 | 60 000 |
| `complex` | 16 | 160 000 |

Эти лимиты относятся к дополнительным файлам. Базовый Context Contract отдельно публикует `artifactCount`, `sectionCount`, `manifestChars` и `fullRepositoryPreload=false`.

Если target не помещается в complex budget, его нужно сузить/разделить либо явно вернуть unresolved unknown. Увеличение budget «по ходу исследования» запрещено.

## Structured payload

Canonical schema описана в `.agents/skills/codebase-grounding/SKILL.md`.

Минимальные semantic sections:

- `flow`;
- `ownership`;
- `boundaries`;
- `interfaces`;
- `invariants`;
- `gotchas`;
- `unknowns`;
- `evidencePaths`;
- `expansions`.

Для PASS `flow`, `ownership` и `boundaries` непустые. Каждый элемент semantic-массива использует envelope `{claim, evidence[]}`; claim-level evidence должно быть доступно в required context/validated expansions и одновременно перечислено в top-level `evidencePaths`.

## Deterministic validation

```bash
python3 .harness/tools/codebase-grounding.py \
  --context-file '<context-contract-json>' \
  --payload-file '<grounding-json>' \
  --json
```

Validator fail-closed проверяет:

- schema/status/scope;
- exact object `repositoryRevision.git_head/worktree_hash`;
- Context Contract `fullRepositoryPreload=false`;
- каждый expansion через canonical Context Contract expansion rule;
- число и character size expansions;
- что `evidencePaths` относятся только к required context или validated expansions.

Таким образом semantic model не может объявить evidence path, который grounding pass не должен был читать.

## PLAN integration

`STEP PLAN` не запускает новый resolver. Planner использует Context Contract из canonical dispatcher handoff и при material trigger вызывает `codebase-grounding` до architecture completeness pass.

Validated grounding payload передаётся planner/architect как compact handoff. Он не заменяет independent planning-review.

## REVIEW integration

Обычный REVIEW не обязан запускать отдельный grounding pass. Но если conditional high-risk capability (например Semantic Blast Radius) требует mental model, grounding использует reviewer Context Contract из dispatcher handoff и exact reviewed revision. Это не разрешает повторный resolver/full-repository scan.

## AUDIT integration

Для subsystem audit capability используется, когда finding требует восстановления фактической цепочки исполнения или ownership.

Если audit handoff ещё не содержит Context Contract, audit workflow может один раз получить planner-style contract через `context-contract.py`. Это остаётся internal read-only tooling и не расширяет command surface.

## Resume / durability

Validated payload можно временно сохранить под `.harness/local/**`, если он нужен после session restart. Перед reuse exact revision должна совпадать с current context.

Grounding payload не становится новым source of truth: durable decisions всё равно принадлежат ADR/REQ/OQ/STEP, а audit conclusions — audit report.
