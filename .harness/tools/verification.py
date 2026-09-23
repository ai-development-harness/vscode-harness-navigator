#!/usr/bin/env python3
"""Deterministic STEP Verification runner.

Verification section accepts explicit entries:
- command: <backtick-wrapped argv text>
- manual: human/semantic check description

Commands run directly as argv without shell. The runner records factual evidence,
checks that verification itself did not mutate repository revision, and updates
only a generated block inside the STEP Evidence section.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
from typing import Any

from document_contract import atomic_write_text, markdown_headings
from harness_config import verification_command_timeout_seconds
from planning_contract import read_task, task_path
from review_contract import repository_revision


COMMAND_RE = re.compile(r"^- command:\s*\x60([^\x60]+)\x60\s*$")
MANUAL_RE = re.compile(r"^- manual:\s*(.+?)\s*$")
EVIDENCE_START = "<!-- VERIFICATION-EVIDENCE:START -->"
EVIDENCE_END = "<!-- VERIFICATION-EVIDENCE:END -->"
SHELL_CONTROL_TOKENS = {
    "|", "||", "&&", ";", "<", ">", ">>", "2>", "2>>", "&",
}


class VerificationError(ValueError):
    """Invalid or unprovable Verification contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_verification(root: Path, step_id: str) -> list[dict[str, str]]:
    """Parse only explicit command/manual entries; never guess prose."""
    task = read_task(root, step_id)
    section = task["sections"].get("Verification", "")
    entries: list[dict[str, str]] = []
    errors: list[str] = []

    for number, raw in enumerate(section.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        command = COMMAND_RE.fullmatch(line)
        if command:
            value = command.group(1).strip()
            if value:
                entries.append({"kind": "command", "value": value})
            else:
                errors.append(f"line {number}: empty command")
            continue
        manual = MANUAL_RE.fullmatch(line)
        if manual:
            value = manual.group(1).strip()
            if value:
                entries.append({"kind": "manual", "value": value})
            else:
                errors.append(f"line {number}: empty manual check")
            continue
        errors.append(
            f"line {number}: unsupported Verification entry; "
            "use explicit command or manual format"
        )

    if errors:
        raise VerificationError("; ".join(errors))
    if not entries:
        raise VerificationError("Verification section has no command/manual entries")
    return entries


def validate_verification_entries(entries: Any) -> list[dict[str, str]]:
    """Validate structured Verification payload before STEP mutation."""
    if not isinstance(entries, list) or not entries:
        raise VerificationError("verification must be a non-empty array")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            raise VerificationError(f"verification[{index}] must be an object")
        unexpected = sorted(set(item) - {"kind", "value"})
        if unexpected:
            raise VerificationError(
                f"verification[{index}] has unsupported keys: " + ", ".join(unexpected)
            )
        kind = item.get("kind")
        value = item.get("value")
        if kind not in {"command", "manual"}:
            raise VerificationError(
                f"verification[{index}].kind must be command or manual"
            )
        if not isinstance(value, str) or not value.strip():
            raise VerificationError(
                f"verification[{index}].value must be non-empty"
            )
        value = value.strip()
        if kind == "command":
            _argv(value)
        normalized.append({"kind": kind, "value": value})
    return normalized


def render_verification_entries(entries: Any) -> str:
    """Render validated structured Verification entries into canonical Markdown."""
    values = validate_verification_entries(entries)
    tick = chr(96)
    lines: list[str] = []
    for item in values:
        if item["kind"] == "command":
            lines.append(f"- command: {tick}{item['value']}{tick}")
        else:
            lines.append(f"- manual: {item['value']}")
    return "\n".join(lines)


def _argv(command: str) -> list[str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise VerificationError(f"cannot parse verification command {command!r}: {exc}") from exc
    if not argv:
        raise VerificationError("verification command is empty")
    controls = sorted(token for token in argv if token in SHELL_CONTROL_TOKENS)
    if controls:
        raise VerificationError(
            "shell control operators are not supported; move complex logic "
            "into a repository script: " + ", ".join(controls)
        )
    return argv


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tail(value: bytes, limit: int = 800) -> str | None:
    if not value:
        return None
    text = value.decode("utf-8", errors="replace").strip()
    return text[-limit:] if text else None


def _revision_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("git_head") == right.get("git_head")
        and left.get("worktree_hash") == right.get("worktree_hash")
    )


def _run_command(
    root: Path,
    command: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    argv = _argv(command)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "kind": "command",
            "command": command,
            "argv": argv,
            "status": "BLOCKED",
            "reasonCode": "EXECUTABLE_NOT_FOUND",
            "message": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        return {
            "kind": "command",
            "command": command,
            "argv": argv,
            "status": "FAIL",
            "reasonCode": "TIMEOUT",
            "timeoutSeconds": timeout_seconds,
            "durationMs": int((time.monotonic() - started) * 1000),
            "exitCode": None,
            "stdoutSha256": _hash(stdout),
            "stderrSha256": _hash(stderr),
            "stdoutBytes": len(stdout),
            "stderrBytes": len(stderr),
            "stdoutTail": _tail(stdout),
            "stderrTail": _tail(stderr),
        }

    result: dict[str, Any] = {
        "kind": "command",
        "command": command,
        "argv": argv,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "durationMs": int((time.monotonic() - started) * 1000),
        "exitCode": proc.returncode,
        "stdoutSha256": _hash(proc.stdout),
        "stderrSha256": _hash(proc.stderr),
        "stdoutBytes": len(proc.stdout),
        "stderrBytes": len(proc.stderr),
    }
    if proc.returncode != 0:
        result["stdoutTail"] = _tail(proc.stdout)
        result["stderrTail"] = _tail(proc.stderr)
    return result


def _manual_results(
    entries: list[dict[str, str]],
    supplied: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    expected = [item["value"] for item in entries if item["kind"] == "manual"]
    if not expected:
        return [], []
    if supplied is None:
        return [], expected
    if not isinstance(supplied, list):
        raise VerificationError("manualVerification must be an array")

    by_check: dict[str, dict[str, Any]] = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise VerificationError("manualVerification entries must be objects")
        check = item.get("check")
        status = item.get("status")
        observed = item.get("observed")
        if not isinstance(check, str) or check not in expected:
            raise VerificationError(f"unknown manual verification check: {check!r}")
        if check in by_check:
            raise VerificationError(f"duplicate manual verification check: {check}")
        if status not in {"PASS", "FAIL"}:
            raise VerificationError(
                f"manual verification status for {check!r} must be PASS or FAIL"
            )
        if not isinstance(observed, str) or not observed.strip():
            raise VerificationError(
                f"manual verification observed for {check!r} must be non-empty"
            )
        by_check[check] = {
            "kind": "manual",
            "check": check,
            "status": status,
            "observed": observed.strip(),
        }

    missing = [check for check in expected if check not in by_check]
    ordered = [by_check[check] for check in expected if check in by_check]
    return ordered, missing


def _evidence_block(result: dict[str, Any]) -> str:
    revision = result["revision"]
    lines = [
        EVIDENCE_START,
        f"- Verification run: {result['runAt']}",
        f"- Status: {result['status']}",
        f"- Git head: {revision.get('git_head') or 'none'}",
        f"- Worktree hash: {revision.get('worktree_hash') or 'clean'}",
        "",
        "### Automated verification",
    ]
    automated = result.get("commands", [])
    if not automated:
        lines.append("- none")
    for item in automated:
        lines.extend(
            [
                f"- Command: {item['command']}",
                f"  - Status: {item['status']}",
                f"  - Exit code: {item.get('exitCode')}",
                f"  - Duration ms: {item.get('durationMs')}",
                f"  - stdout sha256: {item.get('stdoutSha256')}",
                f"  - stderr sha256: {item.get('stderrSha256')}",
                f"  - stdout bytes: {item.get('stdoutBytes')}",
                f"  - stderr bytes: {item.get('stderrBytes')}",
            ]
        )

    lines.extend(["", "### Manual verification"])
    manual = result.get("manual", [])
    pending = result.get("manualPending", [])
    if not manual and not pending:
        lines.append("- none")
    for item in manual:
        lines.extend(
            [
                f"- Check: {item['check']}",
                f"  - Status: {item['status']}",
                "  - Observed: " + json.dumps(item["observed"], ensure_ascii=False),
            ]
        )
    for check in pending:
        lines.extend([f"- Check: {check}", "  - Status: PENDING"])

    lines.append(EVIDENCE_END)
    return "\n".join(lines)


def _replace_evidence_block(text: str, block: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    h2 = [
        (index, title)
        for index, level, title in markdown_headings(text)
        if level == 2
    ]
    evidence_indexes = [index for index, title in h2 if title == "Evidence"]
    if len(evidence_indexes) != 1:
        raise VerificationError(
            f"expected exactly one Evidence section, found {len(evidence_indexes)}"
        )
    heading_index = evidence_indexes[0]
    next_indexes = [index for index, _ in h2 if index > heading_index]
    section_end = min(next_indexes) if next_indexes else len(lines)

    current = lines[heading_index + 1 : section_end]
    start = current.index(EVIDENCE_START) if EVIDENCE_START in current else -1
    end = current.index(EVIDENCE_END) if EVIDENCE_END in current else -1
    if (start >= 0) != (end >= 0):
        raise VerificationError("malformed generated verification Evidence markers")
    if start >= 0:
        if end < start:
            raise VerificationError("reversed generated verification Evidence markers")
        current = current[:start] + block.splitlines() + current[end + 1 :]
    else:
        semantic = "\n".join(current).strip()
        if semantic == "—":
            semantic = ""
        current = block.splitlines() + (["", semantic] if semantic else [])

    result = lines[: heading_index + 1] + [""] + current + [""] + lines[section_end:]
    return "\n".join(result).rstrip() + "\n"


def _write_evidence(root: Path, step_id: str, result: dict[str, Any]) -> None:
    path = task_path(root, step_id)
    text = path.read_text(encoding="utf-8")
    atomic_write_text(
        path,
        _replace_evidence_block(text, _evidence_block(result)),
    )


def run_step_verification(
    root: Path,
    step_id: str,
    *,
    manual_results: list[dict[str, Any]] | None = None,
    write_evidence: bool = True,
) -> dict[str, Any]:
    """Run explicit Verification contract and return factual result."""
    try:
        entries = parse_verification(root, step_id)
        timeout = verification_command_timeout_seconds(root)
        manual, pending = _manual_results(entries, manual_results)
        revision = repository_revision(root)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_CONTRACT_INVALID",
            "message": str(exc),
        }

    commands: list[dict[str, Any]] = []
    try:
        for entry in entries:
            if entry["kind"] != "command":
                continue
            before = repository_revision(root)
            if not _revision_equal(before, revision):
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": "VERIFICATION_BASELINE_CHANGED",
                    "commands": commands,
                }

            item = _run_command(
                root,
                entry["value"],
                timeout_seconds=timeout,
            )
            commands.append(item)
            if item["status"] == "BLOCKED":
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": item.get("reasonCode"),
                    "commands": commands,
                    "message": item.get("message"),
                }

            after = repository_revision(root)
            if not _revision_equal(revision, after):
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": "VERIFICATION_MUTATED_REPOSITORY",
                    "commands": commands,
                    "revisionBefore": revision,
                    "revisionAfter": after,
                }
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_RUNTIME_BLOCKED",
            "commands": commands,
            "message": str(exc),
        }

    if any(item["status"] == "FAIL" for item in commands):
        status = "FAIL"
    elif any(item["status"] == "FAIL" for item in manual):
        status = "FAIL"
    elif pending:
        status = "MANUAL_REQUIRED"
    else:
        status = "PASS"

    result = {
        "schemaVersion": 1,
        "status": status,
        "stepId": step_id,
        "runAt": utc_now(),
        "revision": revision,
        "timeoutSeconds": timeout,
        "commands": commands,
        "manual": manual,
        "manualPending": pending,
    }
    if write_evidence:
        try:
            _write_evidence(root, step_id, result)
        except (OSError, ValueError) as exc:
            return {
                **result,
                "status": "BLOCKED",
                "reasonCode": "EVIDENCE_WRITE_FAILED",
                "message": str(exc),
            }
    return result


__all__ = [
    "VerificationError",
    "parse_verification",
    "render_verification_entries",
    "run_step_verification",
    "validate_verification_entries",
]
