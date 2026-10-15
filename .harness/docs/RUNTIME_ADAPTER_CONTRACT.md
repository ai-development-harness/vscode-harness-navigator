# Runtime Adapter Contract

Runtime Adapter Contract задаёт provider-neutral границу между Harness control plane и конкретным AI runtime.

Главный invariant: **adapter переводит lifecycle/auth/events конкретного runtime, но не меняет canonical semantics команд Harness**. CTS, STEP/REQ/ADR semantics, execution resolver и recovery остаются в control plane.

## Machine-readable source of truth

Канонический контракт:

```text
.harness/runtime-adapter-contract.json
```

Deterministic validator/normalizer:

```text
.harness/tools/runtime_adapter_contract.py
```

Проверка:

```bash
python3 .harness/tools/runtime_adapter_contract.py --json
python3 .harness/tools/runtime_adapter_contract.py --runtime codex --json
python3 .harness/tools/runtime_adapter_contract.py --runtime claude --json
```

Exit codes:

- `0` — контракт валиден;
- `1` — deterministic contract violation;
- `2` — contract нельзя прочитать/интерпретировать.

## Lifecycle API

Provider-neutral adapter обязан реализовать эквивалент следующих операций:

- `getIdentity()` — runtime id/version/adapter version;
- `getCapabilities()` — machine-readable capability snapshot;
- `getAccount()` — factual auth/account state без сохранения secrets;
- `start(request)` — запуск execution и поток normalized events;
- `resume(handle)` — продолжение существующей runtime session, если capability поддерживается;
- `cancel(handle)` — контролируемая отмена;
- `status(handle)` — factual lifecycle status.

Конкретный transport может быть CLI process, App Server, SDK или иной provider mechanism. От этого canonical Harness command semantics не меняются.

## Бесшовное переключение Claude Code ↔ Codex (#286)

Runtime Adapter **не владеет состоянием STEP**. Важно разделять:

1. **Новая canonical команда.** Claude Code выполнил `STEP PLAN STEP-042`,
   затем Codex выполняет `STEP IMPLEMENT STEP-042`. Это независимые
   команды Harness. Provider metadata предыдущей сессии, версия CLI и
   session handle **не проверяются** и не требуют ручной миграции.
2. **Восстановление прерванной команды.** При `HARNESS RESUME` control plane
   сначала проверяет существующие intent/recovery/side-effect guards.
   Если продолжение безопасно, любой runtime может запустить новую нативную
   сессию с контекстом из authoritative Harness state и проектных артефактов.
3. **Повторное использование нативной сессии.** Это только оптимизация внутри
   *того же* provider. Она допустима, если adapter наблюдает валидный handle,
   совместимое окружение и поддерживаемый `resume`. Если этих доказательств
   нет — **fresh session**, а не лишний blocker для STEP.

Валидация этого решения доступна в `plan_session_entry()` из
`.harness/tools/runtime_adapter_contract.py`. Это deterministic contract helper
для runtime-клиентов; он **не запускает Claude/Codex** и не подменяет
`execution_status.py` или command dispatcher. Команда/клиент передаёт уже
проверенный `canonical_reentry_safe` для interrupted recovery; новый
`PLAN → IMPLEMENT` вообще не нуждается в этом параметре.

| Что происходит | Решение adapter |
| --- | --- |
| PLAN в Claude → IMPLEMENT в Codex | `start`, никаких дополнительных действий |
| FIX в Codex → REVIEW в Claude | `start`, прежний review/verification contract сохраняется |
| Прерванный IMPLEMENT, переход Claude → Codex, canonical recovery допустим | `start` с контекстом Harness; не использовать Claude session handle |
| Тот же runtime, совместимая нативная сессия | `resume` |
| Та же модель, handle устарел или compatibility неизвестна | `start` с контекстом Harness |
| Необязательный MCP отключён | Не блокировать, пока конкретная команда его не требует |
| Недоступен именно обязательный инструмент | `blocked` с указанием capability |
| Нет доказательства безопасного continuation (intent/side effect) | `blocked` по canonical recovery, независимо от runtime |

Machine contract объявляет `crossRuntimeCommands=seamless`,
`nativeSessionReuse=best-effort` и `runtimeChangeInvalidatesIntent=false`.
Не добавлять provider ID/model/version/session handle в STEP/REQ/ADR/PLAN
fingerprints; native session metadata не переносится между providers.

## Capabilities

Contract v1 фиксирует следующие capability keys:

- `runtimeIdentity`;
- `authenticatedAccount`;
- `modelEffort`;
- `interactiveInput`;
- `streaming`;
- `resume`;
- `cancel`;
- `subagents`;
- `structuredOutput`;
- `toolMcp`;
- `sessionExecutionIds`.

Для каждой capability adapter обязан явно вернуть один из статусов:

