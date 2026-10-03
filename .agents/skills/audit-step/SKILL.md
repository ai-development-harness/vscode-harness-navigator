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

1. Определи audit target и applicable contract: STEP/REQ/ADR/architecture refs, acceptance, verification и relevant evidence.
2. Зафиксируй фактическое состояние code/config/tests/artifacts до любых последующих fixes.
3. Для каждого material finding опиши:
   - конкретное наблюдение и location;
   - какой contract/evidence с ним расходится;
   - воспроизводимый scenario или доказательство;
   - impact/risk;
   - рекомендуемое corrective direction.
4. Не повышай cosmetic/style difference до substantive drift без влияния на contract, correctness, safety или evidence.
5. Если найденный defect требует product mutation, изменения requirement/ADR/dependency или отдельного исследования — создай/предложи corrective STEP/RESEARCH/ADR; сам audit это изменение не выполняет.

## Report

Новый report сохраняй в configured `protocol.auditDirectory` как `AUDIT-YYYYMMDDTHHMMSSZ.md` с YAML frontmatter `schema: 1`, `kind: audit`.

В human-readable части явно разделяй observed state/evidence, drift/findings, risk и corrective actions. Не объявляй отсутствие drift, если значимая часть target surface не была проверена.

До завершения проверь report:

```bash
python3 .harness/tools/report_contract.py --file '<report-path>' --kind audit
```
