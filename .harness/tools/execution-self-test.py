#!/usr/bin/env python3
"""Regression self-test crash-safe Execution Status on schema-v1 contracts."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from execution_status import (
    begin_command,
    block_execution,
    complete_command,
    load_status,
    resolve_root,
    stamp_plan,
    start_execution,
    unresolved_executions,
)
from document_contract import content_hash
from planning_contract import plan_content_hash, planning_context_basis
from review_contract import (
    latest_trusted_review,
    repository_revision,
    review_reports,
    validate_review_immutability,
)
from review_gates import required_reviewers
from step_context import build_step_context


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")


def manifest() -> str:
    return """execution:
  maxFixReviewCycles: 1
review:
  security: auto
  tests: auto
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
  auditDirectory: planning/audits
  releaseDirectory: planning/releases
  skillSearchDirectory: planning/skill-searches
repository:
  gitPolicy: .harness/git-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
"""


def requirement() -> str:
    return """---
schema: 1
id: REQ-001
priority: medium
source: self_test
steps:
  - STEP-001
adrs: []
---

# REQ-001 — Execution state

## Requirement

Execution state работает детерминированно.

## Rationale

Self-test.

## Acceptance

- Recovery воспроизводим.
"""


def task(
    plan_status: str = "draft",
    basis: str | None = None,
    phash: str | None = None,
    report: str | None = None,
    depends: list[str] | None = None,
) -> str:
    def val(value: str | None) -> str:
        return "null" if value is None else value
    depends = depends or []
    depends_block = (
        "depends_on: []\n"
        if not depends
        else "depends_on:\n" + "".join(f"  - {item}\n" for item in depends)
    )
    return f"""---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: test
{depends_block}requirements:
  - REQ-001
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: {plan_status}
  revision: {1 if plan_status == "ready" else 0}
  context_basis: {val(basis)}
  content_hash: {val(phash)}
  reviewed_report: {val(report)}
  planned_at: {"2026-09-21T00:00:00+00:00" if plan_status == "ready" else "null"}
---

# STEP-001 — Execution state test

## Goal

Проверить execution status.

## Context

Self-test.

## Scope

- fixture.

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

- recovery deterministic.

## Verification

- execution-self-test.py.

## Deliverables

- fixture.

## Implementation plan

1. Execute fixture.
2. Review exact revision.

## Evidence

—

## Blocker / Failure reason

—
"""


def planning_review(basis: str, phash: str) -> str:
    return f"""---
schema: 1
kind: planning_review
step_id: STEP-001
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: {basis}
plan_content_hash: {phash}
created_at: 2026-09-21T00:00:00Z
---

# Planning Review STEP-001 — self-test

## Scope checked

Contract and plan.

## Findings

No material findings.

## Verdict rationale

PASS.
"""


def review_report(root: Path, verdict: str, name: str) -> str:
    revision = repository_revision(root)
    match = re.fullmatch(r"REVIEW-(\d{8}T\d{6}Z)\.md", name)
    if match is None:
        created_at = "2026-09-21T00:00:00Z"
    else:
        created_at = (
            datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    gate = required_reviewers(root, "STEP-001")
    required_block = (
        "\n".join(f"    - {item}" for item in gate["required"])
        if gate["required"]
        else "    []"
    )
    if verdict == "FAIL":
        findings = """### F-001 — Fixture defect

**Severity:** high
**Category:** implementation
**Location:** fixture
**Scenario:** Given fixture / When reviewed / Then defect is found
**Impact:** acceptance is not proven
**Fix direction:** fix fixture
"""
    else:
        findings = "No material findings.\n"
    rel = f"planning/reviews/STEP-001/{name}"
    write(
        root / rel,
        f"""---
schema: 1
kind: step_review
step_id: STEP-001
verdict: {verdict.lower()}
reviewer_role: reviewer
created_at: {created_at}
reviewed_revision:
  git_head: {revision["git_head"] or "null"}
  worktree_hash: {revision["worktree_hash"] or "null"}
specialized_reviews:
  gate_basis: {gate["basis"]}
  required:
{required_block}
  security: not_required
  security_evidence: null
  security_reason: no_security_surface
  tests: pass
  tests_evidence: inline verification in this review
  tests_reason: implementation_step
---

# STEP REVIEW STEP-001 — self-test

## Scope checked

Exact fixture revision.

## Findings

{findings}
## Verification observations

Self-test verification.

## Verdict rationale

