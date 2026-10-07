# Evidence Gate

Evidence Gate не позволяет planner/reviewer/implementer превратить правдоподобную, но не проверенную гипотезу в plan requirement, defect, regression test, hardening или production FIX.

Главное правило:

> Новая agent-derived идея о failure/security/edge scenario сначала является hypothesis. Она может повлиять на plan, стать material finding или породить test/FIX только после проверки необходимых предпосылок и project-specific evidence.

## Зачем это нужно

LLM легко переносит общие знания о framework/runtime на конкретный проект без проверки фактической topology.

Например reviewer знает, что Vite DEV server умеет раздавать файлы, и делает вывод:

```text
"Vite может отдать private.pem по прямой ссылке"
```

Но в реальном проекте может быть:

- `private.pem` существует только внутри backend container;
- frontend container не имеет volume/mount с этим файлом;
- файл не находится в frontend root/public;
- frontend process физически не может его прочитать;
- `GET /private.pem` возвращает `404`.

В этом случае проблема не существует. Добавлять security tests, Vite hardening и новые отчёты нельзя.

## Поток Evidence Gate

```text
new inferred risk
      |
      v
  HYPOTHESIS
      |
      v
identify necessary preconditions
      |
      v
check actual repository/runtime state
      |
      v
run cheapest decisive falsification when practical
      |
   +--+--+
   |     |
invalid confirmed
   |     |
   v     v
 discard OBSERVED
          |
          v
 durable finding
          |
          v
 regression test / FIX
```

Запрещены прямые переходы:

```text
HYPOTHESIS -> FIX
HYPOTHESIS -> regression tests -> hardening
```

## Evidence kinds

Review Contract v3 использует `evidenceBasis.kind`.

### `contract`

Нарушение прямо следует из явного REQ/ADR/STEP/PRN и подтверждено фактическим состоянием.

Пример: REQ запрещает HTTP-доступ к private key, а существующий endpoint действительно возвращает ключ.

### `reproduced`

Дефект уже воспроизведён конкретным запросом, command, test или function call.

### `inferred`

Reviewer сам вывел потенциальный scenario. Для такого finding обязательны:

- необходимые `preconditions[]`;
- проверка этих предпосылок по реальному project state;
- конкретный `verification.method`;
- фактический `verification.result`;
- `verification.outcome: confirmed`.

`invalidated` или `unverified` hypothesis не является material finding и не сохраняется в durable findings.

## Cheapest falsification first

До написания нового regression test reviewer должен предпочесть самый дешёвый решающий эксперимент, если он практически доступен.

Типичные примеры:

- один HTTP request;
- проверка Docker volume/mount;
- чтение route registration;
- inspection реального generated config;
- вызов подозреваемой функции с минимальным input;
- запуск уже существующего узкого test/reproducer.

Цель — не собрать аргументы в пользу собственной идеи, а сначала попытаться её опровергнуть.

## Security reachability

Для нового security scenario общей возможности framework недостаточно.

```text
Framework X can do Y
```

не означает:

```text
This project exposes Y
```

Reviewer должен подтвердить project-specific path:

```text
entry point
    |
trust boundary
    |
reachable operation
    |
asset / security effect
```

Если обязательное звено отсутствует, hypothesis invalidated.

### Пример с PEM

```text
Hypothesis:
Vite DEV может отдать private.pem.

Necessary preconditions:
1. Frontend process может прочитать private.pem.
2. HTTP/static routing может адресовать этот файл.

Checks:
- PEM найден только в backend container.
- Shared mount отсутствует.
- PEM отсутствует в frontend root/public.
- GET /private.pem -> 404.

Conclusion:
Hypothesis invalidated.

Actions:
- no durable finding;
- no regression test;
- no production FIX;
- при необходимости одна короткая заметка в rationale.
```

## Planning / implementation boundary

Evidence Gate применяется **до** появления speculative work в Ready plan, а не только после IMPLEMENT на REVIEW:

- architecture completeness выявляет применимые dimensions, но не требует защиту от каждого теоретически возможного scenario;
- новый scenario без explicit contract/reproducer сначала проверяется как hypothesis;
- unverified hypothesis может породить только bounded proof/falsification obligation — concrete check в Verification/plan, который решает вопрос без product hardening;
- до confirmation hypothesis нельзя превращать в production mutation, regression/security test, hardening, ADR/OQ/prerequisite или planning blocker;
- planning reviewer обязан отклонять speculative production work в draft plan и сам не может BLOCK-ировать PLAN новой неподтверждённой hypothesis;
- если proof obligation дошёл до IMPLEMENT, implementer выполняет только этот check: invalidated scenario отбрасывается; confirmed scenario, требующий новой production mutation, возвращается в fresh `STEP PLAN`.

Это закрывает обходной путь:

```text
HYPOTHESIS -> PLAN -> production tests/hardening -> IMPLEMENT
```

Допустимый planning path выглядит как `HYPOTHESIS → bounded falsification check → invalidated | confirmed`. Только confirmed scenario может породить production work. Review Contract v3 аналогично закрывает:

```text
HYPOTHESIS -> finding -> FIX
```

## Test provenance

Новый regression/security test, появившийся из PLAN/IMPLEMENT/REVIEW/FIX, должен иметь хотя бы один реальный источник:

- explicit REQ/ADR/STEP invariant;
- reproduced defect;
- confirmed Review Contract v3 finding.

Подтверждение одного defect не разрешает автоматически добавлять unrelated exotic scenarios: другие OS, symlink tricks, race conditions, deployment topology и подобное требуют собственного contract/evidence.

## Durable artifacts

Hypothesis — рабочее рассуждение reviewer, а не repository evidence.

Поэтому invalidated hypothesis:

- не создаёт отдельный report;
- не становится `F-NNN`;
- не запускает `FIX ↔ REVIEW`;
- не требует production mutation.

Если факт проверки полезен для человека, reviewer может кратко записать его в rationale текущего review.

## Review Contract v3

Каждый новый material finding содержит:

```json
{
  "evidenceBasis": {
    "kind": "contract|reproduced|inferred",
    "source": "конкретный источник гипотезы/контракта/reproducer",
    "preconditions": ["проверенная предпосылка"],
    "verification": {
      "method": "решающий check",
      "result": "фактический результат",
      "outcome": "confirmed"
    }
  }
}
```

Canonical writer fail-closed отвергает v3 finding без evidence basis, без evidence или с outcome, отличным от `confirmed`.

Historical Review Contract v1/v2 reports остаются immutable history. Однако новый `STEP FIX` требует свежий evidence-gated v3 review, чтобы старый report не обходил Evidence Gate.
