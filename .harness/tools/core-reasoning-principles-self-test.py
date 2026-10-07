#!/usr/bin/env python3
"""Synthetic regression suite for Core Reasoning Principles selection."""
from __future__ import annotations

from pathlib import Path
import copy
import shutil
import tempfile

from context_budget import evaluate_context_budget
from core_reasoning_principles import (
    CoreReasoningPrincipleError,
    NAMESPACE,
    applicability_signals,
    load_core_reasoning_principles,
    select_core_reasoning_principles,
)


ROOT = Path(__file__).resolve().parents[2]


def task(
    *,
    step_type: str = "implementation",
    risk_flags: list[str] | None = None,
    depends_on: list[str] | None = None,
    execution_groups: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "frontmatter": {
            "schema": 1,
            "id": "STEP-001",
            "status": "planned",
            "type": step_type,
            "priority": "medium",
            "phase": "P1",
            "depends_on": depends_on or [],
            "requirements": [],
            "adrs": [],
            "architecture_refs": [],
            "risk_flags": risk_flags or ["none"],
            "plan": {
                "status": "not_planned",
                "revision": 0,
                "execution_groups": execution_groups or {},
            },
        },
        "sections": {},
    }


def selected_ids(
    value: dict[str, object],
    *,
    role: str,
    artifact_count: int = 1,
    section_count: int = 7,
) -> list[str]:
    return [
        str(item["id"])
        for item in select_core_reasoning_principles(
            ROOT,
            value,
            role=role,
            artifact_count=artifact_count,
            section_count=section_count,
        )
    ]


def main() -> int:
    catalog = load_core_reasoning_principles(ROOT)
    assert len(catalog) == 8, catalog
    assert all(item["namespace"] == NAMESPACE == "CRP" for item in catalog)
    assert all(str(item["id"]).startswith("CRP-") for item in catalog)
    assert all("PRN-" not in str(item["id"]) for item in catalog)
    assert all(int(item["chars"]) <= 4_000 for item in catalog)
    catalog_chars = sum(int(item["chars"]) for item in catalog)

    # CRP leaves — pull-based surface и не увеличивают always-on AGENTS/CLAUDE budget.
    always_on = evaluate_context_budget(ROOT)
    assert always_on["status"] == "PASS", always_on

    # Обычный небольшой PLAN не получает ни одного принципа «на всякий случай».
    ordinary = task()
    assert selected_ids(ordinary, role="planner") == []

    # REVIEW получает ровно evidence-oriented leaf, а не весь каталог.
    review_selection = select_core_reasoning_principles(
        ROOT,
        ordinary,
        role="reviewer",
        artifact_count=1,
        section_count=7,
    )
    review_ids = [str(item["id"]) for item in review_selection]
    assert review_ids == ["CRP-003"], review_ids
    assert len(review_ids) < len(catalog)
    assert sum(int(item["chars"]) for item in review_selection) < catalog_chars

    # Большой Context Contract включает только guard-context leaf.
    heavy_ids = selected_ids(
        ordinary,
        role="planner",
        artifact_count=6,
        section_count=20,
    )
    assert heavy_ids == ["CRP-002"], heavy_ids

    # Concurrency выбирает structural shared-state principle.
    concurrent = task(risk_flags=["concurrency"])
    assert selected_ids(concurrent, role="planner") == ["CRP-005"]

    # Refactor получает только subtraction + reader-load principles.
    refactor = task(step_type="refactor")
    assert selected_ids(refactor, role="planner") == ["CRP-007", "CRP-008"]

    # Bugfix включает structural-learning и premise-challenge leaves.
    bugfix = task(step_type="bugfix")
    assert selected_ids(bugfix, role="planner") == ["CRP-001", "CRP-006"]

    # Multi-unit определяется декларативными facts, а не keywords в prose.
    multi = task(
        execution_groups={
            "a": {"depends_on": []},
            "b": {"depends_on": ["a"]},
        }
    )
    assert selected_ids(multi, role="implementer") == ["CRP-004"]

    migration = task(risk_flags=["data-migration"])
    assert selected_ids(migration, role="planner") == ["CRP-004"]

    # Несколько signals могут выбрать несколько независимых leaves, но selection
    # остаётся существенно меньше полного каталога.
    complex_case = task(
        step_type="refactor",
        risk_flags=["architecture", "concurrency"],
        depends_on=["STEP-010", "STEP-011"],
    )
    complex_ids = selected_ids(
        complex_case,
        role="reviewer",
        artifact_count=8,
        section_count=30,
    )
    assert complex_ids == [
        "CRP-002",
        "CRP-003",
        "CRP-004",
        "CRP-005",
        "CRP-007",
        "CRP-008",
    ], complex_ids
    assert len(complex_ids) < len(catalog)

    # Malformed canonical facts fail closed instead of silently producing
    # an empty applicability set.
    for malformed in (
        {"risk_flags": "none"},
        {"depends_on": "STEP-010"},
        {"plan": []},
    ):
        broken = task()
        frontmatter = broken["frontmatter"]
        assert isinstance(frontmatter, dict)
        frontmatter.update(malformed)
        try:
            applicability_signals(
                broken,
                role="planner",
                artifact_count=1,
                section_count=7,
            )
        except CoreReasoningPrincipleError:
            pass
        else:
            raise AssertionError("malformed STEP facts must fail closed")

    # Unexpected Markdown inside the leaves directory cannot bypass catalog
    # validation by using a non-CRP filename.
    with tempfile.TemporaryDirectory(prefix="crp-catalog-") as tmp:
        isolated = Path(tmp)
        destination = (
            isolated
            / ".agents"
            / "skills"
            / "core-reasoning-principles"
            / "leaves"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            ROOT / ".agents/skills/core-reasoning-principles/leaves",
            destination,
        )
        (destination / "notes.md").write_text(
            "# Hidden rule\n",
            encoding="utf-8",
        )
        try:
            load_core_reasoning_principles(isolated)
        except CoreReasoningPrincipleError:
            pass
        else:
            raise AssertionError("unexpected leaf file must fail closed")

    # Applicability itself is deterministic and runtime-neutral.
    codex_signals = applicability_signals(
        copy.deepcopy(complex_case),
        role="reviewer",
        artifact_count=8,
        section_count=30,
    )
    claude_signals = applicability_signals(
        copy.deepcopy(complex_case),
        role="reviewer",
        artifact_count=8,
        section_count=30,
    )
    assert codex_signals == claude_signals

    print("core-reasoning-principles self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
