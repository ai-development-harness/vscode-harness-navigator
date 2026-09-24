# `.harness/`

Namespace/control plane AI Development Harness. Здесь собраны core documentation/tooling, machine-readable protocol metadata, shared Harness configuration и local operational state. Само расположение файла под `.harness/` не означает ownership `harness_owned`.

`manifest.yaml` содержит только техническое состояние Harness, current release, project initialization state и ссылки на основные источники истины. Бизнес-требования, архитектурные решения и планы здесь хранить нельзя.

`project.initialized` меняется на `true` только после успешного `PROJECT INIT` и проверки согласованности созданной документации.

## Execution policy

`.harness/manifest.yaml → execution.maxFixReviewCycles` задаёт максимальное число циклов `FIX → REVIEW` внутри одного `STEP RUN STEP`. Допустимый диапазон — от 1 до 5 включительно; template default — 3.

`execution.verificationCommandTimeoutSeconds` ограничивает одну deterministic STEP Verification command; допустимо 1..3600 секунд, template default — 300. Verification запускается argv-напрямую без shell.

`review.security` и `review.tests` управляют дополнительными specialized reviewers: `auto` запускает reviewer по фактическим рискам/diff/test surface, `always` — при каждом review-проходе. Режима `never` намеренно нет: настройка может усилить review, но не отключить safety gate.

`skills.search.maxResults` задаёт максимальный размер shortlist команды `SKILL FIND`; допустимо от 1 до 10, template default — 5.

Все эти значения проверяются `.harness/tools/validate.py`, поэтому отсутствующая или недопустимая настройка блокирует Harness validation до запуска orchestration.

Локальные/секретные overrides при необходимости складываются в `.harness/local/`; каталог игнорируется Git.

## Ownership внутри namespace

- `docs/**`, `tools/**` и core policies/protocol metadata — преимущественно `harness_owned`;
- `manifest.yaml` и `git-policy.toml` — `shared`;
- `local/**` — local-only и никогда не tracked.

Точный source of truth ownership — `harness-update.toml`; filesystem namespace не заменяет эту policy.

Local-only namespace тоже имеет lifecycle contract: persistent файл обязан иметь owner/tool, recovery semantics, safe deletion condition и migration/version strategy. Temporary semantic/Git input удаляется только deterministic consumer-ом после доказанного SUCCESS и только если exact lexical path/identity не изменились; symlink paths блокируются. Ошибка secondary cleanup не превращает уже успешный primary side effect в failure. Неизвестные local-файлы Harness автоматически не удаляет.

## Repository policies

- `git-policy.toml` — поведение GIT COMMIT / GIT PUSH / GIT PR / GIT PR FINISH / GIT SYNC, ветки и commit messages.
- `harness-policy.toml` — deterministic integrity/safety checks для local preflight и CI.
- `harness-update.toml` — source repository, ownership classes, путь к remote update manifest и merge policy для self-update.
- `harness.lock.json` — машинный known BASE текущего Harness release; JSON намеренно не требует inline-комментариев.
- `harness-update-graph.json` — machine-readable граф допустимых переходов между immutable Harness releases; локальная копия входит в protocol layer, а выбор маршрута делается по версии из canonical `default_branch`.
- `command-transitions.json` — machine-readable source of truth для canonical command surface, краткие descriptions/docs links, chain eligibility, explicit transition edges, `onPreviousResult` и runtime preconditions. До skill routing canonical command проходит structural validation по этому graph.
`.harness/local/execution/execution-status.json` — bounded local operational state canonical executions. Schema v2 хранит full active records, отдельный STEP recovery proof и не более 100 compact terminal tombstones; schema v1 мигрирует автоматически execution layer-ом. Canonical repository artifacts имеют приоритет над local state.

`harness.lock.json` не содержит secrets. Его нужно хранить в Git вместе с проектом; удаление lock переводит updater в legacy-adoption mode.

Все tracked YAML/TOML policy/config files в template снабжены inline-комментариями для каждого параметра. При добавлении нового параметра сохраняй это правило: назначение, допустимое поведение и хотя бы один пример должны быть видны рядом с настройкой.

## Language policy

`.harness/manifest.yaml` → `language` — единый источник языка docs/commits/comments/tests/fixtures/GitHub templates/release notes.
