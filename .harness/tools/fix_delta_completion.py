#!/usr/bin/env python3
"""Bounded reuse of previous full REVIEW facts in a FIX-delta completion (#331).

This is **not** a completion verdict generator. The lead reviewer still checks
all original findings and direct regressions, and the root agent supplies the
same full Completion Contract. Only two concrete evidence references are
validated, so unrelated Acceptance items need not be reviewed a second time.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from completion_gate import CompletionGateError
from document_contract import parse_document
from harness_config import review_directory
from planning_contract import planning_context_basis
from review_contract import validate_review_report
from verification import verification_freshness


_MAX_HISTORY_DEPTH = 8
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVIEW_NAME = re.compile(r"^REVIEW-\d{8}T\d{6}Z\.md$")
_PREFIXES = ("previous-review:", "verification:")


def _review_path(root: Path, step_id: str, relative: Any) -> tuple[Path, str]:
    """Only the canonical STEP review directory, never an arbitrary file.

    The lexical check comes before .resolve(), otherwise a symlink can hide a
    traversal to another STEP or a non-repository path.
    """
    root = root.resolve()
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise CompletionGateError("FIX delta previous report path is invalid")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or "." in rel.parts:
        raise CompletionGateError("FIX delta previous report path is not canonical")
    folder = review_directory(root) / step_id
    try:
        configured_rel = folder.relative_to(root)
    except ValueError as exc:
        raise CompletionGateError("FIX delta review directory escapes repository") from exc
    if rel.parent != configured_rel or not _REVIEW_NAME.fullmatch(rel.name):
        raise CompletionGateError("FIX delta previous report is outside the STEP review directory")
    path = root / rel
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CompletionGateError("FIX delta previous report has symlink components")
    if not path.is_file():
        raise CompletionGateError("FIX delta previous report is missing")
    return path, rel.as_posix()


def _full_review_source(
    root: Path, step_id: str, source: Any,
) -> tuple[Path, str, dict[str, Any]]:
    """Walk a bounded, schema-valid REVIEW provenance chain back to full scope."""
    seen: set[str] = set()
    for _ in range(_MAX_HISTORY_DEPTH):
        path, rel = _review_path(root, step_id, source)
        if rel in seen:
            raise CompletionGateError("FIX delta previous review chain contains a cycle")
        seen.add(rel)
        problems = validate_review_report(root, path, expected_step_id=step_id)
        if problems:
            raise CompletionGateError(
                "FIX delta previous review is invalid: " + "; ".join(problems[:3])
            )
        document = parse_document(path)
        provenance = document["sections"].get("FIX delta provenance")
        if provenance is None:
            # Historical initial/full_explicit REVIEW uses exactly this marker.
            # In particular, a FAIL initial report may have no completion data:
            # we reuse review SCOPE, not a fabricated historical PASS.
            checked = document["sections"].get("Scope checked", "")
            if "- Initial full implementation review" not in checked:
                raise CompletionGateError(
                    "FIX delta coverage reuse requires an initial/full_explicit REVIEW"
                )
            if document["frontmatter"].get("verdict") not in {"pass", "fail"}:
                raise CompletionGateError("FIX delta full baseline has no reviewable verdict")
            return path, rel, document

        match = re.fullmatch(r"\s*```json\s*(\{.*\})\s*```\s*", provenance, re.S)
        if match is None:
            raise CompletionGateError("FIX delta review chain has invalid provenance")
        try:
            details = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise CompletionGateError("FIX delta review chain JSON is invalid") from exc
        if not isinstance(details, dict) or details.get("mode") != "fix_delta":
            raise CompletionGateError("FIX delta review chain has unsupported mode")
        source = details.get("sourceReport")
    raise CompletionGateError("FIX delta review chain exceeds bounded history depth")


def _unchanged_pre_fix_full_report(
    root: Path, source: str, current: bytes, before_tree: Any,
) -> bool:
    """Проверить, что прошлый полный REVIEW существовал ДО FIX без мутаций.

    capture_fix() записывает real Git tree до первой правки, включая
    nonignored untracked reports. Поэтому проверка не зависит от Git HEAD,
    но препятствует тихой подмене baseline report после FIX.
    """
    if not isinstance(before_tree, str) or not re.fullmatch(
        r"[0-9a-f]{40}(?:[0-9a-f]{24})?", before_tree
    ):
        return False
    try:
        result = subprocess.run(
            ["git", "show", before_tree + ":" + source],
            cwd=root.resolve(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout == current


def validate_fix_delta_coverage_reuse(
    root: Path, step_id: str, completion: Any, scope: dict[str, Any],
) -> dict[str, str] | None:
    """Validate scoped references; return immutable provenance for REVIEW JSON.

    Normal completion.coverage is still checked by normalize_semantic_completion.
    We *never* mark an Acceptance criterion 'covered' automatically.
    """
    if not isinstance(completion, dict) or not isinstance(completion.get("coverage"), list):
        return None  # Ordinary Completion Gate will reject malformed coverage.

    reused: list[dict[str, Any]] = []
    for row in completion["coverage"]:
        if not isinstance(row, dict) or not isinstance(row.get("evidence"), list):
            continue  # Ordinary schema checks still apply.
        if any(
            isinstance(entry, str) and entry.startswith(_PREFIXES)
            for entry in row["evidence"]
        ):
            reused.append(row)
    if not reused:
        return None
    if scope.get("mode") != "fix_delta":
        raise CompletionGateError(
            "previous-review:/verification: evidence is allowed only for FIX delta"
        )

    full_path, full_rel, full = _full_review_source(
        root, step_id, scope.get("sourceReport"),
    )
    # Contract identity is semantic (REQ/ADR/STEP/plan); a different Git HEAD
    # after FIX does not invalidate the original inspected contract.
    if not _unchanged_pre_fix_full_report(
        root, full_rel, full_path.read_bytes(), scope.get("beforeTree"),
    ):
        raise CompletionGateError(
            "FIX delta full REVIEW differs from pre-FIX Git tree snapshot"
        )

    baseline_basis = full["frontmatter"].get("contract_basis")
    if not isinstance(baseline_basis, str) or not _SHA256.fullmatch(baseline_basis):
        raise CompletionGateError("previous full review has no trusted contract basis")
    if baseline_basis != planning_context_basis(root, step_id):
        raise CompletionGateError("previous full review contract is stale after FIX")

    fresh = verification_freshness(root, step_id)
    subject = fresh.get("subjectContentHash")
    if (
        fresh.get("status") != "PASS"
        or fresh.get("fresh") is not True
        or not isinstance(subject, str)
        or not _SHA256.fullmatch(subject)
    ):
        raise CompletionGateError("FIX delta coverage reuse requires fresh Verification PASS")

    full_reference = "previous-review:" + full_rel
    verification_reference = "verification:" + subject
    for row in reused:
        evidence = row["evidence"]
        previous = [e for e in evidence if isinstance(e, str) and e.startswith("previous-review:")]
        verified = [e for e in evidence if isinstance(e, str) and e.startswith("verification:")]
        if previous != [full_reference] or verified != [verification_reference]:
            raise CompletionGateError(
                "FIX delta coverage must reference the exact full REVIEW and current Verification"
            )
        if row.get("status") != "covered":
            raise CompletionGateError("FIX delta reused criterion must be covered")

    return {
        "fullReview": full_rel,
        "fullReviewSha256": "sha256:" + hashlib.sha256(full_path.read_bytes()).hexdigest(),
        "verificationSubjectContentHash": subject,
        "contractBasis": baseline_basis,
    }


__all__ = ["validate_fix_delta_coverage_reuse"]
