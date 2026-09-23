# Экономия вычислений модели

## Цель

AI Development Harness проектируется так, чтобы модель тратила вычислительные ресурсы только на решения, которые действительно требуют смысловой оценки. Проверяемая, вычислимая и механическая работа должна выполняться скриптами.

> **Модель получает решения и результаты, а не внутреннее устройство реализации и конфигурации.**

Это архитектурное требование, а не рекомендация по стилю. Текущее распределение ответственности по всем каноническим командам автоматически публикуется в [`REASONING_BOUNDARIES.md`](REASONING_BOUNDARIES.md), а машиночитаемая проекция хранится в `.harness/reasoning-boundaries.json`.

## Граница ответственности

В deterministic слой по умолчанию относятся:

- parsing и structural validation;
- hashes/fingerprints и dependency state;
- Git/repository state и policy checks;
- command routing и execution state;
- report naming/writing и другие механические mutations;
- чтение machine-readable config, когда результат можно вернуть модели компактным JSON.

Модель нужна для задач, где есть смысловая неоднозначность:

- составление и semantic review плана;
- анализ требований и архитектурных альтернатив;
- implementation/code review;
- security reasoning;
- оценка соответствия реализации intent/Acceptance criteria.

Если один и тот же результат можно корректно и безопасно получить Python-скриптом без модели, протокол должен предпочитать скрипт.

Граница для каждой команды фиксируется в `.harness/command-transitions.json → reasoning`. При изменении маршрутизации команды или безопасного быстрого пути сначала обновляется этот контракт, затем пересобираются таблица и JSON командой:

```bash
python3 .harness/tools/reasoning-boundaries.py --write
```

Harness Integrity проверяет, что обе проекции совпадают с таблицей команд, а объявленные быстрые пути действительно существуют в коде.

## Always-on context

Always-on context — Harness instructions, которые runtime получает до выбора command-specific skill.

На baseline v0.7.0 gate учитывает:

- Codex: Harness-controlled часть `AGENTS.md`;
- Claude Code: Harness-controlled часть `AGENTS.md` плюс `CLAUDE.md` adapter.

Generated blocks `PROJECT-CONTEXT` и `SKILL-ROUTING` являются project-owned динамическим контекстом. Gate показывает их размер отдельно, но не включает их в core Harness budget: `PROJECT INIT` не должен становиться невалидным только из-за содержимого конкретного проекта.

Локальные/private overrides также не являются частью tracked Harness baseline.

## Почему измерение идёт в символах, а не в токенах

Token count зависит от модели и tokenizer. Core CI не должен зависеть от внешнего tokenizer package или конкретного runtime. Поэтому hard gate использует число Unicode characters как стабильную dependency-free метрику.

Это не попытка точно предсказать счёт за API. Метрика нужна для другого invariant: always-on Harness context не должен незаметно расти.

Baseline после progressive-disclosure refactor:

| Runtime | Harness-controlled chars | До refactor | Снижение |
| --- | ---: | ---: | ---: |
| Codex | 7 224 | 19 275 | 62,5% |
| Claude Code | 8 029 | 20 080 | 60,0% |

`AGENTS.md` после refactor является bootstrap/router. Command playbooks остаются pull-based в skills/docs и не должны возвращаться в always-on файл.

Повышение этих лимитов считается архитектурным изменением и должно быть явно видно в diff/review. Снижение лимита после очередной оптимизации приветствуется и фиксирует достигнутую экономию как новый ceiling.

## Python source и комментарии

Подробные комментарии в `.harness/tools/*.py` не являются always-on context. При обычной эксплуатации агент должен **исполнять tool**, а не читать его исходник. Source читается только когда это действительно нужно: разработка/аудит самого Harness, диагностика tool failure или явный запрос пользователя.

Поэтому экономия токенов не должна достигаться удалением полезных комментариев из deterministic implementation. Правильная оптимизация — не загружать implementation в LLM context без необходимости.

## Config и документация

