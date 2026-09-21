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

Запусти relevant verification, обнови Evidence с command/exit code/observed facts; не выдавай реконструированный terminal output за буквальный.

После полного исправления command завершается result `SUCCESS`. Старый review не изменяй.

Single FIX после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к свежему REVIEW. Количество `FIX → REVIEW` внутри STEP RUN ограничивает deterministic Execution Resolver по `execution.maxFixReviewCycles`; агент не должен вести собственный счётчик в памяти.
