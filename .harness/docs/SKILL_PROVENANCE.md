# Skill Provenance и future update planning

Third-party skill — dependency с исполняемыми инструкциями. Поэтому Harness разделяет три вещи:

```text
SKILL.md        → workflow semantics
UPSTREAM.md     → человекочитаемый provenance / rationale
PROVENANCE.json → deterministic identity, BASE hashes и update/fork state
```

## Почему одного pinned commit недостаточно

После установки пользователь может адаптировать skill под проект. Если позже upstream обновился, простая замена каталога уничтожит intentional fork.

Нужна обычная трёхсторонняя модель:

```text
BASE   = exact upstream bundle, от которого ставили skill
OURS   = текущая локальная копия
THEIRS = новый exact inspected upstream bundle
```

## PROVENANCE.json

Для third-party skill tool `record-install` сохраняет:

- upstream repository/path;
- immutable inspected и installed revisions;
- license state;
- hash map exact BASE upstream files;
- hash map installed files;
- `localModified` и adaptation rationale;
- `forkSince` для intentional adaptation;
- latest checked upstream revision/update status.

Hashes вычисляет Core. Модель не должна строить их вручную.

## Install recording

Exact inspected upstream bundle временно размещается под `.harness/local/**`. После копирования и локальной адаптации:

```bash
python3 .harness/tools/skill-provenance.py record-install docker \
  --payload-file .harness/local/skill-install/docker/provenance.json \
  --pretty
```

Пример payload:

```json
{
  "upstreamDir": ".harness/local/skill-install/docker/upstream",
  "repository": "owner/repo",
  "sourcePath": "skills/docker",
  "inspectedRevision": "0123456789abcdef",
  "installedRevision": "0123456789abcdef",
  "license": "MIT",
  "adaptationRationale": ["Use repository-specific compose command."]
}
```

Если installed bytes отличаются от inspected upstream, но rationale пуст — recording блокируется.

## Read-only update plan

Новый upstream сначала снова inspect-ится и кладётся в local staging:

```bash
python3 .harness/tools/skill-provenance.py plan docker \
  --candidate-dir .harness/local/skill-update/docker/candidate \
  --candidate-revision fedcba9876543210 \
  --pretty
```

Tool не делает network fetch, не запускает third-party scripts и не меняет установленный skill.

### Статусы

- `clean` — upstream и local относительно BASE не изменились;
- `upstream-changed` — local не расходился с BASE, upstream можно применить механически;
- `local-fork` — есть intentional/local delta, которую нужно сохранить; non-overlap upstream changes видны отдельными path actions;
- `conflict` — OURS и THEIRS несовместимо меняют один path, upstream удалил локально изменённый path или новый upstream path сталкивается с local-only path;
- `unavailable` — exact upstream candidate получить/проверить нельзя.

### Path actions

```text
none
take-upstream
delete
keep-local
conflict
```

Например:

```text
BASE rules.md = A
OURS rules.md = local-A
THEIRS rules.md = A
→ keep-local

BASE helper.md отсутствует
OURS helper.md отсутствует
THEIRS helper.md = new
→ take-upstream
```

Если обе стороны по-разному изменили `rules.md`, plan возвращает `conflict`, а не пытается угадать merge.

## Safety boundaries

- candidate/upstream staging только под `.harness/local/**`;
- symlink и non-regular files fail-closed;
- bounded file count/size;
- exact immutable revision обязателен;
- inspection/update planning никогда не исполняет scripts из skill;
- upstream delete + local modification — conflict;
- new upstream path + local-only path — conflict;
- update planner read-only: content/Registry не изменяются.

## Будущий SKILL UPDATE

Публичная команда пока намеренно не добавлена. Будущий apply должен использовать этот plan как authority и:

1. повторно проверить exact BASE/OURS/THEIRS;
2. применять только разрешённые path actions;
3. блокировать conflict/unavailable;
4. обновлять installed content + `PROVENANCE.json` + configured Registry атомарно;
5. при failure оставлять прежний skill и Registry консистентными.

То есть эта версия добавляет безопасный contract и synthetic matrix, но не скрытый merge engine.
