---
name: audit-step
description: Audit a STEP or subsystem against its contract without mutating production code; capture drift and corrective actions.
---
# audit-step

Используй для `STEP AUDIT STEP-NNN` и audit-type tasks. Production mutation запрещена. Зафиксируй actual state до fixes, evidence, drift, risk. Historical STEP сравнивай с historical contract, а не с поздними future requirements. Substantive defects превращай в corrective STEP. Новый report сохраняй в configured `protocol.auditDirectory` как `AUDIT-YYYYMMDDTHHMMSSZ.md` с YAML frontmatter `schema: 1`, `kind: audit`; до завершения проверь его через `python3 .harness/tools/report_contract.py --file '<report-path>' --kind audit`. Historical legacy reports не переписывай.