{verdict}.
""",
    )
    return rel


def concurrent_start_worker(root_value: str, command: str) -> None:
    """Отдельный process для regression lost-update execution state."""
    start_execution(Path(root_value), command)

def assert_resolved(value: dict, status: str, command: str | None, reason: str) -> None:
    assert value["status"] == status, value
    assert value.get("command") == command, value
    assert value["reasonCode"] == reason, value


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-execution-v1-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(
            root / ".harness/git-policy.toml",
            '[push]\nremote = "publish"\n',
        )
        write(
            root / ".harness/harness-update.toml",
            '[state]\nreport_directory = "planning/harness-updates"\n',
        )
        shutil.copy2(source / ".harness/command-transitions.json", root / ".harness/command-transitions.json")
        write(root / "docs/requirements/REQ-001-execution.md", requirement())
        write(root / "docs/architecture.md", "# Architecture\n")
        dependency = task().replace("id: STEP-001", "id: STEP-002").replace(
            "# STEP-001 — Execution state test",
            "# STEP-002 — Execution dependency test",
        ).replace("type: implementation", "type: research").replace(
            "requirements:\n  - REQ-001",
            "requirements: []",
        )
        write(root / "planning/tasks/STEP-002.md", dependency)
        write(root / "planning/tasks/STEP-001.md", task(depends=["STEP-002"]))

        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.email", "harness-test@example.invalid")
        run(root, "git", "config", "user.name", "Harness Test")
        write(root / ".gitignore", ".harness/local/\n")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # Harness UPDATE reports являются immutable durable history наравне с
        # review/audit/release reports.
        update_report = root / "planning/harness-updates/UPDATE-20260921T000000Z.md"
        write(update_report, "immutable update report\n")
        run(root, "git", "add", update_report.relative_to(root).as_posix())
        run(root, "git", "commit", "-qm", "fixture update history")
        write(update_report, "mutated update report\n")
        immutable_errors = validate_review_immutability(root)
        assert any(
            "UPDATE-20260921T000000Z.md" in item
            for item in immutable_errors
        ), immutable_errors
        run(root, "git", "checkout", "--", update_report.relative_to(root).as_posix())

        # Operational .harness/local/** не является частью reviewed revision
        # даже если такой path уже оказался tracked. Нормализация Git path не
        # должна удалять ведущую точку из скрытого directory name.
        local_state = root / ".harness/local/execution/execution-status.json"
        write(local_state, '{"schemaVersion": 1, "executions": []}\n')
        run(root, "git", "add", "-f", local_state.relative_to(root).as_posix())
        run(root, "git", "commit", "-qm", "fixture tracked local state")
        write(local_state, '{"schemaVersion": 1, "executions": [{"changed": true}]}\n')
        local_only_revision = repository_revision(root)
        assert local_only_revision["worktree_hash"] is None, local_only_revision
        run(root, "git", "checkout", "--", local_state.relative_to(root).as_posix())

        # Configurable reviewDirectory не может исключить произвольный subtree
        # из reviewed revision. Старое blanket-exclusion поведение для docs
        # скрывало бы изменение architecture.md.
        original_manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
        write(
            root / ".harness/manifest.yaml",
            original_manifest.replace(
                "reviewDirectory: planning/reviews",
                "reviewDirectory: docs",
            ),
        )
        run(root, "git", "add", ".harness/manifest.yaml")
        run(root, "git", "commit", "-qm", "fixture custom review directory")
        write(root / "docs/architecture.md", "# Architecture\n\nChanged product architecture.\n")
        broad_review_revision = repository_revision(root)
        assert broad_review_revision["worktree_hash"] is not None, broad_review_revision

        # Тот же trust boundary обязателен для specialized-review preselector:
        # configured reviewDirectory=docs не должен скрывать security-like
        # product path только потому, что он находится под docs/.
        write(root / "docs/security-model.md", "# Security model\n\nChanged.\n")
        broad_gate = required_reviewers(root, "STEP-001")
        review_context = build_step_context(root, "STEP-001", "review")
        assert review_context["deterministic"]["specializedReviewGate"]["basis"] == broad_gate["basis"]
        assert review_context["deterministic"]["repositoryRevision"]["worktree_hash"] is not None
        assert "security" in broad_gate["required"], broad_gate
        (root / "docs/security-model.md").unlink()

        # Git path classification не должна разыменовывать product symlink в
        # operational/local subtree: сам symlink является factual product diff.
        write(root / ".harness/local/hidden-auth.py", "secret fixture\n")
        product_link = root / "src/security-link.py"
        product_link.parent.mkdir(parents=True, exist_ok=True)
        product_link.symlink_to("../.harness/local/hidden-auth.py")
        symlink_revision = repository_revision(root)
        assert symlink_revision["worktree_hash"] is not None, symlink_revision
        symlink_gate = required_reviewers(root, "STEP-001")
        assert "src/security-link.py" in symlink_gate["changedPaths"], symlink_gate
        assert "security" in symlink_gate["required"], symlink_gate
        product_link.unlink()

        run(root, "git", "checkout", "--", "docs/architecture.md")
        write(root / ".harness/manifest.yaml", original_manifest)
        run(root, "git", "add", ".harness/manifest.yaml")
        run(root, "git", "commit", "-qm", "restore review directory")

        # Create durable planning-review matching the draft plan, then stamp Ready.
        basis = planning_context_basis(root, "STEP-001")
        phash = plan_content_hash(root, "STEP-001")
        plan_report = "planning/plan-reviews/STEP-001/PLAN-REVIEW-20260921T000000Z.md"
        write(root / plan_report, planning_review(basis, phash))
        stamped = stamp_plan(root, "STEP-001")
        assert stamped["planStatus"] == "ready", stamped
        ready_basis = planning_context_basis(root, "STEP-001")

        # Phase-specific context manifest resolve-ит canonical inputs без обхода
        # manifest/docs reasoning-моделью. PLAN не требует completion dependency.
        plan_context = build_step_context(root, "STEP-001", "plan")
        assert plan_context["status"] == "PASS", plan_context
        assert plan_context["deterministic"]["dependencyCompletionRequired"] is False
        assert "planning/tasks/STEP-002.md" in plan_context["readPaths"], plan_context
        assert "docs/requirements/REQ-001-execution.md" in plan_context["readPaths"], plan_context
        assert plan_context["semanticInputs"]["dependencies"][0]["status"] == "planned"

        implement_context_blocked = build_step_context(root, "STEP-001", "implement")
        assert (
            implement_context_blocked["deterministic"]["implementPrerequisites"]["status"]
            == "BLOCKED"
        ), implement_context_blocked
        assert any(
            "dependency-incomplete:STEP-002" in item
            for item in implement_context_blocked["deterministic"]["implementPrerequisites"]["failures"]
        ), implement_context_blocked

        # PLAN Ready не требует завершённой dependency, но direct IMPLEMENT
        # обязан fail-closed до появления type-specific completion proof.
        try:
            start_execution(root, "STEP IMPLEMENT STEP-001")
        except ValueError as exc:
            assert "dependency-incomplete:STEP-002" in str(exc), exc
        else:
            raise AssertionError("direct IMPLEMENT accepted incomplete dependency")
        assert planning_context_basis(root, "STEP-001") == ready_basis

        # PLAN -> IMPLEMENT edge несёт тот же deterministic runtime precondition.
        dependency_chain = "STEP PLAN STEP-001 > IMPLEMENT"
        chain_execution = start_execution(root, dependency_chain)
        complete_command(root, dependency_chain, "STEP PLAN STEP-001", "SUCCESS")
        chain_next = resolve_root(root, dependency_chain)
        assert chain_next.get("runtimePreconditions") == ["step-implement-ready"], chain_next
        try:
            begin_command(root, dependency_chain, "STEP IMPLEMENT STEP-001")
        except ValueError as exc:
            assert "dependency-incomplete:STEP-002" in str(exc), exc
        else:
            raise AssertionError("PLAN -> IMPLEMENT bypassed dependency completion")

        # Completion proof появляется без изменения semantic dependency contract:
        # существующий Ready basis остаётся свежим и IMPLEMENT сразу разрешается.
        dependency_path = root / "planning/tasks/STEP-002.md"
        dependency_text = dependency_path.read_text(encoding="utf-8")
        write(
            dependency_path,
            dependency_text.replace("status: planned", "status: completed").replace(
                "## Evidence\n\n—",
                "## Evidence\n\nResearch dependency complete.",
            ),
        )
        assert planning_context_basis(root, "STEP-001") == ready_basis
        implement_context_pass = build_step_context(root, "STEP-001", "implement")
        assert (
            implement_context_pass["deterministic"]["implementPrerequisites"]["status"]
            == "PASS"
        ), implement_context_pass
        direct_implement = start_execution(root, "STEP IMPLEMENT STEP-001")
        complete_command(
            root,
            direct_implement["rootCommand"],
            "STEP IMPLEMENT STEP-001",
            "SUCCESS",
        )

        # Independent commands coexist and invalid reverse chains never create state.
        first = start_execution(root, "PROJECT STATUS")
        complete_command(root, first["rootCommand"], "PROJECT STATUS", "SUCCESS")
        before = len(load_status(root)["executions"])
        try:
            start_execution(root, "GIT PR > COMMIT")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid reverse Git chain accepted")
        assert len(load_status(root)["executions"]) == before

        # Explicit chain advances only on allowed previous result.
        chain = "GIT CHECK > COMMIT > PUSH > PR"
        execution = start_execution(root, chain)
        complete_command(root, chain, "GIT CHECK", "PASS")
        assert_resolved(resolve_root(root, chain), "NEXT", "GIT COMMIT", "CHAIN_NEXT_SEGMENT")
        begin_command(root, chain, "GIT COMMIT")
        complete_command(root, chain, "GIT COMMIT", "SUCCESS")
        assert resolve_root(root, chain)["command"] == "GIT PUSH"

        # Runtime preconditions — не декоративная metadata. Direct CHECK -> PUSH
        # без доказуемого remote context блокируется до dispatch.
        direct_push = "GIT CHECK > PUSH"
        direct_execution = start_execution(root, direct_push)
        complete_command(root, direct_push, "GIT CHECK", "PASS")
        direct_next = resolve_root(root, direct_push)
        assert direct_next.get("runtimePreconditions") == ["git-push-ready"], direct_next
        try:
            begin_command(root, direct_push, "GIT PUSH")
        except ValueError as exc:
            assert "runtime precondition failed" in str(exc), exc
        else:
            raise AssertionError("git-push-ready was not enforced before dispatch")
        direct_blocked = resolve_root(root, direct_push)
        assert direct_blocked["status"] == "BLOCKED", direct_blocked
        direct_record = next(
            item for item in load_status(root)["executions"]
            if item["executionId"] == direct_execution["executionId"]
        )
        failures = direct_record.get("blockedBy", {}).get("failures", [])
        assert any("configured-remote-missing:publish" in item for item in failures), failures

        # Specialized reviewer может быть BLOCKED не только из-за product
        # contract, но и потому что обязательное evidence невозможно получить.
        # Такой blocker должен быть представим без ложного FAIL -> FIX.
        blocked_evidence = root / "planning/reviews/STEP-001/REVIEW-20260921T043000Z.md"
        review_report(root, "PASS", blocked_evidence.name)
        blocked_text = blocked_evidence.read_text(encoding="utf-8")
        blocked_text = blocked_text.replace("verdict: pass", "verdict: blocked")
        blocked_text = blocked_text.replace(
            "  security: not_required",
            "  security: blocked",
        ).replace(
            "  security_evidence: null",
            "  security_evidence: required security evidence is unavailable",
        )
        blocked_text = blocked_text.replace(
            "No material findings.",
            """### F-001 — Security evidence unavailable

