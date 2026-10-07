# AI Development Harness — документация

Эта папка описывает **сам Harness**, а не конкретный продукт. После `PROJECT INIT` продуктовая документация остаётся в repository-level `docs/` и `planning/`, а документация ядра Harness — здесь.

## С чего начать

- [`GETTING_STARTED.md`](GETTING_STARTED.md) — создание проекта из template и `PROJECT INIT`.
- [`DEPENDENCIES.md`](DEPENDENCIES.md) — обязательные core dependencies, runtime adapters и optional GitHub PR capability.
- [`DOCUMENT_MODEL.md`](DOCUMENT_MODEL.md) — какие артефакты существуют, что является источником истины и как связаны REQ / ADR / STEP / PLAN / STATUS / Evidence / Review.
- [`GLOSSARY.md`](GLOSSARY.md) — полный словарь терминов и сокращений Harness.
- [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md) — файловая архитектура и разделение protocol / knowledge / implementation.
- [`COMMANDS.md`](COMMANDS.md) — пользовательский командный интерфейс.
- [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md) — namespaces, targets и chain operator `>`.
- [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md) — полная transition matrix, validation order и runtime conditions.
- [`EXECUTION_STATUS.md`](EXECUTION_STATUS.md) — единый local execution-status.json, resume semantics и independent single/chain/orchestration executions.
- [`LANGUAGE_POLICY.md`](LANGUAGE_POLICY.md) — единая настройка языка для docs/commits/comments/tests/fixtures/templates.
- [`TOKEN_ECONOMY.md`](TOKEN_ECONOMY.md) — правила экономии вычислений модели и постоянного контекста.
- [`REASONING_BOUNDARIES.md`](REASONING_BOUNDARIES.md) — автоматически поддерживаемая таблица и диаграммы: где нужна модель, а где достаточно скриптов.
- [`THREAT_MODEL.md`](THREAT_MODEL.md) — границы защиты Harness, trust boundaries и defense-in-depth.
- [`QUICK_CHANGES.md`](QUICK_CHANGES.md) — когда мелкая правка не требует STEP.
- [`UPDATES.md`](UPDATES.md) — безопасное обновление Harness в уже идущем проекте.
- [`EXECUTION_PROTOCOL.md`](EXECUTION_PROTOCOL.md) — формальная семантика state transitions и выполнения STEP.
- [`STATE_AUTHORITY.md`](STATE_AUTHORITY.md) — ownership canonical control-plane state: semantic proposal → deterministic validation/commit, execution-bound completion и stale-result protection.
- [`INTENT_RESUME.md`](INTENT_RESUME.md) — versioned Intent Basis, stale-intent guards и fail-closed semantic resume.
- [`PROGRESS_GUARD.md`](PROGRESS_GUARD.md) — bounded deterministic detection stagnation/cycles/drift для long-running semantic executions.
- [`RUNTIME_ADAPTER_CONTRACT.md`](RUNTIME_ADAPTER_CONTRACT.md) — provider-neutral lifecycle, capabilities, account identity и normalized events для Codex/Claude.
- [`SIDE_EFFECT_RECOVERY.md`](SIDE_EFFECT_RECOVERY.md) — bounded checkpoints и reconciliation mutation-команд.
- [`ADAPTIVE_REPAIR_STOPPING.md`](ADAPTIVE_REPAIR_STOPPING.md) — deterministic early-stop FIX ↔ REVIEW.
- [`DETERMINISTIC_TEST_HARNESS.md`](DETERMINISTIC_TEST_HARNESS.md) — scripted runtime, adapter conformance и fault injection для orchestration tests.
- [`PROJECT_STATE.md`](PROJECT_STATE.md) — read-only JSON graph состояния проекта для UI, VSCode Navigator и других клиентов.
- [`CONTEXT_CONTRACTS.md`](CONTEXT_CONTRACTS.md) — role-specific progressive disclosure: required sections, explicit expansion, runtime-neutral resolver и token-economy metrics.
- [`CODEBASE_GROUNDING.md`](CODEBASE_GROUNDING.md) — bounded read-only mental model для architecture-sensitive PLAN/AUDIT: flow, ownership, boundaries и validated evidence paths.
- [`SEMANTIC_BLAST_RADIUS.md`](SEMANTIC_BLAST_RADIUS.md) — conditional implicit-impact analysis поверх deterministic dependency impact с executable proof для critical safety assumptions.
- [`DECISION_ARCHAEOLOGY.md`](DECISION_ARCHAEOLOGY.md) — bounded reconstruction historical rationale: documented evidence, inference, conflicts, gaps и stale-ADR diagnostics.
- [`CORE_REASONING_PRINCIPLES.md`](CORE_REASONING_PRINCIPLES.md) — Harness-owned `CRP-NNN` leaves, deterministic applicability и progressive disclosure отдельно от project `PRN-NNN`.
- [`STRUCTURAL_ENFORCEMENT.md`](STRUCTURAL_ENFORCEMENT.md) — recurring correction aggregation, enforcement ladder, regression-fixture contract и architecture safety routing.
- [`HIGH_RIGOR.md`](HIGH_RIGOR.md) — optional Arena/Interrogate fan-out, activation policy, exact input/result trace, budgets и DEGRADED semantics.
- [`BENCHMARK_METHODOLOGY.md`](BENCHMARK_METHODOLOGY.md) — optional performance methodology, reproducible evidence contract, repeated-run statistics и deterministic PASS/INCONCLUSIVE gate.
- [`PR_MAINTENANCE.md`](PR_MAINTENANCE.md) — read-only provider snapshot, CI/review feedback triage, reviewability guidance и bounded PR babysit без mutation authority.
- [`PROJECT_VERIFICATION.md`](PROJECT_VERIFICATION.md) — project-owned Verification Driver, feature map, qualification, drift detection и `product: FEATURE-*` evidence через реальную пользовательскую поверхность.
- [`COMPLETION_GATE.md`](COMPLETION_GATE.md) — отдельная convergence-проверка полноты Acceptance после REVIEW PASS, routing FIX/BLOCKED и crash-safe completion recovery.
- [`EXECUTION_GROUPS.md`](EXECUTION_GROUPS.md) — optional machine-readable dependency groups внутри Implementation plan, mutation conflict boundaries и sequential scheduling semantics.
- [`EVOLUTION_SEMANTICS.md`](EVOLUTION_SEMANTICS.md) — canonical owner изменений REQ/ADR/OQ/STEP, flow-forward/flow-back, deterministic impact propagation и re-plan semantics.
- [`MULTI_PROJECT_CONTEXTS.md`](MULTI_PROJECT_CONTEXTS.md) — accepted architecture contract для разделения Harness project root и Git worktree root; реализация отслеживается в #188.

