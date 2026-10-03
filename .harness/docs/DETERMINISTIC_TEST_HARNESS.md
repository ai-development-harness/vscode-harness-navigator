# Deterministic orchestration test harness

## Цель

Test harness проверяет control loop, runtime contract и recovery/fault boundaries без Claude/Codex process, API key, подписки или сети.

`ScriptedRuntime` — **test double Runtime Adapter Contract**, а не второй dispatcher. Он не содержит собственной CTS и не решает, какая Harness-команда должна выполняться следующей.

## Слои тестирования

### 1. Protocol / orchestration

Production CTS, execution resolver, Review Contract, adaptive repair и side-effect recovery тестируются существующими synthetic self-tests. `orchestration-harness-self-test.py` дополнительно проверяет canonical STEP repair path против реального `.harness/command-transitions.json`.

### 2. Runtime adapter conformance

`.harness/tools/runtime_adapter_conformance.py` запускает одну и ту же deterministic suite для всех adapters, объявленных в `.harness/runtime-adapter-contract.json`:

- capability completeness/support state;
- explicit unsupported behavior;
- normalized event envelope для каждого canonical event type;
- adapter version/runtime identity.

Codex/Claude process не запускаются.

### 3. Optional real-runtime integration

Real Codex/Claude lifecycle/auth/wire tests должны быть отдельными controlled jobs. Они не являются prerequisite deterministic Harness Integrity suite, потому что зависят от установленного runtime, account state и внешней среды.

Текущий core repository не хранит credentials и не запускает такие integration tests автоматически.

## Scripted scenario

Scenario — Python/JSON-compatible object:

~~~json
{
  "steps": [
    {
      "expect": "STEP REVIEW STEP-001",
      "result": "FAIL",
      "events": [
        {"type": "run.started"},
        {"type": "model.message.completed", "data": {"findings": ["F-001"]}},
        {"type": "run.completed"}
      ]
    },
    {
      "expect": "STEP FIX STEP-001",
      "expectResume": "STEP FIX STEP-001",
      "sideEffectIdentity": "fix:STEP-001:F-001",
      "faultOnce": "after_side_effect_before_observation",
      "result": "SUCCESS"
    }
  ]
}
~~~

Mismatch всегда показывает exact step index, expected interaction и фактический interaction.

## Runtime events

Все events проходят production `runtime_adapter_contract.normalize_event()`. Test double не имеет отдельной event schema.

Собранную sequence можно получить через `runtime.events()` и сравнить exact order/type/data.

## Fault injection points

Поддерживаются:

- `before_semantic_handoff`;
- `after_model_return_before_state_checkpoint`;
- `before_side_effect`;
- `after_side_effect_before_observation`;
- `after_observation_before_completion_checkpoint`;
- `during_report_write`;
- `during_execution_state_write`;
- `runtime_disconnect`;
- `input_required`.

Checkpoints привязаны к фактическому порядку logical step: `before_semantic_handoff` срабатывает до scenario events, `before_side_effect` — после model/event boundary, но до mutation, а post-side-effect checkpoints — только после пересечения mutation boundary. Self-test проверяет observable state на этих границах, а не только имя exception.

`faultOnce` срабатывает ровно один раз на scenario step. `resume()` повторяет тот же logical interaction после interruption.

ScriptedRuntime хранит exact ordered journal фактических пересечений side-effect boundary. Один logical scenario step может пересечь эту boundary максимум один раз:

- crash **до** side effect → resume применяет mutation один раз;
- crash **после** side effect → resume не применяет mutation повторно;
- уже emitted scenario events при resume не дублируются.

Self-test проверяет именно exact application count/order, а не множество identities, которое могло бы скрыть повторное выполнение одинаковой mutation.

## Capability injection

`ScriptedRuntime(..., capability_overrides={...})` позволяет пометить capability как `native`, `synthesized` или `unsupported`.

Если step объявляет `requiresCapability`, используется production `require_capability()`. Unsupported capability даёт точную deterministic ошибку на соответствующем scenario step.

## STEP RUN coverage

Deterministic suite проверяет canonical path:

~~~text
PLAN SUCCESS
  → IMPLEMENT SUCCESS
  → REVIEW FAIL
  → FIX SUCCESS
  → REVIEW PASS
~~~

Каждый переход сверяется с production CTS. Runtime scenario затем выдаёт exact normalized events/results в том же порядке.

Hard cap и adaptive early-stop остаются production execution semantics и покрываются `execution-self-test.py` + `repair-cycle-self-test.py`; scripted test harness не дублирует эти алгоритмы.

## CI

`orchestration-harness-self-test.py` соответствует auto-discovery pattern `*-self-test.py`, поэтому всегда запускается через:

~~~bash
python3 .harness/tools/run-self-tests.py
~~~

Никакой отдельный allowlist в CI не нужен.

## Граница ответственности

- CTS — command transitions;
- execution_status — resume/stopping state;
- side_effect_recovery — external mutation reconciliation;
- Runtime Adapter Contract — provider-neutral lifecycle/capabilities/events;
- ScriptedRuntime — deterministic test input/output/fault double;
- real runtime integration — отдельный optional boundary.
