#!/usr/bin/env python3
"""Regression self-test schema-v1 planning contracts.

Проверяет дешёвые invariants: configurable paths, 1000+ IDs, selective
architecture refs, OQ, completion proofs, strict frontmatter, Plan hashes и
обязательный immutable planning-review.
"""
from __future__ import annotations

from pathlib import Path
import tempfile

from document_contract import content_hash
from planning_contract import (
    init_review_basis,
    latest_matching_init_review,
    latest_matching_planning_review,
    plan_content_hash,
    planning_context_basis,
    task_path,
    validate_init_review_report,
    validate_planning_contracts,
    validate_planning_review_report,
)
from project_integrity import validate_adrs, validate_requirements
from project_migration import legacy_schema_pending
from projection_contract import validate_projections
from template_contract import template_targets


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def manifest() -> str:
    return """execution:
  maxFixReviewCycles: 2
review:
  security: auto
  tests: auto
sources:
  projectOverview: spec/PROJECT.md
  requirements: spec/requirements
  adrDirectory: spec/adr
  architecture: spec/architecture.md
  openQuestions: spec/open-questions
  openQuestionsIndex: spec/OPEN_QUESTIONS.md
protocol:
  taskDirectory: work/tasks
  reviewDirectory: work/reviews
  planningReviewDirectory: work/plan-reviews
  initReviewDirectory: work/init-reviews
  auditDirectory: work/audits
  releaseDirectory: work/releases
  skillSearchDirectory: work/skill-searches
"""


def requirement(req_id: str = "REQ-1000", extra: str = "") -> str:
    return f"""---
schema: 1
id: {req_id}
priority: medium
source: self_test
steps:
  - STEP-1000
adrs: []
---

# {req_id} — Planning contract

## Requirement

Plan учитывает upstream contract. {extra}

## Rationale

Self-test.

## Acceptance

- Fingerprint меняется только при relevant upstream change.
"""


def adr(status: str = "accepted") -> str:
    return f"""---
schema: 1
id: ADR-1000
status: {status}
date: 2026-09-21
deciders:
  - test
supersedes: []
superseded_by: []
requirements:
  - REQ-1000
steps:
  - STEP-1000
---

# ADR-1000 — Test decision

## Context

Self-test.

## Problem

Нужно решение.

## Decision

Использовать fixture.

## Alternatives considered

- none.

## Consequences

Predictable.

## Security implications

Not applicable.

## Data / migration implications

Not applicable.

## Compatibility / operational implications

Not applicable.
"""


def task(
    step_id: str,
    *,
    step_type: str = "implementation",
    status: str = "planned",
    depends: list[str] | None = None,
    requirements: list[str] | None = None,
    adrs: list[str] | None = None,
    architecture_refs: list[str] | None = None,
    risks: list[str] | None = None,
    plan_status: str = "not_planned",
    plan_revision: int = 0,
    context_basis: str | None = None,
    plan_hash: str | None = None,
    reviewed_report: str | None = None,
    evidence: str = "—",
    extra_section: str = "",
) -> str:
    depends = depends or []
    requirements = ["REQ-1000"] if requirements is None else requirements
    adrs = adrs or []
    architecture_refs = architecture_refs or ['spec/architecture.md#storage']
    risks = risks or ["none"]

    def block(name: str, values: list[str]) -> str:
        if not values:
            return f"{name}: []\n"
        return f"{name}:\n" + "".join(f'  - "{value}"\n' if "#" in value else f"  - {value}\n" for value in values)

    def scalar(value: str | None) -> str:
        return "null" if value is None else value

    return f"""---
schema: 1
id: {step_id}
status: {status}
type: {step_type}
priority: medium
phase: test
{block("depends_on", depends)}{block("requirements", requirements)}{block("adrs", adrs)}{block("architecture_refs", architecture_refs)}{block("risk_flags", risks)}plan:
  status: {plan_status}
  revision: {plan_revision}
  context_basis: {scalar(context_basis)}
  content_hash: {scalar(plan_hash)}
  reviewed_report: {scalar(reviewed_report)}
  planned_at: {"2026-09-21T00:00:00+00:00" if plan_status == "ready" else "null"}
---

# {step_id} — Planning contract self-test

## Goal

Проверить planning contract.

## Context

Self-test.

## Scope

- deterministic checks.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- unrelated.

## Acceptance criteria

- validator сообщает точный результат.

## Verification

- planning-contract-self-test.py.

## Deliverables

- fixture.

## Implementation plan

1. Проверить fixture.
2. Зафиксировать результат.

## Evidence

{evidence}

## Blocker / Failure reason

—
{extra_section}
"""


