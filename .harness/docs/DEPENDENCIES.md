# Зависимости Harness

Этот документ разделяет **обязательные зависимости ядра**, **runtime adapters** и **optional capabilities**.

## Обязательные зависимости

### Python 3.11+

Deterministic tools и validators Harness используют Python 3.11+.

```bash
python3 --version
```

### Git

Harness использует repository state, revisions, diff, immutable reports и Git workflow, поэтому `git` обязателен.

```bash
git --version
```

## Runtime adapters

Harness поддерживает Codex и Claude Code и **не требует их одновременной установки**. Для agent-session нужен выбранный пользователем runtime. Второй runtime может отсутствовать и не является blocker. Tracked configs обоих adapters всё равно валидируются Harness Integrity как release contract.

Provider-neutral interface, capability negotiation, account sources и normalized events зафиксированы в [`RUNTIME_ADAPTER_CONTRACT.md`](RUNTIME_ADAPTER_CONTRACT.md) и `.harness/runtime-adapter-contract.json`. Unsupported runtime capability должна быть объявлена явно; отсутствие optional capability не маскируется моделью.

## Pull Request capability

`GIT CHECK`, `GIT COMMIT`, `GIT PUSH` и `GIT SYNC` используют обычный Git и не требуют provider CLI. Provider-specific CLI нужен только для `GIT PR` и `GIT PR FINISH`.

Поддерживаются две deterministic пары provider/tool:

```toml
# GitHub
[pull_request]
provider = "github"
preferred_tool = "gh"
```

```toml
# Gitea, включая self-hosted
[pull_request]
provider = "gitea"
preferred_tool = "tea"
```

Неизвестная или несовместимая пара fail-closed блокируется validation/preflight. Выбор provider/tool не делегируется модели.

### GitHub CLI (`gh`)

Проверка установки и авторизации:

```bash
gh --version
gh auth status
```

Первичная авторизация:

```bash
gh auth login
```

Для custom GitHub host:

```bash
gh auth login --hostname <host>
```

Официальная документация:

- https://cli.github.com/
- https://cli.github.com/manual/gh_auth_login

### Gitea Tea CLI (`tea`)

Tea — provider CLI для Gitea. Harness определяет Gitea host из configured `push.remote` и выбирает **ровно один** Tea login profile, URL которого соответствует этому host. Это поддерживает публичные и self-hosted Gitea instances без hard-coded host.

Проверка установки:

```bash
tea --version
```

Пример настройки self-hosted instance:

```bash
tea login add --name work --url https://git.example.com --token "<token>"
```

Если для одного host подходят несколько Tea login profiles, Harness возвращает `PROVIDER_LOGIN_AMBIGUOUS`, а не выбирает профиль случайно.

Официальная документация:

- https://about.gitea.com/products/tea/
- https://gitea.com/gitea/tea

Отсутствующий или неавторизованный provider CLI не блокирует Harness целиком: unavailable становится только Pull Request capability. Основные Git operations остаются provider-neutral.

## Диагностика

`HARNESS DOCTOR` показывает required core dependencies, optional runtimes и configured Pull Request capability раздельно. Для PR capability различаются отсутствие CLI, отсутствие подходящей авторизации/login и provider-specific blocker. Общий status становится `BLOCKED` только из-за обязательной зависимости или повреждения Harness.
