#!/usr/bin/env python3
"""Deterministic UX queries/control commands for AI Development Harness.

Модуль намеренно не содержит LLM reasoning и не меняет product artifacts.
HARNESS RESUME разрешает существующий execution и возвращает exact handoff,
но сам не создаёт новый root execution.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from execution_status import load_status, resolve_execution, unresolved_executions
from harness_config import (
    ConfigError,
    get,
    load_git_policy,
    load_manifest,
    load_update_policy,
    task_directory,
)
from planning_contract import read_task
from projection_contract import write_projections
from review_contract import latest_review
from step_next import resolve_step_next


def _run(root: Path, *args: str, timeout: int = 15) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            args,
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "code": 127, "stdout": "", "stderr": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def _git_snapshot(root: Path) -> dict[str, Any]:
    executable = shutil.which("git")
    if executable is None:
        return {"installed": False, "repository": False}
    inside = _run(root, "git", "rev-parse", "--is-inside-work-tree")
    if not inside["ok"] or inside["stdout"] != "true":
        return {"installed": True, "repository": False}
    branch = _run(root, "git", "branch", "--show-current")
    status = _run(root, "git", "status", "--porcelain")
    remote = _run(root, "git", "remote", "get-url", "origin")
    return {
        "installed": True,
        "repository": True,
        "branch": branch["stdout"] or None,
        "dirty": bool(status["stdout"]),
        "origin": remote["stdout"] if remote["ok"] else None,
    }


def _resolved_unfinished(root: Path) -> list[dict[str, Any]]:
    """Read only current unresolved invocations without mutating recovery state."""
    return unresolved_executions(root, mutate=False)


def _pr_capability(root: Path) -> dict[str, Any]:
    try:
        policy = load_git_policy(root)
        pr = policy.get("pull_request", {})
        provider = pr.get("provider")
        tool = pr.get("preferred_tool")
    except (ConfigError, OSError, ValueError) as exc:
        return {
            "provider": None,
            "tool": None,
            "available": False,
            "requiredForHarness": False,
            "reason": f"invalid git policy: {exc}",
        }

    installed = isinstance(tool, str) and shutil.which(tool) is not None
    authenticated: bool | None = None
    reason: str | None = None

    if provider == "github" and tool == "gh":
        if installed:
            auth = _run(root, "gh", "auth", "status")
            authenticated = auth["ok"]
            if not authenticated:
                reason = "gh is installed but not authenticated"
        else:
            reason = "gh is not installed"
    elif installed:
        reason = "configured provider/tool is not implemented by current PR integration"
    else:
        reason = "configured PR tool is not installed"

    available = provider == "github" and tool == "gh" and installed and authenticated is True
    return {
        "provider": provider,
        "tool": tool,
        "installed": installed,
        "authenticated": authenticated,
        "available": available,
        "requiredForHarness": False,
        "requiredForCommands": ["GIT PR", "GIT PR FINISH"],
        "reason": None if available else reason,
    }


def harness_status(root: Path) -> dict[str, Any]:
    manifest = load_manifest(root)
    return {
        "status": "PASS",
        "harness": {
            "generation": get(manifest, "harness.version"),
            "release": get(manifest, "harness.release"),
        },
        "project": {
            "initialized": bool(get(manifest, "project.initialized", False)),
            "name": get(manifest, "project.name"),
        },
        "git": _git_snapshot(root),
        "executions": _resolved_unfinished(root),
        "capabilities": {"githubPullRequests": _pr_capability(root)},
    }


def harness_resume(root: Path) -> dict[str, Any]:
    # Resolver может применить узкие durable recovery proofs; это часть
    # продолжения, а не read-only запроса состояния.
    items = unresolved_executions(root)
    resumable = [item for item in items if item.get("status") in {"RESUME", "NEXT"}]
    if len(resumable) == 0:
        return {
            "status": "BLOCKED",
            "reasonCode": "NO_RESUMABLE_EXECUTION",
            "executions": items,
        }
    if len(resumable) > 1:
        return {
            "status": "BLOCKED",
            "reasonCode": "MULTIPLE_RESUMABLE_EXECUTIONS",
            "executions": resumable,
        }
    selected = resumable[0]

    if selected.get("status") == "BLOCKED" or not selected.get("command"):
        return {
            "status": "BLOCKED",
            "reasonCode": selected.get("reasonCode", "EXECUTION_BLOCKED"),
            "executionId": selected.get("executionId"),
            "rootCommand": selected.get("rootCommand"),
        }

    return {
        "status": "PASS",
        "executionId": selected.get("executionId"),
        "rootCommand": selected.get("rootCommand"),
        "command": selected.get("command"),
        "resolverStatus": selected.get("status"),
        "reasonCode": selected.get("reasonCode"),
        "instruction": "resume-existing-execution-without-starting-new-root",
    }


def harness_config(root: Path) -> dict[str, Any]:
    manifest_path = ".harness/manifest.yaml"
    manifest = load_manifest(root)
    git_policy = load_git_policy(root)
    update_policy = load_update_policy(root)
    return {
        "status": "PASS",
        "effective": {
            "manifest": manifest,
            "gitPolicy": git_policy,
            "updatePolicy": update_policy,
        },
        "sources": {
            "manifest": manifest_path,
            "gitPolicy": get(manifest, "repository.gitPolicy"),
            "updatePolicy": get(manifest, "repository.harnessUpdatePolicy"),
        },
    }


def harness_doctor(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    python_ok = sys.version_info >= (3, 11)
    checks.append({
        "name": "python",
        "kind": "required",
        "status": "PASS" if python_ok else "BLOCKED",
        "details": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}; required >=3.11",
    })

    git_path = shutil.which("git")
    git_state = _git_snapshot(root)
    git_ok = git_path is not None and git_state.get("repository") is True
    checks.append({
        "name": "git",
        "kind": "required",
        "status": "PASS" if git_ok else "BLOCKED",
        "details": git_path or "git executable not found",
    })

    try:
        load_manifest(root)
        config_ok, config_details = True, ".harness/manifest.yaml"
    except (ConfigError, OSError, ValueError) as exc:
        config_ok, config_details = False, str(exc)
    checks.append({
        "name": "harness-config",
        "kind": "required",
        "status": "PASS" if config_ok else "BLOCKED",
        "details": config_details,
    })

    validator = root / ".harness/tools/validate.py"
    if validator.is_file() and python_ok:
        validation = _run(root, sys.executable, str(validator), "--mode", "manual", timeout=60)
        validator_ok = validation["ok"]
        validator_details = validation["stdout"] or validation["stderr"]
    else:
        validator_ok = False
        validator_details = "validator missing or unsupported Python"
    checks.append({
        "name": "harness-integrity",
        "kind": "required",
        "status": "PASS" if validator_ok else "BLOCKED",
        "details": validator_details,
    })

    try:
        load_status(root)
        execution_ok, execution_details = True, ".harness/local/execution/execution-status.json"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        execution_ok, execution_details = False, str(exc)
    checks.append({
        "name": "execution-state",
        "kind": "required",
        "status": "PASS" if execution_ok else "BLOCKED",
        "details": execution_details,
    })

    for runtime in ("codex", "claude"):
        runtime_path = shutil.which(runtime)
        checks.append({
            "name": f"runtime-{runtime}",
            "kind": "optional",
            "status": "PASS" if runtime_path else "NOT_INSTALLED",
            "details": runtime_path or "optional supported runtime is not installed",
        })

    pr = _pr_capability(root)
    checks.append({
        "name": "github-pull-requests",
        "kind": "optional",
        "status": "PASS" if pr["available"] else "UNAVAILABLE",
        "details": pr,
    })

    core_blocked = any(
        item["kind"] == "required" and item["status"] != "PASS"
        for item in checks
    )
    return {
        "status": "BLOCKED" if core_blocked else "PASS",
        "checks": checks,
        "capabilityPolicy": {
            "python": "required",
            "git": "required",
            "codex": "optional-runtime",
            "claude": "optional-runtime",
            "gh": "optional; required only for GitHub PR commands",
        },
    }



def project_status(root: Path) -> dict[str, Any]:
    """Regenerate deterministic projections and return factual project status."""

    try:
        changed = write_projections(root)
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "reasonCode": "PROJECT_STATUS_PROJECTION_FAILED",
            "message": str(exc),
        }

    validator = root / ".harness/tools/validate.py"
    validation = _run(
        root,
        sys.executable,
        str(validator),
        "--mode",
        "manual",
        timeout=60,
    )
    if not validation["ok"]:
        return {
            "status": "BLOCKED",
            "reasonCode": "PROJECT_STATUS_INTEGRITY_FAILED",
            "changedProjections": changed,
            "validation": validation["stdout"] or validation["stderr"],
        }

    listed = step_list(root)
    if listed.get("status") != "PASS":
        return {
            "status": "BLOCKED",
            "reasonCode": "PROJECT_STATUS_STEP_LIST_FAILED",
            "changedProjections": changed,
            "errors": listed.get("errors", []),
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in listed["steps"]:
        groups.setdefault(str(item.get("status")), []).append(item)

    next_work = resolve_step_next(root)
    return {
        "status": "PASS",
        "changedProjections": changed,
        "summary": {
            "total": len(listed["steps"]),
            "byStatus": {
                name: len(items)
                for name, items in sorted(groups.items())
            },
        },
        "inProgress": groups.get("in_progress", []),
        "blocked": groups.get("blocked", []),
        "completed": [
            str(item["id"])
            for item in groups.get("completed", [])
        ],
        "nextWork": next_work,
        "validation": "PASS",
    }


def _step_title(document: dict[str, Any], step_id: str) -> str:
    prefix = f"# {step_id} — "
    h1 = document.get("h1", "")
    return h1[len(prefix):].strip() if isinstance(h1, str) and h1.startswith(prefix) else ""


def step_list(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        step_id = path.stem
        try:
            document = read_task(root, step_id)
        except Exception as exc:
            errors.append(f"{step_id}: {exc}")
            continue
        meta = document["frontmatter"]
        rows.append({
            "id": step_id,
            "title": _step_title(document, step_id),
            "status": meta.get("status"),
            "priority": meta.get("priority"),
            "type": meta.get("type"),
            "phase": meta.get("phase"),
            "planStatus": (meta.get("plan") or {}).get("status") if isinstance(meta.get("plan"), dict) else None,
            "path": path.relative_to(root).as_posix(),
        })
    rows.sort(key=lambda item: int(str(item["id"]).split("-")[1]))
    return {
        "status": "BLOCKED" if errors else "PASS",
        "steps": rows,
        "errors": errors,
    }


def step_show(root: Path, step_id: str) -> dict[str, Any]:
    if step_id.isdigit() and len(step_id) >= 3:
        step_id = f"STEP-{step_id}"
    document = read_task(root, step_id)
    meta = document["frontmatter"]
    review = latest_review(root, step_id)

    dependencies: list[dict[str, Any]] = []
    for dependency in meta.get("depends_on", []) if isinstance(meta.get("depends_on"), list) else []:
        try:
            dep = read_task(root, dependency)
            dep_status = dep["frontmatter"].get("status")
        except Exception:
            dep_status = "unknown"
        dependencies.append({"id": dependency, "status": dep_status})

    executions = [
        item for item in _resolved_unfinished(root)
        if step_id in str(item.get("rootCommand") or "")
        or step_id in str(item.get("command") or "")
    ]

    return {
        "status": "PASS",
        "step": {
            "id": step_id,
            "title": _step_title(document, step_id),
            "status": meta.get("status"),
            "type": meta.get("type"),
            "priority": meta.get("priority"),
            "phase": meta.get("phase"),
            "plan": meta.get("plan"),
            "dependencies": dependencies,
            "requirements": meta.get("requirements", []),
            "adrs": meta.get("adrs", []),
            "riskFlags": meta.get("risk_flags", []),
            "latestReview": None if review is None else {
                "verdict": review.get("verdict"),
                "path": review["path"].relative_to(root).as_posix(),
            },
            "executions": executions,
            "path": document["path"].relative_to(root).as_posix(),
        },
    }


def render_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


__all__ = [
    "harness_status",
    "harness_resume",
    "harness_config",
    "harness_doctor",
    "project_status",
    "step_list",
    "step_show",
    "render_text",
]
