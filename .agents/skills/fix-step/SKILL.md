---
name: fix-step
description: Resolve every applicable implementation/evidence finding from the latest failing review within the existing STEP contract, then hand off to fresh independent review.
---
# fix-step

Используй для `STEP FIX STEP-NNN`.

Execution Status ведёт global wrapper.

1. Получи последний Review Contract v2 через deterministic parser, а не через повторный разбор Markdown prose:
   ```bash
   python3 .harness/tools/review_findings.py --step STEP-NNN --json
   ```
   Parser обязан вернуть schema-valid FAIL review и normalized findings с `id` + stable `fingerprint`. Если latest report legacy v1/malformed/ambiguous — не угадывай структуру, заверши `BLOCKED` и потребуй свежий REVIEW.
2. Возьми все applicable findings категорий `implementation` и `evidence`, которые остаются внутри существующих Scope/Mutation policy/REQ/ADR. Не исправляй только первый finding, если review уже содержит другие material findings. Используй `fingerprint` как identity finding между FIX/REVIEW циклами; title и формулировка repair guidance не являются identity.
3. Для каждого исправления сохрани явное соответствие **review finding → изменённый code/test/evidence**, чтобы перед completion можно было проверить, что ничего не потеряно.
4. Если review фактически требует изменить product contract, Acceptance, architecture decision, dependency graph или добавить отсутствующий prerequisite, не «чинить» это кодом. Заверши как `BLOCKED` и создай/предложи corrective STEP, RESEARCH или ADR согласно типу проблемы.
5. Передай подтверждённые findings implementer и исправь их вместе с необходимым supporting code в scope. Если command resume-ится после interruption, сначала изучи существующий diff и продолжи только незавершённые findings.
6. Перед `SUCCESS` убедись, что все applicable findings текущего FAIL review либо исправлены и покрыты evidence, либо корректно переведены в BLOCKED по contract-level причине.
7. После исправления предложи result `SUCCESS`; dispatcher сам повторно запускает canonical STEP Verification и обновляет generated Evidence. При factual FAIL продолжи FIX; manual checks выполняй только если runner явно вернул `MANUAL_REQUIRED`.

Command завершается только после PASS verification gate. Старый review не изменяй.

Single FIX после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к свежему REVIEW. Количество `FIX → REVIEW` внутри STEP RUN ограничивает deterministic Execution Resolver по `execution.maxFixReviewCycles`; агент не должен вести собственный счётчик в памяти.
