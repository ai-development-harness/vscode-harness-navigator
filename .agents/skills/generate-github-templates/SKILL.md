---
name: generate-github-templates
description: Regenerate GitHub Issue Forms and Pull Request template from the project's current stack, tooling, CI, conventions and language policy.
---
# generate-github-templates

Используй для `GITHUB GENERATE TEMPLATES`. Команда доступна до и после INIT и всегда работает по **текущему** состоянию repository.

## Цель

Создать/заменить GitHub collaboration templates так, чтобы они отражали реально используемые технологии, команды проверки, компоненты и project conventions, а не generic placeholder прошлой версии проекта.

## Источники

Перед генерацией изучи, что реально существует:

1. `.harness/manifest.yaml`, особенно `language.githubTemplates`;
2. configured `sources.projectOverview`, requirements, architecture и development docs;
3. package/build manifests и workspace configs;
4. test/lint/typecheck/build scripts/targets;
5. CI workflows;
6. runtime/deployment/container/tooling config;
7. текущие `.github/ISSUE_TEMPLATE/*` и `.github/pull_request_template.md`.

Не выдумывай команды/версии/инструменты. Если проект ещё пуст, создай нейтральные templates и пометь только фактически известные поля.

## Обязательный результат

Создай или полностью замени:

- `.github/ISSUE_TEMPLATE/bug_report.yml`;
- `.github/ISSUE_TEMPLATE/feature_request.yml`;
- `.github/ISSUE_TEMPLATE/config.yml`;
- `.github/pull_request_template.md`.

Дополнительные issue forms (`documentation.yml`, `performance.yml` и т.п.) добавляй только если project context реально оправдывает их. Не создавай public security issue form для приватных vulnerability reports без отдельного project policy.

## Правила содержания

- Используй язык `language.githubTemplates`.
- Bug form должен собирать reproduction, expected/actual, environment/tool versions только релевантные проекту, logs/screenshots и affected area.
- Feature form должен начинаться с проблемы/ценности, а не только «что сделать», и позволять указать ограничения/референсы.
- PR template должен отражать реальные verification gates и существующую traceability (`STEP/REQ/ADR`) только там, где она применима; PROJECT QUICK FIX должен иметь возможность указать `N/A`.
- Не включай чекбоксы для tooling, которого нет в проекте.
- Existing target files заменяются намеренно; пользователь увидит изменения в Git diff.

## После генерации

1. Проверь YAML syntax issue forms.
2. Запусти `python3 .harness/tools/validate.py --mode manual`.
3. Покажи список заменённых/созданных файлов и основные изменения.
4. Не делай GIT COMMIT/GIT PUSH автоматически.
