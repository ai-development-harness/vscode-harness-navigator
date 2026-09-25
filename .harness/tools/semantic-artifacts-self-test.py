#!/usr/bin/env python3
"""Synthetic regression suite structured semantic artifact writers."""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import tempfile

from command_dispatch import start_dispatch
from execution_status import (
    block_execution,
    complete_command,
    implementation_baseline_for_step,
    load_status,
    resolve_root,
    review_expectation_for_step,
    stamp_review_expectation,
    start_execution,
)
from planning_contract import read_task, validate_planning_review_report
from review_contract import repository_revision, validate_review_report
from review_gates import required_reviewers
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
        # Tracked path, удалённый из working tree, но не из index (обычный `rm`
        # без `git rm`), fixture не нужен — пропускаем вместо traceback.
        if not source.is_file():
            continue
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

        # Regression #85: file payload — одноразовый transport. Нормально
        # завершившийся writer удаляет его, validation/parsing failure оставляет
        # файл для retry.
        cleanup_step = root / "planning/tasks/STEP-999.md"
        cleanup_step.write_text(
            task().replace("STEP-001", "STEP-999"),
            encoding="utf-8",
            newline="\n",
        )
        cleanup_payload = root / ".harness/local/semantic/plan-999.json"
        cleanup_payload.parent.mkdir(parents=True, exist_ok=True)
        cleanup_payload.write_text(
            json.dumps(
                {
                    "implementationPlan": [
                        {
                            "title": "Проверить cleanup",
                            "actions": ["Создать валидный draft."],
                        }
                    ],
                    "verification": [
                        {"kind": "command", "value": "python3 -V"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cleanup_proc = subprocess.run(
            [
                "python3",
                ".harness/tools/semantic-writer.py",
                "plan-draft",
                "STEP-999",
                "--payload-file",
                ".harness/local/semantic/plan-999.json",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert cleanup_proc.returncode == 0, (
            cleanup_proc.stdout,
            cleanup_proc.stderr,
        )
        assert not cleanup_payload.exists(), cleanup_payload

        failed_payload = root / ".harness/local/semantic/invalid-999.json"
        failed_payload.write_text("{invalid json", encoding="utf-8")
        failed_proc = subprocess.run(
            [
                "python3",
                ".harness/tools/semantic-writer.py",
                "plan-draft",
                "STEP-999",
                "--payload-file",
                ".harness/local/semantic/invalid-999.json",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert failed_proc.returncode == 1, failed_proc.stdout
        assert failed_payload.is_file(), failed_payload

        # Cleanup не имеет права следовать symlink и удалять target. До #85
        # Path.resolve() скрывал symlink до проверки, поэтому unlink удалял
        # фактический recovery/unknown target вместо transport path.
        preserved_payload_target = root / ".harness/local/preserved-payload.json"
        preserved_payload_target.write_text(
            json.dumps({"doNotDelete": True}),
            encoding="utf-8",
        )
        payload_symlink = root / ".harness/local/semantic/payload-link.json"
        payload_symlink.symlink_to("../preserved-payload.json")
        symlink_proc = subprocess.run(
            [
                "python3",
                ".harness/tools/semantic-writer.py",
                "plan-draft",
                "STEP-999",
                "--payload-file",
                ".harness/local/semantic/payload-link.json",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert symlink_proc.returncode == 1, symlink_proc.stdout
        assert payload_symlink.is_symlink(), payload_symlink
        assert preserved_payload_target.is_file(), preserved_payload_target

        parent_target = root / ".harness/local/semantic-parent"
        parent_target.mkdir()
        parent_payload = parent_target / "parent.json"
        parent_payload.write_text(
            json.dumps({"doNotDelete": True}),
            encoding="utf-8",
        )
        parent_link = root / ".harness/local/semantic-alias"
        parent_link.symlink_to(parent_target.name, target_is_directory=True)
        parent_proc = subprocess.run(
            [
                "python3",
                ".harness/tools/semantic-writer.py",
                "plan-draft",
                "STEP-999",
                "--payload-file",
                ".harness/local/semantic-alias/parent.json",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert parent_proc.returncode == 1, parent_proc.stdout
        assert parent_link.is_symlink(), parent_link
        assert parent_payload.is_file(), parent_payload

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

        incomplete_payload = {
            "verdict": "pass",
            "findings": [],
            "verificationObservations": "Semantic review itself passed.",
            "rationale": "Material implementation defects не обнаружены.",
            "specializedReviews": {
                "security": {
                    "status": "pass",
                    "evidence": "Security reviewer подтвердил conservative fallback.",
                },
                "tests": {
                    "status": "pass",
                    "evidence": "Test reviewer подтвердил coverage.",
                },
            },
        }

        # Regression #112: verdict вне active STEP REVIEW не имеет stamped
        # expectation и не должен породить durable report/completion.
        reviews_dir = root / "planning/reviews/STEP-001"
        before_orphan = set(reviews_dir.glob("REVIEW-*.md"))
        try:
            write_step_review(root, "STEP-001", incomplete_payload)
        except SemanticArtifactError as exc:
            assert "requires an active STEP REVIEW" in str(exc), str(exc)
        else:
            raise AssertionError("STEP REVIEW verdict without active REVIEW was accepted")
        assert set(reviews_dir.glob("REVIEW-*.md")) == before_orphan
        assert read_task(root, "STEP-001")["frontmatter"]["status"] == "planned"

        # Semantic PASS alone cannot close a STEP without durable Evidence.
        # Expectation stamp-ится так же, как это делает dispatcher перед handoff.
        orphan_review = start_execution(root, "STEP REVIEW STEP-001")
        orphan_baseline = implementation_baseline_for_step(root, "STEP-001")
        orphan_gate = required_reviewers(
            root,
            "STEP-001",
            implementation_baseline=(
                orphan_baseline.get("gitHead") if orphan_baseline else None
            ),
        )
        stamp_review_expectation(
            root,
            orphan_review["executionId"],
            "STEP-001",
            repository_revision(root),
            orphan_gate["basis"],
        )
        incomplete_review = write_step_review(root, "STEP-001", incomplete_payload)
        assert incomplete_review["status"] == "PASS", incomplete_review
        assert incomplete_review["completionResult"] == "BLOCKED", incomplete_review
        assert incomplete_review["reasonCode"] == "STEP_COMPLETION_PROOF_INCOMPLETE"
        assert read_task(root, "STEP-001")["frontmatter"]["status"] == "planned"
        block_execution(root, "STEP REVIEW STEP-001")

        # Зафиксировать Ready planning state до implementation lifecycle.
        # Baseline должен быть HEAD непосредственно перед первой product mutation.
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "prepare implementation baseline")

        implementation_execution = start_execution(
            root,
            "STEP IMPLEMENT STEP-001",
        )
        implementation_baseline = implementation_execution.get(
            "implementationBaseline"
        )
        assert implementation_baseline, implementation_execution
        baseline_head = implementation_baseline["gitHead"]
        assert implementation_baseline_for_step(root, "STEP-001") == implementation_baseline

        # Regression #80: implementation занимает несколько commits. Security
        # path находится в первом, tests — во втором, последний commit содержит
        # только docs/evidence. Clean REVIEW обязан видеть полный baseline..HEAD.
        current_text = step_path.read_text(encoding="utf-8")
        current_text = current_text.replace("status: planned", "status: in_progress", 1)
        current_text = current_text.replace(
            "## Evidence\n\n—",
            "## Evidence\n\nVerification runner: PASS.",
            1,
        )
        step_path.write_text(current_text, encoding="utf-8", newline="\n")
        auth_path = root / "src/auth/session.py"
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_text("def secure_session():\n    return True\n", encoding="utf-8")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "implementation security change")

        test_path = root / "tests/session_test.py"
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text("def test_session():\n    assert True\n", encoding="utf-8")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "implementation tests")

        note_path = root / "docs/implementation-note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("# Implementation note\n", encoding="utf-8")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "implementation docs")

        complete_command(
            root,
            implementation_execution["rootCommand"],
            "STEP IMPLEMENT STEP-001",
            "SUCCESS",
        )

        # Отдельная REVIEW invocation после restart/session boundary наследует
        # durable baseline завершённого IMPLEMENT. Используем canonical dispatcher,
        # чтобы regression #83 проверял реальный stamp expectation до handoff.
        review_handoff = start_dispatch(root, "STEP REVIEW STEP-001")
        assert review_handoff["status"] == "SEMANTIC", review_handoff
        deterministic = review_handoff["context"]["deterministic"]
        assert deterministic["implementationBaseline"]["gitHead"] == baseline_head
        restored_baseline = implementation_baseline_for_step(root, "STEP-001")
        assert restored_baseline and restored_baseline["gitHead"] == baseline_head

        clean_gate = deterministic["specializedReviewGate"]
        assert clean_gate["surfaceMode"] == "implementation-baseline", clean_gate
        assert clean_gate["baselineStatus"] == "valid", clean_gate
        assert clean_gate["implementationBaseline"] == baseline_head, clean_gate
        assert "src/auth/session.py" in clean_gate["changedPaths"], clean_gate
        assert "tests/session_test.py" in clean_gate["changedPaths"], clean_gate
        assert "docs/implementation-note.md" in clean_gate["changedPaths"], clean_gate
        assert clean_gate["required"] == ["security", "tests"], clean_gate

        review_revision = deterministic["repositoryRevision"]
        assert review_revision == repository_revision(root)
        stamped_expectation = review_expectation_for_step(root, "STEP-001")
        assert stamped_expectation == {
            "stepId": "STEP-001",
            "repositoryRevision": review_revision,
            "gateBasis": clean_gate["basis"],
        }, stamped_expectation
        pass_review_payload = {
            "verdict": "pass",
            "findings": [],
            "verificationObservations": "Generated Evidence и test command проверены.",
            "rationale": "Material defects не обнаружены.",
            "specializedReviews": {
                "security": {
                    "status": "pass",
                    "evidence": "Security reviewer подтвердил отсутствие material risks.",
                },
                "tests": {
                    "status": "pass",
                    "evidence": "Test reviewer подтвердил достаточность coverage.",
                },
            },
        }

        # Regression #83: reviewer видел exact R1. Изменение bytes того же path
        # после handoff не меняет path-set, но обязано invalid-нуть expectation
        # по repositoryRevision; stale verdict не должен породить report.
        before_stale = set(
            (root / "planning/reviews/STEP-001").glob("REVIEW-*.md")
        )
        note_before = note_path.read_text(encoding="utf-8")
        note_path.write_text(
            note_before + "\nmutation after semantic handoff\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            write_step_review(
                root,
                "STEP-001",
                pass_review_payload,
            )
        except SemanticArtifactError as exc:
            assert "repository revision changed" in str(exc), str(exc)
        else:
            raise AssertionError("stale STEP REVIEW verdict was accepted")
        after_stale = set(
            (root / "planning/reviews/STEP-001").glob("REVIEW-*.md")
        )
        assert after_stale == before_stale, (before_stale, after_stale)

        # После exact restore R1 тот же stamped expectation снова применим.
        note_path.write_text(note_before, encoding="utf-8", newline="\n")
        assert repository_revision(root) == review_revision

        step_review = write_step_review(
            root,
            "STEP-001",
            pass_review_payload,
        )
        assert step_review["status"] == "PASS", step_review
        # Regression #114: writer связывает report с active REVIEW execution.
        assert step_review["provenanceRecorded"] is True, step_review
        review_records = [
            item["current"]["context"].get("reviewReport")
            for item in load_status(root)["executions"]
            if isinstance(item.get("current"), dict)
            and isinstance(item["current"].get("context"), dict)
        ]
        assert any(
            record and record.get("path") == step_review["report"]
            for record in review_records
        ), review_records
        assert step_review["completionResult"] == "PASS", step_review
        assert step_review["stepCompletion"]["completed"] is True, step_review
        assert step_review["specializedReviewGate"]["basis"] == clean_gate["basis"], step_review
        assert step_review["specializedReviewGate"]["required"] == clean_gate["required"], step_review
        assert (
            step_review["specializedReviewGate"]["surfaceMode"]
            == "implementation-baseline"
        ), step_review
        assert (
            step_review["specializedReviewGate"]["implementationBaseline"]
            == baseline_head
        ), step_review
        assert (
            step_review["specializedReviewGate"]["changedPathsHash"]
            == clean_gate["changedPathsHash"]
        ), step_review
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
