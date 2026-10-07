---
name: semantic-blast-radius
description: Evaluate implicit behavioral impact beyond deterministic artifact links for high-risk STEP changes and require direct executable proof for critical safety assumptions.
---
# semantic-blast-radius

Это **внутренняя semantic capability**, а не новая пользовательская команда. Она работает поверх deterministic impact analysis и validated `codebase-grounding`.

## Authority boundary

Harness deterministically owns:

- STEP risk flags и exact repository revision;
- explicit downstream STEP/dependency impact;
- Context Contract и expansion safety;
- grounding provenance;
- Verification commands и freshness generated evidence;
- bounded context budget.

Модель не пересчитывает эти facts. Она отвечает только за semantic hypotheses о неявном blast radius.

## Preflight

Сначала вызови:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-NNN --phase plan --json
```

или на review:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-NNN --phase review --json
```

`required=true` для STEP с любым material `risk_flags` кроме `none`. Low-risk STEP с `risk_flags: [none]` не получает capability автоматически.

Если capability required, сначала получи validated `codebase-grounding` для того же revision. Grounding даёт compact flow/ownership/boundaries; blast radius не начинает второй repository scan.

## Что искать

Проверяй только material affected behavior:

- implicit API/data/behavior contracts;
- indirect consumers и integration seams;
- compatibility/migration effects;
- shared state/concurrency boundaries;
- operational/runtime assumptions;
- test surfaces, без которых safety claim не доказан.

Для каждого material hypothesis укажи конкретное affected behavior и evidence paths. Не выдавай vague «может сломаться».

## Critical assumptions

Для required analysis выдели **1–2 critical hypotheses**, на которых держится safety claim.

На PLAN:

- если direct proof уже существует, зафиксируй его только когда **exact Verification command**, указанный в proof, имеет fresh generated PASS evidence на текущем subject revision; pending unrelated manual checks остаются отдельным completion/review gate;
- если proof появится только после реализации, поставь `proof.status=planned` и добавь соответствующий command/check в `testSurfaces`;
- `INCONCLUSIVE` допустим как planning result, но critical proof obligation должен попасть в Verification/Implementation plan до Ready;
- одного model self-report `proof.status=proven` недостаточно для PASS.

На REVIEW:

- `PASS` допустим только когда каждая critical hypothesis имеет `proof.status=proven`;
- direct proof должен ссылаться на exact `Verification` command текущего STEP;
- exact proof command обязана иметь fresh generated PASS evidence на текущем subject revision; unrelated manual checks не подменяются этим proof и проверяются существующими completion/review gates;
- отсутствующий/устаревший executable proof => `INCONCLUSIVE`, не PASS.

## Structured payload

```json
{
  "schemaVersion": 1,
  "status": "INCONCLUSIVE",
  "phase": "plan",
  "scope": "complex",
  "stepId": "STEP-024",
  "repositoryRevision": {"git_head": "...", "worktree_hash": "..."},
  "hypotheses": [
    {
      "id": "H-001",
      "risk": "Consumer assumes old response ordering",
      "affectedBehavior": "Existing API clients parse items in stable order",
      "critical": true,
      "evidencePaths": ["src/api.ts", "src/client.ts"],
      "proof": {
        "status": "planned",
        "kind": "verification-command",
        "command": "python3 tests/compat.py"
      }
    }
  ],
  "provenObservations": [
    {
      "claim": "Client and server share the same ordering field",
      "evidencePaths": ["src/api.ts", "src/client.ts"]
    }
  ],
  "testSurfaces": [
    {
      "behavior": "Old client remains compatible",
      "verification": "python3 tests/compat.py"
    }
  ],
  "expansions": []
}
```

Status: `PASS | INCONCLUSIVE | BLOCKED`.

Проверь payload:

```bash
python3 .harness/tools/semantic-blast-radius.py STEP-NNN \
  --phase plan \
  --context-file '<context-contract-json>' \
  --grounding-file '<validated-grounding-json>' \
  --payload-file '<blast-radius-json>' \
  --json
```

Validator:

- заново строит deterministic preflight;
- revalidates grounding против того же Context Contract;
- не принимает stale revision;
- enforce-ит общий grounding + blast expansion budget;
- проверяет provenance всех hypothesis/observation evidence paths;
- требует 1–2 critical hypotheses для required analysis;
- на REVIEW разрешает PASS только при fresh Verification PASS и critical proofs, привязанных к реально существующим Verification commands.

## Integration

### STEP PLAN

Blast radius выполняется после bounded grounding и до draft Implementation plan. Deterministic explicit affected STEP не смешивай с semantic hypotheses.

Если result `INCONCLUSIVE`, planner обязан перенести critical proof obligations в Verification/plan. Planning reviewer проверяет, что они не потеряны.

### STEP REVIEW

Для required STEP повтори capability на exact reviewed revision. `INCONCLUSIVE` из-за missing executable proof является evidence defect и не может сопровождать semantic REVIEW PASS.

## Запреты

- не менять код;
- не придумывать downstream links, уже вычислимые impact-analysis;
- не считать self-report proof-ом;
- не считать отсутствие найденного риска доказательством безопасности;
- не превращать low-risk STEP в обязательный expensive pass;
- не расширять Context Contract молча.
