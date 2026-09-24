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

Текущий Claude adapter использует project-level `permissions.deny` для обычных Bash/PowerShell форм прямых Git mutations: commit/push/merge/rebase, перезапись и удаление refs (`update-ref`, `branch -f/-M/-D`, `switch -C`, `checkout -B`, удаление/перезапись tags), потеря работы (`reset --hard`, `clean`, `stash drop/clear`, `filter-branch`), глобальные формы `git -C`/`git -c` и `gh pr merge`/`gh api`. Это снижает риск случайного bypass, но command-pattern permission rules не считаются непреодолимой sandbox boundary и намеренно не дублируют весь parser Git policy: shell-алиасы, скрипты и команды `## Verification` (subprocess) под deny rules не попадают. Codex adapter сохраняет `sandbox_mode = "workspace-write"` и `approval_policy = "on-request"`; mutation safety для обоих runtime доказывается одинаковыми deterministic tools.

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

Provider-вызовы `gh` всегда получают явный `--repo`, выведенный из raw URL `push.remote`; если repository из URL не выводится, PR action BLOCKED, а не полагается на выбор default repository самим `gh` (fork-сценарии).

Многошаговый `GIT PR FINISH` допускает crash между mechanical steps. Recovery не доверяет факту текущей ветки: local PR state + provider `MERGED` + exact provider head OID повторно проверяются, и executor продолжает только remaining idempotent/safe cleanup.

### External skills и sources

Third-party skills, fetched docs и update target content считаются недоверенными данными до inspection. Они не могут повышать свой instruction priority, отключать Harness gates или автоматически выполнять bundled scripts.

### Harness update source

Исключение из правила выше — сам Harness. Configured `source.repository` и его immutable release tags являются **доверенным поставщиком Harness-кода**, как любая устанавливаемая dependency: после `HARNESS UPDATE APPLY` следующая Harness-команда в любом случае исполняет установленные `.harness/tools/**`. Поэтому updater не делает вид, что target code не исполняется, а ограничивает и делает обратимым момент его первого запуска ([#98](https://github.com/ai-development-harness/ai-development-harness-template/issues/98)):

- содержимое hop читается только из tags; OID текущего release закреплён в project lock (`SOURCE_TAG_MOVED`);
- target validator запускается отдельным процессом только внутри журналированной транзакции hop, после backup всех затрагиваемых paths;
- failure или прерывание процесса откатывают hop byte-for-byte, включая lock, report и schema local state;
- bundled scripts/install/bootstrap target release updater не запускает; commit/push/PR после update выполняются только через обычный Git gate после инспекции diff.

Компрометация upstream repository/tag остаётся вне границы Harness и закрывается provider controls (protected tags, branch protection, review release PR).

### Durable artifacts и provenance

Review/audit/release reports и `## Evidence` пишут deterministic writers, а validators проверяют их структуру, связь с revision/gate basis и время создания ([#114](https://github.com/ai-development-harness/ai-development-harness-template/issues/114)):

- verdict принимается только внутри active `STEP REVIEW` со stamped expectation;
- writer записывает path, sha256, revision и gate basis report-а в context этого execution (локальный след происхождения);
- report с `created_at` в будущем (сверх допуска на clock skew) невалиден и не может занять место latest;
- generated Verification evidence засчитывается только со `Status: PASS`.

Граница: агент или пользователь с shell-доступом к рабочему дереву технически может вручную создать синтаксически валидный artifact, включая `specialized_reviews` с произвольным evidence. Harness gates защищают от случайного и небрежного обхода и от несогласованного state, но не доказывают, кто написал файл. Независимость review и provenance durable history обеспечиваются снаружи — review Pull Request, CODEOWNERS и branch protection.

### Legacy completion baseline

`legacy_completed_steps` в migration report — одноразовый compatibility proof для истории до контракта immutable review. Он создаётся только migration flow для STEP, мигрированных из legacy формата, и виден в diff того же PR. Harness не защищает от сознательно подделанного migration report (как и от подделанного review report): защитой служит review PR. Невалидный report отвергается целиком, partial allowlist не выдаётся.

### CI и secret hygiene

CI `Harness Integrity` запускает validator из дерева самого PR: PR, ослабляющий validator/policy/workflow, проходит собственную проверку. Поэтому CI помечает изменения trust boundary (`.harness/tools/**`, policy TOML, `.claude/settings.json`, `.codex/**`, `.github/**`) warning-аннотациями, а решающей защитой остаётся review. Проект задаёт владельцев этих путей своим `CODEOWNERS` и включает в branch protection «Require review from Code Owners»; шаблон не поставляет `CODEOWNERS`, потому что владельцы у каждого проекта свои.

Validator блокирует tracked/staged secret material: forbidden globs (basename-паттерны действуют на любой глубине), PEM/PGP private keys любого типа и токены с однозначным форматом (AWS, GitHub, GitLab, Slack) — в том числе внутри binary файлов. Это baseline, а не замена provider secret scanning.

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
