# Multiple Harness Project Contexts — Architecture Contract

**Status:** Accepted
**Accepted:** 2026-10-02
**Architecture issue:** #175
**Implementation follow-up:** #188

Этот документ фиксирует архитектурный contract поддержки нескольких независимых Harness project contexts внутри одного Git worktree. Он является **Harness-owned protocol documentation**.

Это намеренно не project ADR в `docs/adr/`: `docs/adr/` — project-owned surface конкретного пользовательского проекта и не должна получать архитектурные решения самого Harness через template/update.

До реализации #188 текущий runtime остаётся single-root. Этот документ задаёт обязательные boundaries будущей реализации и не объявляет capability уже доступной.

## Context

Текущая модель Harness фактически предполагает:

```text
Harness project root == Git worktree root
```

Для больших monorepo нужна поддержка нескольких независимых project contexts:

```text
repo/                         ← Git worktree root
├── apps/web/                 ← Harness project root A
│   └── .harness/manifest.yaml
├── services/api/             ← Harness project root B
│   └── .harness/manifest.yaml
└── packages/shared/          ← shared code, не Harness project
```

REQ/ADR/OQ/STEP, Project Principles, planning/review history, local execution state и project-owned protocol configuration разных member projects не должны смешиваться.

При этом branch, index, HEAD, remote и PR остаются общими свойствами Git worktree.

## Decision summary

Принимается следующая модель:

```text
Harness project root
    ≠
Git worktree root
```

как нормальное поддерживаемое состояние.

Каждый Harness member project:

- имеет собственный canonical marker `.harness/manifest.yaml`;
- имеет собственный project-local protocol/config/state surface;
- имеет собственные REQ/ADR/OQ/STEP/PRN и reports;
- имеет собственный `.harness/local/**`;
- может находиться на собственной Harness release, если его protocol layer не разделяет writable ownership с другим member;
- использует общий Git worktree для branch/index/HEAD/remote.

Новый второй marker не вводится.

## Terms

### Project root

Directory, содержащая выбранный валидный Harness marker:

```text
<projectRoot>/.harness/manifest.yaml
```

Project root определяет:

- manifest и project-local policies;
- canonical REQ/ADR/OQ/STEP/PRN;
- planning/review/audit/release/update reports;
- project-local templates/projections;
- Execution Status и другую local recovery state;
- project-owned runtime configuration.

### Git root

Actual Git worktree root, определяемый Git, а не расположением Harness marker.

Git root определяет branch, HEAD, index, remotes, commit, push, pull/sync и PR.

### Project context

Machine-readable resolved pair:

```json
{
  "schemaVersion": 1,
  "projectRoot": "/absolute/path/to/member",
  "gitRoot": "/absolute/path/to/repo",
  "selectionSource": "explicit|environment|nearest-parent",
  "projectName": "web",
  "harnessRelease": "0.x.y"
}
```

Absolute paths являются runtime facts и не должны попадать в tracked project artifacts.

## Project root resolution

Canonical precedence:

1. explicit project root, переданный control plane/CLI;
2. `HARNESS_PROJECT_ROOT`, если явно задан процессу;
3. nearest valid parent Harness marker от текущей рабочей директории;
4. иначе fail-closed: project selection required.

### Explicit root

Explicit root имеет высший приоритет.

Если explicit path не существует, не является directory, не содержит валидный `.harness/manifest.yaml`, не принадлежит ожидаемому Git worktree или нарушает containment/symlink boundary — resolver возвращает BLOCKED.

**Silent fallback к cwd, parent marker или Git root запрещён.**

### Nearest parent

При отсутствии explicit override resolver идёт только вверх по parent chain текущей directory и выбирает ближайший валидный Harness marker.

Nested project поэтому всегда выигрывает у более высокого root context.

Resolver не выбирает «первый найденный» descendant project.

### Invocation из Git root

Если сам Git root не является Harness project и project root нельзя определить parent-chain resolution, команда требует explicit selection.

Наличие нескольких descendants не разрешает автоматически выбирать один из них.

## Canonical marker

Единственный marker project context:

```text
.harness/manifest.yaml
```

Не вводить `.harness-project`, registry-файл или другой parallel marker.

