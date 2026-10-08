---
name: fix-step
description: Resolve every applicable implementation/evidence finding from the latest failing review within the existing STEP contract, then hand off to fresh independent review.
---
# fix-step

Используй для `STEP FIX STEP-NNN`.

Execution Status ведёт global wrapper.

1. Получи последний evidence-gated Review Contract v3 через deterministic parser, а не через повторный разбор Markdown prose:
   ```bash
   python3 .harness/tools/review_findings.py --step STEP-NNN --json
   ```
   Parser обязан вернуть schema-valid FAIL review и normalized findings с `id` + stable `fingerprint` + подтверждённым `evidenceBasis`. Если latest report legacy v1/v2, malformed или ambiguous — не угадывай структуру и не исправляй finding «по памяти»: заверши `BLOCKED` и потребуй свежий REVIEW v3.
   Dispatcher до semantic handoff сохраняет exact pre-FIX Git tree во временном alternate index, включая pre-existing staged/unstaged и неигнорируемые новые файлы. Baseline закреплён за executionId и переживает resume. Не пересоздавай snapshot после начала правок и не используй HEAD как эквивалент dirty baseline. После factual SUCCESS + Verification PASS Core закрепляет post-FIX subject и следующий REVIEW получает `fixReview.mode=fix_delta`.
2. Перед repair выполни `python3 .harness/tools/structural-enforcement.py --step STEP-NNN --json`. Tool агрегирует evidence-gated Review Contract v3 findings по stable category/fingerprint и не считает duplicate reports одной reviewed revision новым occurrence. Если current finding class уже recurring, сначала сформируй strongest-feasible structural-enforcement proposal; не делай ещё один локальный patch только потому, что он быстрее. Один occurrence без explicit human request не повышай до recurring pattern.
3. Возьми все applicable findings категорий `implementation` и `evidence`, которые остаются внутри существующих Scope/Mutation policy/REQ/ADR. Не исправляй только первый finding, если review уже содержит другие material findings. Используй `fingerprint` как identity finding между FIX/REVIEW циклами; title и формулировка repair guidance не являются identity.
4. Для каждого исправления сохрани явное соответствие **review finding → изменённый code/test/evidence**, чтобы перед completion можно было проверить, что ничего не потеряно. Для deterministic structural enforcement regression fixture обязателен; после реализации проверь proposal с `--implemented`, а сам fixture command включи в canonical Verification/CI.
5. Если review или structural-enforcement proposal требует изменить product contract, Acceptance, architecture/ownership decision, dependency graph или добавить отсутствующий prerequisite, не «чинить» это кодом. Заверши как `BLOCKED` и создай/предложи corrective STEP, RESEARCH или ADR согласно типу проблемы. `architecture-ownership` никогда не даёт automatic mutation authority.
6. Передай только evidence-gated findings implementer и исправь их вместе с необходимым supporting code в scope. `evidenceBasis` задаёт границу доказанного сценария: FIX не имеет права расширять его в соседние теоретические угрозы/edge cases без отдельного contract или нового подтверждённого finding. Если command resume-ится после interruption, сначала изучи существующий diff и продолжи только незавершённые findings.
7. Новые regression/security tests во время FIX должны иметь явный provenance: конкретный REQ/ADR/STEP invariant либо текущий подтверждённый `F-NNN`. Сначала покрывай воспроизведённый regression и необходимые contract-supported boundary cases. Не добавляй тесты только потому, что framework/platform теоретически допускает экзотический сценарий; если во время FIX возникла новая гипотеза, не превращай её скрыто в test+hardening — верни её в свежий REVIEW/Evidence Gate.
8. После точечных исправлений перечитай весь изменённый artifact/связанный contract, а не только строки findings. Проверь внутреннюю непротиворечивость, примеры и исключения; каждое утверждение о другом ADR/REQ/code/config подтверждай чтением источника. Исправь все известные findings этого раунда одним проходом, включая non-material/low-severity замечания, если они однозначны и находятся в scope. При обобщении правила явно перечисли исключения. Не расширяй artifact в область другого owner/STEP — вместо этого зафиксируй requirement/prerequisite + owner.
   Пока исправляешь findings, используй `python3 .harness/tools/verify-selected.py STEP-NNN --command '<exact configured command>'` для дешёвого точечного feedback (до восьми команд из STEP Verification). `completionProof=false` означает, что это не каноническая Verification: даже PASS выбранных тестов не даёт права пропустить полную проверку dispatcher при FIX SUCCESS. Не запускай весь набор на каждую промежуточную правку.
9. Перед `SUCCESS` убедись, что все applicable findings текущего FAIL review либо исправлены и покрыты evidence, либо корректно переведены в BLOCKED по contract-level причине.
10. После исправления предложи result `SUCCESS`; dispatcher сам повторно запускает canonical STEP Verification и обновляет generated Evidence. При factual FAIL продолжи FIX; manual checks выполняй только если runner явно вернул `MANUAL_REQUIRED`.

Command завершается только после PASS verification gate. Старый review не изменяй.

Single FIX после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к свежему REVIEW. Количество `FIX → REVIEW` внутри STEP RUN ограничивает deterministic Execution Resolver по `execution.maxFixReviewCycles`; агент не должен вести собственный счётчик в памяти.
