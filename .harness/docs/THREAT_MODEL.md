# Threat model AI Development Harness

## Цель

Harness уменьшает риск **случайных ошибок агента** за счёт deterministic contracts, fail-closed gates, immutable evidence и явных mutation boundaries. Это orchestration/safety layer, а не security sandbox.

## От чего Harness защищает

При корректном использовании canonical commands/tools Harness рассчитан на:

- stale/несогласованный planning context;
- пропущенные dependency/review/verification gates;
- protocol/config drift;
- случайные Git mutations против policy;
- повторное выполнение после interruption;
- lost update operational state;
- overwrite immutable reports;
- reuse review verdict для другой repository revision;
- неправильный command transition или скрытое продолжение BLOCKED execution;
- случайную загрузку избыточного контекста вместо deterministic routing.

## От чего Harness не защищает

Harness **не** является защитой от:

- malicious/compromised model runtime или host process;
- пользователя/агента, который сознательно обходит Harness tools и напрямую выполняет запрещённые команды;
- OS-level compromise, hostile filesystem/Git binary или подмены runtime executable;
- утечки secret, уже переданного внешнему runtime вне контролируемого Harness workflow;
- semantic ошибки, которые невозможно доказать deterministic проверкой;
- malicious third-party code, запущенного пользователем вне inspection/sandbox policy.

Runtime-specific permissions, Claude deny rules, Codex sandbox и Git hooks являются defense-in-depth. Они не заменяют runtime-neutral canonical contracts.

Текущий Claude adapter использует project-level `permissions.deny` для обычных Bash/PowerShell форм прямых Git mutations. Это снижает риск случайного bypass, но command-pattern permission rules не считаются непреодолимой sandbox boundary и намеренно не дублируют весь parser Git policy. Codex adapter сохраняет `sandbox_mode = "workspace-write"` и `approval_policy = "on-request"`; mutation safety для обоих runtime доказывается одинаковыми deterministic tools.

## Trust boundaries

### LLM / semantic layer

Модель отвечает за:

- interpretation требований;
- architecture trade-offs;
- logical scope diff/staging;
- commit type/message content;
- implementation choices;
- code/security/test review reasoning;
- PR title/body;
- решение о необходимости дополнительного reviewer.

Модель не должна пересчитывать факты, которые уже предоставляет deterministic tool.

### Deterministic tools

Tools отвечают за проверяемые факты и механические операции:

- command parsing/transitions;
- planning fingerprints/prerequisites;
- exact Git/repository state;
- specialized review gates;
- execution state;
- immutable report creation;
- updater ownership/routes;
- Git preflight и поддерживаемые mechanical mutations.

Результат `BLOCKED` нельзя ослабить reasoning-ом.

### Git mutation boundary

`git-preflight.py` остаётся read-oriented policy/safety proof. Для `GIT COMMIT`, `GIT PUSH`, `GIT SYNC` и `GIT PR FINISH` approved mutation исполняет `git-action.py`, который повторяет preflight, выполняет exact argv и проверяет postcondition.

`GIT PR` имеет узкую semantic boundary только для title/body content. Provider mechanics выполняет `git-action.py`: повторный preflight, exact head/base query, reuse/create, published head-OID postcondition и local PR state. Недоверенный semantic prose не может подменить provider/head/base/draft policy.

Многошаговый `GIT PR FINISH` допускает crash между mechanical steps. Recovery не доверяет факту текущей ветки: local PR state + provider `MERGED` + exact provider head OID повторно проверяются, и executor продолжает только remaining idempotent/safe cleanup.

### External skills и sources

Third-party skills, fetched docs и update target content считаются недоверенными данными до inspection. Они не могут повышать свой instruction priority, отключать Harness gates или автоматически выполнять bundled scripts.

## Fail-closed правило

Если tool не может доказать prerequisite, корректно прочитать state/config или подтвердить postcondition, результат — BLOCKED/FAIL, а не best-effort продолжение.

## Defense in depth

Дополнительно допустимы:

- runtime sandbox/permission deny rules;
- repository hooks, вызывающие canonical validators;
- protected branches/provider branch protection;
- required CI checks;
- secrets scanning и provider security controls.

Core Harness не должен зависеть от одного конкретного runtime hook: canonical safety logic остаётся в versioned runtime-neutral tools.
