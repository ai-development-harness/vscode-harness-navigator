#!/usr/bin/env python3
"""Deterministic budget gate для always-on контекста AI Development Harness.

Цель модуля — не оценивать стоимость конкретного tokenizer, а держать под
контролем объём текста Harness, который runtime обязан загрузить до выбора
command-specific skill. Измерение в Unicode characters стабильно между
runtime/model версиями и не требует внешних dependencies.

В hard budget входят только Harness-controlled bootstrap instructions:
- Codex: AGENTS.md без project-generated marker blocks;
- Claude Code: тот же AGENTS.md + CLAUDE.md adapter.

PROJECT-CONTEXT и SKILL-ROUTING намеренно выводятся отдельно: это project-owned
динамический контекст. Tool показывает их размер, но baseline core Harness они
не могут скрыто увеличивать или уменьшать.

Budget constants первоначально введены в v0.7.0 и после bootstrap refactor зафиксированы на новом минимальном baseline. Их изменение является явным
архитектурным решением и должно быть видно в diff/review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = 1
PROJECT_MARKERS = ("PROJECT-CONTEXT", "SKILL-ROUTING")

DEFAULT_BUDGETS: dict[str, dict[str, Any]] = {
    "codex": {
        "files": ("AGENTS.md",),
        "max_chars": 7224,
    },
    "claude": {
        "files": ("AGENTS.md", "CLAUDE.md"),
        "max_chars": 8029,
    },
}


def _strip_project_blocks(text: str) -> tuple[str, int, list[str]]:
    """Исключить project-owned generated blocks из core Harness budget.

    Marker boundary проверяется fail-closed: незакрытый/дублирующийся marker не
    должен позволять случайно исключить произвольный хвост AGENTS.md из budget.
    """
    controlled = text
    project_chars = 0
    errors: list[str] = []

    for marker in PROJECT_MARKERS:
        start = f"<!-- {marker}:START -->"
        end = f"<!-- {marker}:END -->"
        start_count = controlled.count(start)
        end_count = controlled.count(end)

        if start_count == 0 and end_count == 0:
            continue
        if start_count != 1 or end_count != 1:
            errors.append(
                f"AGENTS.md: marker {marker} must have exactly one START and END"
            )
            continue

        pattern = re.compile(
            rf"{re.escape(start)}[\s\S]*?{re.escape(end)}\n?"
        )
        match = pattern.search(controlled)
        if match is None:
            errors.append(f"AGENTS.md: malformed marker block {marker}")
            continue

        project_chars += len(match.group(0))
        controlled = controlled[: match.start()] + controlled[match.end() :]

    return controlled, project_chars, errors


def _read_surface(root: Path, rel: str) -> dict[str, Any]:
    """Прочитать один bootstrap file и разделить core/project contribution."""
    path = root / rel
    if not path.is_file():
        return {
            "path": rel,
            "error": f"missing always-on context file: {rel}",
            "controlledChars": 0,
            "projectChars": 0,
            "observedChars": 0,
        }

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "path": rel,
            "error": f"cannot read {rel}: {exc}",
            "controlledChars": 0,
            "projectChars": 0,
            "observedChars": 0,
        }

    controlled_text = text
    project_chars = 0
    errors: list[str] = []
    if rel == "AGENTS.md":
        controlled_text, project_chars, errors = _strip_project_blocks(text)

    result: dict[str, Any] = {
        "path": rel,
        "controlledChars": len(controlled_text),
        "projectChars": project_chars,
        "observedChars": len(text),
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def evaluate_context_budget(
    root: Path,
    *,
    budgets: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Вернуть machine-readable budget result без mutation."""
    selected = budgets or DEFAULT_BUDGETS
    files = sorted(
        {
            str(rel)
            for spec in selected.values()
            for rel in spec.get("files", ())
        }
    )
    surfaces = {rel: _read_surface(root, rel) for rel in files}
    errors = [
        str(surface["error"])
        for surface in surfaces.values()
        if surface.get("error")
    ]

    runtimes: dict[str, Any] = {}
    for runtime, spec in selected.items():
        runtime_files = tuple(str(rel) for rel in spec.get("files", ()))
        max_chars = spec.get("max_chars")
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
            errors.append(f"{runtime}: max_chars must be a positive integer")
            continue

        controlled_chars = sum(
            int(surfaces[rel]["controlledChars"])
            for rel in runtime_files
            if rel in surfaces
        )
        project_chars = sum(
            int(surfaces[rel]["projectChars"])
            for rel in runtime_files
            if rel in surfaces
        )
        observed_chars = sum(
            int(surfaces[rel]["observedChars"])
            for rel in runtime_files
            if rel in surfaces
        )
        within = controlled_chars <= max_chars
        if not within:
            errors.append(
                f"{runtime}: controlled always-on context is "
                f"{controlled_chars} chars, budget is {max_chars}"
            )
        runtimes[runtime] = {
            "files": list(runtime_files),
            "controlledChars": controlled_chars,
            "projectChars": project_chars,
            "observedChars": observed_chars,
            "maxChars": max_chars,
            "remainingChars": max_chars - controlled_chars,
            "withinBudget": within,
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS" if not errors else "FAIL",
        "unit": "unicode-characters",
        "runtimes": runtimes,
        "files": surfaces,
        "errors": errors,
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check always-on Harness context against deterministic char budgets."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root; defaults to the repository containing this tool.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()
    result = evaluate_context_budget((args.root or repo_root()).resolve())

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"CONTEXT BUDGET: {result['status']}")
        for runtime, item in result["runtimes"].items():
            print(
                f"  {runtime}: {item['controlledChars']}/{item['maxChars']} "
                f"controlled chars; project={item['projectChars']}"
            )
        for error in result["errors"]:
            print(f"  - {error}")

    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
