---
schema: 1
id: STEP-003
status: completed
type: implementation
priority: high
phase: project-model
depends_on:
  - STEP-002
requirements:
  - REQ-001
  - REQ-003
  - REQ-008
  - REQ-009
adrs:
  - ADR-001
  - ADR-002
architecture_refs:
  - "docs/architecture.md#основные-компоненты-границы"
  - "docs/architecture.md#data-state-model"
  - "docs/architecture.md#reliability-observability"
  - "docs/architecture.md#security-boundaries"
risk_flags:
  - performance-critical
plan:
  status: ready
  revision: 1
  context_basis: sha256:cea16579138bbb335b80f6481d33f9de1e4393eced6b83cbcbee9a0a0e3bf9f1
  content_hash: sha256:099516f4ef528b0f28532273fccb6117bf27c9da6c784ff2f56264084b3f1c35
  reviewed_report: planning/plan-reviews/STEP-003/PLAN-REVIEW-20260922T163405Z.md
  planned_at: 2026-09-22T16:34:44+00:00
---

# STEP-003 — Парсинг артефактов и общие индексы

## Goal

Построить read-only parsing STEP, REQ, ADR и OQ, requirements status reader, Artifact Index и Reference Index с инкрементальным обновлением.

## Context

Все UI и navigation consumers должны получать один согласованный project model. Ошибочный документ не должен блокировать корректные артефакты, а manifest blocker уже изолирован STEP-002.

## Scope

- Typed parsers canonical artifacts и requirements status projection.
- Artifact Index с metadata, status и relations; Reference Index для Harness-aware files.
- Classifier точной области Harness-aware files и FileSystemWatcher invalidation/update paths.
- Diagnostics classification для recoverable artifact errors.
- Producer categories `ArtifactDirectoryMissing`, `ArtifactParseError`, `DuplicateArtifactId`, `InvalidArtifactReference` и `ProjectionReadError` для общего diagnostics flow.
- Command `Harness: Refresh` для controlled rebuild derived state текущего workspace без canonical mutation.
- Unit tests parsing, indexes, relations, status reader, aware-file classifier и incremental update.

## Mutation policy

### Allowed

- Source и tests parser/index/watcher/diagnostics layers.
- Локальные derived in-memory structures Extension Host.

### Conditional

- Минимальные shared types или activation registration, необходимые index lifecycle.

### Forbidden

- Persistent cache в workspace, изменение canonical Harness files или повторный full scan на каждый provider lookup.
- Views, command catalog и navigation UI beyond interfaces, нужные индексам.

## Out of scope

- Tree/Quick Pick presentation и command graph parsing.
- Реализация specific definition/hover/completion/reference providers.

## Acceptance criteria

- Корректные configured STEP, REQ, ADR и OQ представлены одним Artifact Index с ID, title, kind, status, file, metadata и relations.
- REQ lifecycle берётся из requirements status projection; отсутствие artifacts остаётся normal empty state.
- Reference Index и classifier покрывают ровно canonical artifacts, configured projections, project knowledge/planning Markdown, `.harness/**/*.md` и additional Markdown внутри Harness workspace, исключая Markdown вне него.
- Duplicate IDs, parse errors, invalid H1, identity mismatch и invalid reference диагностируются, не ломая корректные artifacts.
- Watcher инкрементально обновляет затронутые derived data без обхода `node_modules`.
- `Harness: Refresh` восстанавливает derived state после пропущенного watcher event без изменения Harness files.

## Verification

- Реальные `typecheck`, `lint` и targeted unit tests parser/index/watcher.
- Integration scenario: изменение одного artifact обновляет индекс без перезапуска Extension Host.
- Targeted tests refresh command и stable artifact/projection diagnostics categories.

## Deliverables

- Artifact parsers, status reader, Artifact/Reference Indexes, classifier, watcher core, diagnostics core и tests.

## Implementation plan

1. **Единая типизированная модель артефактов и диагностик.** Добавить в
   `src/projectModel/` минимальные shared types для `STEP`, `REQ`, `ADR` и `OQ`,
   metadata, исходящих/входящих relations и стабильных категорий
   `ArtifactDirectoryMissing`, `ArtifactParseError`, `DuplicateArtifactId`,
   `InvalidArtifactReference` и `ProjectionReadError`. Продолжить паттерн
   `ProjectDiagnostic`: категория и ключ локализуемого сообщения отделены, а
   новые production message keys включаются в типизированный registry и оба
   EN/RU bundle. Не вводить persistent cache, fallback paths или выполнение
   содержимого Markdown.