Machine-readable config должен читать deterministic tool, когда модель не обязана интерпретировать параметр семантически. Tool возвращает минимальный результат или компактный JSON.

Подробная документация хранится pull-based в `.harness/docs/**` и читается по необходимости. Always-on bootstrap должен оставаться картой/routing surface, а не полным manual.

Для STEP workflow навигация тоже выполняется pull-based: `step-context.py STEP-NNN --phase plan|implement|review --json` разрешает exact canonical `readPaths` и deterministic phase facts. Tool намеренно не генерирует semantic summary — модель получает исходное evidence, но не сканирует unrelated project docs/manifest directories.

Command bootstrap также не является reasoning-задачей. `harness-dispatch.py` объединяет CTS validation, execution state, continuation и routing. Deterministic commands, включая `PROJECT STATUS` и `HARNESS UPDATE CHECK/APPLY`, выполняются внутри dispatcher; semantic command возвращает только exact skill/context handoff. Root-модель не должна отдельно читать transition graph, выбирать skill или вызывать resolver по playbook.

Для coding `STEP RUN` dispatcher также владеет mechanical orchestration: exact child-команду выбирает resolver, поэтому между PLAN/IMPLEMENT/REVIEW/FIX не требуется отдельный root-model turn. Reasoning остаётся внутри самих child-команд. Type-specific non-coding flows сохраняют semantic `run-step` fallback.

Semantic artifact persistence следует тому же правилу. PLAN/REVIEW model возвращает structured JSON payload, а `semantic-writer.py` владеет canonical Markdown/YAML rendering, timestamps, fingerprints, immutable report reservation, specialized gate metadata и post-write validation. Модель не должна тратить context/reasoning на ручную сборку frontmatter или повторное вычисление execution result.

Verification — такой же mechanical layer. Explicit `- command: \`...\`` из STEP запускает `verification.py` без shell; runner фиксирует exit code, duration и hashes output, проверяет отсутствие неожиданных repository mutations и обновляет generated Evidence. Модель получает только factual failure/manual checks, а не должна сама запускать команды и пересказывать terminal output.

Выбор `STEP NEXT` также вычисляется без LLM. Resolver использует active executions, lifecycle, priority, dependency graph, explicit risk flags и canonical roadmap order, возвращая ranking breakdown вместе с exact command. Модель не должна повторно «улучшать» рекомендацию скрытой эвристикой.

STEP lifecycle completion после PASS review тоже mechanical: writer сам меняет status, проверяет type-specific completion proof, синхронизирует projections и возвращает exact `completionResult`. Недостаточный proof не превращается в ложный completion.
Pull Request provider mechanics также не являются reasoning-задачей. Модель формирует только semantic PR prose; `git-action.py pr` выполняет exact provider query/reuse/create, head-OID postcondition и PR lifecycle state.

Git workflow следует той же границе: после semantic staging/message decisions `git-action.py` повторяет preflight, выполняет COMMIT/PUSH/SYNC/PR FINISH и проверяет postconditions. Модели не нужно читать/копировать `mutationPlan.argv` и вручную исполнять mechanical steps.

`GIT CHECK`, `GIT SYNC` и `GIT PR FINISH` маршрутизируются как deterministic dispatcher handlers: для них model call отсутствует полностью. Standalone `GIT PUSH` сохраняет semantic logical-scope boundary. Если PUSH идёт непосредственно после успешного canonical COMMIT в той же chain, scope уже доказан этим segment, а dispatcher дополнительно требует machine-proof продвижения HEAD; только после этого используется deterministic push fast-path без повторного model call.

## Gate

Проверка:

```bash
python3 .harness/tools/context-budget.py
python3 .harness/tools/context-budget.py --json
```

`validate.py` включает тот же invariant в baseline integrity validation, а Harness Integrity CI отдельно запускает synthetic regression self-test.

Нарушение budget — deterministic `FAIL`: новый always-on текст нельзя добавить незаметно. Сначала следует вынести детали в skill/docs/tool output или осознанно пересмотреть baseline.
