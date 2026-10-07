# Core Reasoning Principles

Core Reasoning Principle (CRP) — короткое Harness-owned правило о том, **как semantic agent должен рассуждать или организовывать работу**.

CRP не является пользовательской командой и не является project engineering policy.

## CRP и Project PRN — разные сущности

| | Core Reasoning Principle | Project Principle |
|---|---|---|
| Namespace | `CRP-NNN` | `PRN-NNN` |
| Owner | Harness | конкретный project |
| Назначение | reasoning / execution posture | engineering invariant проекта |
| Storage | `.agents/skills/core-reasoning-principles/leaves/` | configured `sources.principles` |
| Traceability | не участвует | REQ/ADR/project traceability |
| Planning freshness | не stale-ит Ready plan | active blocking PRN входит в planning basis |
| Applicability | deterministic CRP selector | semantic applicability Project Principle |
| Lifecycle | Harness update | project governance |

Нельзя ссылаться на CRP как на project requirement/ADR/principle. Нельзя помещать `PRN-NNN` в `coreReasoningPrinciples`.

## Почему leaves, а не глобальный prompt

Полный catalog не загружается в каждую semantic phase. Deterministic selector читает Harness-owned metadata и возвращает только applicable leaf refs:

```json
{
  "coreReasoningPrinciples": [
    {
      "namespace": "CRP",
      "id": "CRP-003",
      "slug": "prove-the-real-artifact",
      "path": ".agents/skills/core-reasoning-principles/leaves/CRP-003-prove-the-real-artifact.md",
      "triggeredBy": ["review-phase"],
      "chars": 1234
    }
  ]
}
```

Agent читает только перечисленные `path`. Catalog scan моделью запрещён.

Selection выполняется внутри Context Contract до runtime adapter, поэтому одинаков для Codex/Claude.

## Первая итерация catalog

| ID | Principle | Deterministic trigger |
|---|---|---|
| `CRP-001` | Encode lessons in structure | STEP type `bugfix|hardening` |
| `CRP-002` | Guard the context window | resolved context ≥6 artifacts или ≥20 sections |
| `CRP-003` | Prove the real artifact | reviewer phase |
| `CRP-004` | Sequence verifiable units | ≥2 execution groups, ≥2 dependencies, data-migration или release-critical |
| `CRP-005` | Separate shared mutable state | `risk_flags: concurrency` |
| `CRP-006` | Attack repeated assumptions | STEP type `bugfix` |
| `CRP-007` | Subtract before adding | STEP type `refactor` |
| `CRP-008` | Minimize reader/context load | refactor или `risk_flags: architecture` |

Trigger — только coarse deterministic applicability. Сам leaf описывает semantic применение и ограничения.

## Leaf contract

Каждый leaf имеет frontmatter:

```yaml
schema: 1
namespace: CRP
id: CRP-005
slug: separate-shared-mutable-state
status: active
roles:
  - planner
  - implementer
  - reviewer
triggers:
  - concurrency-risk
```

И обязательные sections:

- `Trigger / applicability`;
- `Rationale`;
- `Actionable pattern`.

Catalog ограничен 6–10 leaves в первой версии. Один leaf не должен превышать 4 000 Unicode chars.

## Deterministic selector

Engine:

```text
.harness/tools/core_reasoning_principles.py
```

Он:

1. валидирует весь Harness-owned catalog;
2. получает уже parsed STEP и фактический размер resolved Context Contract;
3. строит closed-set deterministic signals;
4. выбирает leaves по `roles ∩ triggers`;
5. возвращает только refs/metadata selected leaves.

Selector не интерпретирует prose Goal/Context/Implementation plan keywords. Если applicability нельзя доказать из machine facts, leaf не добавляется автоматически.

## Не дублировать deterministic policy

CRP применяется только там, где остаётся judgement.

Если правило можно надёжно enforce-ить кодом, предпочтительный путь:

```text
recurring semantic correction
        ↓
можно доказать механически?
        ├── yes → validator / gate / schema / helper
        └── no  → CRP leaf / semantic instruction
```

Например `CRP-003 Prove the real artifact` не заменяет Verification runner, Completion Gate или Review Gate. Он направляет reviewer к прямому evidence только там, где факт ещё требует semantic judgement.

## Context metrics

Context Contract дополнительно публикует:

- `corePrincipleCount`;
- `corePrincipleChars`.

Это отдельная pull-based semantic cost, не always-on bootstrap budget.

Regression требует, чтобы обычная небольшая phase не получала весь catalog. Пример:

```text
small PLAN      → 0 CRP
small REVIEW    → CRP-003
context-heavy   → CRP-002 (+ role-specific leaves)
full catalog    → никогда автоматически
```

## Runtime neutrality

CRP selector не принимает provider/runtime. Для одного `STEP + role + repository revision` Codex и Claude получают идентичные `coreReasoningPrinciples`.

Runtime adapter только физически читает перечисленные leaf files.

## Provenance

Catalog адаптирован из инженерных principle-skills pstack, но Harness меняет delivery model: вместо глобального principle set — deterministic progressive disclosure и отдельный CRP namespace.

См. `.agents/skills/core-reasoning-principles/UPSTREAM.md`.