**Severity:** high
**Category:** evidence
**Location:** security verification
**Scenario:** Given required security review / When evidence cannot be obtained / Then review cannot safely pass
**Impact:** acceptance cannot be proven
**Fix direction:** restore the missing verification prerequisite
""",
        )
        write(blocked_evidence, blocked_text)
        from review_contract import validate_review_report
        assert not validate_review_report(root, blocked_evidence), validate_review_report(
            root, blocked_evidence
        )
        blocked_evidence.unlink()

        # Schema-v1 implementation review names участвуют в deterministic
        # latest ordering и потому обязаны иметь canonical UTC timestamp.
        invalid_review_name = root / "planning/reviews/STEP-001/REVIEW-not-a-timestamp.md"
        review_report(root, "PASS", invalid_review_name.name)
        from review_contract import validate_review_report
        assert any(
            "filename must be REVIEW-<UTC timestamp>.md" in item
            for item in validate_review_report(root, invalid_review_name)
        )
        invalid_review_name.unlink()

        mismatched_review = root / "planning/reviews/STEP-001/REVIEW-20260921T050000Z.md"
        review_report(root, "PASS", mismatched_review.name)
        mismatch_text = mismatched_review.read_text(encoding="utf-8").replace(
            "created_at: 2026-09-21T05:00:00Z",
            "created_at: 2026-09-21T05:00:01Z",
        )
        write(mismatched_review, mismatch_text)
        mismatch_errors = validate_review_report(root, mismatched_review)
        assert any(
            "created_at must match UTC timestamp encoded in filename" in item
            for item in mismatch_errors
        ), mismatch_errors
        mismatched_review.unlink()

        # STEP RUN recovers completed PLAN from matching basis+content+planning-review.
        run_root = "STEP RUN STEP-001"
        run_exec = start_execution(root, run_root)
        begin_command(root, run_root, "STEP PLAN STEP-001")
        assert_resolved(
            resolve_root(root, run_root),
            "NEXT",
            "STEP IMPLEMENT STEP-001",
            "ORCHESTRATION_CTS_TRANSITION",
        )

        begin_command(root, run_root, "STEP IMPLEMENT STEP-001")
        assert_resolved(
            resolve_root(root, run_root),
            "RESUME",
            "STEP IMPLEMENT STEP-001",
            "COMMAND_INTERRUPTED",
        )
        # An unrelated execution must not overwrite interrupted orchestration.
        overlay = start_execution(root, "GIT CHECK")
        complete_command(root, overlay["rootCommand"], "GIT CHECK", "PASS")
        assert resolve_root(root, run_root)["command"] == "STEP IMPLEMENT STEP-001"
        assert any(item["executionId"] == run_exec["executionId"] for item in unresolved_executions(root))

        # REVIEW crash recovery trusts only valid report for exact revision.
        complete_command(root, run_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        review_report(root, "FAIL", "REVIEW-20260921T010000Z.md")
        invalid_role = root / "planning/reviews/STEP-001/REVIEW-20260921T005000Z.md"
        valid_text = (root / "planning/reviews/STEP-001/REVIEW-20260921T010000Z.md").read_text(encoding="utf-8")
        write(invalid_role, valid_text.replace("reviewer_role: reviewer", "reviewer_role: implementer"))
        from review_contract import validate_review_report
        assert any(
            "reviewer_role must be reviewer" in item
            for item in validate_review_report(root, invalid_role)
        )
        invalid_role.unlink()

        # Schema-v1 PASS report без какого-либо revision identity не может быть
        # durable completion proof даже если остальные поля синтаксически валидны.
        revisionless = root / "planning/reviews/STEP-001/REVIEW-20260921T005500Z.md"
        revision_now = repository_revision(root)
        assert revision_now["git_head"] is not None, revision_now
        revisionless_text = valid_text.replace(
            f"  git_head: {revision_now['git_head']}",
            "  git_head: null",
        )
        if revision_now["worktree_hash"] is not None:
            revisionless_text = revisionless_text.replace(
                f"  worktree_hash: {revision_now['worktree_hash']}",
                "  worktree_hash: null",
            )
        write(revisionless, revisionless_text)
        revisionless_errors = validate_review_report(root, revisionless)
        assert any(
            "reviewed_revision must contain git_head or worktree_hash" in item
            for item in revisionless_errors
        ), revisionless_errors
        revisionless.unlink()

        # Hash/OID fields являются machine trust proof: длины строки недостаточно.
        malformed_revision = root / "planning/reviews/STEP-001/REVIEW-20260921T005600Z.md"
        malformed_text = valid_text.replace(
            f"  git_head: {revision_now['git_head']}",
            "  git_head: not-a-git-object-id",
        )
        if revision_now["worktree_hash"] is not None:
            malformed_text = malformed_text.replace(
                f"  worktree_hash: {revision_now['worktree_hash']}",
                "  worktree_hash: sha256:" + ("g" * 64),
            )
        write(malformed_revision, malformed_text)
        malformed_errors = validate_review_report(root, malformed_revision)
        assert any("40/64-hex Git OID" in item for item in malformed_errors), malformed_errors
        if revision_now["worktree_hash"] is not None:
            assert any("worktree_hash must be null or sha256" in item for item in malformed_errors), malformed_errors
        malformed_revision.unlink()

        recovered = resolve_root(root, run_root)
        assert_resolved(recovered, "NEXT", "STEP FIX STEP-001", "ORCHESTRATION_CTS_TRANSITION")

        begin_command(root, run_root, "STEP FIX STEP-001")
        complete_command(root, run_root, "STEP FIX STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        review_report(root, "PASS", "REVIEW-20260921T020000Z.md")
        assert_resolved(
            resolve_root(root, run_root),
            "RESUME",
            "STEP RUN STEP-001",
            "ORCHESTRATION_CONTINUE",
        )

        # Exact revision invalidation: product mutation after report prevents recovery.
        other_root = "STEP RUN STEP-001"
        existing = resolve_root(root, run_root)
        if existing["status"] == "RESUME":
            begin_command(root, run_root, "STEP RUN STEP-001")
            complete_command(root, run_root, "STEP RUN STEP-001", "SUCCESS")
        second = start_execution(root, other_root)
        begin_command(root, other_root, "STEP IMPLEMENT STEP-001")
        complete_command(root, other_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, other_root, "STEP REVIEW STEP-001")
        review_report(root, "PASS", "REVIEW-20260921T030000Z.md")
        write(root / "src/product.txt", "changed after review\n")
        unresolved = resolve_root(root, other_root)
        assert unresolved["status"] == "RESUME" and unresolved["command"] == "STEP REVIEW STEP-001", unresolved

        # maxFixReviewCycles=1 blocks a second FAIL after one successful FIX→REVIEW cycle.
        # Finish current review explicitly so a clean independent RUN can start.
        complete_command(root, other_root, "STEP REVIEW STEP-001", "PASS")
        begin_command(root, other_root, "STEP RUN STEP-001")
        complete_command(root, other_root, "STEP RUN STEP-001", "SUCCESS")

        limited = start_execution(root, run_root)
        begin_command(root, run_root, "STEP IMPLEMENT STEP-001")
        complete_command(root, run_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        complete_command(root, run_root, "STEP REVIEW STEP-001", "FAIL")
        assert resolve_root(root, run_root)["command"] == "STEP FIX STEP-001"
        begin_command(root, run_root, "STEP FIX STEP-001")
        complete_command(root, run_root, "STEP FIX STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        complete_command(root, run_root, "STEP REVIEW STEP-001", "FAIL")
        exhausted = resolve_root(root, run_root)
        assert_resolved(exhausted, "BLOCKED", None, "FIX_REVIEW_LIMIT_REACHED")
        assert exhausted["fixReviewCycles"] == 1

        # Specialized result без конкретного evidence summary/reference невалиден.
        evidence_probe = root / "planning/reviews/STEP-001/REVIEW-20260921T040000Z.md"
        review_report(root, "PASS", evidence_probe.name)
        probe_text = evidence_probe.read_text(encoding="utf-8").replace(
            "tests_evidence: inline verification in this review",
            "tests_evidence: null",
        )
        write(evidence_probe, probe_text)
        from review_contract import validate_review_report
        assert any(
            "requires evidence summary/reference" in item
            for item in validate_review_report(root, evidence_probe)
        )
        evidence_probe.unlink()

        # Overall PASS не может скрыть FAIL обязательного specialized reviewer.
        specialized_fail = root / "planning/reviews/STEP-001/REVIEW-20260921T041000Z.md"
        review_report(root, "PASS", specialized_fail.name)
        fail_text = specialized_fail.read_text(encoding="utf-8").replace(
            "  tests: pass",
            "  tests: fail",
        )
        write(specialized_fail, fail_text)
        assert any(
            "PASS review requires PASS for all required specialized reviewers" in item
            for item in validate_review_report(root, specialized_fail)
        )
        specialized_fail.unlink()

        # Deterministic preselector задаёт minimum, но reviewer может добровольно
        # добавить security/tests review. Если такая дополнительная проверка
        # реально выполнена и вернула FAIL, overall PASS обязан быть запрещён.
        optional_specialized_fail = root / "planning/reviews/STEP-001/REVIEW-20260921T042000Z.md"
        review_report(root, "PASS", optional_specialized_fail.name)
        optional_fail_text = optional_specialized_fail.read_text(encoding="utf-8")
        optional_fail_text = optional_fail_text.replace(
            "  security: not_required",
            "  security: fail",
        ).replace(
            "  security_evidence: null",
            "  security_evidence: optional security review found a defect",
        )
        write(optional_specialized_fail, optional_fail_text)
        assert any(
            "PASS review cannot ignore optional specialized reviewer FAIL" in item
            for item in validate_review_report(root, optional_specialized_fail)
        )
        optional_specialized_fail.unlink()

        blocked = block_execution(root, run_root, command="STEP REVIEW STEP-001")
        assert blocked["current"]["result"] == "FAIL"

        # Report identity привязан не только к frontmatter, но и к
        # STEP-NNN directory. Иначе PASS другого STEP можно было подложить в
        # чужую history.
        cross_step = root / "planning/reviews/STEP-999/REVIEW-20260921T044000Z.md"
        source_review = root / "planning/reviews/STEP-001/REVIEW-20260921T020000Z.md"
        write(cross_step, source_review.read_text(encoding="utf-8"))
        from review_contract import validate_review_report
        cross_errors = validate_review_report(root, cross_step)
        assert any("step_id must match review directory STEP-999" in item for item in cross_errors), cross_errors
        assert not review_reports(root, "STEP-999"), review_reports(root, "STEP-999")
        cross_step.unlink()

        # Immutable schema-v1 review обязан быть обычным file artifact, не
        # symlink на mutable/чужое содержимое.
        symlink_review = root / "planning/reviews/STEP-001/REVIEW-20260921T044500Z.md"
        symlink_review.symlink_to(source_review.name)
        symlink_errors = validate_review_report(root, symlink_review)
        assert any("must not be a symlink" in item for item in symlink_errors), symlink_errors
        assert all(item["path"] != symlink_review for item in review_reports(root, "STEP-001"))
        symlink_review.unlink()

        # Legacy review filenames до schema-v1 не были канонизированы. Даже
        # лексикографически "поздний" pinned legacy report остаётся historical
        # и не может перекрыть новый schema-v1 review после migration.
        legacy_rel = "planning/reviews/STEP-001/REVIEW-z-legacy.md"
        legacy_path = root / legacy_rel
        write(
            legacy_path,
            """# STEP REVIEW STEP-001 — legacy

