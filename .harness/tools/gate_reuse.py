#!/usr/bin/env python3
"""Bounded content-addressed memoization of the existing read-only integrity gate.

Only PASS is reusable. The gate's expected subject includes HEAD/index/worktree
and tool bytes; a short TTL guards environment-derived unknowns. A cache miss
executes the real validator; it never bypasses writer-side exact revision checks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from document_contract import atomic_write_text
from review_contract import repository_revision

TTL_SECONDS = 120


def validate_once(root: Path) -> dict[str, Any]:
    validator = root / ".harness/tools/validate.py"
    tool_hash = hashlib.sha256(validator.read_bytes()).hexdigest()
    before = repository_revision(root)
    environment = {
        "python": sys.version,
        "PATH": os.environ.get("PATH"),
        "HARNESS_PROJECT_ROOT": os.environ.get("HARNESS_PROJECT_ROOT"),
    }
    basis = hashlib.sha256(json.dumps({
        "revision": before, "validator": tool_hash, "environment": environment,
        "mode": "manual",
    }, sort_keys=True).encode()).hexdigest()
    path = root / ".harness/local/gate-cache/validate-manual.json"
    if path.is_file() and not path.is_symlink():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            age = time.time() - cached.get("recordedAt", 0)
            if cached.get("schemaVersion") == 1 and cached.get("basis") == basis and isinstance(age, (int, float)) and 0 <= age <= TTL_SECONDS:
                return {"status": "PASS", "reused": True, "basis": basis}
        except (OSError, ValueError, TypeError):
            pass

    run = subprocess.run(
        [sys.executable, str(validator), "--mode", "manual"], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=300,
    )
    if run.returncode != 0:
        return {
            "status": "BLOCKED", "reasonCode": "INTEGRITY_VALIDATION_FAILED",
            "diagnostic": (run.stdout + run.stderr).decode("utf-8", "replace")[-4000:],
        }
    if repository_revision(root) != before:
        return {"status": "BLOCKED", "reasonCode": "VALIDATION_MUTATED_REPOSITORY"}
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_symlink():
        atomic_write_text(path, json.dumps({
            "schemaVersion": 1, "basis": basis, "recordedAt": time.time()
        }, sort_keys=True) + "\n")
    return {"status": "PASS", "reused": False, "basis": basis}
