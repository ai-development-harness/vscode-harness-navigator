# Adaptive FIX ↔ REVIEW stopping

## Назначение

`execution.maxFixReviewCycles` остаётся абсолютным safety cap. Adaptive stopping добавляет более раннюю deterministic остановку, когда следующий FIX уже не имеет доказанного смысла или предыдущий repair ухудшил результат.

Порядок применения:

~~~text
REVIEW = FAIL
  ↓
hard cap exhausted? ── yes → FIX_REVIEW_LIMIT_REACHED
  │ no
  ↓
есть сравнимая repair telemetry? ── no → следующий FIX
  │ yes
  ↓
NO_PROGRESS / REPEATED_FINDINGS / REGRESSION → BLOCKED
  │ иначе
  ↓
следующий FIX
~~~

Hard cap проверяется первым, поэтому существующая семантика `FIX_REVIEW_LIMIT_REACHED` остаётся обратно совместимой.

## Источник данных

Adaptive decision не использует chat history и не просит модель оценить «есть ли прогресс». Сравниваются два immutable Review Contract v3 report:

- предыдущий report берётся из `current.context.reviewReportBefore`, зафиксированного при старте REVIEW;
- текущий report — новый canonical REVIEW artifact;
- findings сравниваются по stable `fingerprint` из Review Contract v3;
- repository delta берётся из `reviewed_revision`;
- semantic scope сравнивается через `contract_basis`.

Новые REVIEW reports получают `contract_basis = planning_context_basis(STEP)`, `verification_basis` — SHA-256 canonical Verification/Evidence snapshot — и factual `verification_status`, прочитанный из generated `VERIFICATION-EVIDENCE` block. Historical v2 reports без этих полей остаются валидными: отсутствие `contract_basis` отключает adaptive classification fail-safe, отсутствие verification basis даёт `verificationChanged=null`, а отсутствие persisted status даёт `verificationRegressed=null`.

## Решения

### REPEATED_FINDINGS

Contract scope не менялся, repository revision изменилась, но множество material finding fingerprints осталось тем же. FIX что-то изменил в repository, но не устранил ни один зафиксированный дефект.

Это также strong trigger для internal `structural-enforcement`: следующий FIX не должен автоматически повторять локальный patch, если stable finding class уже доказан как recurring. Adaptive stop по-прежнему владеет orchestration decision; structural-enforcement только классифицирует systemic corrective mechanism.

### NO_PROGRESS

Используется в двух консервативных случаях при неизменном contract scope:

- repository revision не изменилась и findings остались теми же;
- ни один finding не resolved, а highest material severity не снизилась.

### REGRESSION

Contract scope не менялся и выполняется хотя бы одно из условий:

- после FIX появился новый finding и highest severity стала выше предыдущей;
- factual generated Verification status стал хуже по deterministic шкале `PASS > MANUAL_REQUIRED > FAIL > BLOCKED`.

Новый finding сам по себе не считается regression. Изменение только `verification_basis` тоже не считается ухудшением: hash доказывает лишь изменение snapshot, а не его качество.

### REPAIR_BLOCKED

`REPAIR_BLOCKED` зарезервирован для deterministic repair prerequisite/blocker и не подменяет verdict `BLOCKED` самого REVIEW. Текущая версия не генерирует этот code из эвристики findings: если данные сравнения недоступны или legacy, adaptive stop отключается, а hard cap остаётся активным.

## Scope-change guard

`contract_basis` включает STEP contract, связанные REQ/ADR, dependencies, architecture refs и relevant OQ. Если basis между REVIEW отличается, `scopeComparable=false` и comparator возвращает `continue` независимо от новых findings.

Это предотвращает ложную REGRESSION при легитимном изменении постановки во время repair lifecycle.

## Bounded telemetry

Execution state хранит только **последнюю** сводку `repairTelemetry`, а не историю циклов:

~~~json
{
  "cycle": 2,
  "findingsBefore": 4,
  "findingsAfter": 3,
  "resolved": 2,
  "persisted": 2,
  "introduced": 1,
  "highestSeverityBefore": "high",
  "highestSeverityAfter": "medium",
  "repositoryRevisionChanged": true,
  "contractBasisChanged": false,
  "scopeComparable": true,
  "verificationChanged": true,
  "verificationStatusBefore": "PASS",
  "verificationStatusAfter": "FAIL",
  "verificationRegressed": true,
  "stopDecision": "REGRESSION",
  "reasonCode": "REGRESSION"
}
~~~

Fingerprint lists не копируются в execution state. Полный delta всегда восстанавливается из immutable reports. Размер telemetry дополнительно ограничен тем же bounded metadata gate, что и execution details.

`verificationChanged` вычисляется по `verification_basis`: SHA-256 canonical snapshot разделов `Verification` и `Evidence` на момент REVIEW. Это только факт изменения snapshot.

`verificationRegressed` вычисляется отдельно по persisted factual `verification_status` из generated Verification evidence. Harness не интерпретирует semantic prose `Verification observations` как proof. Если historical report не содержит status, comparator оставляет `verificationRegressed=null` и не делает ложный stop.

## Restart semantics

Telemetry записывается при completion второго и последующих `REVIEW=FAIL`, после как минимум одного успешного `FIX → REVIEW` цикла. Resolver использует сохранённый `stopDecision`; после restart chat history не требуется.

Первый FAIL review (`fixReviewCycles=0`) никогда не создаёт adaptive stop.

## Связь с generic Progress Guard

[`PROGRESS_GUARD.md`](PROGRESS_GUARD.md) может сохранять compact progress samples во время FIX/REVIEW для общей observability, но generic stop decisions на repair loop подавляются. `NO_PROGRESS`, `REPEATED_FINDINGS`, `REGRESSION` и hard cap `FIX_REVIEW_LIMIT_REACHED` остаются единственной authoritative taxonomy FIX↔REVIEW.

## Граница ответственности

- CTS определяет допустимость REVIEW → FIX;
- Review Contract v3 определяет finding identity;
- `repair_cycle.py` вычисляет delta;
- `execution_status.py` хранит последнюю telemetry и применяет stop;
- `maxFixReviewCycles` остаётся hard upper bound.

Модель не может переопределить deterministic stop reason.
