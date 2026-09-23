#!/usr/bin/env python3
"""Synthetic regression suite structured semantic artifact writers."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from execution_status import resolve_root, start_execution
from planning_contract import read_task, validate_planning_review_report
from review_contract import validate_review_report
from semantic_artifacts import (
    SemanticArtifactError,
    write_plan_draft,
    write_planning_review,
    write_step_review,
)


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=SOURCE_ROOT,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = token.decode("utf-8")
        source = SOURCE_ROOT / rel
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def task() -> str:
    tick = chr(96)
    return f"""---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: test
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — Structured writer fixture

## Goal

Проверить deterministic writers.

## Context

Synthetic fixture.

## Scope

- Writer flow.

## Mutation policy

### Allowed

- planning artifacts.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- Product work.

## Acceptance criteria

- Artifacts validate.

## Verification

- command: {tick}python3 -c "print(1)"{tick}

## Deliverables

- Valid reports.

## Implementation plan

Требуется PLAN.

## Evidence

—

## Blocker / Failure reason

—
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-semantic-writers-") as tmp:
        root = Path(tmp)
        copy_tracked(root)
        step_path = root / "planning/tasks/STEP-001.md"
        step_path.parent.mkdir(parents=True, exist_ok=True)
        step_path.write_text(task(), encoding="utf-8", newline="\n")

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "writers@example.invalid")
        run(root, "git", "config", "user.name", "Writers Test")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        plan = write_plan_draft(
            root,
            "STEP-001",
            {
                "implementationPlan": [
                    {
                        "title": "Изменить модуль",
                        "actions": [
                            "Обновить основной deterministic writer.",
                            "Сохранить semantic scope без ручного frontmatter.",
                        ],
                        "files": [".harness/tools/semantic_artifacts.py"],
                        "tests": ["Добавить regression для rendered plan."],
                        "risks": ["Не позволить модели подменить metadata."],
                    },
                    {
                        "title": "Добавить тест",
                        "actions": ["Проверить canonical Markdown rendering."],
                    },
                ],
                "verification": [
                    {"kind": "command", "value": 'python3 -c "print(2)"'},
                    {"kind": "manual", "value": "Проверить semantic outcome"},
                ],
            },
        )
        assert plan["status"] == "PASS", plan
        planned = read_task(root, "STEP-001")
        assert planned["frontmatter"]["plan"]["status"] == "draft", planned
        assert planned["frontmatter"]["plan"]["context_basis"] is None
        assert "Изменить модуль" in planned["sections"]["Implementation plan"]
        assert "- manual: Проверить semantic outcome" in planned["sections"]["Verification"]
        assert "**Files:**" in planned["sections"]["Implementation plan"]
        assert ".harness/tools/semantic_artifacts.py" in planned["sections"]["Implementation plan"]
        assert plan["implementationPlan"][0]["title"] == "Изменить модуль"

        try:
            write_plan_draft(
                root,
                "STEP-001",
                {
                    "implementationPlan": [
                        {"title": "x", "actions": ["y"]}
                    ],
                    "verification": [{"kind": "command", "value": "python3 -V"}],
                    "unexpected": True,
                },
            )
        except SemanticArtifactError:
            pass
        else:
            raise AssertionError("unknown plan payload key was accepted")

        try:
            write_plan_draft(
                root,
                "STEP-001",
                {
                    "implementationPlan": [
                        {
                            "title": "Bad\n## Injected",
                            "actions": ["Would corrupt structure"],
                        }
                    ],
                    "verification": [
                        {"kind": "command", "value": "python3 -V"}
                    ],
                },
            )
        except SemanticArtifactError:
            pass
        else:
            raise AssertionError("multiline plan title was accepted")

        planning_review = write_planning_review(
            root,
            "STEP-001",
            {
                "verdict": "pass",
                "findings": [],
                "rationale": "Plan согласован с contract и verification feasible.",
            },
        )
        assert planning_review["status"] == "PASS", planning_review
        assert planning_review["completionResult"] == "SUCCESS", planning_review
        planning_report = root / planning_review["report"]
        assert not validate_planning_review_report(
            root, planning_report, expected_step_id="STEP-001"
        )
        ready = read_task(root, "STEP-001")
        assert ready["frontmatter"]["plan"]["status"] == "ready", ready
        assert ready["frontmatter"]["plan"]["reviewed_report"] == planning_review["report"]

        # Semantic PASS alone cannot close a STEP without durable Evidence.
        incomplete_review = write_step_review(
            root,
            "STEP-001",
            {
                "verdict": "pass",
                "findings": [],
                "verificationObservations": "Semantic review itself passed.",
                "rationale": "Material implementation defects не обнаружены.",
                "specializedReviews": {
                    "tests": {
                        "status": "pass",
                        "evidence": "Test reviewer подтвердил coverage.",
                    }
                },
            },
        )
        assert incomplete_review["status"] == "PASS", incomplete_review
        assert incomplete_review["completionResult"] == "BLOCKED", incomplete_review
        assert incomplete_review["reasonCode"] == "STEP_COMPLETION_PROOF_INCOMPLETE"
        assert read_task(root, "STEP-001")["frontmatter"]["status"] == "planned"

        # Add factual implementation lifecycle/Evidence, then start REVIEW so
        # crash recovery records the first PASS report as its baseline.
        current_text = step_path.read_text(encoding="utf-8")
        current_text = current_text.replace("status: planned", "status: in_progress", 1)
        current_text = current_text.replace(
            "## Evidence\n\n—",
            "## Evidence\n\nVerification runner: PASS.",
            1,
        )
        step_path.write_text(current_text, encoding="utf-8", newline="\n")
        review_execution = start_execution(root, "STEP REVIEW STEP-001")
        assert review_execution["status"] == "running", review_execution

        step_review = write_step_review(
            root,
            "STEP-001",
            {
                "verdict": "pass",
                "findings": [],
                "verificationObservations": "Generated Evidence и test command проверены.",
                "rationale": "Material defects не обнаружены.",
                "specializedReviews": {
                    "tests": {
                        "status": "pass",
                        "evidence": "Test reviewer подтвердил достаточность coverage.",
                    }
                },
            },
        )
        assert step_review["status"] == "PASS", step_review
        assert step_review["completionResult"] == "PASS", step_review
        assert step_review["stepCompletion"]["completed"] is True, step_review
        assert step_review["specializedReviewGate"]["required"] == ["tests"], step_review
        assert read_task(root, "STEP-001")["frontmatter"]["status"] == "completed"

        review_report = root / step_review["report"]
        assert not validate_review_report(
            root,
            review_report,
            expected_step_id="STEP-001",
        )

        # The lifecycle-only completed mutation changes current revision after
        # review. Recovery must still prove PASS from new report + completion proof.
        recovered = resolve_root(root, "STEP REVIEW STEP-001")
        assert recovered["status"] == "DONE", recovered

        before = set((root / "planning/reviews/STEP-001").glob("REVIEW-*.md"))
        try:
            write_step_review(
                root,
                "STEP-001",
                {
                    "verdict": "fail",
                    "findings": [
                        {
                            "title": "Contract defect",
                            "severity": "high",
                            "category": "contract",
                            "location": "STEP contract",
                            "scenario": "Given invalid contract",
                            "impact": "FIX не имеет права менять contract",
                            "fixDirection": "Создать corrective STEP",
                        }
                    ],
                    "verificationObservations": "N/A",
                    "rationale": "Invalid composition fixture.",
                    "specializedReviews": {
                        "tests": {"status": "pass", "evidence": "Tests checked."}
                    },
                },
            )
        except SemanticArtifactError:
            pass
        else:
            raise AssertionError("FAIL contract finding was accepted")
        after = set((root / "planning/reviews/STEP-001").glob("REVIEW-*.md"))
        assert before == after, (before, after)

    print("SEMANTIC ARTIFACTS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
