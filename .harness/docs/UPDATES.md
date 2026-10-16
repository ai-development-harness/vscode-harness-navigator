# Обновление Harness в существующем проекте

## Контракт

`HARNESS UPDATE APPLY` устанавливает последнюю опубликованную версию за одну
транзакцию. `HARNESS UPDATE APPLY TO vX.Y.Z` устанавливает указанный immutable
release напрямую. Промежуточные releases, bridge installs и повторные APPLY
для достижения target не требуются. Явный TO допускает возврат к более старому
поддерживаемому release; неявный latest никогда не понижает версию.

Updater отвечает за служебные файлы, ownership/merge и атомарность установки.
**Никакое состояние рабочих артефактов не блокирует обновление.** Он не читает
и не проверяет актуальность STEP, REQ, ADR, REVIEW, Evidence, dependency proofs,
архитектуры, STATUS/roadmap и project templates. Повреждённые, отсутствующие,
не UTF-8, устаревшие, staged/unstaged/untracked артефакты сохраняются как есть.
Updater не пересобирает projections и не выполняет PROJECT RECONCILE.

Completion, freshness, review/provenance и schema gates остаются обязательными
в обычной работе над соответствующим STEP/проектом. Успешное обновление не
утверждает, что проект готов или исторический BLOCKED стал PASS. До и после
PROJECT INIT действует одинаковая граница: только установка control plane.

## Команды

```text
HARNESS UPDATE CHECK [TO vX.Y.Z]
HARNESS UPDATE APPLY [TO vX.Y.Z]
HARNESS UPDATE CHECK [TO vX.Y.Z] > APPLY
```

Dispatcher вызывает deterministic engine без model call:

```bash
python3 .harness/tools/harness-update.py check [--to vX.Y.Z] --json
python3 .harness/tools/harness-update.py apply [--to vX.Y.Z] --json
```

CHECK строго read-only. APPLY повторяет fresh source/integrity/merge preflight.
BASE — immutable установленный release из lock, OURS — локальные служебные
файлы, THEIRS — единственный конечный immutable target. CHECK проверяет весь
этот переход. `checkedThrough` всегда конечный target, route содержит только
current/target (или пуст при NO_UPDATE).

## Источник и настройки

Manifest задаёт `repository.harnessUpdatePolicy`. Из policy используются
`source.repository`, `source.default_branch`, `source.tag_pattern`,
`source.update_manifest`, `state.lock_file`, `state.report_directory`.

Без TO из каталога на default branch читается только `latest`. С TO каталог
вообще не читается. Content обеих версий разрешается только по immutable Git
tags; moving branch не становится источником устанавливаемого кода. Project
lock pin-ит `source.ref` и `source.commit`; moved tag даёт `SOURCE_TAG_MOVED`.
Release snapshot не содержит собственного source.commit: он ещё не существует.

Каталог `schemaVersion: 1, strategy: direct` сохраняет transitions только для
совместимости со старыми установленными клиентами: каждая известная версия
направлена сразу в latest. Release tooling поддерживает это свойство при
каждом следующем релизе. Новый engine не строит маршрут по transitions.

## Ownership и блокирующие ошибки установки

- `harness_owned`: local bytes/modes должны совпадать с pinned BASE, иначе
  `CURRENT_RELEASE_DRIFT`; неизвестные ignored files не захватываются glob-ом.
- `shared`: deterministic 3-way merge сохраняет настройки проекта; конфликт
  требует разрешения, без silent overwrite.
- `marker_merge`: сохраняет project-owned blocks README/AGENTS; отсутствующий
  ожидаемый block даёт `MARKER_DRIFT`.
- Project-owned/unknown: не меняются, не валидируются, не включаются в scope.
  Core skills перечислены поимённо; соседние project/third-party skills
  остаются под контролем проекта.

Scope — union concrete managed paths immutable BASE/THEIRS и Git-tracked
managed paths. Existing unknown path, впервые захватываемый target, даёт
`NEW_MANAGED_PATH_COLLISION`. Смена ownership при modified OURS даёт
`OWNERSHIP_CLASS_CHANGE`. Retired managed paths удаляются; оставленный target
файл, вышедший из ownership, передаётся проекту и отражается в `handedOver`.
Symlink/unsafe managed paths, binary managed merge, source/tag/lock drift,
service configuration corruption и I/O failure остаются installation blockers.
Это не проверки рабочих артефактов.

Топология source/lock/report policy не меняется неявно:
`UPDATE_POLICY_TOPOLOGY_CHANGE` требует отдельной поддержки engine. Git index,
commit/push/PR updater не меняет и не выполняет.

