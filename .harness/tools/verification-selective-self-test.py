#!/usr/bin/env python3
"""Selective feedback is bounded and never creates completion evidence."""
from __future__ import annotations
from pathlib import Path
import tempfile
import verification_selective as v


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-selective-") as tmp:
        root = Path(tmp)
        saved = (v.parse_verification, v.repository_revision, v._refs_snapshot,
                 v.verification_command_timeout_seconds, v._run_command)
        revision = {"revision": "A"}
        v.parse_verification = lambda *_: [
            {"kind": "command", "value": "pytest one"},
            {"kind": "command", "value": "pytest two"},
        ]
        v.repository_revision = lambda *_: revision["revision"]
        v._refs_snapshot = lambda *_: "unchanged"
        v.verification_command_timeout_seconds = lambda *_: 60
        calls = []
        def perform(_root, command, **_kwargs):
            calls.append(command)
            return {"status": "PASS", "exitCode": 0, "command": command}
        v._run_command = perform
        try:
            one = v.run_selected(root, "STEP-001", ["pytest one"])
            assert one["status"] == "PASS" and not one["completionProof"]
            assert one["fullVerificationRequired"], one
            assert calls == ["pytest one"], calls
            assert v.run_selected(root, "STEP-001", ["unknown"])["status"] == "BLOCKED"
            assert v.run_selected(root, "STEP-001", ["pytest one"] * 2)["status"] == "BLOCKED"
            def mutating(_root, command, **_kwargs):
                revision["revision"] = "B"
                return {"status": "PASS", "command": command}
            v._run_command = mutating
            assert v.run_selected(root, "STEP-001", ["pytest two"])["reasonCode"] == "SELECTED_COMMAND_MUTATED_REPOSITORY"
        finally:
            (v.parse_verification, v.repository_revision, v._refs_snapshot,
             v.verification_command_timeout_seconds, v._run_command) = saved
    print("SELECTIVE VERIFICATION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
