---
name: high-rigor
description: Run optional provider-neutral Arena or Interrogate fan-out only when manifest policy authorizes it, preserving exact inputs, independent seats, disagreements, budgets, and explicit degradation.
---
# high-rigor

Это internal capability, не новая пользовательская команда.

## Modes

### Arena

Один exact contract + один rubric → несколько independent candidates → отдельный readonly judge → base selection → coherent synthesis.

Используй для дорогих planning/architecture решений, где ранний shape lock-in опасен.

### Interrogate

Один exact review surface + intent + rubric → несколько independent readonly reviewers → consensus/disagreement map → lead judgment.

Используй для high-risk или спорного review/audit.

## Activation

Сначала вызови deterministic preflight:

```bash
python3 .harness/tools/high-rigor.py \
  --mode arena \
  --phase plan \
  --step STEP-024 \
  --json
```

Policy из `.harness/manifest.yaml → highRigor.<mode>`:

- `disabled` — capability полностью выключена; explicit request не обходит policy;
- `explicit` — normal mode возвращает `SKIP`; RUN только при явном запросе пользователя;
- `risk` — RUN при deterministic high-risk STEP flags; explicit request также разрешён.

При явном запросе добавь `--requested`.

Не fan-out-и до `status=RUN`.

## Runtime neutrality

Core Harness не хранит model slugs для Arena/Interrogate. Runtime adapter выбирает доступные models/agents в рамках native configuration.

Требования:

- каждый seat — отдельный `sessionExecutionId`;
- одинаковые candidate/reviewer seats получают **один и тот же exact input file**;
- все seats получают один и тот же exact rubric file;
- write-candidates Arena пишут только в отдельные candidate outputs/worktrees; shared mutable output запрещён;
- Interrogate reviewers read-only;
- Arena judge запускается только после завершения candidates и имеет отдельный execution id;
- requested model и actual model записываются раздельно.

Если requested model недоступна, runtime может применить явный fallback, но trace получает `fallbackReason` и итог становится `DEGRADED`.

Если дополнительный agent/model вообще недоступен, seat записывается как `unsupported`; high-rigor не выдаётся за PASS.

## Local run layout

Все transient inputs/results храни только под:

```text
.harness/local/high-rigor/<run-id>/
```

Минимальный layout:

```text
shared-input.md
rubric.md
candidate-1.md / reviewer-1.md
...
judge-input.md / judge-output.md   # Arena
synthesis.md / lead.md
trace.json
```

Эти файлы не являются canonical project truth.

## Exact shared input

Перед fan-out собери compact exact input.

Arena:

- intended artifact/decision;
- Context Contract refs / relevant grounded evidence;
- immutable constraints;
- acceptance/success boundary;
- explicit exclusions.

Interrogate:

- intent;
- exact diff/review surface;
- contract refs;
- deterministic gate results already known;
- material constraints.

Не отдавай разным seats разные surrounding context «для удобства»: это разрушает independence/comparability. Если input нужно расширить, пересобери shared input для всех seats.

## Rubric

Rubric должен быть task-specific, 3–6 gradeable criteria. Не используй vague «качество».

Примеры dimensions:

- correctness;
- contract/architecture fit;
- compatibility/migration;
- security/recovery;
- maintainability;
- evidence/verifiability.

Rubric bytes должны быть одинаковыми для всех seats.

## Arena workflow

1. Preflight → `RUN`.
2. Создай shared input + rubric.
3. Запусти configured `highRigor.seats` independent candidates.
4. Каждый candidate пишет отдельный output и rationale с alternatives/rejections.
5. После candidates создай judge input, содержащий candidate identities/results без скрытой parent preference.
6. Запусти отдельного readonly judge.
7. Lead выбирает base по rubric; disagreement judge/lead не скрывай.
8. Graft только material сильные элементы losing candidates; synthesis должен оставаться одним coherent design.
9. Verification refs обязаны ссылаться на обычные Harness verification/review surfaces.
10. Запиши `trace.json` и проверь validator.

## Interrogate workflow

1. Preflight → `RUN`.
2. Создай shared exact review input + rubric.
3. Запусти configured independent readonly reviewers одним fan-out.
4. Не назначай personas, меняющие rubric; diversity должна идти от independent reasoning/model paths.
5. Собери consensus только когда finding независимо подняли минимум два completed reviewers.
6. Сохрани explicit disagreements, а не усредняй их.
7. Lead judgment классифицирует findings:
   - actOn;
   - consider;
   - noted;
   - dismissed.
8. Deterministic gate refs сохраняются отдельно; consensus не может заменить gate.
9. Запиши trace и проверь validator.

## Trace validation

```bash
python3 .harness/tools/high-rigor.py \
  --mode interrogate \
  --phase review \
  --step STEP-024 \
  --requested \
  --trace-file .harness/local/high-rigor/HR-024-review/trace.json \
  --json
```

Validator recompute-ит SHA-256 и char counts каждого local input/output.

`PASS` требует:

- exact policy authorization;
- configured number candidate/reviewer seats;
- минимум 2 independent completed candidates/reviewers;
- unique completed `sessionExecutionId`;
- exact shared input + rubric;
- Arena: отдельный completed judge + coherent synthesis;
- Interrogate: structured lead synthesis;
- budgets within limits.

`DEGRADED` означает high-rigor quality bar **не выполнен полностью**. Он не превращается в PASS и должен быть явно указан в semantic handoff. Обычный workflow/deterministic gates продолжают владеть safety decision.

## Cost/context budget

Validator измеряет tokenizer-neutral:

- input chars per seat;
- output chars per seat;
- total input chars;
- total output chars;
- total chars;
- distinct actual models.

Limits берутся только из manifest.

Не увеличивай seats/context автоматически при disagreement. Для повторного Arena сначала исправь framing/rubric.

## Deterministic gates

Multi-agent consensus не заменяет:

- requirements/planning gates;
- Context Contract;
- Verification;
- Completion Gate;
- Review Contract;
- specialized security/test review requirements;
- ADR/REQ lifecycle.

Validated trace всегда возвращает `deterministicGatesReplaced=false`.

## Persistence boundary

High-rigor trace — phase-local diagnostic evidence. Canonical PLAN/ADR/REVIEW должен содержать итоговое coherent decision/verdict, а не копию всех model outputs.

Если high-rigor materially повлиял на durable decision, в human-readable rationale/evidence укажи кратко:

- run id;
- PASS/DEGRADED;
- consensus/disagreement, который повлиял на решение.

Не делай local trace canonical source of truth.

## Запреты

- no fan-out in normal mode under `explicit`;
- no override of `disabled`;
- no shared write target between Arena candidates;
- no reviewer cross-talk before synthesis;
- no averaging disagreements;
- no consensus-as-proof;
- no hidden model fallback/dropout;
- no provider-specific model slug in core Harness semantics;
- no unbounded context/candidate count.