Marker считается действительным только после минимальной deterministic validation manifest/protocol identity. Простого существования файла недостаточно.

## Containment and path safety

Project-local paths из manifest/config разрешаются относительно selected `projectRoot`.

Для project-owned/control-plane artifacts обязательны обе проверки:

1. lexical containment после normalization;
2. realpath containment после symlink resolution.

Блокируются:

- `..` escape;
- absolute path вне allowed boundary;
- symlink/junction escape;
- case-fold alias escape на case-insensitive filesystem;
- path в sibling Harness project для project-local artifact.

Пример запрещённого config:

```text
apps/web Harness
→ ../../services/api/planning
```

### Product mutation outside project root

V1 может разрешить STEP менять shared product code **внутри того же gitRoot**, если одновременно:

- path явно разрешён STEP Mutation policy;
- path не выходит за gitRoot;
- target не находится внутри другого Harness project root.

Это позволяет member project менять общий `packages/shared/`, но запрещает неявно мутировать sibling member project.

Project-local Harness artifacts/control state всегда остаются внутри projectRoot.

## Artifact identity

Canonical IDs scoped to project context.

Допустимо:

```text
apps/web       → STEP-001
services/api   → STEP-001
```

Это разные artifacts.

Любой runtime/client cache key для canonical artifact обязан включать project identity, а не только `STEP-001`.

## Project commands

Следующие команды всегда выполняются в selected project context:

- PROJECT INIT / STATUS / RECONCILE;
- STEP ADD / LIST / SHOW / NEXT;
- STEP PLAN / IMPLEMENT / REVIEW / FIX / RUN / AUDIT;
- RELEASE CHECK;
- project-local skills/projections/reports.

Resolvers/validators одного member не читают canonical artifacts sibling member.

## Execution state

Execution Status project-local:

```text
<projectRoot>/.harness/local/execution/execution-status.json
```

Execution records разных members физически разделены.

Resume никогда не должен находить execution из sibling project.

Git-side operational state, если он является repository-global, должен иметь explicit ownership/keying и не притворяться project-local.

## Git commands

Git operations используют actual `gitRoot`.

```text
selected projectRoot → context/provenance
gitRoot              → branch/index/HEAD/remote mutation
```

Следствия:

- members не имеют независимых branches в одном worktree;
- staged index общий;
- commit/push/PR repository-level;
- selected project context обязательно отображается в machine/human result для safety;
- выбор projectRoot не фильтрует Git index автоматически.

Implementation не должна создавать ложную модель «branch per member».

## Protocol and update ownership

V1 использует **project-local protocol layer** для каждого member.

Project-owned/member-local:

- `.harness/**`, кроме explicitly repository-global surfaces;
- project-local `.agents/**`, runtime config и project docs согласно ownership policy;
- update policy/lock/report selected member;
- local execution/recovery state.

### Repository-global surfaces

Nested member не получает автоматического ownership над repository-global files только потому, что такие paths существуют в single-root template.

Примеры:

- repository-root `.github/**`;
- Git repository configuration;
- другие worktree-global integration files.

Их ownership должен оставаться у explicit root/repository context либо вне automatic nested-member update ownership.

Member updater **не пишет вверх за projectRoot** ради синхронизации repository-global surface.

### HARNESS UPDATE

`HARNESS UPDATE CHECK/APPLY` всегда имеет selected project target.

Update engine selected member:

- читает его policy/lock;
- меняет только его owned project-local protocol paths;
- пишет report в его configured report directory;
- не меняет sibling protocol layer;
- не меняет repository-global surface без отдельного explicit repository-level ownership contract.

### Mixed Harness releases

Mixed member releases разрешены в v1 для независимых project-local protocol layers:

```text
apps/web      → Harness vA
services/api  → Harness vB
```

Один execution использует только protocol/code selected member.

Cross-project orchestration между разными releases не поддерживается.

Если future implementation обнаруживает shared writable protocol ownership между members, она обязана fail-closed, а не пытаться 3-way merge нескольких owners.

## Runtime adapter / client boundary

Canonical runtime launch context должен содержать explicit:

```text
projectRoot
gitRoot
runtimeId
```

Process cwd не является canonical project identity.

Runtime adapter не выбирает project сам: selection принадлежит Harness control plane.

