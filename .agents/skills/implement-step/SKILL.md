---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

Execution Status ведёт global wrapper.

- До mutation запусти deterministic validation и убедись, что `plan.status=ready`, `context_basis`, `content_hash` и `reviewed_report` актуальны. Не доверяй одному полю `Plan basis` или текстовому статусу.
- Проверь dependencies.
- Если execution-status показывает resume этой же команды, сначала изучи существующий diff/Evidence и продолжи недостающее; не переделывай готовое.
- При первой фактической product mutation canonical `status → in_progress`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Выполни реальные verification targets.
- Запиши Evidence: command, exit code и observed facts. Не реконструируй terminal output.
- Не ставь `status: completed` до independent schema-valid review PASS и type-specific completion proof.
- После полного scope + verification + Evidence command завершается result `SUCCESS`.

Single IMPLEMENT после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к REVIEW.
