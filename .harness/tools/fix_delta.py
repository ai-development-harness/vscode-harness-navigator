#!/usr/bin/env python3
"""Durable, narrowly scoped FIX -> REVIEW handoff (issue #281).

A temporary Git index snapshots tracked and non-ignored untracked content before
FIX, without modifying the user's index or working tree. A *tree* rather than
HEAD is required for pre-existing staged/unstaged changes and new files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from document_contract import atomic_write_text
from review_findings import latest_structured_findings
from verification import verification_subject_revision

MAX_PATCH_BYTES = 1_000_000
OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


class FixDeltaError(ValueError):
    pass


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise FixDeltaError(
            f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace')[:400]}"
        )
    return result.stdout


def _snapshot_tree(root: Path) -> str:
    """Snapshot exact checkout via alternate index; ordinary index is untouched."""
    with tempfile.TemporaryDirectory(prefix="harness-fix-index-") as temp:
        index = Path(temp) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        _run(root, "read-tree", "HEAD", env=env)
        # Only tracked + non-ignored paths. Gitignored secrets are never added.
        _run(root, "add", "--all", "--", ".", env=env)
        oid = _run(root, "write-tree", env=env).decode("ascii").strip()
        if not OID_RE.fullmatch(oid):
            raise FixDeltaError("snapshot did not produce a valid Git tree")
        return oid


def _path(root: Path, step_id: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        raise FixDeltaError("invalid STEP identifier")
    return root / ".harness/local/execution/fix-delta" / (step_id + ".json")


def _load(root: Path, step_id: str) -> dict[str, Any] | None:
    path = _path(root, step_id)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FixDeltaError("unreadable FIX baseline") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 1 or data.get("stepId") != step_id:
        raise FixDeltaError("malformed FIX baseline")
    return data


def _save(root: Path, step_id: str, data: dict[str, Any]) -> None:
    path = _path(root, step_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise FixDeltaError("FIX baseline path must not be a symlink")
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def capture_fix(root: Path, step_id: str, execution_id: str) -> dict[str, Any]:
    existing = _load(root, step_id)
    if existing and existing.get("executionId") == execution_id:
        return existing  # resume must not overwrite the original pre-FIX snapshot
    review = latest_structured_findings(root, step_id)
    if review.get("verdict") != "fail" or not review.get("findings"):
        raise FixDeltaError("FIX requires a current FAIL review with findings")
    data = {
        "schemaVersion": 1, "stepId": step_id, "executionId": execution_id,
        "sourceReport": review["report"],
        "findings": [item["fingerprint"] for item in review["findings"]],
        "beforeTree": _snapshot_tree(root), "complete": False,
    }
    _save(root, step_id, data)
    return data


def complete_fix(root: Path, step_id: str, execution_id: str) -> None:
    data = _load(root, step_id)
    # Legacy/diagnostic low-level completions may predate this protocol.
    # They cannot claim a delta review, but must not lose FIX completion.
    # The subsequent reviewer falls back to full initial scope.
    if data is None:
        return
    if data.get("executionId") != execution_id:
        raise FixDeltaError("FIX completion baseline belongs to another execution")
    data["afterSubject"] = verification_subject_revision(root, step_id)
    data["complete"] = True
    _save(root, step_id, data)


def request_full_review(root: Path, step_id: str) -> None:
    """Persist an explicitly requested full audit across dispatcher/writer processes."""
    data = _load(root, step_id)
    if data is not None:
        data["fullExplicit"] = True
        _save(root, step_id, data)


def review_scope(root: Path, step_id: str) -> dict[str, Any]:
    data = _load(root, step_id)
    if not data or not data.get("complete"):
        return {"mode": "initial"}
    if data.get("fullExplicit"):
        return {"mode": "full_explicit", "sourceReport": data["sourceReport"]}
    if data.get("afterSubject") != verification_subject_revision(root, step_id):
        raise FixDeltaError("FIX subject changed after completion; stale delta baseline")
    before = data.get("beforeTree")
    if not isinstance(before, str) or not OID_RE.fullmatch(before):
        raise FixDeltaError("FIX baseline tree is missing or invalid")
    after = _snapshot_tree(root)
    if before == after:
        paths: list[str] = []
        patch = b""
    else:
        paths_raw = _run(root, "diff", "--no-renames", "--name-only", "-z", before, after)
        try:
            paths = sorted({item.decode("utf-8") for item in paths_raw.split(b"\0") if item})
        except UnicodeDecodeError as exc:
            raise FixDeltaError("FIX paths are not UTF-8") from exc
        patch = _run(root, "diff", "--binary", "--no-ext-diff", "--no-renames", before, after)
    if len(patch) > MAX_PATCH_BYTES:
        raise FixDeltaError("FIX patch exceeds bounded review handoff budget")
    patch_path = _path(root, step_id).with_suffix(".patch")
    if patch_path.is_symlink():
        raise FixDeltaError("FIX patch path must not be a symlink")
    # Write only local transport; patch may contain sensitive product code.
    atomic_write_text(patch_path, patch.decode("utf-8", "replace"))
    return {
        "mode": "fix_delta",
        "sourceReport": data["sourceReport"],
        "previousFingerprints": data["findings"],
        "beforeTree": before,
        "afterTree": after,
        "changedPaths": paths,
        "patchPath": patch_path.relative_to(root).as_posix(),
    }


def enforce_findings(scope: dict[str, Any], findings: list[dict[str, Any]],
                     causality: dict[str, str] | None) -> None:
    """Reject out-of-delta new findings. A matching file alone never proves causality."""
    if scope.get("mode") != "fix_delta":
        return
    old = set(scope["previousFingerprints"])
    changed = set(scope["changedPaths"])
    supplied = causality or {}
    for finding in findings:
        fingerprint = finding["fingerprint"]
        if fingerprint in old:
            continue  # persisted original finding
        path = finding["location"]["path"]
        justification = supplied.get(finding["id"])
        if path not in changed:
            raise FixDeltaError(
                f"new finding {fingerprint} outside FIX delta: {path}"
            )
        if not isinstance(justification, str) or len(justification.strip()) < 30:
            raise FixDeltaError(
                f"new finding {finding['id']} requires concrete FIX causal evidence"
            )


def clear_scope(root: Path, step_id: str) -> None:
    path = _path(root, step_id)
    if path.is_file() and not path.is_symlink():
        path.unlink()
    patch = path.with_suffix(".patch")
    if patch.is_file() and not patch.is_symlink():
        patch.unlink()
