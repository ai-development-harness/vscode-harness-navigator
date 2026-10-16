---
name: update-harness
description: Install the latest or explicitly selected immutable Harness release directly while preserving all project artifacts.
---
# Update Harness

Для HARNESS UPDATE CHECK/APPLY [TO vX.Y.Z] используй deterministic engine:

```bash
python3 .harness/tools/harness-update.py check [--to vX.Y.Z] --json
python3 .harness/tools/harness-update.py apply [--to vX.Y.Z] --json
```

Без TO обновляй current → latest, с TO current → указанный immutable tag.
Один переход, одна transaction, один report. Не строй цепочку releases и не
требуй повторных APPLY. Не проверяй STEP/REQ/ADR/REVIEW, Evidence, актуальность
планов, dependency proofs, projections или project templates перед обновлением.
Состояние рабочих артефактов НИКАК не блокирует установку. Не запускай full
validator/PROJECT RECONCILE как update prerequisite/postcondition.

CHECK read-only; APPLY сам заново проверяет source, exact current Harness
integrity, ownership/3-way merge safety и installation postconditions. Engine
сохраняет project bytes/modes и Git index, пишет служебные файлы/lock/report
атомарно с journal/rollback. Механики merge/записи не воспроизводи вручную.

UPDATED означает, что конечный target установлен. При reloadRequired=true
перезагрузи runtime перед следующей рабочей командой; не повторяй APPLY для
достижения target. Повторный APPLY — NO_UPDATE без repository mutation.
Покажи report и diff. Commit/push/PR выполняй лишь в авторизованном Git flow.

BLOCKED source/tag/managed-file drift, collisions, merge conflict или failure
установки сохраняют fail-closed semantics. Не обходи их ручным overwrite/lock.
Рабочие proof/freshness/schema gates остаются в обычных STEP/project flows;
обновление не превращает исторический BLOCKED в PASS и не переписывает REVIEW.

Старый установленный engine может блокировать preflight по artifacts ещё до
получения новых файлов. Для него разрешён официальный external installer из
отдельного checkout выбранного immutable release: `harness-update.py apply
--root /absolute/project --to vX.Y.Z --json`. Сначала такой же check. Инструкция,
trusted-source boundary, legacy adoption и narrow stale snapshot recovery:
[UPDATES.md](../../../.harness/docs/UPDATES.md).

Ни target hooks/install/bootstrap, ни произвольные scripts из release updater
не запускает. Floor v0.6.0. Отсутствующий lock требует explicit known baseline
через adopt --from; BASE не угадывается. Новые core skills не захватывают
существующие project/third-party paths молча.