2. **Безопасное чтение и parsers canonical источников.** Использовать только
   `ValidProjectState.configuredPaths` для выбора directories `taskDirectory`,
   `requirements`, `adrDirectory` и `openQuestions`, а также configured
   requirements status projection, но доказывать containment повторно для
   каждого directory entry и открываемого regular Markdown file. Вынести
   file-read seam с no-follow/descriptor identity проверкой и post-open
   contained-path re-derivation там, где capability позволяет, чтобы подмена
   каталога или файла symlink-ом после detection fail-closed давала
   diagnostic, а не external read. Для regular Markdown files ограниченно и
   fail-safe разобрать YAML frontmatter, H1 и известные relation lists;
   сверять ID файла, frontmatter и заголовка. Отсутствующий каталог или пустой
   набор трактовать как normal empty/recoverable state, а malformed input,
   duplicate ID и неизвестную relation изолировать в diagnostics, сохраняя
   остальные корректные артефакты. Не обходить `node_modules`, symlinks за
   contained root или произвольные workspace paths.
3. **Artifact Index и lifecycle REQ.** Реализовать один in-memory index на
   workspace root с lookup по ID, metadata, outgoing/incoming relations и
   snapshot-операциями для будущих consumers. Lifecycle REQ получать только из
   configured requirements status projection, не выводить и не сохранять его
   альтернативно. При обновлении файла пересобирать relations затронутого ID и
   backlinks детерминированно; публичные lookup не должны инициировать I/O или
   full scan.
4. **Reference Index и точный Harness-aware classifier.** Отдельно собрать
   references из допустимых Markdown: canonical artifacts, configured
   projections, project knowledge/planning Markdown, `.harness/**/*.md` и
   additional Markdown внутри Harness workspace. Markdown вне этой области и
   `node_modules` исключить. Reference Index хранит URI/range/target ID и
   допускает ссылку на ещё неизвестный ID как `InvalidArtifactReference`, не
   изменяя Artifact Index; parsing выполняется один раз при build/update, а не
   при provider lookup.
5. **Инкрементальный lifecycle и controlled refresh.** Расширить существующий
   `ProjectStateService` или добавить узкий владеющий ему in-memory service:
   для каждого workspace root создавать manifest watcher независимо от текущего
   project state, чтобы исправление invalid/unsupported/blocked manifest
   повторно запускало detection. Только после valid detection создавать и
   освобождать artifact/reference `FileSystemWatcher`; он классифицирует
   затронутый путь и обновляет только artifact, projection либо reference data,
   уведомляя будущих consumers. При изменении manifest сначала повторять
   detection и при blocker очищать derived indexes. Зарегистрировать `Harness:
   Refresh` через существующий `LifecycleRegistry`: команда явно пересобирает
   derived state текущего workspace, не пишет Harness files и не запускает
   tools/processes.
6. **Проверяемые seams и реальные gates.** Добавить focused unit tests для
   valid/empty/malformed artifacts, ID/H1 mismatch, duplicates, invalid
   references, requirements status reader, classifier inclusions/exclusions,
   isolated incremental invalidation, symlink/swap races каждого read seam и
   refresh без mutation. Проверить, что manifest watcher переводит root из
   invalid/blocked state в valid без restart, а artifact watcher создаётся
   только после valid detection. Дополнить Extension Host integration scenario
   изменением одного fixture artifact и наблюдаемым обновлением index без
   перезапуска; проверить EN/RU production diagnostic keys. Перед независимым
   review выполнить существующие `yarn
   typecheck`, `yarn lint`, `yarn format`, targeted unit tests, `yarn
   test:integration`, `yarn build`, `yarn package`, Harness validation,
   projection check и `git diff --check`, фиксируя только фактическое evidence.

## Evidence

Обновлено `STEP FIX STEP-003` (fix cycle 6, применён напрямую без отдельного
implementer/reviewer subagent — по явному запросу пользователя после 5
циклов review, каждый из которых сжигал существенное время на всё более
узкие TOCTOU-варианты одного и того же containment-механизма) по
независимому review `planning/reviews/STEP-003/REVIEW-20260922T222000Z.md`
(findings F-025—F-027). Предыдущий текст этого раздела (evidence fix cycle 5)
полностью заменён.

### Исправления по findings (fix cycle 6)

