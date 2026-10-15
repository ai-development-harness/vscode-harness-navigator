# Completion Reports

Каждая команда должна завершаться коротким, но пригодным для следующего действия отчётом.

## PROJECT INIT

- project name/summary;
- созданные REQ/ADR/STEP и их количество;
- ключевые архитектурные решения;
- unresolved OPEN_QUESTIONS;
- roadmap phases и critical dependencies;
- рекомендуемый agent profile;
- requirements/roadmap semantic review reports + deterministic consistency result;
- следующая команда.

## ADD / PLAN / IMPLEMENT / FIX

- STEP;
- изменённые canonical artifacts;
- blockers/risks;
- verification result, если применимо;
- следующая команда.

## REVIEW

- schema-valid report path;
- exact reviewed revision;
- verdict;
- blocking findings по severity/category;
- deterministic specialized-review requirements/results;
- следующая команда (`FIX`, blocker action или next step).

## RECONCILE / RELEASE CHECK

- report path;
- найденный drift/blockers;
- созданные corrective STEP;
- verdict/следующее действие.

Не вставляй в completion report длинный пересказ task/REQ/ADR. Durable details уже находятся в repository artifacts.

## GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT PR FINISH / GIT SYNC

- current branch/upstream;
- Harness validation result;
- suspicious/unrelated files or blockers;
- для GIT COMMIT: hash, subject, included files, verification/traceability;
- для GIT PUSH: remote branch, push result, ahead/behind state;
- для `GIT PR`: URL либо точный blocker;
- следующая безопасная команда.

Не скрывай partial success: например, если push прошёл, а PR создать не удалось, сообщи оба результата отдельно.

## Deterministic operational reports: audit / release-check / skill-search (#314–#317)

Для `PROJECT RECONCILE`, `STEP AUDIT`, `RELEASE CHECK`, `SKILL FIND` модель **не пишет Markdown и YAML вручную**. Она передаёт только семантическое содержание (фактические observations/evidence/findings) в уже существующий `semantic-writer.py`. Writer использует текущий project-owned `TEMPLATE.md` в directory из `.harness/manifest.yaml`, резервирует `AUDIT-/RELEASE-/SKILL-SEARCH-<UTC>.md` через `document_contract.create_durable_report()`, задаёт `kind/schema/created_at/mode/status`, проверяет `report_contract.py` и сохраняет receipt в `.harness/local/execution/execution-status.json`.

Для вызова нужен **`executionId` из текущего canonical dispatcher handoff**, не произвольный ID из текста модели. Payload хранить в `.harness/local/**` или передать по stdin (`--payload-file '-'`). Шаблон может иметь project-owned дополнительные H2 sections: их тоже надо заполнить в `sections`. H2-головки внутри содержимого section запрещены; H3 и списки разрешены. Отсутствующий report, `TBD` или пустая обязательная секция → `BLOCKED`.

Пример для `PROJECT RECONCILE` (при `STEP AUDIT STEP-017` укажи `scope: "STEP-017"`):

```json
{
  "scope": "project",
  "sections": {
    "Sources checked": "REQ-001, ADR-001 и фактические реализации проверены.",
    "Actual state": "Код и конфигурация сопоставлены с контрактом.",
    "Drift / findings": "REQ-001: material mismatch в API.",
    "Evidence": "Проверен конкретный source/test, зафиксированы наблюдения.",
    "Corrective actions": "Предложить STEP-017 для закрытия gap."
  }
}
```

```bash
python3 .harness/tools/semantic-writer.py audit-report --execution-id '<exec-id>' --payload-file .harness/local/audit-payload.json
```

`RELEASE CHECK`: semantic поля `target`, `verdict: ready|blocked`, `sections` с `Requirements / scope`, `Verification gates`, `Security / migrations / compatibility`, `Unresolved blockers`, `Evidence`. Вызов: `semantic-writer.py release-report --execution-id ... --payload-file ...`. `verdict: blocked` может быть корректным завершённым аудитом неготового релиза; не превращать обнаруженные фактические blockers в ошибку schema.

`SKILL FIND: <описание>`: payload `query` равен точному тексту исходной команды, `candidates` — массив объектов с полями `name`, `repository`, `path`, `url`, `inspectedRef`, `license`, `whyItFits`, `limitations`, `safetyNotes`, `recommendation`, `sections` — `Search strategy`, `Ranking criteria`, `Rejected / notable alternatives`, `Next command`. Секцию `Candidates` и `candidate_count` writer строит сам. Пустой список допускается только как честный результат без подтверждённых кандидатов. Команда writer: `semantic-writer.py skill-search-report --execution-id ... --payload-file ...`.

Writer возвращает `status: PASS`, `report`, `reportSha256`, `writerValidated: true`, но **НЕ** помечает execution завершённой. Агент вызывает штатный `harness-dispatch.py complete` со своим `executionId`; dispatcher повторно проверяет локальный `operationalReport` receipt (exact command/ID, configured directory, schema/kind/H1/UTC, report SHA256 и fingerprint source). Любое несоответствие возвращает `BLOCKED` **без перезаписи** report и без terminal SUCCESS. `complete BLOCKED` для реальной технической причины доступен без искусственного отчёта. Предыдущие reports без local writer receipt не являются proof текущего выполнения.

Гарантия receipt — **структурная корректность, принадлежность execution и неизменность проверенного содержимого**; он не доказывает истинность семантического текста сам по себе. За наблюдения/выводы отвечает исполняющий semantic role и существующие Evidence Gates.
