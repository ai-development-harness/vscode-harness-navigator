#!/usr/bin/env python3
"""Read-only PR maintenance facts + semantic transport validation.

Existing Git/PR tools remain the only mutation authority. This module:
- reads provider facts through configured GitHub/Gitea adapters;
- preserves external check/comment/review IDs;
- fingerprints one exact provider snapshot;
- validates semantic CI/feedback/reviewability/babysit output against that snapshot;
- never merges, pushes, rewrites history or edits product code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from harness_config import load_git_policy
from pr_provider import (
    ProviderError,
    _json_output,
    _run,
    _tea_api,
    provider_context,
    view_pr,
)


SCHEMA_VERSION = 1
MAX_PROVIDER_ITEMS = 100
MAX_REFRESHES = 3
MODES = {"ci-triage", "feedback", "reviewability", "babysit"}
NEXT_ACTIONS = {"none", "fix", "clarify", "retry", "recheck", "blocked", "wait"}
DISPOSITIONS = {
    "ci-triage": {"fix", "retry", "ignore", "blocked"},
    "feedback": {"fix", "dismiss", "clarify"},
    "reviewability": set(),
    "babysit": {"observe", "fix", "retry", "clarify", "blocked"},
}


class PRMaintenanceError(ValueError):
    """Provider snapshot or semantic payload is unsafe/stale/malformed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, label: str, *, max_chars: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PRMaintenanceError(f"{label} must be a non-empty string")
    result = value.strip()
    if len(result) > max_chars:
        raise PRMaintenanceError(f"{label} exceeds {max_chars} chars")
    return result


