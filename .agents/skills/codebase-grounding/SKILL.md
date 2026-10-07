---
name: codebase-grounding
description: Build a bounded read-only mental model of a subsystem from deterministic Harness context before architecture-sensitive planning or audit work.
---
# codebase-grounding

Это **внутренняя reusable capability**, а не новая пользовательская команда. Вызывай её из planning/audit/architecture-sensitive workflow только когда без восстановления runtime/data flow, ownership и boundaries высок риск строить plan или finding на неверной mental model.

## Граница

- Только read-only исследование.
- Не строит Implementation plan.
- Не принимает ADR/architecture decision.
- Не меняет product code, artifacts, Git state или Harness state.
- Не использует transcript/chat history как source of truth.
- Не начинает с обхода всего repository.
- Deterministic facts и canonical links бери из уже разрешённого Harness context; semantic inference всегда отделяй от evidence.

Для `STEP PLAN` используй **тот же** `context.contextContract`, который пришёл из canonical dispatcher handoff. Не вызывай повторно `step-context.py` или resolver только ради grounding.

Для `STEP REVIEW`, когда grounding явно затребован downstream capability (например, Semantic Blast Radius), используй **тот же reviewer Context Contract** из canonical dispatcher handoff и exact reviewed revision; новый resolver не запускай.

Для `STEP AUDIT`, если command handoff не содержит Context Contract, разреши его **один раз** через existing read-only tool:

```bash
python3 .harness/tools/context-contract.py STEP-NNN --role planner --json
```

Это внутренний deterministic input capability, а не новая command semantics.

## Когда запускать

Запускай grounding, если есть хотя бы один material signal:

- ownership ответственности или state неочевиден;
- изменение пересекает module/service/bounded-context boundary;
- есть public/internal API, protocol/schema или integration seam;
- есть shared state, async/concurrency lifecycle;
- план затрагивает несколько слоёв, а data/runtime flow не очевиден из canonical artifacts;
- audit требует понять фактическую цепочку исполнения, а не только сравнить один файл с contract.

Для локального low-risk изменения в одном очевидном модуле capability не запускай автоматически.

## Bounded context policy

Сначала прочитай только `contextContract.required` и deterministic facts caller-а. Код/tests/config добавляй через explicit Context Contract expansion с material reason.

Выбери scope до expansions:

| Scope | Когда | Max expansion files | Max expansion chars |
|---|---|---:|---:|
| `simple` | один subsystem / короткий flow / очевидные boundaries | 6 | 60 000 |
| `complex` | несколько модулей/services или несколько integration seams | 16 | 160 000 |

`expansion chars` — Unicode character count реально раскрытых дополнительных файлов. Canonical artifact sections учитываются отдельно через `contextContract.metrics` (`artifactCount`, `sectionCount`, `manifestChars`).

Если лимита недостаточно:

1. сузь target;
2. раздели grounding на несколько независимых targets;
3. либо верни unresolved unknown/blocker.

Не повышай лимит молча и не переходи к full-repository preload.

Каждый дополнительный файл обязан пройти:

```bash
python3 .harness/tools/context-contract.py \
  --expand '<repo-relative-path>' \
  --reason '<material reason>' \
  --json
```

## Что восстановить

Собери компактную mental model:

1. **Flow** — runtime/data/control flow от входа до существенного результата.
2. **Ownership** — кто владеет state, orchestration, persistence, side effects и policy.
3. **Boundaries** — module/service/API/state/integration seams.
4. **Interfaces** — public/internal contracts, schemas, events, adapters.
5. **Invariants** — условия, которые downstream change не должен нарушить.
6. **Gotchas** — hidden coupling, lifecycle/recovery assumptions, non-obvious constraints.
7. **Unknowns** — только действительно недоказанные места; не заполняй их догадками.
8. **Evidence paths** — repository paths, на которых основаны claims.

Не превращай список файлов в mental model: downstream phase должен понимать **как система работает**, а не только где лежит код.

## Structured output

Верни schema-v1 JSON:

```json
{
  "schemaVersion": 1,
  "status": "PASS",
  "scope": "simple",
  "target": "конкретная подсистема/flow",
  "repositoryRevision": {
    "git_head": "<exact HEAD or null>",
    "worktree_hash": "<exact worktree hash or null>"
  },
  "flow": [
    {
      "claim": "что происходит",
      "evidence": ["src/example.ts"]
    }
  ],
  "ownership": [
    {
      "claim": "какая ответственность и кто ей владеет",
      "evidence": ["src/example.ts"]
    }
  ],
  "boundaries": [
    {
      "claim": "какая boundary/integration seam существенна",
      "evidence": ["src/example.ts"]
    }
  ],
  "interfaces": [],
  "invariants": [],
  "gotchas": [],
  "unknowns": [],
  "evidencePaths": ["src/example.ts"],
  "expansions": [
    {
      "path": "src/example.ts",
      "reason": "runtime flow implementation required"
    }
  ]
}
```

`flow`, `ownership` и `boundaries` при `PASS` должны быть непустыми. `gotchas` и `unknowns` могут быть пустыми. Каждый элемент semantic-массивов — объект `{claim, evidence[]}` с непустым claim и хотя бы одним repository evidence path; каждый такой path обязан также присутствовать в top-level `evidencePaths`.

Проверь payload детерминированно:

```bash
python3 .harness/tools/codebase-grounding.py \
  --context-file '<context-contract-json>' \
  --payload-file '<grounding-json>' \
  --json
```

Validator:

- сверяет exact repository revision;
- повторно валидирует каждый explicit expansion;
- считает реальные expansion chars;
- enforce-ит `simple|complex` budget;
- запрещает `fullRepositoryPreload=true`;
- разрешает top-level и claim-level evidence только из canonical required paths или validated expansions и требует индексировать claim evidence в `evidencePaths`.

Невалидный payload не передавай downstream как grounding result.

## Handoff downstream

Передай validated payload caller-у как compact phase-local handoff. Caller использует его для следующей semantic стадии вместо повторного полного исследования.

Если payload нужно пережить session boundary, допустимо сохранить его только под `.harness/local/**`; при resume обязательно повторно сверить `repositoryRevision`. Это navigation/working evidence, а не новый canonical source of truth.
