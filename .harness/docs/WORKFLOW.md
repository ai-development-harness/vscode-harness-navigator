# Workflow Design

Harness разделён на три слоя:

```text
HARNESS / protocol
AGENTS + skills + commands + templates
             ↓
PROJECT KNOWLEDGE BASE
REQ + ADR + architecture + planning
             ↓
CODE / TESTS / CONFIG
реализация и evidence
```

## Почему история чата не используется как база знаний

Новая сессия должна восстановить контекст из репозитория. Поэтому каждая стадия сохраняет durable handoff:

- PLAN → draft `Implementation plan` + immutable semantic planning-review + Ready fingerprints;
- REVIEW → immutable schema-valid exact-revision review report;
- audit/reconcile → audit report;
- completion → Evidence + status projections.

## Почему REQ, ADR и STEP разделены

`REQ` отвечает на вопрос «что должно быть истинно для продукта?».
`ADR` — «какое устойчивое решение принято и почему?».
`STEP` — «какую ограниченную работу мы сейчас выполняем?».

Смешивание этих сущностей приводит к тому, что roadmap превращается в ТЗ, ADR — в changelog, а требования — в список файлов.

## Почему PLAN сохраняется в task

PLAN нужен не только текущему чату. Он является handoff от reasoning-heavy planner к implementer, но Ready появляется только после независимого semantic planning-review. `context_basis` fingerprint-ит relevant contract/upstream context, а `content_hash` — сам Implementation plan.

## Почему REVIEW отдельным файлом

Review report — immutable historical artifact с exact repository revision, verdict, findings и specialized-review metadata. Crash recovery может переиспользовать его только после deterministic schema/revision validation.

## Почему RECONCILE обязателен

Реальный проект неизбежно получает ручные изменения, hotfix, drift документации и stale statuses. `PROJECT RECONCILE` периодически восстанавливает согласованность без скрытого исправления production code.


## Skill supply chain

Technology-specific knowledge не нужно заранее встраивать в template. Harness использует on-demand pipeline:

```text
Need capability
   ↓
SKILL FIND
   ↓ configured shortlist + durable report
User selects
   ↓
SKILL INSTALL
   ↓ inspect / provenance / routing
.agents/skills/<name>
```

Если достойного upstream нет:

```text
SKILL CREATE
   ↓
project-native SKILL.md
```

Это сохраняет template универсальным и одновременно не заставляет пользователя вручную искать/писать каждый technology playbook.

## Micro-change path

Не вся работа проходит через STEP. Безопасная мелкая правка использует короткий путь:

```text
PROJECT QUICK FIX: ...   или ручная правка
        ↓
proportional check
        ↓
GIT CHECK
        ↓
GIT COMMIT
```

Если обнаруживается contract/risk change, короткий путь прекращается и начинается `STEP ADD:`.

## Collaboration templates как производный артефакт

Issue/PR templates зависят от текущего tooling и периодически регенерируются командой `GITHUB GENERATE TEMPLATES`. Они не являются canonical source требований или verification commands: генератор извлекает эти данные из repository state.
