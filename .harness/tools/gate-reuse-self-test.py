#!/usr/bin/env python3
"""Cached integrity gate never reuses across changed revision/tool/failure."""
from __future__ import annotations
from pathlib import Path
import tempfile
from types import SimpleNamespace
import gate_reuse


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-gate-reuse-") as tmp:
        root = Path(tmp)
        script = root / ".harness/tools/validate.py"
        script.parent.mkdir(parents=True)
        script.write_text("# test\n", encoding="utf-8")
        original_revision = gate_reuse.repository_revision
        original_run = gate_reuse.subprocess.run
        calls = []
        state = {"revision": "A", "exit": 0}
        gate_reuse.repository_revision = lambda _root: {"git_head": state["revision"], "worktree_hash": None}

        def fake_run(*_args, **_kwargs):
            calls.append(1)
            return SimpleNamespace(returncode=state["exit"], stdout=b"PASS", stderr=b"")
        gate_reuse.subprocess.run = fake_run
        try:
            one = gate_reuse.validate_once(root)
            assert one["status"] == "PASS" and not one["reused"], one
            two = gate_reuse.validate_once(root)
            assert two["reused"] is True and len(calls) == 1, (two, calls)
            state["revision"] = "B"
            assert not gate_reuse.validate_once(root)["reused"]
            script.write_text("# changed test\n", encoding="utf-8")
            assert not gate_reuse.validate_once(root)["reused"]
            state["revision"] = "C"
            state["exit"] = 1
            assert gate_reuse.validate_once(root)["status"] == "BLOCKED"
            assert gate_reuse.validate_once(root)["status"] == "BLOCKED"
            assert len(calls) == 5, calls
        finally:
            gate_reuse.repository_revision = original_revision
            gate_reuse.subprocess.run = original_run
    print("GATE REUSE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
