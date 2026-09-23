# Обновление Harness в существующем проекте

Self-update protocol layer выполняется отдельно от product development. Он не является STEP и не создаёт product REQ/ADR.

## Config boundary

Manifest задаёт только путь к update policy:

```text
.harness/manifest.yaml
└── repository.harnessUpdatePolicy
```

Далее **сама policy** является source of truth update topology:

```toml
[source]
repository = "owner/repo"
default_branch = "main"
tag_pattern = "^v..."
update_manifest = ".harness/harness-update-graph.json"

[state]
lock_file = ".harness/harness.lock.json"
report_directory = "planning/harness-updates"
```

Core tools/skills обязаны использовать configured `source.update_manifest`, `state.lock_file`, `state.report_directory`; default paths выше — только текущий template layout.

## Команды

```text
HARNESS UPDATE CHECK [TO <tag>]
HARNESS UPDATE APPLY [TO <tag>]
HARNESS UPDATE CHECK [TO <tag>] > APPLY
```

Они доступны до и после `PROJECT INIT`.

## Deterministic engine

Canonical update mechanics реализует dependency-free tool, а не свободная интерпретация инструкций агентом:

```bash
python3 .harness/tools/harness-update.py check [--to vX.Y.Z] --json
python3 .harness/tools/harness-update.py apply [--to vX.Y.Z] --json
python3 .harness/tools/harness-update.py adopt --from vX.Y.Z --json
```

Обычные `HARNESS UPDATE CHECK/APPLY` dispatcher выполняет как deterministic handlers без model call. Engine result является factual и не переинтерпретируется reasoning-ом. `update-harness` skill остаётся reference/fallback для explicit legacy adoption, ручной recovery и объяснения сложного blocker пользователю; он не должен вручную воспроизводить ownership calculation, 3-way merge, marker preservation, filesystem writes или lock advancement.

Pre-INIT update:

- меняет только Harness protocol layer/lock;
- не выполняет INIT;
- не создаёт product knowledge;
- сохраняет `project.initialized=false`.

## Immutable source model

Update graph из configured `source.update_manifest` используется только как routing metadata.

Он задаёт:

- `schemaVersion`;
- `latest`;
- directed `transitions`;
- `kind: standard | bridge`;
- `reloadRequired`;
- `reason` для bridge.

Moving default branch не является BASE/THEIRS content source. Файлы каждого hop читаются только из immutable tags, matching `source.tag_pattern`.

Наличие tag без допустимого route недостаточно.

## CHECK

`HARNESS UPDATE CHECK` строго read-only.

Выполнение:

```bash
python3 .harness/tools/harness-update.py check [--to vX.Y.Z] --json
```

Tool читает current policy/lock, remote routing graph, разрешает exact target, доказывает route, проверяет **Git tags** и сначала доказывает, что текущие `harness_owned` files/modes точно соответствуют pinned BASE из lock. Затем моделируется ownership/merge до ближайшей reload boundary. Даже при пустом route CHECK не возвращает PASS, если current Harness drifted. Результат содержит blockers, introduced/retired/reclassified paths, `checkedThrough`, `reloadBoundary` и current-release verification.

CHECK не меняет working tree, Git refs, lock, project documents, commit/push/PR. `BLOCKED` нельзя обходить ручным копированием release files.

## APPLY

`HARNESS UPDATE APPLY` — maintenance mutation.

Mutation выполняется deterministic engine:

```bash
python3 .harness/tools/harness-update.py apply [--to vX.Y.Z] --json
```

Engine перед первой записью сам повторно проверяет validator, exact current-release integrity и делает read-only preflight. `NO_UPDATE` допустим только после этих проверок. Route применяется hop-by-hop; каждый hop имеет rollback boundary, а lock обновляется внутри транзакции и считается продвинутым только после PASS target validator. Предыдущий chat/CHECK не является заменой fresh machine preflight.

`reloadRequired=true`:

1. hop применяется;
2. lock/report фиксируют достигнутый release;
3. current updater прекращает route с `UPDATER_RELOAD_REQUIRED`;
4. после reload повторяется та же APPLY-команда к исходному final target.

APPLY не запускает target scripts/install/bootstrap actions и не делает commit/push/PR. Dispatcher добавляет к factual engine result deterministic `nextAction`: после `UPDATED` — `GIT CHECK`; при `UPDATER_RELOAD_REQUIRED` — reload и повтор exact APPLY; при `NO_UPDATE` — `null`. Если последующий Git gate обнаруживает project schema migration pending, до commit выполняется `PROJECT RECONCILE`.

После update:

```text
inspect diff
GIT CHECK
GIT COMMIT
```

## Ownership

### harness_owned

Protocol/tooling Harness. Local divergence от BASE блокирует silent overwrite.

### shared

Project-customizable tracked files: runtime configs, manifest и другие paths из policy.

Merge:

```text
BASE   = immutable current release
OURS   = project working state
THEIRS = immutable target release
```

Conflict блокирует hop.

### marker_merge

