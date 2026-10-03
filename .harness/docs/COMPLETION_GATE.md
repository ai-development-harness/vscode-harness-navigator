# Completion / Convergence Gate

`STEP REVIEW` и Completion отвечают на разные вопросы:

- **REVIEW** — есть ли material defect в inspected implementation/revision;
- **COMPLETION** — выполнены ли все in-scope obligations текущего STEP/REQ/Ready plan;
- **RECONCILE** — согласован ли repository-wide factual state с knowledge artifacts.

REVIEW PASS сам по себе больше не является разрешением закрыть STEP.

## Pipeline

```text
Verification
→ STEP REVIEW
→ code verdict PASS
→ Completion Convergence
   ├─ PASS    → canonical close + completion proof + projections
   ├─ FAIL    → existing FIX loop
   └─ BLOCKED → stop current RUN
```

Нового command/lifecycle/CTS state нет.

## Deterministic precheck

```bash
python3 .harness/tools/completion-gate.py STEP-024 --json
```

До semantic convergence проверяются:

- machine-discoverable Acceptance;
- generated Verification PASS;
- Verification contract basis;
- exact product/worktree subject revision;
- current Ready/prerequisite contract.

Verification записывает два независимых durability proof:

1. hash exact Verification entries;
2. subject repository revision с исключённым STEP-файлом, в который сам runner
   записывает generated Evidence.

Поэтому запись Evidence не делает proof stale, а изменение code/config после
Verification — делает.

## Semantic payload

При code-review `verdict: pass` reviewer возвращает `completion`:

```json
{
  "disposition": "fix",
  "coverage": [
    {
      "criterion": "Failed save preserves input.",
      "status": "missing",
      "evidence": []
    }
  ],
  "assertions": {
    "requirementObligations": {
      "status": "covered",
      "evidence": ["REQ acceptance mapped"]
    },
    "plannedScope": {
      "status": "covered",
      "evidence": ["Ready plan inspected"]
    },
    "specializedObligations": {
      "status": "not_applicable",
      "evidence": ["No NFR obligation applies"]
    }
  },
  "findings": [
    {
      "kind": "missing_acceptance_coverage",
      "criterion": "Failed save preserves input.",
      "message": "Error path is not implemented."
    }
  ],
  "rationale": "Missing work is inside approved scope."
}
```

Writer присваивает stable `COMP-001...` и route:

- `disposition=fix` → `route=FIX`;
- `disposition=blocked` → `route=BLOCKED`;
- `pass` не допускает material findings/missing coverage.

Coverage criterion обязан буквально принадлежать `## Acceptance criteria`;
out-of-scope obligation добавить нельзя.

Отдельные assertions заставляют reviewer явно проверить linked REQ obligations,
существенные Ready plan actions и specialized/NFR obligations, не сводя
completion только к списку AC.

## Durable review history

Completion result сохраняется **в том же immutable REVIEW report**:

```text
review verdict: pass
completion_contract: 1
completion_result: pass|fail|blocked
## Completion convergence
<structured JSON>
```

Прошлый report не переписывается. PASS review с completion FAIL/BLOCKED не
считается type-specific completion proof.

## Crash recovery

Crash возможен в любой точке:

```text
immutable REVIEW written
→ completion result durable
→ status=completed
→ projections
→ local execution checkpoint
```

Recovery читает durable completion result:

- FAIL → existing REVIEW→FIX CTS edge;
- BLOCKED → terminal blocker;
- PASS → идемпотентно выполняет/повторяет canonical close и projection sync,
  затем восстанавливает PASS.

Поэтому crash после REVIEW report больше не может обойти Completion Gate.

## PROJECT STATUS

STEP metadata различает:

- `completed`;
- `review_pass_completion_pending`;
- `review_pass_completion_fix_required`;
- `review_pass_completion_blocked`;
- `not_ready_for_completion`.

Это projection, не второй lifecycle.
