#!/usr/bin/env python3
"""Deterministic boundary for read-only Decision Archaeology.

Semantic rationale reconstruction belongs to the model. This module owns only
facts that can be recomputed locally: repository revision, bounded target Git
history, allowed context/expansions, evidence provenance and structural rules
that keep documented decisions separate from inference/conflict/gaps.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from context_contracts import ContextContractError, validate_expansion
from document_contract import parse_utc_timestamp
from harness_config import resolve_repo_path
from review_contract import repository_revision


SCHEMA_VERSION = 1
STATUSES = {"PASS", "INCONCLUSIVE", "BLOCKED"}
SCOPES: dict[str, dict[str, int]] = {
    "simple": {
        "maxExpansionFiles": 6,
        "maxExpansionChars": 60_000,
        "maxHistoryCommits": 12,
        "maxClaims": 8,
        "maxSuppliedEvidence": 8,
    },
    "complex": {
        "maxExpansionFiles": 12,
        "maxExpansionChars": 120_000,
        "maxHistoryCommits": 24,
        "maxClaims": 16,
        "maxSuppliedEvidence": 16,
    },
}
CLAIM_BASIS = {"documented", "inference"}
CONFIDENCE = {"high", "medium", "low"}
EVIDENCE_KINDS = {"artifact", "commit", "supplied"}
STALE_ASSESSMENTS = {"current", "possibly-stale", "unknown"}
SUPPLIED_SOURCE_KINDS = {
    "pull_request",
    "issue",
    "project_doc",
    "chat",
    "observability",
    "error_tracking",
    "analytics",
    "external_engineering",
}


class DecisionArchaeologyError(ValueError):
    """Decision archaeology payload cannot be trusted downstream."""


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionArchaeologyError(f"{label} must be a non-empty string")
    return value.strip()


def _list(value: object, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DecisionArchaeologyError(f"{label} must be a list")
    return value


def _revision(value: object, *, label: str) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise DecisionArchaeologyError(f"{label} must be an object")
    unexpected = sorted(set(value) - {"git_head", "worktree_hash"})
    if unexpected:
        raise DecisionArchaeologyError(
            f"{label} has unsupported keys: " + ", ".join(unexpected)
        )
    result: dict[str, str | None] = {}
    for key in ("git_head", "worktree_hash"):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise DecisionArchaeologyError(
                f"{label}.{key} must be null or a non-empty string"
            )
        result[key] = item.strip() if isinstance(item, str) else None
    return result


def _repo_file(root: Path, target: str) -> tuple[Path, str]:
    try:
        path = resolve_repo_path(root, target, label="decision archaeology target")
    except ValueError as exc:
        raise DecisionArchaeologyError(str(exc)) from exc
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DecisionArchaeologyError("target escapes repository") from exc
    if not path.is_file():
        raise DecisionArchaeologyError(f"target file not found: {rel}")
    if rel == ".harness/tools" or rel.startswith(".harness/tools/"):
        raise DecisionArchaeologyError(
            "Harness tool source is forbidden as archaeology product context"
        )
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DecisionArchaeologyError(
            f"target must be readable UTF-8 text: {rel}: {exc}"
        ) from exc
    return path, rel


def _git(root: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ("git", "-c", "core.quotepath=false", *args),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DecisionArchaeologyError(
            f"git {args[0] if args else '?'} failed: {exc}"
        ) from exc
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        raise DecisionArchaeologyError(
            f"git {' '.join(args[:2])} failed: {message}"
        )
    return proc.stdout


def _commit_metadata(root: Path, sha: str) -> dict[str, str]:
    raw = _git(root, "show", "-s", "--format=%H%n%aI%n%s", sha)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DecisionArchaeologyError(
            f"commit {sha} contains non-UTF-8 metadata"
        ) from exc
    if len(lines) < 3:
        raise DecisionArchaeologyError(f"malformed metadata for commit {sha}")
    resolved, authored_at = lines[0], lines[1]
    subject = "\n".join(lines[2:]).strip()
    if resolved != sha or not authored_at or not subject:
        raise DecisionArchaeologyError(f"incomplete metadata for commit {sha}")
    return {
        "sha": resolved,
        "authoredAt": authored_at,
        "subject": subject,
    }


def _target_history(root: Path, target: str, limit: int) -> list[dict[str, str]]:
    raw = _git(
        root,
        "log",
        "--follow",
        f"--max-count={limit}",
        "--format=%H",
        "--",
        target,
    )
    try:
        shas = [
            line.strip()
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
    except UnicodeDecodeError as exc:
        raise DecisionArchaeologyError(
            "git history contains non-UTF-8 metadata"
        ) from exc
    for sha in shas:
        if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
            raise DecisionArchaeologyError(
                f"malformed commit id in target history: {sha!r}"
            )
    return [_commit_metadata(root, sha) for sha in shas]

def _artifact_timestamp(root: Path, path: str) -> str | None:
    raw = _git(root, "log", "-1", "--format=%aI", "--", path)
    value = raw.decode("utf-8", errors="strict").strip()
    return value or None


def _context_paths(context_contract: dict[str, Any] | None) -> set[str]:
    if context_contract is None:
        return set()
    if context_contract.get("status") != "PASS":
        raise DecisionArchaeologyError("context contract status must be PASS")
    required = _list(context_contract.get("required"), label="context.required")
    result: set[str] = set()
    for index, item in enumerate(required):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(
                f"context.required[{index}] must be an object"
            )
        result.add(
            _text(item.get("path"), label=f"context.required[{index}].path")
        )
    return result


def _artifact_kind(path: str) -> str:
    name = Path(path).name
    if re.match(r"ADR-\d{3,}", name):
        return "adr"
    if re.match(r"REQ-\d{3,}", name):
        return "requirement"
    if re.match(r"PRN-\d{3,}", name):
        return "principle"
    if re.match(r"OQ-\d{3,}", name):
        return "open_question"
    if re.match(r"STEP-\d{3,}", name):
        return "step"
    if "architecture" in path.lower():
        return "architecture"
    return "project_file"


def decision_archaeology_preflight(
    root: Path,
    target: str,
    scope: str,
    context_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scope not in SCOPES:
        raise DecisionArchaeologyError(f"scope must be one of {sorted(SCOPES)}")
    path, rel = _repo_file(root, target)
    revision = repository_revision(root)
    if context_contract is not None:
        expected = _revision(
            context_contract.get("repositoryRevision"),
            label="context.repositoryRevision",
        )
        if revision != expected:
            raise DecisionArchaeologyError(
                "Context Contract repositoryRevision does not match current repository"
            )
    context_paths = sorted(_context_paths(context_contract))
    limits = SCOPES[scope]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "scope": scope,
        "target": rel,
        "repositoryRevision": revision,
        "contextPaths": context_paths,
        "targetChars": len(path.read_text(encoding="utf-8")),
        "history": _target_history(
            root,
            rel,
            limits["maxHistoryCommits"],
        ),
        "limits": limits,
    }


def _normalize_supplied_evidence(
    value: object,
    *,
    limit: int,
) -> dict[str, dict[str, Any]]:
    items = _list(value, label="suppliedEvidence")
    if len(items) > limit:
        raise DecisionArchaeologyError(
            f"suppliedEvidence allows at most {limit} entries"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(
                f"suppliedEvidence[{index}] must be an object"
            )
        evidence_id = item.get("id")
        expected = f"E-{index:03d}"
        if evidence_id != expected or evidence_id in result:
            raise DecisionArchaeologyError(
                f"suppliedEvidence[{index}].id must be {expected}"
            )
        source_kind = item.get("sourceKind")
        if source_kind not in SUPPLIED_SOURCE_KINDS:
            raise DecisionArchaeologyError(
                f"suppliedEvidence[{index}].sourceKind must be one of "
                f"{sorted(SUPPLIED_SOURCE_KINDS)}"
            )
        ref = _text(item.get("ref"), label=f"suppliedEvidence[{index}].ref")
        observed_at = _text(
            item.get("observedAt"),
            label=f"suppliedEvidence[{index}].observedAt",
        )
        if parse_utc_timestamp(observed_at) is None:
            raise DecisionArchaeologyError(
                f"suppliedEvidence[{index}].observedAt must be timezone-aware ISO-8601"
            )
        title = _text(
            item.get("title"),
            label=f"suppliedEvidence[{index}].title",
        )
        result[evidence_id] = {
            "id": evidence_id,
            "kind": "supplied",
            "sourceKind": source_kind,
            "ref": ref,
            "title": title,
            "observedAt": observed_at,
            "verification": "supplied-not-locally-verifiable",
        }
    return result


def _normalize_evidence_refs(
    root: Path,
    refs: object,
    *,
    label: str,
    allowed_paths: set[str],
    history: dict[str, dict[str, str]],
    supplied: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items = _list(refs, label=label)
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(f"{label}[{index}] must be an object")
        kind = item.get("kind")
        if kind not in EVIDENCE_KINDS:
            raise DecisionArchaeologyError(
                f"{label}[{index}].kind must be one of {sorted(EVIDENCE_KINDS)}"
            )
        ref = _text(item.get("ref"), label=f"{label}[{index}].ref")
        identity = (str(kind), ref)
        if identity in seen:
            continue
        seen.add(identity)
        if kind == "artifact":
            if ref not in allowed_paths:
                raise DecisionArchaeologyError(
                    f"{label}[{index}] artifact was not available to archaeology: {ref}"
                )
            result.append(
                {
                    "kind": "artifact",
                    "ref": ref,
                    "artifactKind": _artifact_kind(ref),
                    "observedAt": _artifact_timestamp(root, ref),
                    "verification": "repository-local",
                }
            )
        elif kind == "commit":
            commit = history.get(ref)
            if commit is None:
                raise DecisionArchaeologyError(
                    f"{label}[{index}] commit is outside bounded target history: {ref}"
                )
            result.append(
                {
                    "kind": "commit",
                    "ref": ref,
                    "observedAt": commit["authoredAt"],
                    "subject": commit["subject"],
                    "verification": "repository-local",
                }
            )
        else:
            evidence = supplied.get(ref)
            if evidence is None:
                raise DecisionArchaeologyError(
                    f"{label}[{index}] supplied evidence id not found: {ref}"
                )
            result.append(evidence)
    return result


def validate_decision_archaeology_payload(
    root: Path,
    target: str,
    scope: str,
    payload: dict[str, Any],
    context_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight = decision_archaeology_preflight(
        root,
        target,
        scope,
        context_contract,
    )
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise DecisionArchaeologyError(
            f"schemaVersion must be {SCHEMA_VERSION}"
        )
    status = payload.get("status")
    if status not in STATUSES:
        raise DecisionArchaeologyError(
            f"status must be one of {sorted(STATUSES)}"
        )
    if payload.get("scope") != scope:
        raise DecisionArchaeologyError("payload scope does not match requested scope")
    if payload.get("target") != preflight["target"]:
        raise DecisionArchaeologyError("payload target does not match requested target")
    revision = _revision(
        payload.get("repositoryRevision"),
        label="repositoryRevision",
    )
    if revision != preflight["repositoryRevision"]:
        raise DecisionArchaeologyError(
            "repositoryRevision does not match current repository"
        )

    limits = SCOPES[scope]
    context_paths = set(preflight["contextPaths"])
    allowed_paths = set(context_paths)
    target_rel = preflight["target"]
    allowed_paths.add(target_rel)

    expansions = _list(payload.get("expansions"), label="expansions")
    max_files = limits["maxExpansionFiles"]
    normalized_expansions: list[dict[str, Any]] = []
    expansion_chars = 0
    counted_paths: set[str] = set()

    # A target outside the Context Contract consumes the same budget as an
    # explicit expansion. Without a Context Contract, the target is the first
    # bounded archaeology input rather than a free full-repository read.
    if target_rel not in context_paths:
        target_path = (root / target_rel).resolve()
        target_chars = len(target_path.read_text(encoding="utf-8"))
        counted_paths.add(target_rel)
        expansion_chars += target_chars
        normalized_expansions.append(
            {
                "path": target_rel,
                "reason": "decision archaeology target",
                "chars": target_chars,
                "implicitTarget": True,
            }
        )

    for index, item in enumerate(expansions):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(f"expansions[{index}] must be an object")
        path = _text(item.get("path"), label=f"expansions[{index}].path")
        reason = _text(item.get("reason"), label=f"expansions[{index}].reason")
        if path in context_paths or path in counted_paths:
            raise DecisionArchaeologyError(
                f"duplicate/redundant expansion path: {path}"
            )
        try:
            validated = validate_expansion(root, path, reason)
        except ContextContractError as exc:
            raise DecisionArchaeologyError(str(exc)) from exc
        candidate = (root / validated["path"]).resolve()
        try:
            chars = len(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise DecisionArchaeologyError(
                f"cannot measure expansion {validated['path']}: {exc}"
            ) from exc
        counted_paths.add(validated["path"])
        allowed_paths.add(validated["path"])
        expansion_chars += chars
        normalized_expansions.append(
            {
                "path": validated["path"],
                "reason": validated["reason"],
                "chars": chars,
                "implicitTarget": False,
            }
        )

    if len(normalized_expansions) > max_files:
        raise DecisionArchaeologyError(
            f"{scope} archaeology expansion file budget exceeded: "
            f"{len(normalized_expansions)}>{max_files}"
        )
    if expansion_chars > limits["maxExpansionChars"]:
        raise DecisionArchaeologyError(
            f"{scope} archaeology expansion char budget exceeded: "
            f"{expansion_chars}>{limits['maxExpansionChars']}"
        )

    supplied = _normalize_supplied_evidence(
        payload.get("suppliedEvidence"),
        limit=limits["maxSuppliedEvidence"],
    )
    history = {item["sha"]: item for item in preflight["history"]}

    claims_raw = _list(payload.get("claims"), label="claims")
    if len(claims_raw) > limits["maxClaims"]:
        raise DecisionArchaeologyError(
            f"{scope} archaeology allows at most {limits['maxClaims']} claims"
        )
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    ungrounded_inference = False
    evidence_map: dict[str, list[dict[str, Any]]] = {}

    for index, item in enumerate(claims_raw, start=1):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(f"claims[{index}] must be an object")
        claim_id = item.get("id")
        expected = f"R-{index:03d}"
        if claim_id != expected or claim_id in claim_ids:
            raise DecisionArchaeologyError(f"claims[{index}].id must be {expected}")
        claim_ids.add(claim_id)
        statement = _text(
            item.get("statement"),
            label=f"claims[{index}].statement",
        )
        basis = item.get("basis")
        if basis not in CLAIM_BASIS:
            raise DecisionArchaeologyError(
                f"claims[{index}].basis must be one of {sorted(CLAIM_BASIS)}"
            )
        confidence = item.get("confidence")
        if confidence not in CONFIDENCE:
            raise DecisionArchaeologyError(
                f"claims[{index}].confidence must be one of {sorted(CONFIDENCE)}"
            )
        evidence = _normalize_evidence_refs(
            root,
            item.get("evidence"),
            label=f"claims[{index}].evidence",
            allowed_paths=allowed_paths,
            history=history,
            supplied=supplied,
        )
        uncertainty = item.get("uncertainty")
        if basis == "documented":
            if not evidence:
                raise DecisionArchaeologyError(
                    f"claims[{index}] documented claim requires evidence"
                )
        elif not evidence:
            ungrounded_inference = True
            if confidence != "low":
                raise DecisionArchaeologyError(
                    f"claims[{index}] inference without evidence must have low confidence"
                )
            uncertainty = _text(
                uncertainty,
                label=f"claims[{index}].uncertainty",
            )
        elif uncertainty is not None:
            uncertainty = _text(
                uncertainty,
                label=f"claims[{index}].uncertainty",
            )
        claims.append(
            {
                "id": claim_id,
                "statement": statement,
                "basis": basis,
                "confidence": confidence,
                "evidence": evidence,
                **({"uncertainty": uncertainty} if uncertainty is not None else {}),
            }
        )
        evidence_map[claim_id] = evidence

    conflicts: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(payload.get("conflicts"), label="conflicts"),
        start=1,
    ):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(f"conflicts[{index}] must be an object")
        ids = _list(item.get("claimIds"), label=f"conflicts[{index}].claimIds")
        if (
            len(ids) < 2
            or any(not isinstance(value, str) for value in ids)
            or len(set(ids)) != len(ids)
        ):
            raise DecisionArchaeologyError(
                f"conflicts[{index}].claimIds must contain 2+ unique claim ids"
            )
        unknown = sorted(set(ids) - claim_ids)
        if unknown:
            raise DecisionArchaeologyError(
                f"conflicts[{index}] references unknown claims: "
                + ", ".join(unknown)
            )
        conflicts.append(
            {
                "claimIds": ids,
                "summary": _text(
                    item.get("summary"),
                    label=f"conflicts[{index}].summary",
                ),
            }
        )

    gaps: list[str] = []
    for index, value in enumerate(_list(payload.get("gaps"), label="gaps")):
        text = _text(value, label=f"gaps[{index}]")
        if text not in gaps:
            gaps.append(text)

    stale_decisions: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(payload.get("staleDecisions"), label="staleDecisions"),
        start=1,
    ):
        if not isinstance(item, dict):
            raise DecisionArchaeologyError(
                f"staleDecisions[{index}] must be an object"
            )
        artifact = _text(
            item.get("artifact"),
            label=f"staleDecisions[{index}].artifact",
        )
        if artifact not in allowed_paths or _artifact_kind(artifact) != "adr":
            raise DecisionArchaeologyError(
                f"staleDecisions[{index}].artifact must be an available ADR"
            )
        assessment = item.get("assessment")
        if assessment not in STALE_ASSESSMENTS:
            raise DecisionArchaeologyError(
                f"staleDecisions[{index}].assessment must be one of "
                f"{sorted(STALE_ASSESSMENTS)}"
            )
        evidence = _normalize_evidence_refs(
            root,
            item.get("evidence"),
            label=f"staleDecisions[{index}].evidence",
            allowed_paths=allowed_paths,
            history=history,
            supplied=supplied,
        )
        if assessment != "unknown" and not evidence:
            raise DecisionArchaeologyError(
                f"staleDecisions[{index}] {assessment} assessment requires evidence"
            )
        stale_decisions.append(
            {
                "artifact": artifact,
                "assessment": assessment,
                "reason": _text(
                    item.get("reason"),
                    label=f"staleDecisions[{index}].reason",
                ),
                "evidence": evidence,
            }
        )

    if status == "PASS":
        if not claims:
            raise DecisionArchaeologyError("PASS requires at least one rationale claim")
        if ungrounded_inference:
            raise DecisionArchaeologyError(
                "PASS cannot contain inference with no historical evidence"
            )
    if status == "INCONCLUSIVE" and not (gaps or ungrounded_inference):
        raise DecisionArchaeologyError(
            "INCONCLUSIVE requires an explicit gap or ungrounded inference"
        )
    if ungrounded_inference and not gaps:
        raise DecisionArchaeologyError(
            "inference without historical evidence requires a gap entry"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "scope": scope,
        "target": preflight["target"],
        "repositoryRevision": revision,
        "claims": claims,
        "conflicts": conflicts,
        "gaps": gaps,
        "staleDecisions": stale_decisions,
        "evidenceMap": evidence_map,
        "suppliedEvidence": list(supplied.values()),
        "history": preflight["history"],
        "expansions": normalized_expansions,
        "contextBudget": {
            "expansionFiles": len(normalized_expansions),
            "expansionChars": expansion_chars,
            "maxExpansionFiles": limits["maxExpansionFiles"],
            "maxExpansionChars": limits["maxExpansionChars"],
            "historyCommits": len(preflight["history"]),
            "maxHistoryCommits": limits["maxHistoryCommits"],
        },
    }


__all__ = [
    "DecisionArchaeologyError",
    "decision_archaeology_preflight",
    "validate_decision_archaeology_payload",
]
