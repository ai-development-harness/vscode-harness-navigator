---
name: decision-archaeology
description: Reconstruct historical rationale from canonical artifacts and bounded repository history, preserving conflicting evidence and separating documented decisions from inference.
---
# decision-archaeology

Это **внутренняя read-only capability**, а не новая пользовательская команда. Используй её, когда перед architecture change или reconcile нужно понять, **почему** существующее устройство системы появилось и какие historical constraints нельзя случайно потерять.

Capability отвечает на rationale/history. Для фактического runtime flow/ownership используй `codebase-grounding`.

## Authority boundary

Harness deterministically owns:

- exact repository revision;
- bounded Git history target-файла;
- allowed Context Contract paths и explicit expansions;
- evidence provenance/timestamps для repository-local artifacts и commits;
- context/history limits;
- structural separation `documented | inference`.

Модель отвечает за semantic synthesis: competing explanations, confidence, conflicts, gaps и possible stale-decision assessment.

Conversation/transcript **никогда** не является evidence/source of truth.

## Evidence priority

Ищи rationale в таком порядке:

1. canonical ADR / REQ / Project Principles / architecture artifacts;
2. Git history target-файла: commits, commit messages, blame/show при необходимости;
3. реально полученные issue / PR / project-doc sources;
4. дополнительные engineering sources, только если они фактически доступны.

Не начинай с issue/PR/chat, если canonical decision уже документирован. Более новый источник не считается автоматически более авторитетным.

## Preflight

Определи один concrete repository-relative target, вокруг которого возник вопрос `why`, затем:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target '<path>' \
  --scope simple \
  --json
```

Если capability вызывается из STEP PLAN/REVIEW context, передай тот же Context Contract:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target '<path>' \
  --scope complex \
  --context-file '<context-contract-json>' \
  --json
```

Preflight возвращает exact revision, bounded history и budget. Не заменяй его full-repository `git log`.

## Bounded investigation

`simple`:

- target + максимум 6 expansion files / 60 000 chars;
- максимум 12 commits target history;
- максимум 8 rationale claims;
- максимум 8 supplied external evidence records.

`complex`:

- target + максимум 12 expansion files / 120 000 chars;
- максимум 24 commits;
- максимум 16 claims;
- максимум 16 supplied external evidence records.

Если target уже входит в Context Contract, он не расходует expansion budget. Иначе target считается первым bounded expansion.

Дополнительный файл разрешён только explicit expansion с reason. Не сканируй repository целиком.

## Source-control investigation

Preflight даёт список candidate commits touching target. Для material candidates разрешены read-only Git inspection commands, например:

```bash
git show --stat --format=fuller <sha>
git show --format=fuller <sha> -- '<target>'
git blame -L <start>,<end> -- '<target>'
```

Не выполняй Git mutations. Claim может ссылаться только на commit из bounded preflight history; validator отвергнет произвольный SHA.

## External evidence

Issue/PR/docs/chat/observability/analytics могут попасть в `suppliedEvidence` **только если источник реально был получен runtime/connector-ом в текущем investigation**.

Для каждого supplied record нужны:

- stable local ID `E-NNN`;
- `sourceKind`;
- URL/ref;
- title;
- timestamp `observedAt`.

Validator помечает такой source как `supplied-not-locally-verifiable`. Это не repository-local proof.

Не создавай фиктивный URL/ref, чтобы усилить confidence.

## Claim contract

Каждый rationale claim:

```json
{
  "id": "R-001",
  "statement": "Retry limit was introduced to cap provider recovery latency.",
  "basis": "documented",
  "confidence": "high",
  "evidence": [
    {"kind": "artifact", "ref": "docs/adr/ADR-004-recovery.md"},
    {"kind": "commit", "ref": "<sha>"}
  ]
}
```

`basis=documented` требует evidence. Это может быть repository-local artifact/commit либо реально полученный external source (PR/issue/doc). External source остаётся явно помеченным как `supplied-not-locally-verifiable`, поэтому его нельзя выдавать за локально проверенный факт.

Inference:

```json
{
  "id": "R-002",
  "statement": "The same constraint probably explains the current timeout.",
  "basis": "inference",
  "confidence": "low",
  "evidence": [],
  "uncertainty": "No historical source names the timeout value directly."
}
```

Inference без evidence:

- обязана иметь `confidence=low`;
- обязана сопровождаться explicit `gaps[]`;
- делает итог `INCONCLUSIVE`, а не PASS.

## Conflicting evidence

Не сглаживай противоречие в один красивый narrative. Если два supported claims конфликтуют, верни оба и отдельный:

```json
{
  "claimIds": ["R-001", "R-002"],
  "summary": "ADR says compatibility drove the choice; later PR says latency drove the replacement."
}
```

Recency сама по себе не решает conflict.

## Stale ADR assessment

Если current implementation/history выглядит несовместимым с Accepted ADR, верни `staleDecisions[]` с:

- artifact path;
- `current | possibly-stale | unknown`;
- reason;
- evidence.

Это **diagnostic assessment**, не canonical lifecycle mutation. Capability не меняет ADR status и не создаёт superseding ADR сама.

## Validation

Собери payload и проверь:

```bash
python3 .harness/tools/decision-archaeology.py \
  --target '<path>' \
  --scope complex \
  --context-file '<context-contract-json>' \
  --payload-file '<archaeology-json>' \
  --json
```

Validated result возвращает:

- claims + confidence;
- normalized timestamped `evidenceMap`;
- explicit conflicts;
- gaps;
- stale-decision assessments;
- bounded history/context metrics.

## Integration

### architecture-change

Используй capability перед новым/superseding ADR, если:

- rationale текущего решения неочевиден;
- есть competing architecture explanations;
- Accepted ADR может быть stale;
- изменение рискует снять historical compatibility/security/operational constraint.

После investigation преврати findings в:

- **Preserve** — historical constraints, которые всё ещё доказанно действуют;
- **Change** — explicit intended replacement;
- **Avoid** — ранее отвергнутые/опасные варианты, если evidence это подтверждает;
- **Risk** — gaps/conflicts, требующие ADR/OQ/RESEARCH.

### PROJECT RECONCILE

Используй archaeology только для material drift, где нельзя честно классифицировать owner без historical rationale. Не запускай по каждому файлу.

Если evidence показывает, что code intentional и ADR obsolete — route к architecture owner/superseding ADR. Если evidence подтверждает current ADR — code drift остаётся code/corrective STEP. Если history ambiguous — не выбирай intent; оставь finding BLOCKED/RESEARCH.

## Запреты

- не менять code/docs/ADR;
- не использовать transcript/memory как evidence;
- не выдавать inference за documented decision;
- не скрывать conflicting evidence;
- не считать newest source автоматически authoritative;
- не читать весь repository/history;
- не повышать confidence из-за количества одинаково зависимых источников;
- не создавать provider-specific обязательность для core Harness.
