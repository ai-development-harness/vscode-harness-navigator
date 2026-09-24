# Harness Navigator

English | Русский (ниже)

Read-only navigation and reference for AI Development Harness projects in Visual Studio Code.

## What it does

- Shows Harness artifacts (STEP, REQ, ADR, OQ) from your workspace in the Harness Navigator Activity Bar container.
- Views: Harness Summary, Harness Artifacts, Harness Focus and Harness Commands (a catalog of canonical Harness commands with help).
- Go to an artifact by ID, find all references to a Harness ID, show relations, copy an artifact ID or path.
- Sort and filter STEP artifacts by status, type, priority and phase.

### Commands

Command Palette:

- Harness: Show Diagnostics
- Harness: Refresh
- Harness: Go to Artifact
- Harness: Set Sort Order
- Harness: Set Filter
- Harness: Clear Filters
- Harness: Find Command
- Harness: Find All References (when a Markdown editor is active)
- Harness: Show Relations (when a Markdown editor is active)

Context menus:

- Harness Artifacts and Harness Focus view items: Copy Artifact ID, Copy Artifact Path, Find All References, Show Relations, Copy Command
- Harness Commands view items: Copy Command
- Markdown editor: Harness: Find All References, Harness: Show Relations
- Harness Artifacts view title buttons: Set Sort Order, Set Filter, Clear Filters

### Settings

`harnessNavigator.artifacts.sortOrder` and `harnessNavigator.artifacts.filter.status`, `.type`, `.priority`, `.phase`.

## Read-only boundary

The extension only reads files. It does not run Harness commands, agents, shell or Python tools, does not open terminals or WebViews, does not use the network or telemetry, and never modifies Harness artifacts. Artifact paths are taken from `.harness/manifest.yaml`.

## Requirements

- Visual Studio Code 1.85.0 or newer.
- A workspace with an AI Development Harness project (Harness 0.6.0 or newer) that contains `.harness/manifest.yaml`.

## Links

- Extension source: https://github.com/ai-development-harness/vscode-harness-navigator
- AI Harness source: https://github.com/ai-development-harness/ai-development-harness-template
- AI Harness website: https://ai-development-harness.ru

---

## Русский

Локальная read-only навигация и справка по проектам AI Development Harness в Visual Studio Code.

### Что делает расширение

- Показывает артефакты Harness (STEP, REQ, ADR, OQ) из рабочей области в контейнере Harness Navigator на Activity Bar.
- Представления: «Сводка Harness», «Артефакты Harness», «Фокус Harness» и «Команды Harness» (каталог canonical-команд Harness со справкой).
- Переход к артефакту по ID, поиск всех ссылок на Harness ID, показ связей, копирование ID и пути артефакта.
- Сортировка и фильтрация STEP по статусу, типу, приоритету и фазе.

#### Команды

Палитра команд (Command Palette):

- Harness: Показать диагностику
- Harness: Обновить
- Harness: Перейти к артефакту
- Harness: Задать порядок сортировки
- Harness: Задать фильтр
- Harness: Очистить фильтры
- Harness: Найти команду
- Harness: Найти все ссылки (при активном Markdown-редакторе)
- Harness: Показать связи (при активном Markdown-редакторе)

Контекстные меню:

- Элементы представлений «Артефакты Harness» и «Фокус Harness»: Скопировать ID артефакта, Скопировать путь артефакта, Найти все ссылки, Показать связи, Скопировать команду
- Элементы представления «Команды Harness»: Скопировать команду
- Markdown-редактор: Harness: Найти все ссылки, Harness: Показать связи
- Кнопки в заголовке представления «Артефакты Harness»: Задать порядок сортировки, Задать фильтр, Очистить фильтры

#### Настройки

`harnessNavigator.artifacts.sortOrder` и `harnessNavigator.artifacts.filter.status`, `.type`, `.priority`, `.phase`.

### Граница read-only

Расширение только читает файлы. Оно не запускает Harness-команды, агентов, shell и Python tools, не открывает терминалы и WebView, не использует сеть и telemetry и не изменяет артефакты Harness. Пути артефактов берутся из `.harness/manifest.yaml`.

### Требования

- Visual Studio Code 1.85.0 или новее.
- Рабочая область с проектом AI Development Harness (Harness 0.6.0 или новее), содержащая `.harness/manifest.yaml`.

### Ссылки

- Исходный код плагина: https://github.com/ai-development-harness/vscode-harness-navigator
- Исходный код AI Harness: https://github.com/ai-development-harness/ai-development-harness-template
- Сайт проекта AI Harness: https://ai-development-harness.ru
