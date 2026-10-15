#!/usr/bin/env python3
"""Focused #316: deterministic operational report writer and provenance."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from operational_reports import OperationalReportError, write_operational_report
from report_contract import (
    validate_audit_report,
    validate_release_report,
    validate_skill_search_report,
)
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts

SOURCE = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    result = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout, result.stderr)


def payload(kind: str) -> dict:
    if kind == "audit":
        return {
            "scope": "project",
            "sections": {
                "Sources checked": "REQ and STEP sources read.",
                "Actual state": "Current project state inspected.",
                "Drift / findings": "No unsupported claims of absence of drift.",
                "Evidence": "Observed stable source snapshots.",
                "Corrective actions": "None required by current evidence.",
            },
        }
    if kind == "release_check":
        return {
            "target": "v1.0.0",
            "verdict": "blocked",
            "sections": {
                "Requirements / scope": "Scope from verified REQ.",
                "Verification gates": "Build gate is unavailable.",
                "Security / migrations / compatibility": "No migration expected for this version.",
                "Unresolved blockers": "Build result unavailable.",
                "Evidence": "Actual repository has no build artifact for this fixture.",
            },
        }
    return {
        "query": "find reliable TypeScript testing skill",
        "candidates": [{
            "name": "safe-test", "repository": "owner/repository",
            "path": "skills/safe-test", "url": "https://example.invalid/safe-test",
            "inspectedRef": "0123456789abcdef0123456789abcdef01234567",
            "license": "MIT", "whyItFits": "Tests TypeScript services.",
            "limitations": "No integration harness.",
            "safetyNotes": "Read-only inspection.", "recommendation": "Worth reviewing.",
        }],
        "sections": {
            "Search strategy": "Inspected pinned repository sources.",
            "Ranking criteria": "Compatibility and safety.",
            "Rejected / notable alternatives": "No alternative with verified provenance.",
            "Next command": "Ask before installation.",
        },
    }


def evaluate(root: Path, kind: str, value: dict, *,
             command: str, execution_id: str = "exec-a") -> tuple[dict, list]:
    execution = {
        "executionId": execution_id,
        "status": "running",
        "current": {"command": command, "status": "running", "context": {}},
    }
    receipts: list = []
    with (
        patch("execution_status.load_status", return_value={"executions": [execution]}),
        patch("operational_reports.active_execution_for_command", return_value=execution),
        patch("operational_reports.record_operational_report", side_effect=lambda *a: receipts.append(a)),
    ):
        result = write_operational_report(root, kind, value, execution_id=execution_id)
    return result, receipts


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="operational-reports-") as directory:
        root = Path(directory).resolve()
        copy_effective_harness_checkout(SOURCE, root)
        isolate_project_artifacts(root)
        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "report@example.invalid")
        run(root, "git", "config", "user.name", "Operational Reports Test")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "initial tracked project")

        cases = [
            ("audit", "PROJECT RECONCILE", validate_audit_report),
            ("release_check", "RELEASE CHECK", validate_release_report),
            ("skill_search", "SKILL FIND: find reliable TypeScript testing skill", validate_skill_search_report),
        ]
        for kind, command, validator in cases:
            result, receipts = evaluate(root, kind, payload(kind), command=command)
            assert result["status"] == "PASS", result
            assert result["writerValidated"] is True
            assert result["executionId"] == "exec-a"
            report = root / result["report"]
            assert report.is_file() and not validator(root, report)
            assert len(receipts) == 1 and receipts[0][2] == "exec-a"
            assert receipts[0][3]["path"] == result["report"]
            assert receipts[0][3]["subjectHash"].startswith("sha256:")
            content = report.read_text(encoding="utf-8")
            assert "TBD" not in content and "created_at: YYYY" not in content

            # Второй независимый writer не имеет права перезаписать report.
            result2, _ = evaluate(root, kind, payload(kind), command=command,
                                  execution_id="exec-b")
            assert result2["report"] != result["report"]
            assert report.read_text(encoding="utf-8") == content

        for broken in (
            {"scope": "project", "sections": {"Evidence": "TBD"}},
            {**payload("audit"), "mode": "reconcile"},
            {**payload("audit"), "scope": "STEP-001"},
        ):
            try:
                evaluate(root, "audit", broken, command="PROJECT RECONCILE")
            except OperationalReportError:
                pass
            else:
                raise AssertionError("malformed report unexpectedly persisted")

        # Заблокировать повторную запись после writer-owned receipt.
        existing = {
            "executionId": "exec-a", "status": "running",
            "current": {
                "command": "PROJECT RECONCILE", "status": "running",
                "context": {"operationalReport": {"recorded": True}},
            },
        }
        with (
            patch("execution_status.load_status", return_value={"executions": [existing]}),
            patch("operational_reports.active_execution_for_command", return_value=existing),
        ):
            try:
                write_operational_report(root, "audit", payload("audit"), execution_id="exec-a")
            except OperationalReportError as exc:
                assert exc.code == "REPORT_ALREADY_RECORDED", exc
            else:
                raise AssertionError("duplicate report recorded")

        # Legacy status допускает пустой/отсутствующий command context. Это
        # controlled BLOCKED, а не необработанный AttributeError из writer.
        existing["current"]["context"] = None
        with (
            patch("execution_status.load_status", return_value={"executions": [existing]}),
            patch("operational_reports.active_execution_for_command", return_value=existing),
        ):
            try:
                write_operational_report(root, "audit", payload("audit"), execution_id="exec-a")
            except OperationalReportError as exc:
                assert exc.code == "REPORT_EXECUTION_CONTEXT_INVALID", exc
            else:
                raise AssertionError("missing command context accepted")

    print("operational-reports-self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