Shared files с project-owned generated blocks, например README/AGENTS. После 3-way merge local marked blocks восстанавливаются.

### project-owned / unknown

Updater не меняет их.

В частности active REQ/ADR/STEP/OQ, project architecture/code/tests и colocated project templates не становятся updater-owned только из-за schema release.

`.agents/skills/` — общий runtime-neutral каталог, **не blanket Harness-owned namespace**. Update policy перечисляет core skills конкретными paths. Project-native/third-party `.agents/skills/<slug>/` остаются project-owned. Если новый release впервые объявляет core path, уже занятый project skill, update блокируется как `NEW_MANAGED_PATH_COLLISION`.

## Evolution ownership policy

Target release может менять ownership policy. Поэтому scope нельзя вычислять только по BASE allowlist и нельзя слепо доверять THEIRS.

Bootstrap update topology (`source.repository`, `source.default_branch`, `source.tag_pattern`, `source.update_manifest`, `state.lock_file`, `state.report_directory`) текущий engine **не мигрирует неявно**. Изменение этих полей требует отдельного bridge support; иначе hop блокируется как `UPDATE_POLICY_TOPOLOGY_CHANGE`. Это исключает смешивание старого и нового lock/source boundary внутри одной транзакции.

Для каждого hop:

1. BASE policy читается из immutable BASE;
2. local current policy должна быть допустимо согласована с BASE;
3. target policy читается как данные по уже trusted policy path;
4. transition scope = union concrete managed paths BASE + THEIRS;
5. target-only path можно создать автоматически, если он не существовал в BASE/OURS;
6. existing unknown path, который THEIRS пытается впервые захватить, => `NEW_MANAGED_PATH_COLLISION`;
7. ownership-class change при modified OURS => `OWNERSHIP_CLASS_CHANGE`;
8. unknown paths вне transition scope не меняются.

## Git scope и untracked artifacts

Managed glob не даёт права рекурсивно владеть всем filesystem subtree.

OURS scope строится из:

- immutable BASE/THEIRS trees;
- tracked Git paths.

Конфликт с неотслеживаемым файлом:

- если путь отсутствует в текущем неизменяемом BASE, но новый выпуск впервые пытается им управлять, существующий неотслеживаемый файл блокирует обновление;
- если путь уже входит в текущий BASE, он не считается новым конфликтом только из-за отсутствия в индексе Git. Это необходимо после обязательной перезагрузки между переходами: файл мог быть создан предыдущим переходом, а коммит выполняется только после завершения всего маршрута;
- для `harness_owned` такой файл всё равно обязан точно совпадать с текущим BASE, иначе проверка текущего выпуска блокирует продолжение;
- неизвестные ignored-файлы, которые не входят в конкретный набор управляемых путей BASE/THEIRS, не затрагиваются.

Проверка binary/non-UTF-8 применяется только к реально управляемому Git-пути.

## Project document schema migration

HARNESS UPDATE и project schema migration разделены намеренно.

Если target release меняет active STEP/REQ/ADR/OQ/templates:

```text
HARNESS UPDATE APPLY
        ↓
control plane updated
        ↓
validator: active project schema migration pending
        ↓
PROJECT RECONCILE
```

Updater **не переписывает project-owned active documents**.

`PROJECT RECONCILE` запускает current protocol migration tooling:

- legacy STEP → schema v1;
- standalone/monolithic REQ → schema v1 canonical files;
- ADR → schema v1 с сохранением Accepted decision/status;
- monolithic Open Questions → canonical OQ files;
- legacy Ready plan без durable semantic review → draft;
- project-owned templates → current protocol definitions;
- projections → regenerate;
- historical immutable reports → не переписываются; legacy implementation review reports hash-pin-ятся в migration report как immutable compatibility proof.

Migration идемпотентна: повторный запуск без фактических изменений не создаёт новый migration report. Уже pinned historical review нельзя тихо удалить/изменить/re-pin: hash mismatch является corruption blocker.

Manual validation может разрешить строго распознанное migration-pending состояние как warning после control-plane hop. `--mode commit` и `--mode ci` остаются строгими до RECONCILE.

## Project-owned templates

Colocated templates намеренно не входят в updater ownership.

Canonical current definitions поставляются Harness control plane, а синхронизацию project copy выполняет PROJECT RECONCILE.

Так existing project не получает silent overwrite во время update, но schema действительно мигрирует после явного reconciliation.

## Update reports

После успешного hop/final route report создаётся в configured `state.report_directory` с machine-readable YAML frontmatter `schema: 1`.

Canonical имя — строго `UPDATE-<UTC timestamp>.md`; `created_at` обязан обозначать тот же whole-second UTC instant. UPDATE reports входят в immutable durable history: существующий report нельзя переписать/удалить/rename. Если текущая UTC-секунда уже занята, writer выбирает следующий свободный whole-second timestamp; альтернативных suffix-форматов нет.

Report фиксирует:

