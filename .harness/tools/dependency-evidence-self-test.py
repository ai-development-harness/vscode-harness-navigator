#!/usr/bin/env python3
"""#355: completed — исторический факт; актуальность относится к новой работе.

Synthetic reports проверяются настоящим schema/trust validator. Эти fixtures
не являются историей canary: реальные принятые reports проверяет отдельный runner.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

from planning_contract import (
    dependency_completion_basis,
    historical_completion_projection_proof,
    planning_context_basis,
    step_completion_proof,
)
from verification import verification_context_basis, verification_dependency_facts


MANIFEST = """execution:
  verificationCommandTimeoutSeconds: 300
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  openQuestions: docs/open-questions
  principles: docs/principles
  architecture: docs/architecture.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""


def write(root: Path, rel: str, value: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def requirement(step_id: str, req_id: str) -> str:
    return f"""---
schema: 1
id: {req_id}
source: fixture
priority: medium
steps:
  - {step_id}
adrs: []
---

# {req_id} — Completion fixture

## Requirement

Implement {step_id} with approved behavior.

## Rationale

Dependency test.

## Acceptance

- Behavior remains correct.
"""


def step(step_id: str, req_id: str, dependency: str | None = None) -> str:
    deps = "depends_on: []" if dependency is None else f"depends_on:\n  - {dependency}"
    return f"""---
schema: 1
id: {step_id}
status: completed
type: implementation
priority: medium
phase: P1
{deps}
requirements:
  - {req_id}
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

# {step_id} — Dependency fixture

## Goal

Deliver {step_id}.

## Context

Fixture.

## Scope

- Implement.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- Other work.

## Acceptance criteria

- Deliver stable behavior.

## Verification

- manual: verify feature

## Deliverables

- Implementation.

## Implementation plan

- Implementation done.

## Evidence

- Verified by independent review.

## Blocker / Failure reason

—
"""


def review(root: Path, sid: str, *, verdict: str = "pass", modern: bool = False) -> Path:
    """Создать явно synthetic, но schema-valid исторический REVIEW без mock trust."""
    from document_contract import render_document
    from review_contract import validate_review_report

    meta = {
        "schema": 1, "kind": "step_review", "step_id": sid,
        "verdict": verdict, "reviewer_role": "reviewer",
        "created_at": "2020-01-01T00:00:00Z",
        "reviewed_revision": {"git_head": "1" * 40, "worktree_hash": None},
        "contract_basis": planning_context_basis(root, sid),
        "specialized_reviews": {
            "gate_basis": "sha256:" + "1" * 64, "required": [],
            "security": "not_required", "security_reason": "Synthetic fixture.",
            "tests": "not_required", "tests_reason": "Synthetic fixture.",
        },
    }
    if modern:
        meta["reviewed_subject_content_hash"] = "sha256:" + "2" * 64
        deps = dependency_completion_basis(root, sid)
        if deps:
            meta["dependency_completion_basis"] = deps
    rel = f"planning/reviews/{sid}/REVIEW-20200101T000000Z.md"
    sections = {
        "Scope checked": "Synthetic contract и результат.",
        "Findings": "Material findings отсутствуют.",
        "Verification observations": "Synthetic результат проверен.",
        "Verdict rationale": "Synthetic исторический fixture.",
    }
    body = f"# STEP REVIEW {sid} — Synthetic\n\n" + "\n\n".join(
        f"## {name}\n\n{text}" for name, text in sections.items()) + "\n"
    write(root, rel, render_document(meta, body))
    path = root / rel
    assert not validate_review_report(root, path), validate_review_report(root, path)
    return path


def main() -> int:
    from planning_contract import dependency_completion_failures
    from review_contract import latest_trusted_review, validate_review_report
    from traceability_coverage import build_coverage
    import planning_contract as pc

    with tempfile.TemporaryDirectory(prefix="harness-completed-history-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        write(root, "docs/architecture.md", "## Module map\n\nПринятое описание.\n")
        for n in range(1, 5):
            sid, rid = f"STEP-{n:03d}", f"REQ-{n:03d}"
            text = step(sid, rid, f"STEP-{n-1:03d}" if n in (2, 3) else None)
            text = text.replace("architecture_refs: []", "architecture_refs:\n  - docs/architecture.md#module-map")
            if n == 4:
                text = text.replace("status: completed", "status: planned")
                text = text.replace("depends_on: []", "depends_on:\n  - STEP-003")
            write(root, f"planning/tasks/{sid}.md", text)
            write(root, f"docs/requirements/{rid}-fixture.md", requirement(sid, rid))
            if n < 4:
                review(root, sid, modern=n == 3)
        original = {p: p.read_bytes() for p in root.rglob("*.md")}
        historical = step_completion_proof(root, "STEP-003")
        assert historical["complete"], historical
        assert dependency_completion_failures(root, "STEP-004") == []
        assert not step_completion_proof(root, "STEP-004")["complete"]
        assert build_coverage(root)["metrics"]["verified"] == 3

        # Даже нормативное изменение REQ не отменяет прошлую приёмку.
        # Новый consumer использует свой текущий контекст и собственный PLAN.
        for rel in ("docs/architecture.md", "docs/requirements/REQ-001-fixture.md"):
            path = root / rel
            path.write_text(path.read_text() + "\nНовое описание или требование.\n", encoding="utf-8")
        assert step_completion_proof(root, "STEP-003") == historical
        assert historical_completion_projection_proof(root, "STEP-003") == historical
        assert dependency_completion_failures(root, "STEP-004") == []
        assert verification_dependency_facts(root, "STEP-004")[0]["complete"]
        assert build_coverage(root)["metrics"]["verified"] == 3

        # Изменившийся upstream REVIEW не требует повторно принимать child.
        first = root / "planning/reviews/STEP-001/REVIEW-20200101T000000Z.md"
        first.unlink()
        assert step_completion_proof(root, "STEP-003") == historical
        assert not step_completion_proof(root, "STEP-001")["complete"]
        assert dependency_completion_failures(root, "STEP-004") == []
        first.write_bytes(original[first])

        # Нынешний depends_on completed STEP не является его прошлым контрактом.
        second = root / "planning/tasks/STEP-003.md"
        text = second.read_text()
        second.write_text(text.replace("  - STEP-002", "  - STEP-999"), encoding="utf-8")
        assert step_completion_proof(root, "STEP-003") == historical
        assert dependency_completion_failures(root, "STEP-004") == []
        second.write_text(text, encoding="utf-8")

        # Прямой prerequisite новой работы обязан иметь сохранный trusted PASS.
        report = root / "planning/reviews/STEP-003/REVIEW-20200101T000000Z.md"
        good = report.read_bytes()
        report.write_text("повреждённый отчёт", encoding="utf-8")
        assert latest_trusted_review(root, "STEP-003") is None
        assert dependency_completion_failures(root, "STEP-004")
        report.write_bytes(good)
        task = root / "planning/tasks/STEP-003.md"
        good_task = task.read_text()
        for replacement in ("status: in_progress", "status: planned"):
            task.write_text(good_task.replace("status: completed", replacement), encoding="utf-8")
            assert dependency_completion_failures(root, "STEP-004")
        task.write_text(good_task.replace("- Verified by independent review.", "—"), encoding="utf-8")
        assert dependency_completion_failures(root, "STEP-004")
        task.write_text(good_task, encoding="utf-8")
        generated = "<!-- VERIFICATION-EVIDENCE:START -->\n- Status: FAIL\n<!-- VERIFICATION-EVIDENCE:END -->"
        task.write_text(good_task.replace("- Verified by independent review.", generated), encoding="utf-8")
        assert dependency_completion_failures(root, "STEP-004")
        task.write_text(good_task, encoding="utf-8")
        report.write_bytes(good.replace(b"verdict: pass", b"verdict: blocked"))
        assert dependency_completion_failures(root, "STEP-004")
        report.write_bytes(good)
        assert not validate_review_report(root, report)

        # Проверка completed не читает чужие STEP/REQ/architecture и не обходит DAG.
        with patch("planning_contract.read_task", wraps=pc.read_task) as reads, \
             patch("planning_contract.planning_context_basis", side_effect=AssertionError("historical context recalculated")):
            assert step_completion_proof(root, "STEP-003")["complete"]
            assert all(call.args[1] == "STEP-003" for call in reads.call_args_list)
            assert reads.call_count <= 3, reads.call_count
        for path, data in original.items():
            if path.name not in {"architecture.md", "REQ-001-fixture.md"}:
                assert path.read_bytes() == data, path
    print("DEPENDENCY EVIDENCE ENFORCEMENT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
