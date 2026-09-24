# Поддержка Harness

## Lifecycle local operational state

`.harness/local/**` не входит в Git, но это не означает «можно удалять всё».

Для каждого нового persistent local artifact при review должны быть определены одновременно:

- deterministic owner/tool;
- recovery semantics;
- условие, при котором данные доказанно больше не нужны;
- schema/version migration strategy;
- concurrency boundary, если файл мутируется несколькими sessions.

Для temporary transport действует более узкое правило: Harness принимает только доказанный owned lexical path без symlink traversal, фиксирует exact content/identity и передаёт primary consumer-у captured snapshot, а не mutable path. После успешного postcondition удаляется только тот же unchanged file identity. Failure сохраняет input для retry. Ошибка secondary cleanup не меняет уже доказанный primary SUCCESS. Lock files cleanup-механизм не удаляет. Неизвестный local path без зарегистрированного lifecycle fail-safe не трогается.

Изменение формата persistent local state без migration regression считается незавершённым protocol change.

Зарегистрированный persistent artifact: `.harness/local/update-journal/` — owner `harness_update.py`/`update_recovery.py`; существует только во время hop; recovery — rollback по журналу (APPLY или `harness-update.py recover`); удаляется в commit point hop или после rollback; формат `schemaVersion: 1` обязан читаться любым будущим engine; concurrency boundary — эксклюзивное создание каталога и проверка живого владельца.

## Что относится к control plane Harness

Основное правило: internal implementation и human-readable core documentation собраны под `.harness/**`, но сам namespace не является единой ownership class. `.harness/docs/**` и `.harness/tools/**` относятся к core, `.harness/manifest.yaml` и `.harness/git-policy.toml` являются shared, а `.harness/local/**` — local-only operational state.

Отдельно снаружи остаются integration surfaces, потому что их расположение определяется runtime/repository conventions:

- `AGENTS.md` (кроме generated project blocks);
- `CLAUDE.md`, `.codex/`, baseline `.claude/`;
- core `.agents/skills/`;
- baseline `.github/` integration.

Colocated `TEMPLATE.md` рядом с REQ/ADR/STEP и другими project artifacts являются project-owned scaffolds. Они обязательны для структуры Harness, но updater не захватывает их ownership: legacy projects могли адаптировать эти файлы до появления текущей update-policy.

## Что относится к конкретному проекту

- generated blocks README/AGENTS;
- `docs/PROJECT.md`;
- requirements;
- ADR;
- architecture/subsystem docs;
- roadmap/tasks/reviews/audits;
- Harness update reports;
- product code/tests/config;
- project-native/third-party skills;
- project-specific runtime additions, отсутствующие в upstream allowlist.

## Правило обновлений

Не копируй новый Harness поверх проекта вручную.

Используй:

```text
HARNESS UPDATE CHECK
HARNESS UPDATE APPLY
```

Формальная модель ownership, BASE/OURS/THEIRS, legacy adoption и release lifecycle описана в [`UPDATES.md`](UPDATES.md).

`HARNESS UPDATE APPLY` — maintenance mutation, а не STEP. После неё не выполняются commit/push/PR автоматически: сначала inspect diff, затем обычный `GIT CHECK` → `GIT COMMIT`.

## Version и release

`.harness/manifest.yaml` разделяет два понятия:

- `harness.version` — поколение protocol/schema layer;
- `harness.release` — конкретный semver release.

Пока protocol generation совместимо, `harness.version` остаётся `"1"`, а поставки получают immutable tags `vMAJOR.MINOR.PATCH`.

Known BASE проекта фиксируется в `.harness/harness.lock.json`. Moving `main` не используется как update baseline.

Current updater читает moving `source.default_branch` только через canonical `.harness/harness-update-graph.json`. Файлы protocol layer для каждого hop по-прежнему читаются только из immutable tags.

## Ownership

`.harness/harness-update.toml` делит обновляемые пути на:

- `harness_owned` — локальная модификация блокирует silent overwrite;
- `shared` — 3-way merge;
- `marker_merge` — 3-way merge с сохранением generated project blocks.

Runtime tuning относится к `shared`: пользователь может менять model/effort в `.codex/` и tracked Claude adapter, не теряя настройки при обычном Harness update. Colocated project `TEMPLATE.md` updater не меняет.

Всё неизвестное считается project-owned и updater не меняет. Например project-specific `.claude/skills/**` не становится Harness-owned только потому, что находится внутри `.claude/`.

То же относится к локальным игнорируемым артефактам внутри управляемого каталога: `__pycache__/`, bytecode и другие cache/build-файлы не входят в область владения только из-за совпадения с glob. Новый управляемый путь блокируется, если до обновления на его месте уже существует неотслеживаемый пользовательский файл. Путь, который уже принадлежит текущему неизменяемому BASE, после промежуточного перехода может оставаться неотслеживаемым до финального коммита и не считается новым конфликтом; для `harness_owned` его содержимое при этом обязано точно совпадать с BASE.

## Legacy projects

Если проект создан до появления lock, безопасный BASE неизвестен. Updater не должен угадывать его по похожести файлов.