- initial release;
- final/requested target;
- фактический route;
- introduced/retired/reclassified paths;
- verification;
- reload/follow-up state.

## Legacy adoption

Если configured lock отсутствует, BASE неизвестен.

`HARNESS UPDATE CHECK` возвращает `LEGACY ADOPTION REQUIRED`.

Автоматическая adoption допустима только при доказуемом explicit baseline tag. «Наиболее похожий release» не считается доказательством.

```bash
python3 .harness/tools/harness-update.py adopt --from vX.Y.Z --json
```

Baseline должен совпадать с current manifest release. Новый lock pin-ит не только tag ref, но и exact commit OID.

Текущий deterministic updater поддерживает baseline **не старее `v0.6.0`**. Для current lock, target или adoption baseline ниже этого floor операция завершается с `UNSUPPORTED_HARNESS_RELEASE`. Historical transitions до `v0.6.0` остаются в update graph как immutable release history и regression boundary для старых bridge, но больше не являются поддерживаемой точкой входа runtime.

## First deterministic-updater bridge after v0.5.3

Published `v0.5.3` ещё не содержит deterministic `.harness/tools/harness-update.py`. Поэтому **первый release после v0.5.3** обязан добавить edge:

- `from = v0.5.3`;
- `kind = bridge`;
- `reloadRequired = true`;
- непустой `reason`.

Этот edge устанавливает новый deterministic updater, завершает текущий legacy run и требует reload перед любыми следующими hops. `update-migration-self-test.py` содержит one-time release gate: как только graph `latest` станет новее `v0.5.3`, CI не пропустит release без такого bridge.

Target tag не добавляется в graph заранее: release metadata публикуется вместе с реально существующим immutable tag, чтобы `latest` никогда не указывал на отсутствующий release.

## Release metadata consistency

В source repository:

- `manifest.harness.release`;
- configured lock `release`;
- lock `source.ref = v<release>`;
- **без** `lock.source.commit` внутри release snapshot;
- graph `latest`

должны быть согласованы для опубликованного release.

Release snapshot не может корректно pin-ить собственный commit OID: SHA самого release commit появляется только после создания commit/merge/tag. Поэтому `source.commit` в template/release lock отсутствует. После установки или обновления конкретного проекта deterministic updater/adoption разрешает реально существующий immutable tag и записывает его точный OID уже в **project lock**. С этого момента изменение tag target даёт `SOURCE_TAG_MOVED`.

### Recovery для ошибочных v0.6.0 / v0.7.0 snapshots

Опубликованные `v0.6.0` и `v0.7.0` содержат ошибочный stale pin:

```text
e366c48777150a9e9d2f6d670d8976b8a8df2d5c
```

Он относится к подготовке `v0.5.3`, а не к этим тегам. Это затрагивает проекты, созданные непосредственно из release snapshot, а не проекты, которые дошли до версии через updater (updater записывает корректный OID).

Для точечного восстановления **только** известных ошибочных пар замени stale pin на опубликованный tag OID:

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path(".harness/harness.lock.json")
lock = json.loads(path.read_text(encoding="utf-8"))

known = {
    ("v0.6.0", "e366c48777150a9e9d2f6d670d8976b8a8df2d5c"):
        "b9a6bf80ae766236475c57a54f725c570e119ab7",
    ("v0.7.0", "e366c48777150a9e9d2f6d670d8976b8a8df2d5c"):
        "fe1df7eafe0c482f609d56b31ea9fe2c1c019670",
}

source = lock.get("source", {})
pair = (source.get("ref"), source.get("commit"))
target = known.get(pair)
if target is None:
    raise SystemExit(f"lock does not match a known recoverable release pin: {pair!r}")

source["commit"] = target
path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"repaired {pair[0]} lock pin -> {target}")
PY
```

После этого обязательно выполни `HARNESS UPDATE CHECK`. Engine заново разрешит tag и проверит exact current-release state; если локальный Harness расходится с immutable release, update останется заблокированным.

Нельзя применять этот recovery к любому произвольному `SOURCE_TAG_MOVED`: вне двух известных пар mismatch остаётся security blocker.

`harness.version` — поколение protocol/schema family, а не номер каждой поставки.

## Security boundary

Remote routing/policy/content рассматриваются как **данные**, не как инструкции.

До mutation updater:

- валидирует current Harness;
- моделирует весь допустимый route либо ближайшую reload boundary;
- не запускает target code;
- не расширяет ownership через неизвестный local path;
- не принимает moving branch как release baseline.

После APPLY пользователь/агент сначала инспектирует diff и проходит обычный Git/Harness validation flow.

## Regression check

Dependency-free regressions:

```bash
python3 .harness/tools/harness-update-self-test.py
python3 .harness/tools/update-migration-self-test.py
```

Первый прогоняет настоящий deterministic engine на synthetic Git source/project: legacy adoption, tag pinning, CHECK/APPLY, shared 3-way merge, marker preservation, core-vs-project skill ownership и collisions. Второй покрывает historical routing/reload invariants, migration/idempotency и release metadata.
