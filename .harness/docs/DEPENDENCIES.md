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

## GitHub Pull Request capability

`GIT CHECK`, `GIT COMMIT`, `GIT PUSH` и `GIT SYNC` используют обычный Git и не требуют GitHub CLI.

Текущая PR integration поддерживает GitHub:

```toml
[pull_request]
provider = "github"
preferred_tool = "gh"
```

Для `GIT PR` и `GIT PR FINISH` нужен установленный и авторизованный `gh` (`gh auth status`).

Отсутствующий или неавторизованный `gh` не блокирует Harness целиком: он делает unavailable только GitHub Pull Request capability. Поэтому `gh` — optional capability dependency, а не global dependency Harness.

## Диагностика

`HARNESS DOCTOR` показывает required core dependencies, optional runtimes и GitHub PR capability раздельно. Общий status становится `BLOCKED` только из-за обязательной зависимости или повреждения Harness.