- **F-025** (high, `src/projectModel/artifactIndex.ts`, `readContainedMarkdown`,
  `markdownFiles`) — независимый review показал, что F-022 закрыл гонку
  внутри самой post-open re-derivation (`readlinkSync` вместо `realpathSync`),
  но depth-0 open в `markdownFiles` и file-open в `readContainedMarkdown`
  по-прежнему резолвили ВЕСЬ путь (`directory` или `candidate`) одним
  multi-component string open. `O_NOFOLLOW` защищает только финальный
  component такой строки: подмена ЛЮБОГО промежуточного ancestor
  (например, `planning` в `planning/tasks`) на symlink наружу между
  pre-open containment-check и этим open заставляла kernel прозрачно
  последовать через него; последующий rename внешнего дерева обратно внутрь
  root до вызова `readlink` мог обмануть containment-проверку. Исправлено
  структурно, а не сдвигом проверки: путь теперь проходится покомпонентно —
  `walkAnchoredDirectory` открывает `root` (уже существующий trust anchor),
  затем каждый segment `directory`/родительского каталога файла открывается
  ПО ОДНОМУ, каждый раз как единственный (и потому реально защищённый
  `O_NOFOLLOW`) path component относительно уже открытого fd родителя —
  тот же примитив, которым вложенные уровни `visit` уже были защищены с
  cycle 2 (F-011/F-017). Итоговый файл в `readContainedMarkdown` открывается
  тем же способом — как один component относительно anchored fd
  родительского каталога. Общие helpers `openAnchoredRootDirectory`,
  `openVerifiedDirectoryLevel`, `walkAnchoredDirectory` переиспользуются и
  `markdownFiles`, и `readContainedMarkdown`.
- **F-026** (medium, evidence) — комментарии и Evidence снова переписаны на
  точный механизм (покомпонентный fd-anchored walk, а не "post-open
  re-derivation одного open"); unit-тест `F-022: подмена ancestor ПОСЛЕ
  open... (directory)` обновлён под новую архитектуру: `root` и `planning`
  теперь открываются как отдельные покомпонентные уровни (root вообще не
  вызывает `deriveOpenedDirectoryPath` — проверка containment root против
  самого себя избыточна), поэтому подмена ancestor "planning" для уже
  открытого "tasks" соответствует ВТОРОМУ вызову хука, а не первому — тест
  адаптирован (`callCount === 2`) и по-прежнему проходит.
- **F-027** (low, `descriptorLinkPath`) — не тронут отдельно в этом цикле:
  edge case с суффиксом ` (deleted)` остаётся зафиксированным как fail-closed
  (ContainmentError для unlinked target), что уже является безопасным
  поведением; отдельная обработка легитимных каталогов с таким именем в
  scope этого fix cycle не выполнялась (низкий приоритет, не блокирует
  containment-гарантию).

### Реально выполненные gates (fix cycle 6, эта revision)

- `yarn typecheck` — exit code 0.
- `yarn lint` — exit code 0.
- `yarn format` — exit code 0 (после `format:fix`, применённого к
  `src/projectModel/artifactIndex.ts`).
- `yarn test:unit` — exit code 0; **64/64 passing** (включая обновлённый
  F-022 directory-тест и все ранее закрытые F-011/F-012/F-013/F-015/F-017/
  F-021/F-024 сценарии — регрессий нет).
- Ручной independent probe нового кода (`node --import tsx`, вне test suite):
  классический F-025 sequence (rename ancestor → symlink наружу, повторено
  2000 раз с сбросом состояния) — **0 leaks**, каждая попытка либо fail-closed
  (`ContainmentError`/`ELOOP`), либо не совпадает с моментом гонки; это не
  замена многопоточному racer'у прошлого review (не выполнялся в этом
  цикле), но подтверждает, что сама уязвимая multi-component-open
  конструкция, которую эксплуатировал F-025, из кода удалена.
- `yarn test:integration` — exit code 0; EN 6 passing (624 ms), RU 6 passing
  (557 ms) — оба через watcher-путь, без обращения к refresh-fallback.
- `yarn build` — exit code 0.
- `yarn package` — exit code 0; VSIX (`vscode-harness-navigator-0.0.1.vsix`,
  10 файлов, 27.77 KB) содержит production bundle и EN/RU localization
  bundles.
- `python3 .harness/tools/validate.py --mode manual` — exit code 0:
  `HARNESS VALIDATION: PASS (248 tracked files checked, mode=manual)`;
  warnings только про stale ready context уже завершённых STEP-001/STEP-008
  (не относится к STEP-003).
- `python3 .harness/tools/sync-projections.py --check` — exit code 0 (PASS).
- `git diff --check` — exit code 0 (no whitespace errors).

### Явно принятый остаточный риск

По явному решению пользователя (см. `AGENTS.local.md`, добавлен в этом же
цикле): containment-код этого read-only расширения защищается от обычных
ошибок конфигурации и от единичных явных security issues, но не обязан
защищаться от adversarial multi-process race condition, требующей
скоординированной гонки нескольких потоков ради успеха с вероятностью
кратно ниже 1%. Если независимый review найдёт ещё более узкий вариант
такого класса, это принимается как accepted risk, а не как повод для
очередного `STEP FIX`/`STEP REVIEW` цикла, если явно не решено иное.

## Blocker / Failure reason

—
