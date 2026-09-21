# Генерация GitHub Issue / Pull Request templates

Команда:

```text
GITHUB GENERATE TEMPLATES
```

нужна потому, что хороший template зависит от реального проекта. До появления кода неизвестно, какие runtime, test runner, build tool, CI gates, компоненты и deployment targets действительно используются.

## Что делает команда

Агент изучает **текущее** repository state и полностью регенерирует managed GitHub templates:

```text
.github/
├── ISSUE_TEMPLATE/
│   ├── bug_report.yml
│   ├── feature_request.yml
│   └── config.yml
└── pull_request_template.md
```

При необходимости могут появиться дополнительные issue forms, но только если они оправданы проектом.

## Почему файлы заменяются

Templates — производное представление текущего development workflow. Если проект сменил test runner, workspace layout или CI gates, старые чекбоксы вредны. Поэтому команда намеренно заменяет target files целиком; пользователь проверяет результат обычным Git diff.

## На любом этапе

Команда работает:

- **до INIT** — создаёт нейтральные формы из известного Harness context;
- **после INIT, до code** — использует PROJECT/REQ/architecture и выбранный stack;
- **после появления code/tooling** — использует реальные scripts, CI и component boundaries.

Её можно вызывать повторно после крупных изменений tooling.

## Язык

Язык issue/PR templates задаётся в `.harness/manifest.yaml`:

```yaml
language:
  githubTemplates: ru
```

## Безопасность

Генератор не придумывает публичный security issue form по умолчанию: disclosure policy должна быть осознанной. Он также не выдумывает commands/version fields, которых нет в repository.
