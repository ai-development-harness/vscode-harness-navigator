#!/usr/bin/env python3
"""Проекция границ между вычислениями модели и детерминированными скриптами.

Источник истины — .harness/command-transitions.json. Этот модуль не принимает
архитектурных решений: он проверяет ссылки на быстрые пути, строит стабильную
машиночитаемую проекцию и синхронизирует человекочитаемую документацию.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from command_transitions import load_transition_table, validate_transition_table


JSON_PATH = ".harness/reasoning-boundaries.json"
DOC_PATH = ".harness/docs/REASONING_BOUNDARIES.md"
START_MARKER = "<!-- REASONING-BOUNDARIES:START -->"
END_MARKER = "<!-- REASONING-BOUNDARIES:END -->"
BT = chr(96)
FENCE = BT * 3
MODE_LABELS = {
    "none": "Без модели",
    "required": "Модель обязательна",
    "conditional": "Зависит от сценария",
}

DOC_PREAMBLE = (
    "# Границы вычислений модели\n\n"
    "Harness использует модель только там, где требуется смысловое решение.\n"
    "Проверяемая, вычислимая и механическая работа по возможности выполняется\n"
    "детерминированными скриптами.\n\n"
    "Источник истины — " + BT + ".harness/command-transitions.json" + BT + ". "
    "Таблица и числовая\n"
    "сводка ниже генерируются автоматически. Ручное редактирование блока между\n"
    "служебными маркерами запрещено.\n\n"
    "Режим относится к собственной обработке канонической команды. Если команда\n"
    "запускает дочерние команды, их вычисления учитываются отдельно. Например,\n"
    "обычный STEP RUN управляется скриптом, но дочерние PLAN, IMPLEMENT, REVIEW\n"
    "и FIX по-прежнему выполняют необходимую смысловую работу модели.\n\n"
    "Машиночитаемая проекция для внешних потребителей:\n\n"
    + FENCE + "text\n"
    ".harness/reasoning-boundaries.json\n"
    + FENCE + "\n\n"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _commands(table: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for domain_name, domain in table["domains"].items():
        for operation, spec in domain["commands"].items():
            result.append(
                {
                    "command": spec["canonical"],
                    "domain": domain_name,
                    "operation": operation,
                    "summary": spec["summary"],
                    "documentation": spec["documentation"],
                    "dispatch": deepcopy(spec["dispatch"]),
                    "reasoning": deepcopy(spec["reasoning"]),
                }
            )
    return result


def build_projection(table: dict[str, Any]) -> dict[str, Any]:
    """Построить стабильную JSON-проекцию без временных меток."""

    commands = _commands(table)
    counts = {"none": 0, "required": 0, "conditional": 0}
    for item in commands:
        counts[item["reasoning"]["mode"]] += 1
    return {
        "schemaVersion": 1,
        "generatedFrom": ".harness/command-transitions.json",
        "classification": {
            "scope": "command-node",
            "description": (
                "Режим относится к собственной обработке канонической команды; "
                "вызванные ею дочерние команды учитываются отдельно."
            ),
        },
        "summary": {
            "total": len(commands),
            "none": counts["none"],
            "required": counts["required"],
            "conditional": counts["conditional"],
        },
        "commands": commands,
    }


def _md_text(values: list[str]) -> str:
    if not values:
        return "—"
    return "<br>".join(value.replace("|", "\\|") for value in values)


def _fast_path_text(values: list[dict[str, str]]) -> str:
    if not values:
        return "—"
    return "<br>".join(
        item["description"].replace("|", "\\|")
        for item in values
    )


def render_markdown_block(projection: dict[str, Any]) -> str:
    """Сформировать сгенерированный блок документации из проекции."""

    summary = projection["summary"]
    lines = [
        "## Сводка",
        "",
        "| Режим | Количество команд |",
        "|---|---:|",
        f"| Без вычислений модели | {summary['none']} |",
        f"| Вычисления модели обязательны | {summary['required']} |",
        f"| Зависит от сценария | {summary['conditional']} |",
        f"| **Всего** | **{summary['total']}** |",
        "",
        FENCE + "mermaid",
        "pie showData",
        "    title Где Harness использует вычисления модели",
        f'    "Без модели" : {summary["none"]}',
        f'    "Модель обязательна" : {summary["required"]}',
        f'    "Зависит от сценария" : {summary["conditional"]}',
        FENCE,
        "",
        "## Принцип выполнения",
        "",
        FENCE + "mermaid",
        "flowchart LR",
        '    A["Каноническая команда"] --> B{"Как выполняется команда?"}',
        '    B -->|"Без модели"| C["Детерминированные скрипты"]',
        '    B -->|"Модель обязательна"| D["Вычисления модели"]',
        '    B -->|"Зависит от сценария"| E{"Есть безопасный быстрый путь?"}',
        '    E -->|"Да"| C',
        '    E -->|"Нет"| D',
        '    D --> C',
        '    C --> F["Проверка, состояние и результат"]',
        FENCE,
        "",
        "## Команды",
        "",
        "| Команда | Режим | Что делает модель | Что делают скрипты | Когда модель не нужна |",
        "|---|---|---|---|---|",
    ]
    for item in projection["commands"]:
        reasoning = item["reasoning"]
        lines.append(
            "| "
            + " | ".join(
                [
                    BT + item["command"] + BT,
                    MODE_LABELS[reasoning["mode"]],
                    _md_text(reasoning["modelWork"]),
                    _md_text(reasoning["deterministicWork"]),
                    _fast_path_text(reasoning["fastPaths"]),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Условные быстрые пути",
            "",
            "Условный быстрый путь разрешён только тогда, когда код явно доказывает",
            "его предпосылки. Одного ответа модели об успехе недостаточно.",
            "",
        ]
    )
    conditional = [
        item
        for item in projection["commands"]
        if item["reasoning"]["mode"] == "conditional"
    ]
    for item in conditional:
        lines.append("### " + BT + item["command"] + BT)
        lines.append("")
        for fast_path in item["reasoning"]["fastPaths"]:
            lines.append("- " + fast_path["description"] + ".")
            lines.append(
                "  Реализация: " + BT + fast_path["implementation"] + BT + "."
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(projection: dict[str, Any]) -> str:
    return json.dumps(projection, ensure_ascii=False, indent=2) + "\n"


def validate_fast_path_implementations(
    root: Path,
    table: dict[str, Any],
) -> list[str]:
    """Проверить, что объявленный быстрый путь существует в указанном модуле."""

    errors: list[str] = []
    for item in _commands(table):
        for fast_path in item["reasoning"]["fastPaths"]:
            implementation = fast_path["implementation"]
            rel, symbol = implementation.split("::", 1)
            path = root / rel
            if not path.is_file():
                errors.append(
                    f"{item['command']}: файл быстрого пути не найден: {rel}"
                )
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(
                    f"{item['command']}: быстрый путь нельзя прочитать: {exc}"
                )
                continue
            pattern = re.compile(
                rf"^\s*def\s+{re.escape(symbol)}\s*\(",
                re.MULTILINE,
            )
            if pattern.search(text) is None:
                errors.append(
                    f"{item['command']}: функция быстрого пути не найдена: "
                    f"{implementation}"
                )
    return errors


def _replace_generated_block(text: str, block: str) -> str:
    if START_MARKER not in text or END_MARKER not in text:
        raise ValueError("в документе отсутствуют маркеры сгенерированного блока")
    before, rest = text.split(START_MARKER, 1)
    _old, after = rest.split(END_MARKER, 1)
    return (
        before
        + START_MARKER
        + "\n"
        + block.rstrip()
        + "\n"
        + END_MARKER
        + after
    )


def expected_document(projection: dict[str, Any], current: str | None = None) -> str:
    block = render_markdown_block(projection)
    if current is None:
        current = DOC_PREAMBLE + START_MARKER + "\n" + END_MARKER + "\n"
    return _replace_generated_block(current, block)


def projection_drift_errors(
    root: Path,
    table: dict[str, Any],
) -> list[str]:
    """Проверить Markdown/JSON проекции на точное соответствие CTS."""

    errors = validate_fast_path_implementations(root, table)
    projection = build_projection(table)

    json_path = root / JSON_PATH
    if not json_path.is_file():
        errors.append(f"отсутствует машиночитаемая проекция: {JSON_PATH}")
    else:
        try:
            actual_json = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"не удалось прочитать {JSON_PATH}: {exc}")
        else:
            if actual_json != projection:
                errors.append(
                    f"{JSON_PATH} не соответствует .harness/command-transitions.json"
                )

    doc_path = root / DOC_PATH
    if not doc_path.is_file():
        errors.append(f"отсутствует документ: {DOC_PATH}")
    else:
        try:
            actual_doc = doc_path.read_text(encoding="utf-8")
            expected_doc = expected_document(projection, actual_doc)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            errors.append(f"не удалось проверить {DOC_PATH}: {exc}")
        else:
            if actual_doc != expected_doc:
                errors.append(
                    f"{DOC_PATH} содержит устаревший сгенерированный блок"
                )
    return errors


def write_outputs(root: Path, table: dict[str, Any]) -> dict[str, Any]:
    """Пересобрать обе отслеживаемые проекции из канонического CTS."""

    projection = build_projection(table)
    json_path = root / JSON_PATH
    doc_path = root / DOC_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(render_json(projection), encoding="utf-8")
    current = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else None
    doc_path.write_text(
        expected_document(projection, current),
        encoding="utf-8",
    )
    return projection


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить или пересобрать границы вычислений модели."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--write",
        action="store_true",
        help="пересобрать Markdown и JSON из таблицы команд",
    )
    actions.add_argument(
        "--check",
        action="store_true",
        help="проверить, что Markdown, JSON и быстрые пути не устарели",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="вывести машиночитаемую проекцию",
    )
    args = parser.parse_args()

    root = repo_root()
    table = load_transition_table(root)
    schema_errors = validate_transition_table(table)
    if schema_errors:
        for item in schema_errors:
            print(item)
        return 1

    projection = write_outputs(root, table) if args.write else build_projection(table)
    errors = projection_drift_errors(root, table)

    if args.as_json:
        print(json.dumps(projection, ensure_ascii=False, indent=2))
    elif not args.check and not args.write:
        summary = projection["summary"]
        print(
            "ГРАНИЦЫ ВЫЧИСЛЕНИЙ: "
            f"всего {summary['total']}; "
            f"без модели {summary['none']}; "
            f"модель обязательна {summary['required']}; "
            f"зависит от сценария {summary['conditional']}"
        )

    if errors:
        for item in errors:
            print(f"ОШИБКА: {item}")
        return 1
    if args.check and not args.as_json:
        print("ГРАНИЦЫ ВЫЧИСЛЕНИЙ: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