def planning_review(
    step_id: str,
    basis: str,
    plan_hash: str,
    created_at: str = "2026-09-21T00:00:00Z",
) -> str:
    return f"""---
schema: 1
kind: planning_review
step_id: {step_id}
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: {basis}
plan_content_hash: {plan_hash}
created_at: {created_at}
---

# Planning Review {step_id} — self-test

## Scope checked

Contract and plan.

## Findings

No material findings.

## Verdict rationale

Plan is consistent.
"""


def init_review(
    stage: str,
    basis: str,
    verdict: str,
    finding_count: int,
    created_at: str = "2026-09-21T00:00:00Z",
) -> str:
    findings = "No material findings." if verdict == "pass" else "Blocking contradiction."
    return f"""---
schema: 1
kind: init_review
stage: {stage}
verdict: {verdict}
reviewer_role: reviewer
finding_count: {finding_count}
basis: {basis}
created_at: {created_at}
---

# PROJECT INIT Review — {stage}

## Scope checked

Current candidate contracts.

## Findings

{findings}

## Verdict rationale

{verdict}.
"""


def make_ready(root: Path, step_id: str, **kwargs: object) -> None:
    draft = task(step_id, plan_status="draft", **kwargs)
    write(root / f"work/tasks/{step_id}.md", draft)
    basis = planning_context_basis(root, step_id)
    phash = plan_content_hash(root, step_id)
    rel = f"work/plan-reviews/{step_id}/PLAN-REVIEW-20260921T000000Z.md"
    write(root / rel, planning_review(step_id, basis, phash))
    ready = task(
        step_id,
        plan_status="ready",
        plan_revision=1,
        context_basis=basis,
        plan_hash=phash,
        reviewed_report=rel,
        **kwargs,
    )
    write(root / f"work/tasks/{step_id}.md", ready)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-planning-v1-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(root / "spec/PROJECT.md", "# Project\n\nConstraint A.\n")
        write(root / "spec/requirements/REQ-1000-contract.md", requirement())
        write(root / "spec/adr/ADR-1000-test.md", adr())
        write(
            root / "spec/architecture.md",
            "# Architecture\n\n## Storage\n\nStorage A.\n\n## Auth\n\nAuth A.\n",
        )
        write(root / "spec/OPEN_QUESTIONS.md", "# Open Questions\n")
        write(
            root / "work/tasks/STEP-1001.md",
            task(
                "STEP-1001",
                step_type="research",
                status="completed",
                requirements=[],
                architecture_refs=[],
                evidence="Research result recorded.",
            ),
        )
        write(root / "work/tasks/STEP-1000.md", task("STEP-1000", depends=["STEP-1001"]))

        # INIT semantic proof должен инвалидироваться при изменении
        # project constraints или ADR, а не только REQ/roadmap.
        init_a = init_review_basis(root, "requirements")
        write(root / "spec/PROJECT.md", "# Project\n\nConstraint B.\n")
        init_b = init_review_basis(root, "requirements")
        assert init_a != init_b, (init_a, init_b)
        write(root / "spec/PROJECT.md", "# Project\n\nConstraint A.\n")
        init_c = init_review_basis(root, "requirements")
        adr_text = (root / "spec/adr/ADR-1000-test.md").read_text(encoding="utf-8")
        write(
            root / "spec/adr/ADR-1000-test.md",
            adr_text.replace("Использовать fixture.", "Использовать изменённый fixture."),
        )
        init_d = init_review_basis(root, "requirements")
        assert init_c != init_d, (init_c, init_d)
        write(root / "spec/adr/ADR-1000-test.md", adr_text)

        # Для одного basis более новый BLOCKED обязан отменять старый PASS.
        init_basis = init_review_basis(root, "requirements")
        write(
            root / "work/init-reviews/INIT-REVIEW-20260921T010000Z.md",
            init_review(
                "requirements",
                init_basis,
                "pass",
                0,
                "2026-09-21T01:00:00Z",
            ),
        )
        assert latest_matching_init_review(root, "requirements") is not None
        write(
            root / "work/init-reviews/INIT-REVIEW-20260921T020000Z.md",
            init_review(
                "requirements",
                init_basis,
                "blocked",
                1,
                "2026-09-21T02:00:00Z",
            ),
        )
        assert latest_matching_init_review(root, "requirements") is None
        (root / "work/init-reviews/INIT-REVIEW-20260921T020000Z.md").unlink()

        # Semantic trust reports должны быть обычными immutable files, а не
        # symlink на mutable соседний artifact.
        init_source = root / "work/init-reviews/INIT-REVIEW-20260921T010000Z.md"
        init_link = root / "work/init-reviews/INIT-REVIEW-20260921T015000Z.md"
        init_link.symlink_to(init_source.name)
        init_link_errors = validate_init_review_report(root, init_link)
        assert any("must not be a symlink" in item for item in init_link_errors), init_link_errors
        init_link.unlink()

        # Configurable layout + 1000+ IDs.
        assert task_path(root, "STEP-1000") == root / "work/tasks/STEP-1000.md"
        assert not validate_planning_contracts(root), validate_planning_contracts(root)

        # Project-owned STEP template follows configured architecture path.
        task_template = template_targets(root)[root / "work/tasks/TEMPLATE.md"]
        assert "spec/architecture.md#relevant-section" in task_template
        assert "docs/architecture.md#relevant-section" not in task_template

        # Repository containment.
        valid_manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
        write(
            root / ".harness/manifest.yaml",
            valid_manifest.replace("taskDirectory: work/tasks", "taskDirectory: ../outside"),
        )
        errors = validate_planning_contracts(root)
        assert any("inside repository" in item or "escapes repository" in item for item in errors), errors
        write(root / ".harness/manifest.yaml", valid_manifest)

        # Selective architecture refs: unrelated section does not invalidate basis.
        basis_a = planning_context_basis(root, "STEP-1000")
        write(
            root / "spec/architecture.md",
            "# Architecture\n\n## Storage\n\nStorage A.\n\n## Auth\n\nAuth B.\n",
        )
        basis_b = planning_context_basis(root, "STEP-1000")
        assert basis_a == basis_b, (basis_a, basis_b)
        write(
            root / "spec/architecture.md",
            "# Architecture\n\n## Storage\n\nStorage B.\n\n## Auth\n\nAuth B.\n",
        )
        basis_c = planning_context_basis(root, "STEP-1000")
        assert basis_b != basis_c, (basis_b, basis_c)

        # REQ and dependency completion proof are planning inputs.
        write(root / "spec/requirements/REQ-1000-contract.md", requirement(extra="Changed."))
        basis_d = planning_context_basis(root, "STEP-1000")
        assert basis_c != basis_d
        dep = (root / "work/tasks/STEP-1001.md").read_text(encoding="utf-8")
        write(root / "work/tasks/STEP-1001.md", dep.replace("Research result recorded.", "Research result changed."))
        basis_e = planning_context_basis(root, "STEP-1000")
        assert basis_d != basis_e

        # Ready requires matching semantic planning-review and both hashes.
        make_ready(root, "STEP-1000", depends=["STEP-1001"])
        errors = validate_planning_contracts(root)
        assert not errors, errors

        plan_source = root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T000000Z.md"
        plan_link = root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T003000Z.md"
        plan_link.symlink_to(plan_source.name)
        plan_link_errors = validate_planning_review_report(root, plan_link, expected_step_id="STEP-1000")
        assert any("must not be a symlink" in item for item in plan_link_errors), plan_link_errors
        plan_link.unlink()

        # Новый BLOCKED для того же basis/content отменяет более старый PASS.
        current_basis = planning_context_basis(root, "STEP-1000")
        current_hash = plan_content_hash(root, "STEP-1000")
        blocked = planning_review(
            "STEP-1000",
            current_basis,
            current_hash,
            "2026-09-21T01:00:00Z",
        ).replace(
            "verdict: pass\nreviewer_role: reviewer\nfinding_count: 0",
            "verdict: blocked\nreviewer_role: reviewer\nfinding_count: 1",
        ).replace("No material findings.", "Blocking contradiction.")
        write(
            root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T010000Z.md",
            blocked,
        )
        assert latest_matching_planning_review(root, "STEP-1000") is None
        (root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T010000Z.md").unlink()
        assert latest_matching_planning_review(root, "STEP-1000") is not None

        # Upstream REQ change делает Ready context stale, но global-style
        # validation остаётся PASS с warning; execution resolver перепланирует
        # отдельно перед IMPLEMENT.
        req_before = (root / "spec/requirements/REQ-1000-contract.md").read_text(encoding="utf-8")
        write(
            root / "spec/requirements/REQ-1000-contract.md",
            req_before.replace("Plan учитывает upstream contract.", "Plan учитывает changed upstream contract."),
        )
        warnings: list[str] = []
        errors = validate_planning_contracts(root, warnings=warnings)
        assert not errors, errors
        assert any("context_basis is stale" in item for item in warnings), warnings
        write(root / "spec/requirements/REQ-1000-contract.md", req_before)

        # Editing plan content makes Ready invalid even when context is unchanged.
        ready = (root / "work/tasks/STEP-1000.md").read_text(encoding="utf-8")
        write(root / "work/tasks/STEP-1000.md", ready.replace("2. Зафиксировать результат.", "2. Изменить результат."))
        errors = validate_planning_contracts(root)
        assert any("content_hash is stale" in item for item in errors), errors
        write(root / "work/tasks/STEP-1000.md", ready)

        # Relevant canonical OQ participates in basis and blocks Ready.
        write(
            root / "spec/open-questions/OQ-1000-choice.md",
            """---
schema: 1
id: OQ-1000
status: open
affects:
  - REQ-1000
created_at: 2026-09-21T00:00:00+00:00
resolved_at: null
---

# OQ-1000 — Choice

## Context

Need a decision.

## Decision needed

Choose a mode.

## Resolution


""",
        )
        errors = validate_planning_contracts(root)
        assert any("blocked by OQ-1000" in item for item in errors), errors

        # Missing affects target is rejected.
        oq = (root / "spec/open-questions/OQ-1000-choice.md").read_text(encoding="utf-8")
        write(root / "spec/open-questions/OQ-1000-choice.md", oq.replace("REQ-1000", "REQ-9999"))
        errors = validate_planning_contracts(root)
        assert any("affects target does not exist" in item for item in errors), errors
        (root / "spec/open-questions/OQ-1000-choice.md").unlink()

        # Duplicate/malformed canonical REQ/ADR are never silently dropped.
        duplicate_req = root / "spec/requirements/REQ-1000-duplicate.md"
        write(duplicate_req, requirement())
        req_errors = validate_requirements(root)
        assert any("duplicate canonical id REQ-1000" in item for item in req_errors), req_errors
        duplicate_req.unlink()

        malformed_req = root / "spec/requirements/REQ-2000-broken.md"
        write(malformed_req, "---\nschema: [broken\n")
        req_errors = validate_requirements(root)
        assert any("REQ-2000-broken.md" in item for item in req_errors), req_errors
        malformed_req.unlink()

        duplicate_adr = root / "spec/adr/ADR-1000-duplicate.md"
        write(duplicate_adr, adr())
        adr_errors = validate_adrs(root)
        assert any("duplicate canonical id ADR-1000" in item for item in adr_errors), adr_errors
        duplicate_adr.unlink()

        malformed_adr = root / "spec/adr/ADR-2000-broken.md"
        write(malformed_adr, "---\nschema: [broken\n")
        adr_errors = validate_adrs(root)
        assert any("ADR-2000-broken.md" in item for item in adr_errors), adr_errors
        malformed_adr.unlink()

        # Malformed STEP stays a deterministic validation error and does not
        # crash cross-document ADR validation or migration detection.
        malformed_step = root / "work/tasks/STEP-2000.md"
        write(malformed_step, "---\nschema: [broken\n")
        planning_errors = validate_planning_contracts(root)
        assert any("STEP-2000" in item for item in planning_errors), planning_errors
        projection_errors = validate_projections(root)
        assert any("projection derivation failed" in item for item in projection_errors), projection_errors
        validate_adrs(root)
        assert legacy_schema_pending(root)
        malformed_step.unlink()

        # Unknown/mixed risk flags are deterministic errors.
        write(root / "work/tasks/STEP-1000.md", task("STEP-1000", risks=["none", "security-sensitive"]))
        errors = validate_planning_contracts(root)
        assert any("mutually exclusive" in item for item in errors), errors
        write(root / "work/tasks/STEP-1000.md", task("STEP-1000", risks=["typo-risk"]))
        errors = validate_planning_contracts(root)
        assert any("unknown risk flag" in item for item in errors), errors

        # Duplicate contract sections are invalid instead of silently merged.
        duplicate = task("STEP-1000") + "\n## Scope\n\nDuplicate.\n"
        write(root / "work/tasks/STEP-1000.md", duplicate)
        errors = validate_planning_contracts(root)
        assert any("duplicate section" in item for item in errors), errors

        # Semantic review schema is enforced, not only matching hashes.
        malformed_review = planning_review(
            "STEP-1000",
            "sha256:" + "0" * 64,
            "sha256:" + "1" * 64,
            "2026-09-21T03:00:00Z",
        ).replace(
            "reviewer_role: reviewer",
            "reviewer_role: implementer",
        )
        write(
            root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T030000Z.md",
            malformed_review,
        )
        errors = validate_planning_contracts(root)
        assert any("reviewer_role must be reviewer" in item for item in errors), errors
        (root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T030000Z.md").unlink()

        # Dependency cycle is graph-detectable.
        write(root / "work/tasks/STEP-1000.md", task("STEP-1000", depends=["STEP-1001"]))
        write(
            root / "work/tasks/STEP-1001.md",
            task(
                "STEP-1001",
                step_type="research",
                status="completed",
                depends=["STEP-1000"],
                requirements=[],
                architecture_refs=[],
                evidence="done",
            ),
        )
        errors = validate_planning_contracts(root)
        assert any("dependency cycle" in item for item in errors), errors

        # latest semantics опирается на sortable immutable report names.
        # Schema-v1 report с произвольным/невалидным timestamp именем fail-closed.
        invalid_plan_report = (
            root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-not-a-timestamp.md"
        )
        write(
            invalid_plan_report,
            planning_review(
                "STEP-1000",
                planning_context_basis(root, "STEP-1000"),
                plan_content_hash(root, "STEP-1000"),
            ),
        )
        assert any(
            "filename must be PLAN-REVIEW-<UTC timestamp>.md" in item
            for item in validate_planning_review_report(
                root,
                invalid_plan_report,
                expected_step_id="STEP-1000",
            )
        )
        invalid_plan_report.unlink()

        mismatched_plan_report = (
            root / "work/plan-reviews/STEP-1000/PLAN-REVIEW-20260921T040000Z.md"
        )
        write(
            mismatched_plan_report,
            planning_review(
                "STEP-1000",
                planning_context_basis(root, "STEP-1000"),
                plan_content_hash(root, "STEP-1000"),
                "2026-09-21T04:00:01Z",
            ),
        )
        mismatch_errors = validate_planning_review_report(
            root,
            mismatched_plan_report,
            expected_step_id="STEP-1000",
        )
        assert any(
            "created_at must match UTC timestamp encoded in filename" in item
            for item in mismatch_errors
        ), mismatch_errors
        mismatched_plan_report.unlink()

        invalid_init_report = root / "work/init-reviews/INIT-REVIEW-not-a-timestamp.md"
        write(
            invalid_init_report,
            init_review(
                "requirements",
                init_review_basis(root, "requirements"),
                "pass",
                0,
            ),
        )
        assert any(
            "filename must be INIT-REVIEW-<UTC timestamp>.md" in item
            for item in validate_init_review_report(
                root,
                invalid_init_report,
                expected_stage="requirements",
            )
        )
        invalid_init_report.unlink()

    print("PLANNING CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
