# Repository Skills

Harness skills описывают **workflow**, а не конкретный technology stack.

Каждый skill bundle хранит человекочитаемый provenance в соседнем `UPSTREAM.md`. Для встроенных core skills это `Source: project-native`. Third-party skills дополнительно имеют deterministic `PROVENANCE.json` с exact BASE/installed hashes и fork/update metadata; его создаёт `.harness/tools/skill-provenance.py`, а не модель вручную.


Основные:

- `init-project`
- `add-plan-step`
- `plan-step`
- `implement-step`
- `review-step`
- `fix-step`
- `run-step`
- `audit-step`
- `codebase-grounding` — conditional read-only mental-model capability для architecture-sensitive PLAN/AUDIT; не пользовательская команда
- `semantic-blast-radius` — conditional implicit-impact/proof capability поверх deterministic impact analysis; не пользовательская команда
- `decision-archaeology` — bounded read-only reconstruction historical rationale с evidence/confidence/conflict contract; не пользовательская команда
- `core-reasoning-principles` — internal CRP router; Context Contract выдаёт только applicable leaf paths, не весь catalog
- `structural-enforcement` — recurring structured corrections → strongest feasible enforcement proposal; не пользовательская команда
- `high-rigor` — optional Arena/Interrogate fan-out с deterministic activation, exact trace и explicit degradation; не пользовательская команда
- `benchmark-methodology` — optional performance evidence methodology + deterministic sufficiency gate; не пользовательская команда
- `pr-maintenance` — read-only PR facts + bounded semantic CI/review triage поверх существующего Git/PR lifecycle; не пользовательская команда

Отдельно от Harness-owned core skills проект может иметь **project-owned Verification Driver** `.agents/skills/verify-product/SKILL.md`. Его структура и qualification контролируются `.harness/tools/project-verification.py`, а machine-readable feature map хранится в `docs/verification/feature-map.json`. Этот skill не входит в `required_skills` и не обновляется Harness updater-ом как Core.
- `project-status`
- `reconcile-project`
- `architecture-change`
- `requirements-review`
- `documentation-sync`
- `code-review`
- `security-review`
- `write-tests`
- `release-check`
- `find-skill`
- `install-skill`
- `create-skill`
- `update-harness`

После INIT добавляй project/technology-specific skills отдельно. Выбирай минимальный достаточный набор на задачу: лишние skills увеличивают контекст и риск конфликтующих инструкций.

## Skill management

Дополнительные technology/project skills ищи через `SKILL FIND`, устанавливай через `SKILL INSTALL` и создавай через `SKILL CREATE`. Third-party content проходит inspection и provenance tracking; registry находится в `docs/skills/REGISTRY.md`.

- `git-workflow` — GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT PR FINISH / GIT SYNC и repository publication policy.

## Дополнительные core workflow skills

- `quick-fix` — мелкие low-risk изменения без STEP/REQ/ADR;
- `generate-github-templates` — регенерация GitHub Issue Forms и PR template по актуальному tooling;
- `update-harness` — read-only check и безопасный self-update protocol layer из immutable release tags.