Legacy adoption разрешён только для явно известного release через `update-harness`: укажи конкретный immutable tag `vX.Y.Z`. Current updater принимает baseline только начиная с `v0.6.0`; более старый release возвращает `UNSUPPORTED_HARNESS_RELEASE`. При неизвестном или более старом baseline нужен ручной reconciliation.

## Project-specific skills

Добавляй отдельно. Универсальный `implement-step` не должен знать конкретный framework. Если technology skill нужен большинству задач проекта — зарегистрируй его в `.agents/skills/` и упомяни в generated project context/architecture docs.

`.agents/skills/` является runtime-neutral canonical location, но **не единым Harness-owned namespace**. В update policy core Harness skills перечисляются конкретными paths; произвольный project/third-party `.agents/skills/<slug>/` остаётся project-owned и переживает Harness update без silent overwrite. Если будущий core skill претендует на уже занятый project slug, deterministic updater обязан остановиться с collision.

Не создавай вторую tracked копию core Harness skill в `.claude/skills/` только ради Claude Code.

## Third-party skills

Не смешивай upstream skill upgrades с обычным Harness update. У каждого внешнего skill должен быть `UPSTREAM.md` и запись в `docs/skills/REGISTRY.md`. Обновление upstream требует повторного inspection; не делай silent auto-update.

## Экономия вычислений модели

Core Harness следует правилу: **модель получает решения и результаты, а не внутреннее устройство реализации и конфигурации**. Если проверку, вычисление или безопасную механическую операцию можно выполнить скриптом, обычный протокол не должен заставлять модель сначала читать реализацию или конфигурацию и воспроизводить ту же логику.

При изменении маршрутизации команды, способа вызова модели или быстрого пути одновременно обновляй `.harness/command-transitions.json → reasoning` и запускай `python3 .harness/tools/reasoning-boundaries.py --write`. Сгенерированные блоки `REASONING_BOUNDARIES.md` и `.harness/reasoning-boundaries.json` вручную не редактируй.

Подробные комментарии в `.harness/tools/*.py` сохраняются: при обычной эксплуатации Python source исполняется, а не загружается в model context. Чтение source оправдано при разработке/аудите Harness, диагностике tool failure или явном запросе пользователя.

Always-on bootstrap ограничен deterministic budget gate; детали и справка должны оставаться pull-based в skills/docs. Правила и baseline описаны в [`TOKEN_ECONOMY.md`](TOKEN_ECONOMY.md).

## Regression discovery

Новые synthetic regressions оформляй как `.harness/tools/<name>-self-test.py`. Harness Integrity не перечисляет их вручную: `run-self-tests.py` обнаруживает файлы по suffix и автоматически включает их в suite. Это уменьшает риск добавить validator без CI coverage.

Skill/agent Markdown frontmatter разбирается тем же restricted YAML contract из `document_contract.py`, что и остальные machine-readable Markdown artifacts. Не добавляй локальные YAML-парсеры в `validate.py`.
## Поддержка Python validators и validation gates

Python validators являются частью executable protocol contract, поэтому code comments и human-readable reference обновляются **одновременно** с behavior.

При добавлении нового validator/gate или изменении существующего:

1. подробно прокомментируй module responsibility, fail-closed boundary и decision points непосредственно в `.py`;
2. если есть CLI, опиши все actions/keys, exit codes и минимум по одному типичному примеру в [`VALIDATORS.md`](VALIDATORS.md);
3. если CLI нет, опиши module как internal contract: кто его вызывает, какие invariants он доказывает и какой результат возвращает;
4. явно отделяй read-only validation от mutation mode, если один tool поддерживает оба режима;
5. добавь/обнови regression self-test для нового safety invariant;
6. проверь, что новый public validator/gate включён в Harness Integrity CI, если он должен быть baseline gate;
7. не дублируй parsing/config/path semantics — используй общие `harness_config.py` и `document_contract.py`.

Структура разделов в `VALIDATORS.md` намеренно единообразна: **Файл/Файлы → Роль → Когда использовать → Что проверяет → CLI → Аргументы → Exit codes → Примеры → Внутренние зависимости/границы**. Для internal modules без CLI блоки CLI/Аргументы/Exit codes заменяются явным описанием caller contract.

## Самодокументируемые конфиги

Tracked YAML/TOML в `.harness/`, `.codex/` и baseline GitHub Actions должны оставаться читаемыми без перехода в отдельную справку. Каждый параметр обязан иметь рядом комментарий с назначением и примером. Harness Integrity проверяет это правило для patterns из `.harness/harness-policy.toml`.

Claude Code settings являются strict JSON и не допускают комментариев. Поэтому их назначение и defaults документируются в [`CLAUDE_CODE.md`](CLAUDE_CODE.md), а validator проверяет JSON structure и обязательные значения отдельно.

При добавлении нового YAML/TOML policy/config key одновременно:

1. объясни назначение;
2. перечисли допустимое поведение, если оно неочевидно;
3. приведи `Пример:` или `Example:`;
4. только после этого добавляй значение.
