# Управление repository skills

## Зачем отдельный workflow

Skill — это не просто Markdown-справка. `SKILL.md` задаёт повторяемый workflow, а рядом могут лежать references, templates и scripts. Поэтому сторонний skill следует рассматривать примерно как dependency: сначала найти и изучить, затем осознанно установить. OpenAI Agent Skills используют папку с `SKILL.md` и supporting resources; это хорошо подходит для хранения в Git рядом с проектом.

Каждый tracked skill bundle должен содержать `UPSTREAM.md`. Для project-native/core skill он фиксирует `Source: project-native`, дату фиксации provenance, references и rationale. Для third-party skill рядом дополнительно создаётся machine-readable `PROVENANCE.json`: exact upstream/path/revisions/license, baseline hashes, intentional adaptations/fork state и update metadata. `UPSTREAM.md` остаётся человекочитаемым объяснением; `PROVENANCE.json` — deterministic input будущего update planner. Исполняемая инструкция остаётся в `SKILL.md`.


## Команды

### `SKILL FIND: <описание>`

Ищет GitHub/доступный web, инспектирует подходящие repository skills и возвращает shortlist размером не более `.harness/manifest.yaml → skills.search.maxResults` (1–10). Ничего не устанавливает. Schema-v1 report сохраняется в configured `protocol.skillSearchDirectory`, поэтому позже можно написать `SKILL INSTALL: #3`.

Пример:

```text
SKILL FIND: Нужен skill для Docker: Dockerfile, multi-stage builds, docker compose, безопасность образов и оптимизация build cache.
```

Рейтинг учитывает не только популярность, но и реальное содержимое `SKILL.md`, релевантность, качество workflow, provenance/maintenance, license и safety.

### `SKILL INSTALL: <source>`

Устанавливает **выбранный пользователем** кандидат после повторного inspection. Поддерживаются:

```text
SKILL INSTALL: #2
SKILL INSTALL: https://github.com/owner/repo/tree/main/skills/docker
SKILL INSTALL: owner/repo:skills/docker
```

Номер `#N` берётся из последнего durable search report, а не из памяти чата.

Установка:

1. фиксирует exact source/ref/commit, если возможно;
2. читает весь доступный bundle;
3. не запускает сторонние scripts;
4. блокирует явно опасный skill;
5. копирует bundle в `.agents/skills/<slug>/`;
6. создаёт `UPSTREAM.md`;
7. обновляет registry по `.harness/manifest.yaml → protocol.skillRegistry`;
8. добавляет краткий routing rule в generated `SKILL-ROUTING` block `AGENTS.md`.

### `SKILL CREATE: <описание>`

Fallback, когда подходящего готового skill нет. Создаётся project-native `SKILL.md`, основанный на фактических conventions проекта и авторитетной документации технологии.

## Почему routing живёт в AGENTS.md

`AGENTS.md` не должен копировать содержимое каждого skill. В нём хранится только маршрутизация:

```text
Docker/containerization task → consider `docker` skill
Database migration task      → consider `database-migrations` skill
```

Полный workflow остаётся внутри skill. Это удерживает основной контекст компактным.

## Приоритет инструкций

Third-party skill никогда не становится выше repository contract. При конфликте:

```text
AGENTS / execution protocol / Accepted ADR / task scope
    > project-specific rules
    > third-party skill
```

Skill не имеет права отменить tests, security checks, sandbox/approval policy, scope или source hierarchy.

## Security checklist перед установкой

Проверить минимум:

- source repository/path и автора;
- license;
- `SKILL.md`;
- scripts/hooks;
- сетевые вызовы;
- filesystem/git destructive actions;
- credential/environment access;
- package install / `curl | sh`;
- попытки отключить verification/security;
- скрытые/encoded payloads;
- конфликт с существующими repository rules.

Сам факт наличия scripts не делает skill плохим, но повышает уровень scrutiny.

## Обновление сторонних skills

Новая версия upstream снова считается внешним кодом и сначала проходит inspection. До появления публичной команды `SKILL UPDATE` Harness уже имеет deterministic **update-plan contract**:

1. resolve exact immutable upstream revision;
2. статически inspect bundle, ничего из него не исполняя;
3. положить candidate bytes под `.harness/local/**`;
4. вызвать:
   ```bash
   python3 .harness/tools/skill-provenance.py plan <slug> \
     --candidate-dir .harness/local/skill-update/<slug>/candidate \
     --candidate-revision <commit> --pretty
   ```
5. использовать status/actions как факты, а не пересчитывать merge моделью.

Planner сравнивает старый exact upstream BASE, текущий installed OURS и новый inspected THEIRS. Результаты: `clean | upstream-changed | local-fork | conflict | unavailable`.

Первая итерация намеренно **не применяет update**: plan read-only. Поэтому local fork не может быть случайно перезаписан. Будущий `SKILL UPDATE` должен строиться поверх этого контракта и делать content + provenance/registry commit атомарно.
