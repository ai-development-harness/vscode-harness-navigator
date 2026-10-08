#!/usr/bin/env python3
"""Conservative automated Verification continuation for pending manual evidence.

Not a global test-result cache: only a bounded, unchanged manual stage can
reuse the exact preceding automated PASS. Unknown state always re-executes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any

from document_contract import atomic_write_text
from planning_contract import read_task

RESUME_TTL_SECONDS = 1800
NON_REUSABLE_FLAGS = {
    "external-integration", "security-sensitive", "data-migration",
    "destructive", "release-critical",
}


def _path(root: Path, step_id: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        raise ValueError("invalid verification STEP identifier")
    return root / ".harness/local/verification-resume" / (step_id + ".json")


def _environment_basis(commands: list[str]) -> str:
    executables = []
    for command in commands:
        # Parse the same command contract as the actual runner.
        from verification import _argv
        argv = _argv(command)
        resolved = shutil.which(argv[0])
        if resolved is None:
            return ""  # no proof about executable identity
        try:
            stat = Path(resolved).stat()
        except OSError:
            return ""
        executables.append((resolved, stat.st_size, stat.st_mtime_ns))
    environment = {
        "path": os.environ.get("PATH"),
        "virtualEnv": os.environ.get("VIRTUAL_ENV"),
        "pythonPath": os.environ.get("PYTHONPATH"),
        "nodeOptions": os.environ.get("NODE_OPTIONS"),
        "python": sys.version,
        "executables": executables,
    }
    return hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()


def _eligible(root: Path, step_id: str) -> bool:
    flags = read_task(root, step_id)["frontmatter"].get("risk_flags", [])
    return isinstance(flags, list) and not NON_REUSABLE_FLAGS.intersection(flags)


def remember_pending(
    root: Path, step_id: str, *,
    contract: str, subject: dict[str, Any], commands: list[dict[str, Any]],
    timeout: int,
) -> None:
    """Record successful automated stage only; no stdout or manual observations."""
    if not commands or not _eligible(root, step_id):
        return
    if any(item.get("status") != "PASS" for item in commands):
        return
    names = [str(item["command"]) for item in commands]
    environment = _environment_basis(names)
    if not environment:
        return
    stored_commands = [
        {key: item.get(key) for key in (
            "kind", "command", "argv", "status", "exitCode", "durationMs",
            "stdoutSha256", "stderrSha256", "stdoutBytes", "stderrBytes",
        )}
        for item in commands
    ]
    path = _path(root, step_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        return
    payload = {
        "schemaVersion": 1, "stepId": step_id,
        "recordedAt": time.time(), "contractBasis": contract,
        "subjectRevision": subject, "timeoutSeconds": timeout,
        "environmentBasis": environment, "commands": stored_commands,
    }
    atomic_write_text(path, json.dumps(payload, sort_keys=True) + "\n")


def reuse_pending(
    root: Path, step_id: str, *, contract: str,
    subject: dict[str, Any], names: list[str], timeout: int,
) -> list[dict[str, Any]] | None:
    if not _eligible(root, step_id):
        return None
    path = _path(root, step_id)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("schemaVersion") != 1:
        return None
    recorded_at = cached.get("recordedAt")
    if not isinstance(recorded_at, (int, float)) or isinstance(recorded_at, bool):
        return None
    age = time.time() - recorded_at
    if not (0 <= age <= RESUME_TTL_SECONDS):
        return None
    if (cached.get("stepId") != step_id
            or cached.get("contractBasis") != contract
            or cached.get("subjectRevision") != subject
            or cached.get("timeoutSeconds") != timeout):
        return None
    if cached.get("environmentBasis") != _environment_basis(names):
        return None
    commands = cached.get("commands")
    if not isinstance(commands, list) or [c.get("command") for c in commands if isinstance(c, dict)] != names:
        return None
    if len(commands) != len(names) or any(
        not isinstance(item, dict)
        or item.get("status") != "PASS"
        or item.get("exitCode") != 0
        for item in commands
    ):
        return None
    return commands


def forget_pending(root: Path, step_id: str) -> None:
    path = _path(root, step_id)
    if path.is_file() and not path.is_symlink():
        path.unlink()