## Атомарная установка

1. Проверить immutable source identity и построить единый ownership/merge plan.
2. Создать журнал `.harness/local/update-journal/` с backup затронутых bytes,
   modes, lock и local execution state под его concurrency lock.
3. Записать managed files атомарно, entry points engine последними, затем lock.
4. Сравнить установленные bytes/modes с планом и проверить только syntax и
   обязательные managed files/config/manifest/lock через installation validator.
   Загруженный target code, full project validator и project commands не запускаются.
5. Опубликовать один immutable UPDATE report через reserved staging/inode/hash
   ledger и атомарный link без overwrite. Rollback удаляет только свой report.
6. Atomic journal→tombstone rename фиксирует transaction commit. Сбой до этой
   точки откатывает bytes/modes/lock/execution state; прерванный процесс
   восстанавливается по журналу перед следующим APPLY. CHECK при pending
   journal read-only блокируется с `UPDATE_JOURNAL_PENDING`.

`UPDATED` уже означает достижение конечного target. Если `reloadRequired=true`,
перезагрузи runtime перед следующей рабочей командой; повторять APPLY не нужно.
Повторный APPLY возвращает `NO_UPDATE` с `repositoryMutated=false`, не меняя
project templates. После reload inspect diff и обычный GIT CHECK. Project
schema/freshness problems решаются в работе с проектом, отдельно от установки.

## Совместимость со старыми установленными updater

Старый binary может выполнять full preflight до получения новых файлов.
Новый release не может ретроактивно изменить этот код. Если он блокирует
обновление по STEP/REVIEW/STATUS, используй официальный installer из отдельного
checkout **выбранного immutable release**, не редактируя lock и не копируя
служебные файлы вручную:

```bash
git clone --branch vX.Y.Z --depth 1 https://github.com/ai-development-harness/ai-development-harness-template.git /tmp/harness-installer
python3 /tmp/harness-installer/.harness/tools/harness-update.py check --root /absolute/project --to vX.Y.Z --json
python3 /tmp/harness-installer/.harness/tools/harness-update.py apply --root /absolute/project --to vX.Y.Z --json
```

Здесь vX.Y.Z — реально опубликованный release с новым installer. Это явный
запуск trusted Harness tool; он использует policy/BASE проекта и те же ownership,
source integrity, journal/rollback safeguards. После установки работает обычный
HARNESS UPDATE APPLY. Для legacy journaled engine новый validate --mode manual
автоматически выбирает installation-only профиль лишь при совпадающем token
активной verifying-транзакции. Обычный manual/commit/ci остаётся project validation.
Отдельный `validate.py --mode update` проверяет только установку.

Поддерживаемый floor current/target/adoption — v0.6.0. Старые, до namespace
migration версии требуют отдельной миграции. Если lock отсутствует, BASE
нельзя угадывать: `adopt --from vX.Y.Z` требует явно известный immutable baseline,
совпадающий с manifest и exact harness_owned bytes/modes. Adoption проверяет
только installation postconditions; проектные артефакты не блокируют adoption.

## Release qualification

Перед публикацией exact candidate SHA проходит core suite на Linux 3.13,
Linux 3.11 и Windows 3.13, pristine initialized canary upgrade и отдельную
`update-artifact-canary.py` matrix на disposable copies того же canary.
Матрица проверяет latest/TO, единственную установку, сохранение bytes/modes и
Git index для 16 состояний artifacts, read-only CHECK и повторный NO_UPDATE.
Любой FAIL блокирует release. Полный project validator нужен в pristine lane
для проверки нормальной работы продукта; он не является updater postcondition.

## Update reports

Одна transaction создаёт один `UPDATE-<UTC timestamp>.md` со schema: 1 в
configured report_directory. Он фиксирует current/target, direct route,
introduced/retired/handedOver/reclassified paths и installation verification.
Report не утверждает валидность рабочих артефактов. Существующие durable reports
не переписываются; занятая секунда заменяется следующей свободной UTC-секундой.

## Local runtime state migration

Project-owned schema migration и local operational state migration — разные boundaries.

`.harness/local/**` не обновляется HARNESS UPDATE и не мигрируется PROJECT RECONCILE. Persistent local format обязан мигрировать deterministic owner-ом при чтении/записи под собственным concurrency lock.

Для `execution-status.json` current execution layer поддерживает `schemaVersion: 1 → 2`:

- legacy bytes сначала полностью валидируются;
- v2 строится in-memory;
- active recovery и STEP baseline сохраняются;
- terminal history компактируется;
- v2 повторно валидируется;
- только затем выполняется fsync + atomic replace;
- migration failure не уничтожает исходный v1.

Будущее изменение persistent local format без backward reader/migration + old-state regression не считается готовым к release.

## PROJECT RECONCILE migration preflight

Active project schema migration использует two-phase safety boundary:

```text
read-only preflight
→ deterministic blockers = none
→ mutations
→ projections
→ immutable migration report
```

Preflight выполняется до первой repository write и проверяет как минимум immutable legacy review pins, parse/identity active STEP/REQ/ADR, duplicate IDs monolithic SPEC/OQ и non-additive project-owned template conflicts. Если blocker заранее обнаружим, RECONCILE завершается без partial migration: уже существующие project bytes остаются прежними, новые canonical artifacts/reports не создаются.

Filesystem I/O failure, возникший уже во время mutation и не предсказуемый read-only preflight, по-прежнему fail-closed; preflight не выдаётся за filesystem transaction/rollback.

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
- project-owned templates → additive structural migration к current protocol definitions с сохранением existing project values/prose; non-additive conflict остаётся blocker;
- projections → regenerate;
- historical immutable reports → не переписываются; legacy implementation review reports hash-pin-ятся в migration report как immutable compatibility proof;
- completed implementation-like legacy STEP без единого trusted review (например, из релизов, где review reports ещё не хранились) → **legacy completion baseline**: migration report перечисляет их в `legacy_completed_steps`, completion proof принимает их с пометкой `LEGACY_COMPLETION`. Это не PASS review и не восстановленный задним числом отчёт; любой новый trusted review по STEP имеет приоритет. Baseline создаётся только для STEP, мигрированных из legacy формата в этом же прогоне.

Legacy migration не теряет содержимое:

- разделы вне канонического набора и исходные metadata-строки (включая значения, перенесённые на следующую строку) сохраняются в конце документа (`## Legacy metadata`);
- REQ из монолитного `SPEC.md` получает весь свой текст (заголовок следующей главы в него не попадает); отсутствующие обязательные разделы REQ/ADR добавляются с явной пометкой «не выделялось в legacy документе», а не выдумываются;
- legacy ADR на русском (`- Статус: Принято`, `## Контекст`, `## Решение` …) распознаётся; частичная замена («Заменяет: ADR-026, только …») остаётся текстом и не превращается в `supersedes`;
- legacy `Mutation policy` без подразделов получает `### Allowed/Conditional/Forbidden`, исходная формулировка сохраняется в `Allowed`;
- взаимные ссылки STEP/REQ/ADR дополняются для документов этой миграции;
- hand-written файлы на месте generated projections (`SPEC.md`, `STATUS.md`, roadmap, status, OQ index) до перезаписи сохраняются рядом как `<name>.legacy.md`.

Migration идемпотентна: повторный запуск без фактических изменений не создаёт новый migration report. Уже pinned historical review нельзя тихо удалить/изменить/re-pin: hash mismatch является corruption blocker.

Manual validation может разрешить строго распознанное migration-pending состояние как warning после control-plane hop. `--mode commit` и `--mode ci` остаются строгими до RECONCILE.

## Project-owned templates

Colocated templates намеренно не входят в updater ownership.

Canonical current definitions поставляются Harness control plane, а синхронизацию project copy выполняет PROJECT RECONCILE.

Для initialized project действует общий migration invariant:

- missing template создаётся из current protocol default;
- missing frontmatter mapping keys и missing structural sections добавляются additive способом;
- существующие project values, unknown keys и prose не заменяются protocol defaults;
- изменение `kind` или mapping/non-mapping shape считается non-additive и блокирует автоматическую миграцию;
- повышение `schema` мигрирует только по шагам, объявленным в `TEMPLATE_SCHEMA_MIGRATIONS` (`template_contract.py`): ключ — `kind` template (или prefix id: `STEP`, `REQ`, `ADR`, `OQ`), значение — `{from_schema: step}`, где `None` означает аддитивный шаг, а callable `(meta, body) -> (meta, body)` — non-additive преобразование; `PROJECT RECONCILE` применяет цепочку шагов, затем обычную additive migration. Необъявленный шаг, понижение `schema` или ошибка преобразования остаются blocker-ом;
- `legacy_schema_pending()` обязан обнаруживать structural drift до commit/CI;
- любое будущее изменение обязательной template shape должно иметь regression `old valid project → update/reconcile → current validation PASS`.

Так existing project не получает silent overwrite во время update, но schema действительно мигрирует после явного reconciliation.

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
