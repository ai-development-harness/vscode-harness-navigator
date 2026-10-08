#!/usr/bin/env python3
"""Regression tests for exact FIX delta with dirty index/worktree/new paths."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

import fix_delta


def git(root: Path, *args: str) -> None:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stderr)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-fix-delta-") as directory:
        root = Path(directory)
        git(root, "init", "-q")
        git(root, "config", "user.email", "test@example.invalid")
        git(root, "config", "user.name", "Harness Test")
        (root / ".gitignore").write_text(".harness/local/\n", encoding="utf-8")
        (root / "tracked.py").write_text("one\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-qm", "initial")

        (root / "tracked.py").write_text("already-dirty\n", encoding="utf-8")
        git(root, "add", "tracked.py")
        (root / "new-before.py").write_text("new before\n", encoding="utf-8")
        initial_index = (root / ".git/index").read_bytes()

        original = fix_delta.latest_structured_findings
        original_subject = fix_delta.verification_subject_revision
        fix_delta.latest_structured_findings = lambda *_: {
            "verdict": "fail",
            "report": "planning/reviews/STEP-001/REVIEW-before.md",
            "findings": [{"fingerprint": "sha256:old"}],
        }
        fix_delta.verification_subject_revision = lambda *_: {"subject": "postfix"}
        try:
            first = fix_delta.capture_fix(root, "STEP-001", "exec-1")
            assert first["complete"] is False
            assert (root / ".git/index").read_bytes() == initial_index
            assert fix_delta.capture_fix(root, "STEP-001", "exec-1") == first

            (root / "tracked.py").write_text("fixed\n", encoding="utf-8")
            (root / "new-before.py").write_text("modified new before\n", encoding="utf-8")
            (root / "new-after.py").write_text("added during fix\n", encoding="utf-8")
            fix_delta.complete_fix(root, "STEP-001", "exec-1")
            scope = fix_delta.review_scope(root, "STEP-001")
            assert scope["mode"] == "fix_delta", scope
            assert sorted(scope["changedPaths"]) == [
                "new-after.py", "new-before.py", "tracked.py",
            ], scope
            assert "already-dirty" in (root / scope["patchPath"]).read_text()
            assert "fixed" in (root / scope["patchPath"]).read_text()
            assert (root / ".git/index").read_bytes() == initial_index

            existing = {"id": "F-001", "fingerprint": "sha256:old",
                        "location": {"path": "elsewhere.py"}}
            fix_delta.enforce_findings(scope, [existing], None)
            new = {"id": "F-002", "fingerprint": "sha256:new",
                   "location": {"path": "tracked.py"}}
            try:
                fix_delta.enforce_findings(scope, [new], None)
                raise AssertionError("new finding without causal proof accepted")
            except fix_delta.FixDeltaError:
                pass
            fix_delta.enforce_findings(
                scope, [new], {"F-002": "FIX replaced the tracked return value, and the changed branch now fails."}
            )
            outside = {"id": "F-003", "fingerprint": "sha256:outside",
                       "location": {"path": "unchanged.py"}}
            try:
                fix_delta.enforce_findings(
                    scope, [outside], {"F-003": "A supposed causal explanation for an unchanged path."}
                )
                raise AssertionError("outside finding accepted")
            except fix_delta.FixDeltaError:
                pass

            fix_delta.verification_subject_revision = lambda *_: {"subject": "stale"}
            try:
                fix_delta.review_scope(root, "STEP-001")
                raise AssertionError("stale subject accepted")
            except fix_delta.FixDeltaError:
                pass
            fix_delta.clear_scope(root, "STEP-001")
            assert fix_delta.review_scope(root, "STEP-001")["mode"] == "initial"

            # CTS FIX has no contextPhase. The dispatcher must capture before
            # handing semantic work to the model (regression for issue #281).
            import command_dispatch
            skill = root / ".agents/skills/fix-step/SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text("fixture", encoding="utf-8")
            saved_route = command_dispatch.route_command
            saved_capture = command_dispatch.capture_fix
            seen = []
            command_dispatch.route_command = lambda *_: {
                "command": "STEP FIX STEP-001",
                "dispatch": {"kind": "semantic", "skill": "fix-step"},
                "domain": "STEP", "operation": "FIX",
                "target": "STEP-001", "input": None, "authority": {},
            }
            command_dispatch.capture_fix = lambda *_: seen.append("pre-FIX")
            try:
                response = command_dispatch._semantic_handoff(
                    root, {"rootCommand": "STEP FIX STEP-001", "executionId": "exec-42"},
                    "STEP FIX STEP-001",
                )
                assert response["status"] == "SEMANTIC", response
                assert seen == ["pre-FIX"], seen
            finally:
                command_dispatch.route_command = saved_route
                command_dispatch.capture_fix = saved_capture

            # Deliberate full audit persists across independent writer calls.
            fix_delta.verification_subject_revision = lambda *_: {"subject": "postfix"}
            fix_delta.capture_fix(root, "STEP-001", "exec-2")
            fix_delta.complete_fix(root, "STEP-001", "exec-2")
            fix_delta.request_full_review(root, "STEP-001")
            assert fix_delta.review_scope(root, "STEP-001")["mode"] == "full_explicit"
            fix_delta.clear_scope(root, "STEP-001")

            # A real FIX must not silently start delta review without a
            # confirmed immutable FAIL report. This is deliberately NOT
            # bypassed by the Verification-only synthetic test.
            fix_delta.latest_structured_findings = original
            try:
                fix_delta.capture_fix(root, "STEP-001", "exec-no-review")
                raise AssertionError("FIX accepted missing FAIL review")
            except ValueError:
                pass
        finally:
            fix_delta.latest_structured_findings = original
            fix_delta.verification_subject_revision = original_subject

    print("INCREMENTAL REVIEW SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
