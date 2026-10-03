# VSCode Harness Navigator

## Краткое описание

VSCode Harness Navigator — локальное расширение Visual Studio Code для навигации, поиска, справки и read-only dependency graph проектов AI Development Harness версии 0.10.3 и новее.

## Проблема и цель

Артефакты Harness распределены между Markdown-файлами и protocol-документацией. Цель расширения — дать разработчику быстрый IDE-уровень доступа к состояниям, связям, навигации по ID и canonical-командам, не превращая расширение в runtime или альтернативный источник истины.

## Пользователи / участники

- Разработчик, работающий в VS Code с одним или несколькими Harness-проектами.
- Пользователь Harness, которому нужна навигация по STEP, REQ, ADR, OQ и справка по командам без ручного поиска файлов.

## Ключевые сценарии

- Открыть Harness-проект и увидеть артефакты, открытые вопросы, активные и заблокированные STEP.
- Найти артефакт через Quick Pick по ID, названию или типу, перейти к нему, посмотреть hover, связи и все упоминания.
- Набрать ссылку на Harness ID и получить completion, definition или document link.
- Открыть read-only каталог canonical-команд текущей версии Harness, понять их назначение и скопировать текст команды.
- Открыть интерактивный overview graph зависимостей и связей Project State API, увидеть diagnostics/MISSING references и перейти к canonical артефакту.
- Получить понятное состояние для обычной папки, повреждённого manifest или неподдерживаемого Harness без сбоя Extension Host.

## Границы продукта

### In scope

- Read-only разбор configured Harness-artifacts, projections и command graph; fixed local Project State API для graph snapshot.
- Нативные VS Code Tree Views, навигационные providers, diagnostics, watcher, изолированный dependency Graph WebView и локализация RU/EN.
- Локальные Artifact Index, Reference Index и Command Catalog для одного или нескольких workspace roots.
- Harness-aware Markdown: canonical артефакты, configured projections, Markdown в project knowledge/planning paths, `.harness/**/*.md` и дополнительный Markdown внутри текущего Harness workspace.

### Out of scope

- Запуск Harness-команд, dispatcher, агентов, shell-команд или произвольных Python tools из расширения.
- Изменение артефактов, projections, manifest либо execution state Harness.
- AI-интеграции, telemetry, сетевые обращения, GitHub-авторизация и собственный Markdown editor.
- Редактирование graph/artifacts, network, telemetry, persistent graph layouts, command-chain helper и полноценная визуализация execution-group DAG.

## Ограничения

- Минимально поддерживаемый release Harness — 0.10.3; legacy parsing, compatibility graph и автоматическая миграция не поддерживаются.
- В trusted workspace допускается только `.harness/tools/project-state.py --json`: fixed read-only process boundary для graph snapshot, а не общий launcher Harness tools.
- Все пути артефактов берутся из `.harness/manifest.yaml`; стандартные пути не являются fallback-источником.
- Harness semantic functionality не применяется к произвольному Markdown вне Harness workspace.
- Canonical ID, machine enum и Harness-команды не локализуются.
- Основной язык — TypeScript со strict mode; используются официальный VS Code Extension API, YAML parser, Yarn, ESLint, Prettier и production bundling.

## Нефункциональные ожидания

- Работа offline без network, telemetry, shell и Git history; Project State API выполняется только локально в trusted workspace.
- Корректная деградация при локальной ошибке артефакта и fail-closed поведение при project-level blocker.
- Incremental update индексов без обхода `node_modules` и без полного повторного сканирования на каждое изменение.
- Пользовательские элементы полностью локализованы как минимум на русском и английском; business logic не зависит от locale.

## Референсы и внешние источники

- `PROJECT_BRIEF.local.md` — исходный product brief.
- https://github.com/ai-development-harness/ai-development-harness-template — справочный репозиторий Harness.
- https://github.com/ai-development-harness/ai-development-harness-vscode-extension — предыдущая попытка реализации, допустимая только как источник идей.

## Основные риски и неопределённости

Требования MVP не оставляют project-level открытых решений. Совместимость с будущими schema Harness ограничена поддерживаемыми форматами и должна выражаться явным состоянием ошибки, а не эвристическим parsing.