## Агенты и автоматизация

- [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md) — runtime-neutral роли субагентов, модели, reasoning effort, локальные runtime overrides и стратегии экономии.
- [`CLAUDE_CODE.md`](CLAUDE_CODE.md) — project settings, subagents и ownership Claude Code adapter.
- [`WORKFLOW.md`](WORKFLOW.md) — устройство orchestration и durable handoff между стадиями.
- [`REPORTING.md`](REPORTING.md) — требования к итоговым отчётам.
- [`SKILL_MANAGEMENT.md`](SKILL_MANAGEMENT.md) — поиск, inspection, установка и создание skills.
- [`SKILL_PROVENANCE.md`](SKILL_PROVENANCE.md) — deterministic provenance, intentional fork detection и read-only update planning для third-party skills.
- [`GITHUB_TEMPLATES.md`](GITHUB_TEMPLATES.md) — регенерация Issue Forms и PR template по текущему стеку проекта.

## Repository operations

- [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) — `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT SYNC`.
- [`CI.md`](CI.md) — Harness Integrity CI и граница между Harness CI и product CI.
- [`VALIDATORS.md`](VALIDATORS.md) — единый справочник Python-валидаторов, validation gates, CLI-ключей, exit codes и примеров запуска.
- [`RELEASE_QUALIFICATION.md`](RELEASE_QUALIFICATION.md) — exact-SHA release qualification, platform/runtime lanes и граница с обычным Harness Integrity.
- [`STRESS_SUITE.md`](STRESS_SUITE.md) — canonical manifest/runner bounded concurrency/process stress scenarios.
- [`INITIALIZED_UPGRADE_QUALIFICATION.md`](INITIALIZED_UPGRADE_QUALIFICATION.md) — previous stable → exact candidate на disposable initialized downstream state с preservation/no-op proof.
- [`MAINTENANCE.md`](MAINTENANCE.md) — как изменять Harness, не смешивая protocol layer с product knowledge.
- [`UPDATES.md`](UPDATES.md) — release/lock/ownership/legacy-adoption lifecycle self-update.

## Project-specific документация

После `PROJECT INIT` основными продуктовыми источниками становятся:

- [`docs/PROJECT.md`](../../docs/PROJECT.md) — что это за проект и его границы;
- [`docs/requirements/`](../../docs/requirements/) — canonical `REQ-NNN-*.md`;
- [`docs/requirements/SPEC.md`](../../docs/requirements/SPEC.md) — index projection требований;
- [`docs/requirements/STATUS.md`](../../docs/requirements/STATUS.md) — lifecycle projection REQ;
- [`docs/architecture.md`](../../docs/architecture.md) — текущий архитектурный baseline;
- [`docs/adr/`](../../docs/adr/) — история устойчивых архитектурных решений;
- [`planning/PLAN.md`](../../planning/PLAN.md) — roadmap projection;
- [`planning/tasks/`](../../planning/tasks/) — канонические task contracts;
- [`docs/GLOSSARY.md`](../../docs/GLOSSARY.md) — **продуктовый** глоссарий конкретного проекта.

Не смешивай продуктовый глоссарий с [`GLOSSARY.md`](GLOSSARY.md): последний определяет язык и сущности самого Harness.