def _optional_text(value: Any, *, max_chars: int = 20000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return value[:max_chars]


def _actor(value: Any) -> str | None:
    if isinstance(value, dict):
        raw = value.get("login") or value.get("username") or value.get("name")
        return str(raw) if raw is not None else None
    return str(value) if value is not None else None


def _basis(value: dict[str, Any]) -> str:
    stable = {
        key: value[key]
        for key in ("provider", "pr", "checks", "comments", "reviews", "files")
    }
    encoded = json.dumps(
        stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _current_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    value = proc.stdout.strip()
    if proc.returncode or not value:
        raise PRMaintenanceError("cannot resolve current branch for PR maintenance")
    return value


def _gate(config: dict[str, Any], selector: str | int) -> dict[str, Any]:
    pr = config.get("pull_request")
    push = config.get("push")
    if not isinstance(pr, dict) or not isinstance(push, dict):
        raise PRMaintenanceError("Git policy pull_request/push sections are required")
    return {
        "provider": pr.get("provider"),
        "preferredTool": pr.get("preferred_tool"),
        "remote": push.get("remote"),
        "branch": str(selector),
        "base": pr.get("base"),
    }


def _github_host_args(ctx: Any) -> list[str]:
    if ctx.identity.host in {"github.com", "www.github.com", "ssh.github.com"}:
        return []
    return ["--hostname", ctx.identity.host]


def _github_api(root: Path, ctx: Any, endpoint: str) -> Any:
    proc = _run(
        root,
        [ctx.tool, "api", *_github_host_args(ctx), endpoint],
    )
    return _json_output(proc, label=f"gh api {endpoint}")


def _bounded(items: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise PRMaintenanceError(f"{label} provider result must be an object array")
    if len(items) >= MAX_PROVIDER_ITEMS:
        raise PRMaintenanceError(
            f"{label} reached bounded provider limit {MAX_PROVIDER_ITEMS}; snapshot may be truncated"
        )
    return items


def _github_snapshot(root: Path, ctx: Any, pr: dict[str, Any]) -> dict[str, Any]:
    number = pr.get("number")
    head = pr.get("headRefOid")
    if not isinstance(number, int) or not isinstance(head, str) or not head:
        raise PRMaintenanceError("GitHub PR identity/head revision is incomplete")
    base = f"repos/{ctx.identity.owner}/{ctx.identity.repo}"

    comments_raw = _bounded(
        _github_api(root, ctx, f"{base}/issues/{number}/comments?per_page={MAX_PROVIDER_ITEMS}"),
        "comments",
    )
    reviews_raw = _bounded(
        _github_api(root, ctx, f"{base}/pulls/{number}/reviews?per_page={MAX_PROVIDER_ITEMS}"),
        "reviews",
    )
    files_raw = _bounded(
        _github_api(root, ctx, f"{base}/pulls/{number}/files?per_page={MAX_PROVIDER_ITEMS}"),
        "files",
    )
    checks_payload = _github_api(
        root, ctx, f"{base}/commits/{head}/check-runs?per_page={MAX_PROVIDER_ITEMS}"
    )
    if not isinstance(checks_payload, dict):
        raise PRMaintenanceError("GitHub check-runs response must be object")
    check_runs = _bounded(checks_payload.get("check_runs"), "check runs")
    if checks_payload.get("total_count", len(check_runs)) > len(check_runs):
        raise PRMaintenanceError("GitHub check-runs snapshot is truncated")
    statuses_payload = _github_api(root, ctx, f"{base}/commits/{head}/status")
    if not isinstance(statuses_payload, dict):
        raise PRMaintenanceError("GitHub commit status response must be object")
    statuses = _bounded(statuses_payload.get("statuses", []), "commit statuses")

    comments = [{
        "factId": f"comment:{item.get('id')}",
        "providerId": item.get("id"),
        "url": item.get("html_url"),
        "author": _actor(item.get("user")),
        "body": _optional_text(item.get("body")),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
    } for item in comments_raw if item.get("id") is not None]

    reviews = [{
        "factId": f"review:{item.get('id')}",
        "providerId": item.get("id"),
        "url": item.get("html_url"),
        "author": _actor(item.get("user")),
        "state": str(item.get("state") or "").upper(),
        "body": _optional_text(item.get("body")),
        "submittedAt": item.get("submitted_at"),
    } for item in reviews_raw if item.get("id") is not None]

    checks: list[dict[str, Any]] = []
    for item in check_runs:
        if item.get("id") is None:
            continue
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        checks.append({
            "factId": f"check:{item.get('id')}",
            "providerId": item.get("id"),
            "kind": "check-run",
            "name": item.get("name"),
            "status": str(item.get("status") or "").upper(),
            "conclusion": str(item.get("conclusion") or "").upper() or None,
            "url": item.get("html_url") or item.get("details_url"),
            "outputTitle": _optional_text(output.get("title"), max_chars=2000),
            "outputSummary": _optional_text(output.get("summary"), max_chars=12000),
            "outputText": _optional_text(output.get("text"), max_chars=12000),
        })
    for item in statuses:
        if item.get("id") is None:
            continue
        state = str(item.get("state") or "").upper()
        checks.append({
            "factId": f"status:{item.get('id')}",
            "providerId": item.get("id"),
            "kind": "commit-status",
            "name": item.get("context"),
            "status": "COMPLETED",
            "conclusion": state,
            "url": item.get("target_url"),
            "description": _optional_text(item.get("description"), max_chars=4000),
        })

    files = [{
        "path": item.get("filename"),
        "status": item.get("status"),
        "additions": item.get("additions"),
        "deletions": item.get("deletions"),
        "changes": item.get("changes"),
    } for item in files_raw if isinstance(item.get("filename"), str)]

    return {"checks": checks, "comments": comments, "reviews": reviews, "files": files}


def _gitea_snapshot(root: Path, ctx: Any, pr: dict[str, Any]) -> dict[str, Any]:
    number = pr.get("number")
    head = pr.get("headRefOid")
    if not isinstance(number, int) or not isinstance(head, str) or not head:
        raise PRMaintenanceError("Gitea PR identity/head revision is incomplete")
    base = f"/repos/{ctx.identity.owner}/{ctx.identity.repo}"
    try:
        comments_raw = _bounded(
            _tea_api(root, ctx, f"{base}/issues/{number}/comments?limit={MAX_PROVIDER_ITEMS}"),
            "comments",
        )
        reviews_raw = _bounded(
            _tea_api(root, ctx, f"{base}/pulls/{number}/reviews?limit={MAX_PROVIDER_ITEMS}"),
            "reviews",
        )
        files_raw = _bounded(
            _tea_api(root, ctx, f"{base}/pulls/{number}/files?limit={MAX_PROVIDER_ITEMS}"),
            "files",
        )
        status_payload = _tea_api(root, ctx, f"{base}/commits/{head}/status")
    except ProviderError as exc:
        raise ProviderError(
            "PR_MAINTENANCE_CAPABILITY_UNAVAILABLE",
            f"Gitea PR maintenance read capability unavailable: {exc}",
            provider="gitea",
            causeCode=exc.code,
        ) from exc
    if not isinstance(status_payload, dict):
        raise PRMaintenanceError("Gitea commit status response must be object")
    statuses = _bounded(status_payload.get("statuses", []), "commit statuses")

    comments = [{
        "factId": f"comment:{item.get('id')}",
        "providerId": item.get("id"),
        "url": item.get("html_url"),
        "author": _actor(item.get("user")),
        "body": _optional_text(item.get("body")),
        "createdAt": item.get("created_at"),
        "updatedAt": item.get("updated_at"),
    } for item in comments_raw if item.get("id") is not None]
    reviews = [{
        "factId": f"review:{item.get('id')}",
        "providerId": item.get("id"),
        "url": item.get("html_url"),
        "author": _actor(item.get("user")),
        "state": str(item.get("state") or "").upper(),
        "body": _optional_text(item.get("body")),
        "submittedAt": item.get("submitted_at"),
    } for item in reviews_raw if item.get("id") is not None]
    checks = [{
        "factId": f"status:{item.get('id')}",
        "providerId": item.get("id"),
        "kind": "commit-status",
        "name": item.get("context"),
        "status": "COMPLETED",
        "conclusion": str(item.get("status") or item.get("state") or "").upper(),
        "url": item.get("target_url"),
    } for item in statuses if item.get("id") is not None]
    files = [{
        "path": item.get("filename"),
        "status": item.get("status"),
        "additions": item.get("additions"),
        "deletions": item.get("deletions"),
        "changes": item.get("changes"),
    } for item in files_raw if isinstance(item.get("filename"), str)]
    return {"checks": checks, "comments": comments, "reviews": reviews, "files": files}


def provider_snapshot(root: Path, selector: str | int) -> dict[str, Any]:
    config = load_git_policy(root)
    pr = view_pr(root, config, selector)
    ctx = provider_context(root, _gate(config, selector))
    facts = _github_snapshot(root, ctx, pr) if ctx.provider == "github" else _gitea_snapshot(root, ctx, pr)
    value = {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": _utc_now(),
        "provider": {
            "name": ctx.provider,
            "host": ctx.identity.host,
            "repository": ctx.identity.slug,
        },
        "pr": pr,
        **facts,
    }
    value["snapshotBasis"] = _basis(value)
    return value


def _strings(value: Any, label: str, *, max_items: int = 50) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise PRMaintenanceError(f"{label} must be an array with <= {max_items} items")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{label}[{index}]", max_chars=4000))
    return result


def validate_semantic(snapshot: dict[str, Any], payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PRMaintenanceError("semantic payload must be an object")
    required = {
        "schemaVersion", "mode", "snapshotBasis", "refreshCount", "items",
        "reviewerGuidance", "nextAction", "rationale"
    }
    if set(payload) != required:
        raise PRMaintenanceError("semantic payload has unsupported/missing keys")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise PRMaintenanceError(f"schemaVersion must be {SCHEMA_VERSION}")
    mode = payload.get("mode")
    if mode not in MODES:
        raise PRMaintenanceError(f"mode must be one of {sorted(MODES)}")
    if payload.get("snapshotBasis") != snapshot.get("snapshotBasis"):
        raise PRMaintenanceError("PR_SNAPSHOT_STALE")
    refresh_count = payload.get("refreshCount")
    if isinstance(refresh_count, bool) or not isinstance(refresh_count, int):
        raise PRMaintenanceError("refreshCount must be integer")
    if refresh_count < 0 or refresh_count > MAX_REFRESHES:
        raise PRMaintenanceError(f"refreshCount must be 0..{MAX_REFRESHES}")
    next_action = payload.get("nextAction")
    if next_action not in NEXT_ACTIONS:
        raise PRMaintenanceError(f"nextAction must be one of {sorted(NEXT_ACTIONS)}")
    rationale = _text(payload.get("rationale"), "rationale")

    all_facts: dict[str, dict[str, Any]] = {}
    for category in ("checks", "comments", "reviews"):
        for item in snapshot.get(category, []):
            fact_id = item.get("factId")
            if isinstance(fact_id, str):
                all_facts[fact_id] = {**item, "_category": category}

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > 100:
        raise PRMaintenanceError("items must be an array with <= 100 entries")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_dispositions = DISPOSITIONS[mode]
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or set(raw) != {
            "factId", "disposition", "summary", "action"
        }:
            raise PRMaintenanceError(
                f"items[{index}] keys must be factId, disposition, summary, action"
            )
        fact_id = _text(raw.get("factId"), f"items[{index}].factId")
        if fact_id in seen:
            raise PRMaintenanceError(f"duplicate semantic fact reference: {fact_id}")
        seen.add(fact_id)
        fact = all_facts.get(fact_id)
        if fact is None:
            raise PRMaintenanceError(f"unknown provider fact: {fact_id}")
        disposition = raw.get("disposition")
        if disposition not in allowed_dispositions:
            raise PRMaintenanceError(f"items[{index}].disposition invalid for {mode}")
        if mode == "ci-triage":
            if fact["_category"] != "checks":
                raise PRMaintenanceError("ci-triage may reference only check facts")
            conclusion = str(fact.get("conclusion") or "").upper()
            if conclusion in {"SUCCESS", "NEUTRAL", "SKIPPED", "PASS", "PASSED"}:
                raise PRMaintenanceError("ci-triage may not treat successful check as failure")
        if mode == "feedback" and fact["_category"] not in {"comments", "reviews"}:
            raise PRMaintenanceError("feedback may reference only comment/review facts")
        items.append({
            "factId": fact_id,
            "providerId": fact.get("providerId"),
            "disposition": disposition,
            "summary": _text(raw.get("summary"), f"items[{index}].summary"),
            "action": _text(raw.get("action"), f"items[{index}].action"),
        })

    if mode == "ci-triage":
        fix_items = [item for item in items if item["disposition"] == "fix"]
        if len(fix_items) > 1:
            raise PRMaintenanceError(
                "ci-triage must focus on at most one first actionable root failure"
            )

    guidance = payload.get("reviewerGuidance")
    if mode == "reviewability":
        if not isinstance(guidance, dict) or set(guidance) != {
            "summary", "risks", "verification", "generatedOrMechanicalPaths"
        }:
            raise PRMaintenanceError("reviewerGuidance contract is malformed")
        known_paths = {
            item.get("path") for item in snapshot.get("files", [])
            if isinstance(item.get("path"), str)
        }
        generated = _strings(
            guidance.get("generatedOrMechanicalPaths"),
            "reviewerGuidance.generatedOrMechanicalPaths",
        )
        unknown_paths = sorted(set(generated) - known_paths)
        if unknown_paths:
            raise PRMaintenanceError(
                "reviewerGuidance references paths outside PR diff: "
                + ", ".join(unknown_paths)
            )
        normalized_guidance = {
            "summary": _text(guidance.get("summary"), "reviewerGuidance.summary"),
            "risks": _strings(guidance.get("risks"), "reviewerGuidance.risks"),
            "verification": _strings(
                guidance.get("verification"), "reviewerGuidance.verification"
            ),
            "generatedOrMechanicalPaths": generated,
        }
        if items:
            raise PRMaintenanceError("reviewability mode does not use provider finding items")
    else:
        if guidance is not None:
            raise PRMaintenanceError("reviewerGuidance must be null outside reviewability")
        normalized_guidance = None

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "BLOCKED" if next_action == "blocked" else "PASS",
        "mode": mode,
        "snapshotBasis": snapshot["snapshotBasis"],
        "refreshCount": refresh_count,
        "items": items,
        "reviewerGuidance": normalized_guidance,
        "nextAction": next_action,
        "rationale": rationale,
        "mutationAuthority": "existing-git-pr-workflow-only",
        "autoMergeAllowed": False,
        "historyRewriteAllowed": False,
    }


def _payload(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read PR facts and validate semantic maintenance output.")
    sub = parser.add_subparsers(dest="operation", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--selector")
    snap.add_argument("--pretty", action="store_true")

    validate = sub.add_parser("validate")
    validate.add_argument("--selector")
    validate.add_argument("--payload-file", required=True)
    validate.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    selector: str | int = args.selector or _current_branch(root)
    if isinstance(selector, str) and selector.isdigit():
        selector = int(selector)
    try:
        snapshot = provider_snapshot(root, selector)
        result = snapshot if args.operation == "snapshot" else validate_semantic(
            snapshot, _payload(args.payload_file)
        )
    except ProviderError as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, PRMaintenanceError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": "PR_MAINTENANCE_BLOCKED",
            "message": str(exc),
        }
    print(json.dumps(
        result,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
        separators=None if args.pretty else (",", ":"),
    ))
    return 0 if result.get("status") == "PASS" or "snapshotBasis" in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
