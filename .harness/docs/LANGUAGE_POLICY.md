# Языковая политика

Единый источник языковых настроек — `.harness/manifest.yaml` → `language`.

Настройки разделены, потому что проект может, например, вести документацию на русском, а test names или commit messages — на английском. Используются BCP 47 tags (`ru`, `en`, `pt-BR` и т.д.).

Поля:

- `default` — обязательный fallback для любого специализированного ключа, который отсутствует;
- `agentResponses` — ответы агентов;
- `documentation` — PROJECT/REQ/ADR/STEP/reports;
- `commitMessages` — Git commits;
- `codeComments` — комментарии/doc-comments;
- `testNames` — человекочитаемые названия test cases;
- `fixtures` — sample/fixture content;
- `githubTemplates` — Issue/PR templates;
- `releaseNotes` — changelog/release notes.

## Fallback semantics

Runtime/tooling должен читать специализированный ключ через единый config layer:

```text
language.<domain>
  └─ отсутствует → language.default
```

Отсутствующий `language.documentation`/`testNames`/другой специализированный ключ не является configuration error, пока валиден `language.default`.

Machine-readable schema/CTS tokens (`schema`, `status`, `type`, `pass`, `blocked`, ID formats и т. п.) не локализуются и не зависят от language policy.

`language.documentation` применяется к **agent-authored human-readable prose** в PROJECT/REQ/ADR/STEP и durable reports. Он не означает runtime-перевод protocol schema: названия обязательных structural sections, machine frontmatter keys/enums и deterministic boilerplate/templates Harness остаются protocol-stable. Агент заполняет содержимое этих секций на configured языке, сохраняя технические identifiers без перевода.

## Что не переводится автоматически

Language policy не требует переводить:

- identifiers, class/function/variable names;
- API paths/JSON keys;
- package/framework/tool names;
- protocol keywords (`REQ`, `ADR`, `STEP`, `PASS`);
- данные, которые тестируют конкретную локаль.

При конфликте с доменной задачей фактический contract имеет приоритет: multilingual fixture для i18n-теста остаётся multilingual независимо от `language.fixtures`.