**Verdict:** PASS
""",
        )
        trusted = latest_trusted_review(
            root,
            "STEP-001",
            extra_legacy_pins={
                legacy_rel: content_hash(legacy_path.read_text(encoding="utf-8"))
            },
        )
        assert trusted is not None and not trusted.get("legacy"), trusted
        legacy_path.unlink()

        # One fixed project-level state file, no per-STEP JSON.
        fixed = root / ".harness/local/execution/execution-status.json"
        assert fixed.is_file()
        assert not list((root / ".harness/local/execution").glob("STEP-*.json"))

        # Immutable review history: addition разрешена, но после попадания report
        # в Git его rewrite блокируется и в pre-commit state, и в CI diff.
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "checkpoint immutable review")
        immutable_report = root / "planning/reviews/STEP-001/REVIEW-20260921T010000Z.md"
        original_report = immutable_report.read_text(encoding="utf-8")
        write(immutable_report, original_report + "\n<!-- rewritten -->\n")
        # Existing immutable report mutation is not a self-created report
        # addition and therefore must stay visible in exact revision fingerprint.
        rewritten_revision = repository_revision(root)
        assert rewritten_revision["worktree_hash"] is not None, rewritten_revision
        immutability_errors = validate_review_immutability(root)
        assert any("existing report changed" in item for item in immutability_errors), immutability_errors
        run(root, "git", "add", immutable_report.relative_to(root).as_posix())
        run(root, "git", "commit", "-qm", "rewrite immutable review")
        ci_immutability_errors = validate_review_immutability(root, ci_mode=True)
        assert any("existing report changed (commit)" in item for item in ci_immutability_errors), ci_immutability_errors

        # Shallow checkout с единственным видимым commit не является настоящим
        # root commit: отсутствие HEAD^1 должно fail closed, а не обходить gate.
        shallow_parent = Path(tempfile.mkdtemp(prefix="harness-shallow-review-"))
        try:
            shallow = shallow_parent / "repo"
            run(
                root,
                "git",
                "clone",
                "-q",
                "--depth",
                "1",
                f"file://{root.resolve()}",
                str(shallow),
            )
            shallow_errors = validate_review_immutability(shallow, ci_mode=True)
            assert any(
                "cannot resolve CI baseline HEAD^1" in item
                for item in shallow_errors
            ), shallow_errors
        finally:
            shutil.rmtree(shallow_parent, ignore_errors=True)

        # Durable directories могут перекрываться. Более широкий
        # reviewDirectory не должен маскировать nested planningReviewDirectory
        # при проверке immutable history.
        overlap_manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
        write(
            root / ".harness/manifest.yaml",
            overlap_manifest.replace(
                "reviewDirectory: planning/reviews",
                "reviewDirectory: planning",
            ),
        )
        run(root, "git", "add", ".harness/manifest.yaml")
        run(root, "git", "commit", "-qm", "overlapping review directories fixture")
        nested_plan_report = root / plan_report
        nested_plan_original = nested_plan_report.read_text(encoding="utf-8")
        write(nested_plan_report, nested_plan_original + "\n<!-- rewritten nested planning review -->\n")
        overlap_errors = validate_review_immutability(root)
        assert any(
            "existing report changed" in item and "PLAN-REVIEW-" in item
            for item in overlap_errors
        ), overlap_errors
        run(root, "git", "checkout", "--", plan_report)
        write(root / ".harness/manifest.yaml", overlap_manifest)
        run(root, "git", "add", ".harness/manifest.yaml")
        run(root, "git", "commit", "-qm", "restore review directories fixture")

        # Exact revision различает index и working tree. Одинаковые working bytes
        # при разных staged blobs не могут давать одинаковый review proof.
        write(root / "src/index-proof.txt", "base\n")
        run(root, "git", "add", "src/index-proof.txt")
        run(root, "git", "commit", "-qm", "add index proof fixture")
        write(root / "src/index-proof.txt", "staged-a\n")
        run(root, "git", "add", "src/index-proof.txt")
        write(root / "src/index-proof.txt", "working-same\n")
        index_revision_a = repository_revision(root)
        write(root / "src/index-proof.txt", "staged-b\n")
        run(root, "git", "add", "src/index-proof.txt")
        write(root / "src/index-proof.txt", "working-same\n")
        index_revision_b = repository_revision(root)
        assert index_revision_a["worktree_hash"] != index_revision_b["worktree_hash"], (
            index_revision_a,
            index_revision_b,
        )
        run(root, "git", "add", "src/index-proof.txt")
        run(root, "git", "commit", "-qm", "finish index proof fixture")

        # Same staged/worktree bytes + same XY должны различаться только Git
        # mode. Старый content-only hash давал collision между 100644 и 100755.
        mode_path = root / "src/mode-proof.sh"
        write(mode_path, "#!/bin/sh\necho base\n")
        mode_path.chmod(0o644)
        run(root, "git", "add", "src/mode-proof.sh")
        run(root, "git", "commit", "-qm", "add mode proof fixture")
        write(mode_path, "#!/bin/sh\necho changed\n")
        mode_path.chmod(0o644)
        run(root, "git", "add", "src/mode-proof.sh")
        mode_revision_644 = repository_revision(root)
        run(root, "git", "update-index", "--chmod=+x", "src/mode-proof.sh")
        mode_path.chmod(0o755)
        mode_revision_755 = repository_revision(root)
        assert mode_revision_644["worktree_hash"] != mode_revision_755["worktree_hash"], (
            mode_revision_644,
            mode_revision_755,
        )
        run(root, "git", "reset", "--hard", "HEAD")

        # Gitlink path обязан включать current nested HEAD. Два разных submodule
        # commits при одинаковом parent XY/paths не могут иметь один proof.
        submodule_source = Path(tempfile.mkdtemp(prefix="harness-submodule-source-"))
        try:
            run(submodule_source, "git", "init", "-q")
            run(submodule_source, "git", "config", "user.email", "harness-test@example.invalid")
            run(submodule_source, "git", "config", "user.name", "Harness Test")
            write(submodule_source / "value.txt", "a\n")
            run(submodule_source, "git", "add", ".")
            run(submodule_source, "git", "commit", "-qm", "a")
            sha_a = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=submodule_source, text=True
            ).strip()
            write(submodule_source / "value.txt", "b\n")
            run(submodule_source, "git", "add", ".")
            run(submodule_source, "git", "commit", "-qm", "b")
            sha_b = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=submodule_source, text=True
            ).strip()
            write(submodule_source / "value.txt", "c\n")
            run(submodule_source, "git", "add", ".")
            run(submodule_source, "git", "commit", "-qm", "c")
            sha_c = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=submodule_source, text=True
            ).strip()

            run(
                root,
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "-q",
                str(submodule_source),
                "vendor/demo",
            )
            run(root / "vendor/demo", "git", "checkout", "-q", sha_a)
            run(root, "git", "add", ".gitmodules", "vendor/demo")
            run(root, "git", "commit", "-qm", "add submodule proof fixture")

            run(root / "vendor/demo", "git", "checkout", "-q", sha_b)
            submodule_revision_b = repository_revision(root)
            run(root / "vendor/demo", "git", "checkout", "-q", sha_c)
            submodule_revision_c = repository_revision(root)
            assert submodule_revision_b["worktree_hash"] != submodule_revision_c["worktree_hash"], (
                submodule_revision_b,
                submodule_revision_c,
            )
            run(root / "vendor/demo", "git", "checkout", "-q", sha_a)
        finally:
            shutil.rmtree(submodule_source, ignore_errors=True)
        # На clean tree specialized preselector не теряет уже committed implementation surface.

        # Rename/copy source path входит в exact revision identity. Иначе два
        # staged rename из разных одинаковых source files в один destination
        # давали бы одинаковый fingerprint.
        write(root / "src/rename-a.txt", "same bytes\n")
        write(root / "src/rename-b.txt", "same bytes\n")
        run(root, "git", "add", "src/rename-a.txt", "src/rename-b.txt")
        run(root, "git", "commit", "-qm", "add rename identity fixtures")
        run(root, "git", "mv", "src/rename-a.txt", "src/rename-target.txt")
        rename_revision_a = repository_revision(root)
        run(root, "git", "reset", "--hard", "HEAD")
        run(root, "git", "mv", "src/rename-b.txt", "src/rename-target.txt")
        rename_revision_b = repository_revision(root)
        assert rename_revision_a["worktree_hash"] != rename_revision_b["worktree_hash"], (
            rename_revision_a,
            rename_revision_b,
        )
        run(root, "git", "reset", "--hard", "HEAD")

        write(root / "src/auth/session.py", "def changed_auth():\n    return True\n")
        run(root, "git", "add", "src/auth/session.py")
        run(root, "git", "commit", "-qm", "committed auth change")
        committed_gate = required_reviewers(root, "STEP-001")
        assert committed_gate["surfaceMode"] == "clean-tree-fallback", committed_gate
        assert {"security", "tests"}.issubset(set(committed_gate["required"])), committed_gate
        assert "src/auth/session.py" in committed_gate["changedPaths"], committed_gate

        # Последний harmless commit не должен скрыть security change из более
        # раннего unreviewed commit: clean-tree fallback остаётся fail-closed.
        write(root / "notes.txt", "harmless follow-up\n")
        run(root, "git", "add", "notes.txt")
        run(root, "git", "commit", "-qm", "harmless follow-up commit")
        multi_commit_gate = required_reviewers(root, "STEP-001")
        assert multi_commit_gate["surfaceMode"] == "clean-tree-fallback", multi_commit_gate
        assert {"security", "tests"}.issubset(set(multi_commit_gate["required"])), multi_commit_gate
        assert "src/auth/session.py" not in multi_commit_gate["changedPaths"], multi_commit_gate
        assert "clean tree has no exact implementation baseline" in multi_commit_gate["reasons"]["security"]

        # Параллельные sessions не должны потерять attempt update или создать
        # несколько running records одной root command. Восемь процессов
        # одновременно проходят один load -> mutate -> save transaction.
        concurrent_command = "HARNESS CONFIG"
        workers = [
            multiprocessing.Process(
                target=concurrent_start_worker,
                args=(str(root), concurrent_command),
            )
            for _ in range(8)
        ]
        for worker_process in workers:
            worker_process.start()
        for worker_process in workers:
            worker_process.join(20)
            assert worker_process.exitcode == 0, worker_process.exitcode

        concurrent_status = load_status(root)
        concurrent_records = [
            item
            for item in concurrent_status["executions"]
            if item.get("rootCommand") == concurrent_command
            and item.get("status") == "running"
        ]
        assert len(concurrent_records) == 1, concurrent_records
        assert concurrent_records[0]["current"]["attempt"] == 8, concurrent_records[0]
        complete_command(
            root,
            concurrent_command,
            concurrent_command,
            "SUCCESS",
        )
    print("EXECUTION STATUS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
