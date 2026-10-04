---
schema: 1
id: REQ-012
priority: high
source: brief
steps:
  - STEP-019
adrs:
  - ADR-008
---

# REQ-012 — Аналитический обзор и интерактивный граф проекта

## Requirement

Страница `Harness: Dependency Graph` должна помогать разработчику быстро оценить структуру Harness-проекта, увидеть предоставленные API проблемы и изучить связи выбранного артефакта через компактный обзор, интерактивный граф и структурированный inspector.

## Rationale

Техническое представление с grid-размещением, dropdown-фильтрами и raw JSON требует ручной интерпретации данных. Нужен читаемый production UI поверх существующего Project State API и границ REQ-011/ADR-008, без нового источника данных или собственной проектной аналитики.

## Acceptance

- Страница содержит компактный Project Overview, левую панель Views/Filters с поиском, SVG canvas, Selected Artifact Inspector и компактную область Project Health/Diagnostics. Raw JSON `summary`, `insights`, `sources`, `diagnostics` и metadata не является пользовательским представлением этих данных.
- Overview показывает имя проекта, имя workspace folder, переданный API Harness release, canonical `integrity: ok | degraded` и доступные реальные counts/coverage. `summary.artifacts` считает только canonical project artifacts; REVIEW и SKILL учитываются отдельно. Warning/error акценты применяются к проблемным метрикам только при ненулевых counts и к degraded integrity.
- Доступны client-side views Full graph, STEP dependencies, Blockers, Dependency cycles, Missing references, Uncovered requirements и Isolated artifacts. Views используют только текущие nodes/edges и IDs из API insights; поиск по ID/title совместим с filters типов, статусов и relations, а очистка поиска восстанавливает выбранный view.
- Типы PROJECT/REQ/ADR/STEP/OQ/REVIEW/SKILL/MISSING различимы, counts берутся из snapshot; filter/legend relations содержит только присутствующие canonical schema-v1 relations. Детерминированное layered-размещение сохраняет isolated nodes и отдельно группирует MISSING; одинаковый snapshot даёт одинаковые координаты.
- Тип узла, status, selection, members cycles и longest dependency chain имеют отдельные визуальные признаки; selection имеет высший приоритет. Направление edges однозначно, tooltip и inspector сохраняют source/target/relation/declaredBy; выбор выделяет прямые связи и приглушает несвязанные элементы.
- Подсветка `insights.dependency.longestChain` называется только `Longest dependency chain` / `Самая длинная цепочка зависимостей`; cycle members берутся из API. Navigator не вычисляет альтернативные цепочки, lifecycle, blockers, impact или рекомендации.
- Inspector показывает ID/type/title/status и только имеющиеся applicable metadata. Для STEP доступны фактические plan/review/completion/freshness поля; stale/blocked/invalid plan показывает предоставленные причины и remediation как копируемый текст команды без запуска. Прямые relations группируются по направлению и типу, связанные nodes выбираются кликом.
- Downstream impact отображается только как уже полученный per-node факт из metadata/insights. Execution groups имеют только компактное read-only представление. MISSING показывает проблему и diagnostic context без open action; остальные artifacts открываются по ID через существующую containment-проверку Extension Host.
- Project Health показывает canonical integrity, relationship/traceability coverage и реальные problem counts; диагностика представлена читаемым списком с имеющимися полями. Не добавляются health score, проценты integrity, вымышленные missing-reference percentages, chronology/history, Git branch, Critical Path, новые relations или synthetic SKILL → STEP edges.
- Selection/open/focus/related, keyboard activation, zoom/pan/fit и один panel на root сохраняются. Multi-root Command Palette использует существующий Quick Pick; degraded snapshot отображается, unavailable/invalid API сохраняет диагностируемое error state без fallback.
- Поиск, filters, presets, selection и zoom/pan работают над текущей presentation model без повторного запуска API. UI использует VS Code theme variables, адаптируется к обычному editor и split editor, доступен с клавиатуры и локализован RU/EN; отсутствует зависимость только от цвета.
- Граф остаётся read-only и presentation-only по ADR-008. Проверки наблюдаемого поведения покрывают overview, views/filters/search, layout, inspector/diagnostics, API facts, navigation/security boundaries, refresh, multi-root и RU/EN; production build и package gates проходят.
