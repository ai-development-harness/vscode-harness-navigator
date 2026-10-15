# Матрица контрактов 33 core skills

Проверено по `.agents/skills/*/SKILL.md`, `.harness/command-transitions.json`, `template_contract.py`, `report_contract.py`, `semantic_artifacts.py` и `command_dispatch.py` после merge PR #308. Область: **только core skills**, не сторонние installs. Здесь перечислен **обязательный артефакт для конкретного skill**, а не все файлы, которые он может прочитать/изменить по задаче. `N/A` означает отсутствие отдельного обязательного durable report, а не отсутствие других проверок.

| Skill | Обязательный результат / владелец | Шаблон или writer | Проверка и граница SUCCESS |
| --- | --- | --- | --- |
| add-plan-step | STEP; project-owned | configured `taskDirectory/TEMPLATE.md` | `validate.py --mode manual` после записи |
| architecture-change | ADR при durable decision; project-owned | configured `adrDirectory/TEMPLATE.md` | `validate.py`; N/A если ADR не требуется |
| audit-step | audit report | `semantic-writer.py audit-report` + configured template | `report_contract.py --kind audit` после записи; gate #317 |
| benchmark-methodology | diagnostic assessment; N/A report | internal rubric / evidence | Не переносить INCONCLUSIVE в PASS |
| code-review | findings/assessment; N/A report | role prompt | Evidence gate, без самостоятельного durable writer |
| codebase-grounding | read-only grounding; N/A report | context/grounding tools | Факты только из actual source |
| core-reasoning-principles | правила reasoning; N/A | N/A | Не отдельная execution |
| create-skill | skill bundle, routing/provenance | skill spec / configured registry | `validate.py`, проверка routing |
| decision-archaeology | read-only assessment; N/A report | grounding/rubric | Unknown сохраняется unknown |
| documentation-sync | синхронизированные docs | existing project docs | Реальные ссылки и validate по scope |
| find-skill | skill-search report | `semantic-writer.py skill-search-report` + configured template | `report_contract.py --kind skill_search`; gate #317 |
| fix-step | исправленный product/evidence | STEP plan, verification dispatcher | `verification_freshness` / `complete_dispatch` |
| generate-github-templates | GitHub issue/PR templates | configured repository context | `validate.py` |
| git-workflow | git operation или local payload | git action executor | side-effect postconditions, no model PASS |
| high-rigor | bounded assessment; N/A report | internal arena/interrogate | reviewer evidence gates |
| implement-step | implementation changes | STEP plan | dispatcher Verification before SUCCESS |
| init-project | REQ/ADR/OQ/STEP + INIT reviews | configured templates + `finalize-project-init.py` | `validate.py` и finalizer |
| install-skill | installed skill bundle/provenance | inspected source | `validate.py`, registry/review |
| plan-step | draft + immutable planning-review | `semantic-writer.py` | current basis + Ready stamp |
| pr-maintenance | PR maintenance evidence; N/A durable report | provider/Git contracts | No auto merge or rewrite |
| project-status | generated status projections | `sync-projections.py` | `validate.py` |
| quick-fix | scoped product change; N/A report | project toolchain | tests/checks по request |
| reconcile-project | audit report | `semantic-writer.py audit-report` + configured template | `report_contract.py --kind audit` + `validate.py`; gate #317 |
| release-check | release-check report | `semantic-writer.py release-report` + configured template | `report_contract.py --kind release_check`; gate #317 |
| requirements-review | semantic review; N/A standalone report | canonical INIT review (когда INIT) | INIT finalizer проверяет lifecycle |
| review-step | immutable STEP REVIEW | `semantic-writer.py` | exact revision, review+completion proof |
| run-step | orchestrated STEP lifecycle; N/A report | command dispatcher | CTS + existing child guards |
| security-review | readonly review result; N/A report | reviewer rubric | structured findings |
| semantic-blast-radius | proof/assessment; N/A report | internal deterministic validator | current executable evidence |
| structural-enforcement | verified rules/proposals; N/A report | deterministic checks | no unsupported rule |
| structured-reflection | immutable reflection report | `structured-reflection.py write` | dedicated validator/tool |
| update-harness | managed update outcome/report | updater | update contract + transaction |
| write-tests | test/code changes; N/A report | project tests | real test runner/validation |

## Findings первого этапа (#313, #315)

1. **Missing specification:** `reconcile-project` ранее требовал лишь `schema: 1`, не документировал `mode: audit`, H1 и timestamp. Исправлено явной отсылкой к canonical template и post-write validation.
2. **Manual operational report construction:** `audit-step`, `release-check`, `find-skill` валидировали отчёты, но сами создавали filename/UTC/frontmatter. Следующий этап **#316** должен перенести механику в deterministic writer; длинные технические поля из skill после внедрения writer можно удалить.
3. **Already deterministic:** `plan-step` / `review-step` используют `semantic-writer.py`, `init-project` — `finalize-project-init.py`; не переписывать готовые lifecycle paths.
4. **Missing execution-bound enforcement:** для audit/reconcile/release/search один только `report_contract.py` не связывает отчёт с текущим executionId. Это отдельный этап **#317**, до его завершения запись отчёта моделью не является технической гарантией `complete SUCCESS`.
5. **Payload truth:** обязательные sections должны содержать фактическое evidence. Заполненные шаблонные `TBD` нельзя принимать за доказательство. Проверять и структурно, и с позиции current execution/provenance; не подменять живые semantic observations одним regex.

## Область изменений

Нет новых CTS-команд, второго парсера YAML/Markdown, массового преобразования 33 skills, изменений Claude/Codex runtime contract или переписывания исторических immutable reports. Детали writer/gate задают последующие #316/#317 и должны быть отражены в документации только после работающих тестов.

## Исполнение после #316/#317

`semantic-writer.py audit-report|release-report|skill-search-report` формирует metadata/имя/UTC и сохраняет **operationalReport receipt** в текущей local execution. `command_dispatch.complete_dispatch()` повторно проверяет path, owner/kind, content SHA-256, canonical timestamp/schema и subject hash. Обычная текстовая проверка самим агентом больше не служит authority для terminal SUCCESS. Потребитель не должен вручную создавать второй report или подменять `executionId`.
