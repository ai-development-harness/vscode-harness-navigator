#!/usr/bin/env python3
"""Workflow regressions for clarification persistence and re-check semantics.

Semantic judgement itself remains model-owned. The fixture evaluator exists only
to prove the repository contract around that judgement:
incomplete canonical input -> NEEDS_INPUT -> persisted answer -> PASS.
"""
from __future__ import annotations

from pathlib import Path
import tempfile

from requirements_quality import normalize_result


BASE_QUALITY = {
    "completeness": "pass",
    "clarity": "pass",
    "measurability": "pass",
    "scenarioCoverage": "pass",
}
ANSWER = "Recovery policy: retry once after timeout, then return a terminal error."


def semantic_fixture(req_text: str) -> dict[str, object]:
    """Deterministic stand-in used only to exercise clarification workflow."""
    if ANSWER in req_text:
        return {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": dict(BASE_QUALITY),
            "findings": [],
        }
    return {
        "schemaVersion": 1,
        "status": "NEEDS_INPUT",
        "quality": {**BASE_QUALITY, "completeness": "fail"},
        "findings": [
            {
                "code": "AMBIGUOUS_RECOVERY_POLICY",
                "severity": "blocking",
                "owner": "REQ-014",
                "question": "Какой recovery behavior обязателен после timeout?",
                "rationale": "Ответ меняет acceptance и retry semantics.",
                "sourceRefs": ["REQ-014#Reliability"],
            }
        ],
    }


def evaluate_for_runtimes(req_path: Path) -> dict[str, dict[str, object]]:
    text = req_path.read_text(encoding="utf-8")
    return {
        runtime: normalize_result(semantic_fixture(text))
        for runtime in ("codex", "claude")
    }


def assert_skill_wiring(repo_root: Path) -> None:
    paths = (
        ".agents/skills/init-project/SKILL.md",
        ".agents/skills/add-plan-step/SKILL.md",
        ".agents/skills/plan-step/SKILL.md",
    )
    for relative in paths:
        text = (repo_root / relative).read_text(encoding="utf-8")
        assert "Requirements Quality Gate" in text, relative
        assert "\\n" not in text, f"{relative}: literal \\n leaked into Markdown"

    plan = (repo_root / ".agents/skills/plan-step/SKILL.md").read_text(encoding="utf-8")
    assert "не спрашивай то, что уже зафиксировано" in plan
    assert "сохрани в соответствующий REQ/ADR/OQ/STEP и запусти gate повторно" in plan


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    assert_skill_wiring(repo_root)

    with tempfile.TemporaryDirectory() as tmp:
        req_path = Path(tmp) / "REQ-014.md"
        req_path.write_text(
            "# REQ-014\n\n## Reliability\n\nTimeout recovery is not defined.\n",
            encoding="utf-8",
        )

        first = evaluate_for_runtimes(req_path)
        assert first["codex"] == first["claude"]
        assert first["codex"]["status"] == "NEEDS_INPUT"
        assert first["codex"]["findings"][0]["code"] == "AMBIGUOUS_RECOVERY_POLICY"

        # Required persistence: answer is written into the canonical owner,
        # never only into chat/runtime state.
        req_path.write_text(
            req_path.read_text(encoding="utf-8") + f"\n{ANSWER}\n",
            encoding="utf-8",
        )

        second = evaluate_for_runtimes(req_path)
        assert second["codex"] == second["claude"]
        assert second["codex"]["status"] == "PASS"
        assert second["codex"]["findings"] == []

        # Further runs must use the canonical answer and not repeat the question.
        third = evaluate_for_runtimes(req_path)
        assert third == second

    print("requirements-quality workflow self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
