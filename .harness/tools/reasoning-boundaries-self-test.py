#!/usr/bin/env python3
"""Regression-проверки проекции границ вычислений модели."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile

from command_transitions import load_transition_table, validate_transition_table
from reasoning_boundaries import (
    build_projection,
    projection_drift_errors,
    render_markdown_block,
    validate_fast_path_implementations,
    write_outputs,
)


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    table = load_transition_table(SOURCE_ROOT)
    projection = build_projection(table)
    summary = projection["summary"]
    assert summary["total"] == len(projection["commands"]), summary
    assert (
        summary["none"] + summary["required"] + summary["conditional"]
        == summary["total"]
    ), summary
    assert summary["none"] > 0, summary
    assert summary["required"] > 0, summary
    assert summary["conditional"] > 0, summary
    assert projection["classification"]["scope"] == "command-node", projection

    markdown = render_markdown_block(projection)
    assert "Без вычислений модели" in markdown
    assert "Вычисления модели обязательны" in markdown
    assert "Зависит от сценария" in markdown
    assert "STEP RUN STEP-NNN" in markdown
    assert "GIT PUSH" in markdown
    assert "pie showData" in markdown
    assert "flowchart LR" in markdown

    missing = deepcopy(table)
    del missing["domains"]["PROJECT"]["commands"]["STATUS"]["reasoning"]
    errors = validate_transition_table(missing)
    assert any(
        "PROJECT.STATUS.reasoning must be an object" in item
        for item in errors
    ), errors

    mismatch = deepcopy(table)
    mismatch["domains"]["PROJECT"]["commands"]["STATUS"]["reasoning"]["mode"] = "required"
    mismatch["domains"]["PROJECT"]["commands"]["STATUS"]["reasoning"]["modelWork"] = [
        "Лишнее вычисление модели"
    ]
    errors = validate_transition_table(mismatch)
    assert any(
        "deterministic dispatch requires reasoning.mode=none" in item
        for item in errors
    ), errors

    conditional = deepcopy(table)
    commit_reasoning = conditional["domains"]["GIT"]["commands"]["COMMIT"]["reasoning"]
    commit_reasoning["mode"] = "conditional"
    commit_reasoning["fastPaths"] = []
    errors = validate_transition_table(conditional)
    assert any(
        "reasoning.mode=conditional requires at least one fastPath" in item
        for item in errors
    ), errors

    broken_fast_path = deepcopy(table)
    broken_fast_path["domains"]["GIT"]["commands"]["PUSH"]["reasoning"]["fastPaths"][0][
        "implementation"
    ] = ".harness/tools/command_dispatch.py::_missing_fast_path"
    errors = validate_fast_path_implementations(SOURCE_ROOT, broken_fast_path)
    assert any("_missing_fast_path" in item for item in errors), errors

    with tempfile.TemporaryDirectory(prefix="reasoning-boundaries-") as tmp:
        root = Path(tmp)
        (root / ".harness/tools").mkdir(parents=True)
        shutil.copy2(
            SOURCE_ROOT / ".harness/tools/command_dispatch.py",
            root / ".harness/tools/command_dispatch.py",
        )

        write_outputs(root, table)
        assert projection_drift_errors(root, table) == []

        json_path = root / ".harness/reasoning-boundaries.json"
        stale = json.loads(json_path.read_text(encoding="utf-8"))
        stale["summary"]["none"] += 1
        json_path.write_text(
            json.dumps(stale, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        errors = projection_drift_errors(root, table)
        assert any("reasoning-boundaries.json" in item for item in errors), errors

        write_outputs(root, table)
        doc_path = root / ".harness/docs/REASONING_BOUNDARIES.md"
        text = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(
            text.replace("Без вычислений модели", "Устаревшее описание", 1),
            encoding="utf-8",
        )
        errors = projection_drift_errors(root, table)
        assert any("устаревший сгенерированный блок" in item for item in errors), errors

    print("reasoning boundaries self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
