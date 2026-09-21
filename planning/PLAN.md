# Project Roadmap

> Tracked deterministic projection. Полный contract каждого STEP находится в configured protocol.taskDirectory.

| STEP | Название | Type | Priority | Status | Depends on | REQ |
|---|---|---|---|---|---|---|
| STEP-001 | Базовый каркас расширения и toolchain | implementation | high | planned | — | REQ-001, REQ-008, REQ-010 |
| STEP-002 | Определение проекта и чтение manifest | implementation | high | planned | STEP-001 | REQ-001, REQ-002, REQ-008 |
| STEP-003 | Парсинг артефактов и общие индексы | implementation | high | planned | STEP-002 | REQ-001, REQ-003, REQ-008, REQ-009 |
| STEP-004 | Views артефактов, фокуса и поиск | implementation | high | planned | STEP-003 | REQ-001, REQ-004, REQ-008 |
| STEP-005 | Навигация, references и relations Harness ID | implementation | high | planned | STEP-003 | REQ-001, REQ-005, REQ-006, REQ-008 |
| STEP-006 | Каталог и справка Harness-команд | implementation | high | planned | STEP-002 | REQ-001, REQ-007, REQ-008 |
| STEP-007 | Интеграция MVP и release proof | implementation | high | planned | STEP-004, STEP-005, STEP-006 | REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010 |
