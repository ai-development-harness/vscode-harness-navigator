# VSCode Harness Navigator

## Краткое описание

VSCode Harness Navigator — локальное расширение Visual Studio Code для навигации, поиска и справки по документной модели проектов AI Development Harness версии 0.6.0 и новее.

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
- Получить понятное состояние для обычной папки, повреждённого manifest или неподдерживаемого Harness без сбоя Extension Host.

## Границы продукта

### In scope

- Read-only разбор configured Harness-artifacts, projections и command graph.
- Нативные VS Code Tree Views, навигационные providers, diagnostics, watcher и локализация RU/EN.
- Локальные Artifact Index, Reference Index и Command Catalog для одного или нескольких workspace roots.
- Harness-aware Markdown: canonical артефакты, configured projections, Markdown в project knowledge/planning paths, `.harness/**/*.md` и дополнительный Markdown внутри текущего Harness workspace.

### Out of scope

- Запуск Harness-команд, агентов, shell-команд или Python tools из расширения.
- Изменение артефактов, projections, manifest либо execution state Harness.
- AI-интеграции, telemetry, сетевые обращения, GitHub-авторизация и собственный Markdown editor.
- WebView для MVP, graph/details/favorites/recent history и command-chain helper после MVP.

## Ограничения

- Минимально поддерживаемый release Harness — 0.6.0; legacy parsing и автоматическая миграция не поддерживаются.
- Все пути артефактов берутся из `.harness/manifest.yaml`; стандартные пути не являются fallback-источником.
- Harness semantic functionality не применяется к произвольному Markdown вне Harness workspace.
- Canonical ID, machine enum и Harness-команды не локализуются.
- Основной язык — TypeScript со strict mode; используются официальный VS Code Extension API, YAML parser, Yarn, ESLint, Prettier и production bundling.

## Нефункциональные ожидания

- Работа offline без network, telemetry, shell и Git history.
- Корректная деградация при локальной ошибке артефакта и fail-closed поведение при project-level blocker.
- Incremental update индексов без обхода `node_modules` и без полного повторного сканирования на каждое изменение.
- Пользовательские элементы полностью локализованы как минимум на русском и английском; business logic не зависит от locale.

## Референсы и внешние источники

- `PROJECT_BRIEF.local.md` — исходный product brief.
- https://github.com/ai-development-harness/ai-development-harness-template — справочный репозиторий Harness.
- https://github.com/ai-development-harness/ai-development-harness-vscode-extension — предыдущая попытка реализации, допустимая только как источник идей.

## Основные риски и неопределённости

Требования MVP не оставляют project-level открытых решений. Совместимость с будущими schema Harness ограничена поддерживаемыми форматами и должна выражаться явным состоянием ошибки, а не эвристическим parsing.
