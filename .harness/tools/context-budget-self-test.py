#!/usr/bin/env python3
"""Synthetic regressions для context_budget.py."""
from __future__ import annotations

from pathlib import Path
import tempfile

from context_budget import evaluate_context_budget


TEST_BUDGETS = {
    "codex": {"files": ("AGENTS.md",), "max_chars": 32},
    "claude": {"files": ("AGENTS.md", "CLAUDE.md"), "max_chars": 48},
}


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        agents = (
            "core\n"
            "<!-- PROJECT-CONTEXT:START -->\n"
            + ("P" * 500)
            + "\n<!-- PROJECT-CONTEXT:END -->\n"
            "<!-- SKILL-ROUTING:START -->\n"
            "route\n"
            "<!-- SKILL-ROUTING:END -->\n"
        )
        write(root, "AGENTS.md", agents)
        write(root, "CLAUDE.md", "@AGENTS.md\nadapter\n")

        result = evaluate_context_budget(root, budgets=TEST_BUDGETS)
        assert result["status"] == "PASS", result
        assert result["files"]["AGENTS.md"]["projectChars"] > 500
        assert result["runtimes"]["codex"]["controlledChars"] == len("core\n")
        assert result["runtimes"]["codex"]["observedChars"] > 500

        # Project-generated marker content не расходует core Harness budget.
        write(
            root,
            "AGENTS.md",
            agents.replace("P" * 500, "P" * 5000),
        )
        result = evaluate_context_budget(root, budgets=TEST_BUDGETS)
        assert result["status"] == "PASS", result

        # Рост Harness-controlled bootstrap text обязан блокироваться.
        write(root, "AGENTS.md", "X" * 33)
        result = evaluate_context_budget(root, budgets=TEST_BUDGETS)
        assert result["status"] == "FAIL"
        assert any("codex:" in item for item in result["errors"])

        # Malformed marker не должен позволять исключить хвост файла из budget.
        write(
            root,
            "AGENTS.md",
            "core\n<!-- PROJECT-CONTEXT:START -->\nunterminated\n",
        )
        result = evaluate_context_budget(root, budgets=TEST_BUDGETS)
        assert result["status"] == "FAIL"
        assert any("PROJECT-CONTEXT" in item for item in result["errors"])

        # Отсутствующий runtime bootstrap file является deterministic failure.
        write(root, "AGENTS.md", "core\n")
        (root / "CLAUDE.md").unlink()
        result = evaluate_context_budget(root, budgets=TEST_BUDGETS)
        assert result["status"] == "FAIL"
        assert any("CLAUDE.md" in item for item in result["errors"])

    print("context-budget self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
