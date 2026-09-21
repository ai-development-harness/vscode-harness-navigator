# Repository Skills

Harness skills описывают **workflow**, а не конкретный technology stack.

Основные:

- `init-project`
- `add-plan-step`
- `plan-step`
- `implement-step`
- `review-step`
- `fix-step`
- `run-step`
- `audit-step`
- `project-status`
- `next-step`
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

- `git-workflow` — GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT SYNC и repository publication policy.

## Дополнительные core workflow skills

- `quick-fix` — мелкие low-risk изменения без STEP/REQ/ADR;
- `generate-github-templates` — регенерация GitHub Issue Forms и PR template по актуальному tooling;
- `update-harness` — read-only check и безопасный self-update protocol layer из immutable release tags.
