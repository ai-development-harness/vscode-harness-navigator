---
name: audit-step
description: Perform a read-only evidence-based audit of a STEP or subsystem against the applicable contract, record drift and risk, and route substantive defects into corrective work.
---
# audit-step

Используй для `STEP AUDIT STEP-NNN` и audit-type tasks.

## Граница

- Production mutation запрещена.
- Audit сначала фиксирует actual state и evidence, а не исправляет найденное.
- Historical STEP сравнивай с **historical contract, применимым к этой работе**, а не с требованиями, появившимися позже.
- Projection или поздняя документация не должны задним числом менять смысл уже проверенного historical contract.
- Historical legacy reports не переписывай.

## Что проверить

Если audit target — subsystem/flow и для finding нужно восстановить фактический runtime/data flow, ownership или integration boundaries, сначала используй внутренний core capability `codebase-grounding`. Capability остаётся read-only и bounded. Если command handoff не содержит Context Contract, для `STEP AUDIT STEP-NNN` разреши planner-style contract один раз через `python3 .harness/tools/context-contract.py STEP-NNN --role planner --json`; дополнительный code context — только explicit expansions. Validated grounding payload используй как compact input аудита, а не как новый source of truth.

1. Определи audit target и applicable contract: STEP/REQ/ADR/architecture refs, acceptance, verification и relevant evidence.
2. Зафиксируй фактическое состояние code/config/tests/artifacts до любых последующих fixes.
3. Для каждого material finding опиши:
   - конкретное наблюдение и location;
   - какой contract/evidence с ним расходится;
   - воспроизводимый scenario или доказательство;
   - impact/risk;
   - рекомендуемое corrective direction.
4. Не повышай cosmetic/style difference до substantive drift без влияния на contract, correctness, safety или evidence.
5. Если audit finding уже представлен structured evidence и совпадает с повторяющимся error class, передай его internal `structural-enforcement` через normalized evidence envelope. Не реконструируй classKey из audit prose и не используй transcript как evidence.
6. Для спорного/high-risk audit surface проверь optional Interrogate: `python3 .harness/tools/high-rigor.py --mode interrogate --phase audit --step STEP-NNN --json`. При `RUN` reviewers получают один exact read-only audit surface/rubric; consensus/disagreement map используется только как дополнительный semantic signal. Audit evidence/contract остаются authority; `DEGRADED` раскрывай явно.
7. Если найденный defect требует product mutation, изменения requirement/ADR/dependency или отдельного исследования — создай/предложи corrective STEP/RESEARCH/ADR; сам audit это изменение не выполняет.

## Report

Новый report сохраняй в configured `protocol.auditDirectory` как `AUDIT-YYYYMMDDTHHMMSSZ.md` с YAML frontmatter `schema: 1`, `kind: audit`.

В human-readable части явно разделяй observed state/evidence, drift/findings, risk и corrective actions. Не объявляй отсутствие drift, если значимая часть target surface не была проверена.

До завершения проверь report:

```bash
python3 .harness/tools/report_contract.py --file '<report-path>' --kind audit
```
