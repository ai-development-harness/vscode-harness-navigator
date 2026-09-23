---
name: fix-step
description: Fix confirmed implementation findings from the latest failing review of a STEP, then hand off to a fresh independent review.
---
# fix-step

Используй для `STEP FIX STEP-NNN`.

Execution Status ведёт global wrapper.

Найди последний schema-valid FAIL review в configured `protocol.reviewDirectory`, относящийся к применимой implementation revision. FIX имеет право исправлять только findings категорий `implementation` и `evidence`, которые остаются внутри существующих Scope/Mutation policy/REQ/ADR.

Если review фактически требует изменить product contract, Acceptance, architecture decision, dependency graph или добавить отсутствующий prerequisite, не «чинить» это кодом. Заверши как `BLOCKED` и создай/предложи corrective STEP, RESEARCH или ADR согласно типу проблемы.

Передай подтверждённые findings implementer и исправь их вместе с необходимым supporting code в scope. Если command resume-ится после interruption, сначала изучи существующий diff и продолжи незавершённые findings.

После исправления предложи result `SUCCESS`; dispatcher сам повторно запускает canonical STEP Verification и обновляет generated Evidence. При factual FAIL продолжи FIX; manual checks выполняй только если runner явно вернул `MANUAL_REQUIRED`.

Command завершается только после PASS verification gate. Старый review не изменяй.

Single FIX после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к свежему REVIEW. Количество `FIX → REVIEW` внутри STEP RUN ограничивает deterministic Execution Resolver по `execution.maxFixReviewCycles`; агент не должен вести собственный счётчик в памяти.
