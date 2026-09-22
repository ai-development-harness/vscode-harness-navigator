---
schema: 1
id: ADR-005
status: accepted
date: 2026-09-21
deciders:
  - Владелец проекта
supersedes: []
superseded_by: []
requirements:
  - REQ-002
steps:
  - STEP-008
---

# ADR-005 — Platform-scoped гарантия containment при чтении manifest

## Context

`STEP-002` реализовал read-only чтение `.harness/manifest.yaml` с containment
check, не допускающим чтение файла за пределами owning workspace root
(`ADR-001`, `docs/architecture.md#security-boundaries`). Независимый review
(`planning/reviews/STEP-002/REVIEW-20260921T184919Z.md`, F-009) и последующий
independent planning-review corrective `STEP-008`
(`planning/plan-reviews/STEP-008/PLAN-REVIEW-20260921T193300Z.md`, F-001/F-002)
установили: текущая реализация закрывает TOCTOU-гонку между containment
check и открытием файла только на Linux, через `/proc/self/fd/<fd>` — magic
symlink, дающий canonical path уже открытого descriptor независимо от того,
что произошло с исходной path string после проверки. Portable-эквивалента
этому механизму средствами Node.js `fs` без native addon не существует:
macOS не предоставляет для этого `/dev/fd` (это не symlink на target, а
отдельный `fdesc`-механизм; реальный API — `fcntl(fd, F_GETPATH)`, которого
Node не экспонирует), а Windows не определяет POSIX-специфичные open-флаги
(`O_NOFOLLOW`, `O_NONBLOCK`) в `node:fs` вовсе. При этом package manifest не
ограничивает поддерживаемую OS, а `docs/architecture.md` описывает обычный
universal VS Code extension.

## Problem

Нужно решить, какую гарантию containment расширение обязано давать на
macOS и Windows, чтобы корректный пустой Harness-проект мог достигать
состояния `valid` (`REQ-002`) без native-code зависимости, и как эта
гарантия документируется, чтобы не создавать ложное впечатление полного
паритета с Linux.

## Decision

Расширение принимает **platform-scoped** модель containment guarantee для
чтения `.harness/manifest.yaml` (и, по аналогии, для любого другого
configured path, читаемого этим слоем):

1. На **всех** платформах, безусловно и без изменений, действует
   существующая portable защита: `realpathSync` итогового пути и
   `isContained(realRoot, ...)` до какой-либо попытки открыть файл, плюс
   post-open identity check по `dev`/`ino` между открытым descriptor и
   текущим `lstat` того же path. Это отклоняет любой **статический**
   (не гоночный) symlink за пределами root — final component или любой
   promежуточный ancestor — и любую подмену **финального** компонента
   path на symlink в течение самой операции open, независимо от platform.
2. Дополнительная защита от **гонки на промежуточном ancestor** (активный
   параллельный локальный процесс подменяет каталог между containment
   check и open) реализуется через canonical-path re-derivation открытого
   descriptor и остаётся Linux-specific (`/proc/self/fd/<fd>`), поскольку
   единственный доказанный, не требующий native addon механизм существует
   только там.
3. На platform, где эта re-derivation недоступна (macOS, Windows, любая
   ещё не поддержанная platform), расширение **осознанно принимает**
   остаточный риск именно этого узкого сценария (одновременно исполняющийся
   локальный процесс, атакующий гонку в течение открытия одного файла) и
   **достигает `valid`** для корректного проекта вместо `configurationBlocked`.
   Platform capability (какие open-флаги реально применены, доступна ли
   re-derivation) фиксируется в типизированной, наблюдаемой в tests
   структуре, а не подразумевается.
4. Native addon (`fcntl F_GETPATH` на macOS, `GetFinalPathNameByHandle` на
   Windows) для достижения полного паритета с Linux не добавляется в этом
   решении: это отдельный, значительно более тяжёлый product/architecture
   выбор (packaging, prebuilt-бинарники под platform/arch, Electron ABI
   VSCode, новая security-поверхность), не оправданный узостью закрываемого
   остаточного риска.

## Alternatives considered

### Вариант A — Linux-only `valid` state

Оставить `valid` достижимым только на Linux, честно отразив это в
`package.json`/`docs/architecture.md`. Отклонено: не решает исходный дефект
F-009 по существу — расширение как universal VS Code extension должно
работать на заявленных desktop platforms; REQ-002 acceptance («корректный
пустой Harness-проект») не выполнялось бы на macOS/Windows вовсе.

### Вариант B — Native addon для полного паритета

Использовать `fcntl(F_GETPATH)`/`GetFinalPathNameByHandle` через native
addon. Отклонено для этого решения: непропорционально увеличивает build/
packaging/security surface ради закрытия узкого, требующего уже
исполняющегося локального attacker-процесса сценария; может быть
пересмотрено отдельным ADR, если появится веская причина.

### Вариант C — Platform-scoped guarantee (выбрано)

Портируемая защита от статических symlink и final-component swap — везде;
защита от ancestor-race — только там, где она реально доказуема (Linux).
Выбрано как пропорциональный ответ на реальный threat model: сценарий,
защищаемый дополнительно только на Linux, требует уже присутствующего на
машине пользователя конкурентного локального процесса, что само по себе —
существенно более сильная attacker capability, чем предполагает обычная
модель «открыл недоверенный workspace».

## Consequences

`valid` состояние достижимо на всех заявленных platform для корректного
project, что закрывает F-009 по существу. Diagnostic/test surface обязаны
делать различие platform capability наблюдаемым (какие защитные механизмы
реально активны), а не скрытым допущением. Будущее добавление native addon
для полного паритета потребует отдельного ADR, а не тихого расширения этого
решения.

## Security implications

Остаточный риск явно ограничен: конкурентный локальный процесс на машине
пользователя, успевающий подменить промежуточный ancestor directory именно
в момент открытия `.harness/manifest.yaml`, на platform без re-derivation
(macOS, Windows) может добиться чтения файла за пределами workspace root.
Любой статический (не гоночный) symlink и любая подмена финального
component **на symlink** — по-прежнему блокируются на каждой platform (см.
Decision §1); подмена финального component через hard link — отдельный,
не входящий в это решение случай: `realpath`/`dev`/`ino`/procfs identity
check по построению не отличает hard link от исходного inode ни на одной
platform. Это не расширяет привилегии расширения за пределы read-only
границы `ADR-001`.

## Data / migration implications

Отсутствуют: решение не меняет формат или расположение project data.

## Compatibility / operational implications

`configurationBlocked` для corretного проекта на macOS/Windows,
вызванный исключительно недоступностью re-derivation (текущий дефект
F-009), перестаёт возникать. Platform capability, отсутствие которой
приводит к более узкой (но не отсутствующей) защите, должна быть покрыта
тестами инъекцией capability profile, а не только реальным OS раннером.