UI/Navigator должен отображать selected project context минимум через project name, path relative to gitRoot и Harness release.

## Cross-project dependencies

V1 **не вводит federation/scheduler** между member projects.

Запрещено implicit resolution sibling artifact ID.

Canonical REQ/STEP/OQ/ADR/PRN links resolve только внутри selected project.

Read-only external references могут появиться позже только как explicit external contract; они не участвуют автоматически в STEP dependency resolver, planning/completion proof, REVIEW completion или scheduling.

## Backward compatibility

Existing single-root project остаётся валидным частным случаем:

```text
projectRoot == gitRoot
```

Для включения capability не требуется перенос существующих files, новый marker, новый artifact ID namespace или обязательная migration layout.

Single-root workflow должен пройти existing regression suite semantics-compatible, кроме появления новых explicit context fields в versioned API.

## Migration / creation of members

Автоматическая массовая migration existing repository layout не входит в v1.

Создание nested member должно быть explicit operation/bootstrap.

Нельзя автоматически превращать каждый `apps/*` directory в Harness project.

Если root Harness project уже существует, nested member может сосуществовать с ним; nearest-parent resolution определяет active project.

## Failure semantics

Implementation #188 должна использовать stable machine reason codes минимум для:

- `PROJECT_ROOT_INVALID`;
- `PROJECT_ROOT_SELECTION_REQUIRED`;
- `PROJECT_ROOT_OUTSIDE_GIT_WORKTREE`;
- `PROJECT_PATH_ESCAPE`;
- `SIBLING_PROJECT_MUTATION_FORBIDDEN`;
- `PROJECT_CONTEXT_VERSION_CONFLICT` — только если обнаружен реально shared writable protocol ownership.

Exact names могут быть уточнены до merge implementation, но semantic distinction обязателен.

## Alternatives considered

### Всегда использовать Git root

Отклонено: смешивает project-local contracts/state и делает независимые member projects невозможными.

### Выбирать project только по cwd

Отклонено: cwd — transport detail. Нужны marker validation и explicit override.

### Автоматически искать первый Harness descendant

Отклонено: selection становится nondeterministic/опасной при нескольких members.

### Один shared protocol layer на весь monorepo

Отклонено для v1: делает independent releases/config/state сложными и создаёт global coupling. Repository-global integrations могут иметь отдельного owner, но project protocol остаётся member-local.

### Cross-project scheduler сразу

Отклонено: federation существенно расширяет lifecycle, IDs, completion/recovery и version compatibility. Это отдельная будущая capability.

### Запретить mixed Harness releases

Отклонено как искусственное ограничение, пока member protocol layers действительно независимы. Shared writable ownership, наоборот, fail-closed.

## Security implications

Основной новый trust boundary — root/path selection.

Реализация обязана считать attacker-controlled/misconfigured cwd, explicit root, environment override, manifest paths, symlinks/junctions и sibling project layout.

Ни один из этих inputs не может расширить writable boundary за selected project/git contract.

## Data / migration implications

Нового product data format нет.

Execution/local state остаётся project-local. Existing single-root state не перемещается.

Artifact IDs становятся conceptually `(projectContext, artifactId)` для clients/caches, но tracked Markdown ID format не меняется.

## Compatibility / operational implications

- Git history/index остаются общими.
- Member projects могут обновляться независимо.
- Repository-global integrations требуют explicit owner.
- UI/runtime должны различать projectRoot и gitRoot.
- Existing single-root repositories продолжают работать без layout migration.

## Implementation boundary

Архитектурный contract считается принятым этим документом.

**Не реализуется здесь:** root resolver, containment engine, dispatcher plumbing, update engine scoping, runtime contract version bump, UI changes и monorepo regressions.

Вся implementation work вынесена в #188.

## Architecture completion criteria for #175

#175 можно закрыть после merge этого contract, потому что:

- project root vs Git root разделены;
- canonical marker определён;
- explicit selection precedence определён;
- invalid explicit root fail-closed;
- containment/symlink boundary определён;
- Execution/Git/update ownership определён;
- mixed-version policy определена;
- runtime/client boundary определена;
- cross-project dependencies явно deferred;
- implementation follow-up #188 создан.

Полная capability считается реализованной только после закрытия #188.
