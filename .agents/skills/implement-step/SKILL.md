---
name: implement-step
description: Implement a planned STEP within its scope, update tests, satisfy canonical verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

Execution Status ведёт global wrapper.

- Используй `context`, уже возвращённый canonical dispatcher handoff: `context.contextContract.required` задаёт exact artifact sections, а `implementPrerequisites.status=PASS` — deterministic prerequisite gate. Если `context.contextContract.coreReasoningPrinciples` непуст, прочитай только перечисленные CRP leaf `path`; не загружай весь catalog. CRP задаёт способ reasoning/execution и не заменяет project-owned `PRN-NNN` или deterministic gates. Legacy `readPaths` остаётся compatibility surface и не означает «прочитать artifact целиком». Дополнительный context загружай только через explicit expansion с material reason; `.harness/tools/**` не является normal semantic input. Повторно `step-context.py`/resolver и prerequisite reasoning не запускай.
- До product mutation запусти обычную deterministic validation проекта/Harness согласно workflow; не дублируй prerequisite reasoning.
- Если execution-status показывает resume этой же команды, сначала изучи существующий diff/Evidence и продолжи недостающее; не переделывай готовое.
- При первой фактической product mutation canonical `status → in_progress`.
- Если Ready plan содержит `plan.execution_groups`, прочитай deterministic projection через `python3 .harness/tools/execution-groups.py STEP-NNN --json`. В v1 исполняй groups **последовательно** по `topologicalOrder`; не начинай group до её `dependsOn`. `parallel=true` — только capability/reporting hint для будущего orchestration и не разрешает автоматически запускать несколько write-agents. Соблюдай `mutationPaths` как declared conflict boundary и выполни `verificationResponsibilities` группы, не подменяя ими canonical STEP Verification.
- Выбирай write-role по характеру работы:
  - `mechanic` — только механическая/локальная трансформация с уже однозначно заданным результатом, без нового behavior/semantic design;
  - `implementer` — изменение behavior, нескольких взаимодействующих компонентов либо работа, где остаются инженерные решения внутри утверждённого STEP contract.
  При сомнении используй `implementer`; `mechanic` не является способом удешевить reasoning там, где решение ещё нужно принять.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Если implementation обнаружил, что approved REQ/ADR/STEP contract невозможно корректно выполнить или требуется изменить behavior/architecture/Acceptance, верни `BLOCKED`. Не меняй owning contract и не подгоняй документацию под уже изменённый code из IMPLEMENT. Handoff должен назвать предполагаемого owner: REQ / ADR / OQ / STEP.
- Добавь только необходимые tests, которые доказывают затронутое Acceptance/regression. Новый regression/security test должен иметь provenance: explicit REQ/ADR/STEP/PRN invariant, reproduced defect либо confirmed project-specific scenario; framework/platform capability сама по себе не является основанием.
- Если Ready plan содержит unresolved hypothesis/proof obligation, выполни только запланированный bounded falsification/evidence check. Не материализуй production hardening/test из hypothesis автоматически: invalidated scenario отбрасывается; confirmed scenario, требующий новой production mutation вне уже доказанного contract, возвращает `BLOCKED` с handoff к свежему `STEP PLAN STEP-NNN`.
- Verification commands вручную не запускай только ради completion: при result `SUCCESS` dispatcher сам запускает canonical Verification и пишет generated Evidence.
- `VERIFICATION_FAIL` возвращает factual command failure — исправь его и повтори completion. `VERIFICATION_MANUAL_REQUIRED` означает выполнить только перечисленные manual checks и передать exact `manualVerification` observations через dispatcher details.
- `VERIFICATION_BLOCKED` не обходи reasoning-ом: invalid/mutating verification требует исправления contract/workflow.
- Не ставь `status: completed` до independent schema-valid review PASS и type-specific completion proof.
- После полного scope предложи result `SUCCESS`; фактический verification gate принадлежит dispatcher.

Single IMPLEMENT после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к REVIEW.
