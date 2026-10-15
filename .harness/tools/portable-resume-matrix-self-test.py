#!/usr/bin/env python3
"""#302: негативная матрица Portable Resume на реальных Git-клонах.

Один локальный bare remote, отдельные независимые clones и настоящие Git
objects. Ни один тест не использует внешнюю сеть, Claude/Codex или GitHub API.
Fixtures переиспользуют уже проверенный #301 helper, а не создают второй
parser STEP/REQ/ADR или собственный список canonical документов.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

from portable_handoff import (
    PortableHandoffError,
    _handoff_path,
    check_handoff,
    write_handoff,
)
from portable_resume import portable_resume_candidate
from harness_ux import harness_resume
from planning_contract import (
    latest_matching_planning_review,
    planning_context_basis,
)
from repository_recovery import repository_recovery_preview
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]
STEP_ID = "STEP-017"


def _existing_fixture():
    """Брать существующие реалистичные STEP и PLAN-REVIEW из #301 self-test."""
    path = Path(__file__).with_name("portable-resume-self-test.py")
    spec = importlib.util.spec_from_file_location("portable_resume_test_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURE = _existing_fixture()


def git(root: Path, *args: str, success: bool = True) -> str:
    process = subprocess.run(
        ("git", *args), cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=45,
    )
    if success:
        assert process.returncode == 0, (args, process.stdout, process.stderr)
    else:
        assert process.returncode != 0, (args, process.stdout, process.stderr)
    return process.stdout.strip()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def requirement() -> str:
    return """---
schema: 1
id: REQ-901
priority: medium
source: portable_resume_test
steps:
  - STEP-017
adrs:
  - ADR-901
---

# REQ-901 — Cross-clone contract

## Requirement

Portable transfer may not silently change project behavior.

## Rationale

The same implementation should be safe on another computer.

## Acceptance

- Published code matches the reviewed intent.
"""


def adr() -> str:
    return """---
schema: 1
id: ADR-901
status: accepted
date: 2026-10-11
deciders:
  - test
supersedes: []
superseded_by: []
requirements:
  - REQ-901
steps:
  - STEP-017
---

# ADR-901 — Portable safety boundary

## Context

The project has two independent workspaces.

## Problem

Native execution sessions are not portable.

## Decision

Transfer only published canonical Git state.

## Alternatives considered

- Copying local execution-status.json is forbidden.

## Consequences

A new local PLAN is required.

## Security implications

No native session handles or tokens.

## Data / migration implications

No remote execution state migration.

## Compatibility / operational implications

Local resume semantics must remain stable.
"""


def principle() -> str:
    return """---
schema: 1
id: PRN-901
status: active
severity: blocking
scope: project
superseded_by: null
requirements:
  - REQ-901
adrs:
  - ADR-901
---

# PRN-901 — Git publication safety

## Rule

Do not resume from an outdated Git handoff.

## Rationale

Old evidence does not authorize future code.

## Applies to

All project STEP implementations.

## Exceptions / approved deviation

Explicit reviewed deviation only.
"""


def linked_ready_step(root: Path) -> None:
    """Создать реальные связанные REQ/ADR/PRN и обновить canonical basis."""
    FIXTURE._prepare_ready_step(root)
    req = root / "docs/requirements/REQ-901-portable.md"
    adrp = root / "docs/adr/ADR-901-portable.md"
    prn = root / "docs/principles/PRN-901-portable.md"
    write(req, requirement())
    write(adrp, adr())
    write(prn, principle())

    path = root / "planning/tasks/STEP-017.md"
    raw = path.read_text(encoding="utf-8")
    # Изначальная Ready basis записана до появления linked REQ/ADR/PRN.
    # Не вычислять её заново по уже изменённым artifacts: это был бы
    # другой (непубликованный) semantic snapshot.
    stored_basis = raw.split("  context_basis: ", 1)[1].splitlines()[0]
    assert stored_basis.startswith("sha256:"), stored_basis
    raw = raw.replace("requirements: []", "requirements:\n  - REQ-901", 1)
    raw = raw.replace("adrs: []", "adrs:\n  - ADR-901", 1)
    write(path, raw)
    current_basis = planning_context_basis(root, STEP_ID)
    assert current_basis != stored_basis
    raw = raw.replace(stored_basis, current_basis, 1)
    write(path, raw)

    review = root / "planning/plan-reviews/STEP-017/PLAN-REVIEW-20261011T000000Z.md"
    original_review = review.read_text(encoding="utf-8")
    assert stored_basis in original_review
    write(review, original_review.replace(stored_basis, current_basis, 1))
    assert latest_matching_planning_review(root, STEP_ID) is not None


def setup(root: Path) -> tuple[Path, Path]:
    """Создать desktop → bare origin с опубликованным единственным handoff."""
    desktop, origin = root / "desktop", root / "origin.git"
    desktop.mkdir()
    copy_effective_harness_checkout(SOURCE_ROOT, desktop)
    isolate_project_artifacts(desktop)
    manifest = desktop / ".harness/manifest.yaml"
    content = manifest.read_text(encoding="utf-8")
    assert "initialized: false" in content
    write(manifest, content.replace("initialized: false", "initialized: true", 1))
    linked_ready_step(desktop)
    git(root, "init", "--bare", "-q", "-b", "main", str(origin))
    git(desktop, "init", "-q", "-b", "main")
    git(desktop, "config", "user.name", "Portable matrix")
    git(desktop, "config", "user.email", "matrix@example.invalid")
    git(desktop, "remote", "add", "origin", str(origin))
    git(desktop, "add", ".")
    git(desktop, "commit", "-qm", "canonical ready project")
    git(desktop, "push", "-q", "-u", "origin", "main")

    # Приватная история и Verification proof остаются только на desktop.
    from execution_status import start_execution
    origin_execution = start_execution(desktop, "STEP IMPLEMENT STEP-017")
    assert origin_execution["executionId"]
    write(desktop / ".harness/local/verification-proofs/local-only.json", '{"valid":false}\n')
    assert git(desktop, "status", "--porcelain") == ""

    handoff = write_handoff(desktop, STEP_ID)
    assert handoff["status"] == "PASS", handoff
    git(desktop, "add", handoff["path"])
    git(desktop, "commit", "-qm", "publish STEP handoff")
    git(desktop, "push", "-q", "origin", "main")
    assert check_handoff(desktop, STEP_ID)["status"] == "PASS"
    return desktop, origin


def clone(root: Path, origin: Path, name: str) -> Path:
    path = root / name
    git(root, "clone", "-q", "--branch", "main", str(origin), str(path))
    git(path, "config", "user.name", "Portable matrix")
    git(path, "config", "user.email", "matrix@example.invalid")
    return path


def commit(root: Path, path: str, message: str) -> None:
    git(root, "add", "--", path)
    git(root, "commit", "-qm", message)


def assert_blocked(root: Path, *reasons: str) -> None:
    """Проверить и raw handoff, и публичный HARNESS RESUME, без local import."""
    raw = check_handoff(root, STEP_ID)
    assert raw["status"] == "BLOCKED", raw
    assert raw["reasonCode"] in reasons, (raw, reasons)
    selected = harness_resume(root)
    assert selected["status"] == "BLOCKED", selected
    assert selected["reasonCode"] in reasons, (selected, reasons)
    assert not (root / ".harness/local/execution/execution-status.json").exists()


def test_semantic_changes(root: Path, origin: Path) -> None:
    # REQ / accepted ADR / blocking PRN are actual canonical upstream inputs.
    for filename, before, after in (
        ("docs/requirements/REQ-901-portable.md",
         "Published code matches the reviewed intent.", "Reviewed intent changed."),
        ("docs/adr/ADR-901-portable.md",
         "Transfer only published canonical Git state.", "Transfer some other state."),
        ("docs/principles/PRN-901-portable.md",
         "Do not resume from an outdated Git handoff.", "A different safety rule."),
    ):
        folder = filename.split("/")[1]
        other = clone(root, origin, "drift-" + folder)
        path = other / filename
        content = path.read_text(encoding="utf-8")
        assert before in content
        write(path, content.replace(before, after, 1))
        commit(other, filename, "upstream semantic drift")
        assert_blocked(other, "HANDOFF_CONTRACT_STALE")

    # Modified acceptance and Ready plan are changes of the STEP Git object.
    for name, before, after in (
        ("acceptance", "New clone receives a new local planning execution only.",
         "A changed, not-reviewed acceptance criterion."),
        ("plan", "Inspect the published code and task.",
         "Do unrelated work in a new plan."),
        ("status", "status: in_progress", "status: completed"),
    ):
        target = clone(root, origin, "step-" + name)
        filename = "planning/tasks/STEP-017.md"
        content = (target / filename).read_text(encoding="utf-8")
        assert before in content
        write(target / filename, content.replace(before, after, 1))
        commit(target, filename, "change canonical STEP " + name)
        if name == "status":
            # Completed is not offered as interrupted; there is no candidate.
            result = harness_resume(target)
            assert result["reasonCode"] == "NO_RESUMABLE_EXECUTION", result
        else:
            assert_blocked(target, "HANDOFF_STEP_CHANGED")

    missing = clone(root, origin, "missing-ref")
    filename = "planning/tasks/STEP-017.md"
    text = (missing / filename).read_text(encoding="utf-8")
    assert "REQ-901" in text
    write(missing / filename, text.replace("REQ-901", "REQ-999", 1))
    commit(missing, filename, "missing REQ fixture")
    bad_refs = repository_recovery_preview(missing)
    assert bad_refs["status"] == "BLOCKED", bad_refs
    assert bad_refs["reasonCode"] == "STEP_REFERENCES_UNPROVEN", bad_refs

    # Dependency cycle must never become portable execution, even when all
    # referenced files exist. STEP Git object changes after publication,
    # so the existing canonical freshness gate is enough to fail closed.
    cyclic = clone(root, origin, "dependency-cycle")
    current_step = "planning/tasks/STEP-017.md"
    first = (cyclic / current_step).read_text(encoding="utf-8")
    assert "depends_on: []" in first
    write(cyclic / current_step, first.replace(
        "depends_on: []", "depends_on:\n  - STEP-018", 1,
    ))
    second = FIXTURE._task().replace("STEP-017", "STEP-018")
    second = second.replace("status: in_progress", "status: planned", 1)
    second = second.replace("depends_on: []", "depends_on:\n  - STEP-017", 1)
    write(cyclic / "planning/tasks/STEP-018.md", second)
    git(cyclic, "add", current_step, "planning/tasks/STEP-018.md")
    git(cyclic, "commit", "-qm", "introduce cyclic STEP dependencies")
    cycle_result = harness_resume(cyclic)
    assert cycle_result["status"] == "BLOCKED", cycle_result
    assert not (cyclic / ".harness/local/execution/execution-status.json").exists()

    partial = clone(root, origin, "draft-plan")
    filename = "planning/tasks/STEP-017.md"
    text = (partial / filename).read_text(encoding="utf-8")
    assert "  status: ready" in text
    write(partial / filename, text.replace("  status: ready", "  status: draft", 1))
    commit(partial, filename, "plan is no longer ready")
    assert harness_resume(partial)["status"] == "BLOCKED"

    # Two independent in_progress STEP are intentionally ambiguous for the
    # argument-free HARNESS RESUME; use explicit planning outside auto adoption.
    multiple = clone(root, origin, "parallel-steps")
    other = FIXTURE._task().replace("STEP-017", "STEP-018")
    write(multiple / "planning/tasks/STEP-018.md", other)
    commit(multiple, "planning/tasks/STEP-018.md", "second active step")
    ambiguous = harness_resume(multiple)
    assert ambiguous["reasonCode"] == "PORTABLE_CANDIDATES_AMBIGUOUS", ambiguous


def test_schema_and_traversal(root: Path, origin: Path) -> None:
    for kind in ("future-schema", "session-secret"):
        local = clone(root, origin, kind)
        name = "planning/handoffs/STEP-017.json"
        path = local / name
        value = json.loads(path.read_text(encoding="utf-8"))
        if kind == "future-schema":
            value["schemaVersion"] = 999
        else:
            value["nativeSessionId"] = "secret-must-never-cross"
        write(path, json.dumps(value, sort_keys=True) + "\n")
        commit(local, name, "unsupported handoff")
        assert_blocked(local, "HANDOFF_SCHEMA_INVALID")

    bad_id = clone(root, origin, "bad-step-id")
    invalid = check_handoff(bad_id, "STEP-../secret")
    assert invalid["status"] == "BLOCKED", invalid
    # Public checker wraps the repository diagnostic; preserve inner code.
    assert invalid["reasonCode"] == "REPOSITORY_STATE_INVALID", invalid
    assert "INVALID_STEP_ID" in invalid["message"], invalid

    unsafe = clone(root, origin, "symlink-path")
    file = unsafe / "planning/handoffs/STEP-017.json"
    outside = root / "outside.json"
    write(outside, '{"owner":"outside"}\n')
    file.unlink()
    try:
        file.symlink_to(outside)
    except (OSError, NotImplementedError):
        # Windows runner может быть без privileges; Linux обязательно проверит.
        assert os.name == "nt"
    else:
        try:
            _handoff_path(unsafe, STEP_ID, create=False)
        except PortableHandoffError as exc:
            assert exc.code == "HANDOFF_PATH_UNSAFE", exc
        else:
            raise AssertionError("symlink handoff must never be allowed")
        assert outside.read_text(encoding="utf-8") == '{"owner":"outside"}\n'


def test_publication_races(root: Path, origin: Path) -> None:
    a = clone(root, origin, "publisher-a")
    b = clone(root, origin, "publisher-b")
    for clone_root, message in ((a, "renewal from A"), (b, "renewal from B")):
        renewed = write_handoff(clone_root, STEP_ID)
        assert renewed["status"] == "PASS", renewed
        commit(clone_root, renewed["path"], message)

    git(a, "push", "-q", "origin", "main")
    git(b, "push", "-q", "origin", "main", success=False)
    git(b, "fetch", "-q", "origin")
    # B's local snapshot still has correct STEP/REQ/ADR fingerprints.
    # But remote-tracking branch is now another published head: fail closed.
    assert_blocked(b, "HANDOFF_UPSTREAM_DIVERGED")

    # Explicit pull/reconciliation moves HEAD to A. B's superseded handoff
    # must not become magically safe just because its source is an ancestor.
    git(b, "reset", "--hard", "origin/main")
    matched = check_handoff(b, STEP_ID)
    assert matched["status"] == "PASS", matched

    # A continued work and pushed after handoff; B explicitly fetched and
    # pulled the new commit, which makes the old handoff stale even if the
    # STEP object and its semantic hashes did not change.
    write(a / "src/new-code.txt", "product code changed after publication\n")
    commit(a, "src/new-code.txt", "continued implementation")
    git(a, "push", "-q", "origin", "main")
    git(b, "pull", "-q", "--ff-only", "origin", "main")
    assert_blocked(b, "HANDOFF_OUTDATED")

    # Без явного fetch/pull B не может знать о новом удалённом commit.
    # Поэтому Harness сам не делает сеть и не обещает distributed lease.



def test_custom_task_directory(root: Path, origin: Path) -> None:
    """Manifest-first layout: нет скрытого planning/tasks второго источника."""
    custom = clone(root, origin, "custom-layout")
    git(custom, "switch", "-q", "-c", "custom-layout")
    manifest = custom / ".harness/manifest.yaml"
    original = manifest.read_text(encoding="utf-8")
    assert "taskDirectory: planning/tasks" in original
    write(
        manifest,
        original.replace("taskDirectory: planning/tasks", "taskDirectory: custom/steps", 1),
    )
    (custom / "custom/steps").mkdir(parents=True)
    git(custom, "mv", "planning/tasks/STEP-017.md", "custom/steps/STEP-017.md")

    task_path = custom / "custom/steps/STEP-017.md"
    text = task_path.read_text(encoding="utf-8")
    old_basis = text.split("  context_basis: ", 1)[1].splitlines()[0]
    basis = planning_context_basis(custom, STEP_ID)
    if basis != old_basis:
        write(task_path, text.replace(old_basis, basis, 1))
        review = custom / "planning/plan-reviews/STEP-017/PLAN-REVIEW-20261011T000000Z.md"
        data = review.read_text(encoding="utf-8")
        assert old_basis in data
        write(review, data.replace(old_basis, basis, 1))
    assert latest_matching_planning_review(custom, STEP_ID) is not None
    git(custom, "add", ".harness/manifest.yaml",
        "planning/plan-reviews/STEP-017/PLAN-REVIEW-20261011T000000Z.md",
        "custom/steps/STEP-017.md")
    git(custom, "commit", "-qm", "use manifest-defined custom STEP topology")
    git(custom, "push", "-q", "-u", "origin", "custom-layout")

    handoff = write_handoff(custom, STEP_ID)
    assert handoff["status"] == "PASS", handoff
    assert handoff["path"] == "custom/handoffs/STEP-017.json", handoff
    commit(custom, handoff["path"], "publish custom topology handoff")
    git(custom, "push", "-q", "origin", "custom-layout")

    other = root / "custom-laptop"
    git(root, "clone", "-q", "--branch", "custom-layout", str(origin), str(other))
    proven = check_handoff(other, STEP_ID)
    assert proven["status"] == "PASS", proven
    picked = harness_resume(other)
    assert picked["status"] == "PASS" and picked["portable"] is True, picked
    assert picked["command"] == "STEP PLAN STEP-017"
    assert picked["sourceHandoff"] == "custom/handoffs/STEP-017.json"


def test_rewritten_git_history(root: Path, origin: Path) -> None:
    """Старый handoff не допускается после rebase/force-push style rewrite."""
    other = clone(root, origin, "rewritten-history")
    # Создаём новый root commit с тем же tree; никаких внешних Git push.
    new_root = git(other, "commit-tree", "HEAD^{tree}", "-m", "synthetic rewritten root")
    git(other, "update-ref", "refs/heads/main", new_root)
    outcome = check_handoff(other, STEP_ID)
    assert outcome["status"] == "BLOCKED", outcome
    assert outcome["reasonCode"] == "HANDOFF_SOURCE_UNREACHABLE", outcome
    assert harness_resume(other)["status"] == "BLOCKED"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="portable-matrix-") as temp:
        root = Path(temp)
        desktop, origin = setup(root)
        laptop = clone(root, origin, "laptop")
        assert desktop != laptop and desktop.resolve() != laptop.resolve()
        assert not (laptop / ".harness/local/execution/execution-status.json").exists()
        assert not (laptop / ".harness/local/verification-proofs/local-only.json").exists()
        assert check_handoff(laptop, STEP_ID)["status"] == "PASS"
        choice = harness_resume(laptop)
        assert choice["status"] == "PASS", choice
        assert choice["portable"] is True and choice["command"] == "STEP PLAN STEP-017"
        assert not (laptop / ".harness/local/execution/execution-status.json").exists()

        # Unpublished changes on the producer must be committed before writer.
        write(desktop / "uncommitted-code.ts", "// not transferred\n")
        writer = write_handoff(desktop, STEP_ID)
        assert writer["status"] == "BLOCKED", writer
        (desktop / "uncommitted-code.ts").unlink()

        test_semantic_changes(root, origin)
        test_schema_and_traversal(root, origin)
        test_custom_task_directory(root, origin)
        test_rewritten_git_history(root, origin)
        test_publication_races(root, origin)

    print("PORTABLE RESUME CROSS-WORKSPACE MATRIX: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