- `native` — runtime предоставляет semantics напрямую;
- `synthesized` — adapter детерминированно собирает semantics поверх runtime primitives;
- `unsupported` — capability отсутствует.

Нельзя молча считать unsupported capability доступной. Consumer обязан проверить snapshot до использования.

Optional High-Rigor Arena/Interrogate использует существующие `subagents`, `modelEffort` и `sessionExecutionIds`; новый provider-specific capability key не вводится. Если runtime не может выделить дополнительный independent seat/model, high-rigor trace обязан зафиксировать `unsupported`/fallback и вернуть `DEGRADED`. Core Harness не хранит canonical model slugs для fan-out.

## Normalized events

Control plane/client работают с закрытым набором событий:

- `run.started`;
- `model.message.delta`;
- `model.message.completed`;
- `tool.started`;
- `tool.completed`;
- `input.required`;
- `auth.required`;
- `run.interrupted`;
- `run.completed`;
- `run.failed`.

Общий envelope:

```json
{
  "schemaVersion": 1,
  "type": "model.message.delta",
  "runtimeId": "codex",
  "sessionId": "runtime-session-id",
  "executionId": "harness-execution-id",
  "data": {},
  "providerMetadata": {}
}
```

`providerMetadata` optional и opaque. Core orchestration **не имеет права** принимать canonical transition/recovery решения на основании provider-only metadata.

Unknown normalized event type fail-closed. Если provider генерирует собственное событие, adapter должен либо отобразить его в один из canonical event types, либо оставить его вне provider-neutral stream.

## Codex mapping

Текущий canonical mapping:

### Account

Использовать Codex App Server:

```text
account/read
```

Не парсить human-oriented `codex login status` и не читать auth-файлы как public contract.

Adapter получает только данные, необходимые для UI/runtime identity. Secrets/tokens в Harness state, reports и client payload не сохраняются.

### Lifecycle

Основной transport — App Server/session lifecycle. Runtime-specific session id сохраняется только как runtime handle/operational metadata и не подменяет Harness `executionId`.

### Capabilities

Текущий tracked capability snapshot находится в `.harness/runtime-adapter-contract.json`. При изменениях Codex API/behavior snapshot обновляется отдельным Harness change с contract tests.

## Claude Code mapping

### Account

Machine-readable источник:

```bash
claude auth status
```

Adapter нормализует login/account/subscription/auth-method данные и не сохраняет credential material.

### Lifecycle

Start может быть реализован через managed CLI process. Resume/cancel/status должны использовать runtime-native semantics там, где они доступны; если конкретная версия runtime их не предоставляет, adapter обязан объявить capability `unsupported`, а не имитировать успешную поддержку.

### Synthesized fields

Если Claude Code не выдаёт отдельное canonical поле для Harness client contract, adapter может синтезировать normalized event/session metadata только из наблюдаемых runtime facts. Такие capabilities помечаются `synthesized`.

## Versioning

Machine contract version и adapter version различаются:

- `schemaVersion` — версия provider-neutral Harness contract;
- `adapterVersion` — версия mapping конкретного runtime.

Breaking change normalized methods/capabilities/events требует новой `schemaVersion`. Изменение mapping одного provider без изменения общей формы увеличивает только его adapter version.

Consumers должны fail-closed обрабатывать неизвестную schema.

## Security / privacy

Запрещено сохранять в contract/event/account state:

- access/refresh tokens;
- API keys;
- cookies;
- private keys;
- raw credential files;
- provider auth headers.

Harness/client может отображать безопасную account identity (например email/display name/org/subscription method), если runtime сам предоставляет её как status metadata.

## Contract tests

`.harness/tools/runtime-adapter-contract-self-test.py` автоматически входит в общий `run-self-tests.py`.

Он проверяет:

- полноту method/capability/event registries;
- Codex/Claude capability snapshots;
- explicit `unsupported`;
- normalized event validation;
- запрет неизвестных provider-only полей в canonical envelope.

Real Codex/Claude integration tests — отдельный слой. Они не должны заменять deterministic contract suite.

## Project context identity

Accepted architecture contract [`MULTI_PROJECT_CONTEXTS.md`](MULTI_PROJECT_CONTEXTS.md) требует, чтобы после реализации #188 runtime launch получал explicit `projectRoot` и `gitRoot` от Harness control plane. Adapter не должен определять project по process cwd самостоятельно.

До #188 machine Runtime Adapter Contract v1 не объявляет эти поля реализованными; breaking change общей request/envelope schema должен сопровождаться обычным `schemaVersion` bump и contract regressions.

## Связь с UI client

UI/client должен строить runtime bridge поверх этого контракта:

```text
Harness control plane
        │
        ├── Runtime Adapter Contract
        │       ├── Codex adapter
        │       └── Claude adapter
        │
        └── normalized events/capabilities/account
                │
                ▼
              Client
```

Client не должен дублировать CTS или самостоятельно интерпретировать provider-specific lifecycle в canonical Harness transitions.
