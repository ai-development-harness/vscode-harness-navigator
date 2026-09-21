# Codex agents

`.codex/config.toml` регистрирует project-scoped роли через `[agents.<role>]` и `config_file`.

Настройки модели/effort находятся в `.codex/agents/*.toml`, чтобы стоимость и качество можно было менять независимо для каждой роли.

Перед изменением конфигурации прочитай `.harness/docs/AGENT_CONFIGURATION.md`.

## Локальные настройки

Codex сейчас не имеет нативного project-local файла, эквивалентного Claude Code `.claude/settings.local.json`. Не создавай `.codex/config.local.toml` в расчёте на автоматическую загрузку: Codex такой слой конфигурации пока не поддерживает.

Для пользовательских defaults используй `~/.codex/config.toml`, для именованных профилей — `~/.codex/<profile>.config.toml` + `--profile`, а для переопределения project settings — CLI flags и `--config`. Project `.codex/config.toml` имеет более высокий приоритет, чем profile.

Если нужен постоянный project-local launcher или helper, его можно хранить в gitignored `.codex/local/`, но Codex этот каталог автоматически не читает.

Подробное сравнение с Claude Code, примеры и upstream feature request: [`.harness/docs/AGENT_CONFIGURATION.md`](../.harness/docs/AGENT_CONFIGURATION.md#локальные-настройки-runtime).

- `skill-curator` — поиск, inspection, установка и создание repository skills.
- `harness-updater` — безопасный `HARNESS UPDATE CHECK` / `HARNESS UPDATE APPLY` с сохранением project-owned state.
