# Claude Code

AI Development Harness поддерживает Claude Code как отдельный runtime adapter рядом с Codex. Семантика Harness при этом остаётся общей: команды, REQ/ADR/STEP contracts, skills, Git policy и update policy не принадлежат конкретному AI runtime.

Официальная документация Claude Code:

- settings: https://code.claude.com/docs/en/settings
- subagents: https://code.claude.com/docs/en/sub-agents
- project instructions / `CLAUDE.md`: https://code.claude.com/docs/en/memory

## Файлы adapter

```text
CLAUDE.md
.claude/
├── README.md
├── settings.json
└── agents/
    ├── initializer.md
    ├── architect.md
    ├── planner.md
    ├── implementer.md
    ├── reviewer.md
    ├── security-reviewer.md
    ├── test-reviewer.md
    ├── docs.md
    ├── mechanic.md
    ├── skill-curator.md
    ├── git-operator.md
    └── harness-updater.md
```

`CLAUDE.md` импортирует `@AGENTS.md`. Это сохраняет `AGENTS.md` каноническим repository contract и не заставляет поддерживать две копии protocol instructions.

## Root profile

Tracked `.claude/settings.json` задаёт shared defaults:

```json
{
  "model": "sonnet",
  "effortLevel": "medium",
  "permissions": {
    "defaultMode": "default"
  }
}
```

Для персонального override используй `.claude/settings.local.json`. Этот файл не должен попадать в Git.

В интерактивной сессии модель и effort можно временно менять средствами Claude Code (`/model`, `/effort`, `--model`, `--effort`). Такой session override не меняет Harness protocol.

## Role profiles

| Роль | Model alias | Effort | Permission mode |
|---|---|---:|---|
| initializer | opus | high | default |
| architect | opus | high | plan |
| planner | opus | high | plan |
| implementer | sonnet | medium | default |
| reviewer | opus | high | plan |
| security-reviewer | opus | high | plan |
| test-reviewer | sonnet | low | plan |
| docs | sonnet | low | default |
| mechanic | sonnet | low | default |
| skill-curator | opus | medium | default |
| git-operator | sonnet | medium | default |
| harness-updater | opus | high | default |

Используются family aliases (`opus`, `sonnet`), а не жёстко зафиксированные model IDs: Claude Code подставляет актуальную разрешённую модель семейства. При необходимости проект может заменить alias на конкретный model ID.

`effort` каждого subagent переопределяет session effort для этой роли.

### Read-only роли

Для architect/planner/reviewer/security-reviewer/test-reviewer установлен `permissionMode: plan`, что соответствует read-only exploration в обычной Manual/Plan session.

У Claude Code есть важная runtime-особенность: если основная сессия запущена в `auto`, `acceptEdits` или `bypassPermissions`, runtime может применить mode основной сессии к subagent вместо declared `permissionMode`. Поэтому Harness semantic restriction «не менять файлы» остаётся обязательной даже при runtime override. Shared settings по умолчанию используют Manual mode (`permissions.defaultMode = default`).

## Skills

Canonical Harness skills остаются в:

```text
.agents/skills/<name>/SKILL.md
```

Claude Code adapter **не** создаёт зеркальную копию core skills в `.claude/skills/`. Дублирование сделало бы update/routing недетерминированным и создало бы риск расхождения двух версий одного workflow.

Когда `AGENTS.md`, command routing или role instructions выбирают Harness skill, Claude читает его напрямую из `.agents/skills/`.

Project-specific Claude-native skills разрешены в `.claude/skills/`, если проекту действительно нужна нативная интеграция Skill tool. Эти файлы не входят в upstream allowlist и по умолчанию считаются project-owned.

## Local instructions

Claude Code автоматически читает `CLAUDE.local.md` рядом с `CLAUDE.md`. Используй его только для персональных/private Claude-specific preferences, а repository-wide правила держи в `AGENTS.md`.

`CLAUDE.local.md` и `.claude/settings.local.json` добавлены в ignore/integrity policy.

## Harness Update

Tracked Claude adapter files разделены по ownership:

- `.claude/README.md` — `harness_owned`;
- `CLAUDE.md`, `.claude/settings.json`, `.claude/agents/**` — `shared`;
- неизвестные `.claude/**`, включая project-specific `.claude/skills/**`, — project-owned.

Такой boundary позволяет Harness обновлять adapter, но сохранять project-specific model/effort и role tuning через BASE/OURS/THEIRS merge.

## Проверка конфигурации

`.harness/tools/validate.py` проверяет:

- наличие Claude adapter и всех обязательных ролей;
- валидность `.claude/settings.json`;
- наличие root `model` и `effortLevel`;
- обязательные frontmatter поля каждого `.claude/agents/*.md`;
- допустимый `effort`;
- уникальность agent names;
- импорт `@AGENTS.md` из `CLAUDE.md`;
- ignore local Claude files.

Дополнительно установленный Claude Code можно попросить проверить native agent frontmatter собственной командой:

```bash
claude plugin validate .claude/agents
```

Эта команда является дополнительной runtime-проверкой и не заменяет deterministic Harness Integrity.
