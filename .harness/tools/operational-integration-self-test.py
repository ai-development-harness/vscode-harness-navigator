#!/usr/bin/env python3
"""#318: writer -> dispatcher E2E, own execution, configured paths, crash windows."""

from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

from command_dispatch import complete_dispatch
from execution_status import load_status, start_execution
from operational_reports import OperationalReportError, write_operational_report
from report_contract import validate_audit_report, validate_release_report, validate_skill_search_report
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts

SOURCE = Path(__file__).resolve().parents[2]


def git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, (args, result.stdout, result.stderr)


def audit(scope: str) -> dict:
    return {
        "scope": scope,
        "sections": {
            "Sources checked": "Observed REQ and actual project files.",
            "Actual state": "Current implementation assessed.",
            "Drift / findings": "Material drift found in expected behavior.",
            "Evidence": "Source and scenario verified.",
            "Corrective actions": "Propose a corrective STEP.",
        },
    }


def release() -> dict:
    return {
        "target": "v2.3.1", "verdict": "blocked",
        "sections": {
            "Requirements / scope": "Release scope identified.",
            "Verification gates": "Build command was checked.",
            "Security / migrations / compatibility": "Compatibility reviewed.",
            "Unresolved blockers": "Required test has not passed.",
            "Evidence": "Observed failure prevents READY.",
        },
    }


def search() -> dict:
    return {
        "query": "testing skill",
        "candidates": [],
        "sections": {
            "Search strategy": "Looked up pinned source references.",
            "Ranking criteria": "Reliability and maintained provenance.",
            "Rejected / notable alternatives": "No candidate had sufficient proof.",
            "Next command": "Create new skill only if requested.",
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="operational-integration-", ignore_cleanup_errors=True,
    ) as tmp:
        root = Path(tmp).resolve()
        copy_effective_harness_checkout(SOURCE, root)
        isolate_project_artifacts(root)
        manifest = root / ".harness/manifest.yaml"
        text = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in text
        manifest.write_text(text.replace("initialized: false", "initialized: true", 1), encoding="utf-8")
        task_template = root / "planning/tasks/TEMPLATE.md"
        task = task_template.read_text(encoding="utf-8")
        task = task.replace("STEP-NNN", "STEP-017").replace("phase: TBD", "phase: test")
        task = task.replace("requirements:\n  - REQ-NNN", "requirements: []")
        task = task.replace('architecture_refs:\n  - "docs/architecture.md#relevant-section"', "architecture_refs: []")
        (root / "planning/tasks/STEP-017.md").write_text(task, encoding="utf-8")

        git(root, "init", "-q", "-b", "main")
        git(root, "config", "maintenance.auto", "false")
        git(root, "config", "gc.auto", "0")
        git(root, "config", "user.email", "integration@example.invalid")
        git(root, "config", "user.name", "Skills Contracts Integration")
        git(root, "add", ".")
        git(root, "commit", "-qm", "project fixture")

        cases = (
            ("PROJECT RECONCILE", "audit", audit("project"), validate_audit_report),
            ("STEP AUDIT STEP-017", "audit", audit("STEP-017"), validate_audit_report),
            ("RELEASE CHECK", "release_check", release(), validate_release_report),
            ("SKILL FIND: testing skill", "skill_search", search(), validate_skill_search_report),
        )
        for command, kind, value, validate in cases:
            execution = start_execution(root, command)
            eid = execution["executionId"]
            no_report = complete_dispatch(
                root, command, command, "SUCCESS", execution_id=eid,
            )
            assert no_report["status"] == "BLOCKED", no_report
            assert no_report["reasonCode"] == "OPERATIONAL_REPORT_MISSING", no_report
            assert any(e["executionId"] == eid for e in load_status(root)["executions"])

            if kind == "release_check":
                # Проверить действительный CLI writer в новом Python процессе:
                # JSON передаём через stdin, receipt должен пережить restart.
                writer = subprocess.run(
                    [
                        sys.executable, ".harness/tools/semantic-writer.py",
                        "release-report", "--execution-id", eid,
                        "--payload-file", "-",
                    ],
                    input=json.dumps(value), text=True,
                    capture_output=True, cwd=root,
                )
                assert writer.returncode == 0, (writer.stdout, writer.stderr)
                result = json.loads(writer.stdout)
            else:
                result = write_operational_report(root, kind, value, execution_id=eid)
            assert result["status"] == "PASS", result
            report = root / result["report"]
            assert report.is_file() and not validate(root, report), result

            # Validator должен принять и реальный material drift (audit),
            # и честный вердикт blocked (release) как валидный report.
            if kind == "release_check":
                # Completion после независимого запуска подтверждает durable
                # receipt, а не случайную память текущего Python-процесса.
                completed = subprocess.run(
                    [
                        sys.executable, ".harness/tools/harness-dispatch.py",
                        "complete", "--root", command, "--command", command,
                        "--result", "SUCCESS", "--execution-id", eid,
                    ],
                    text=True, capture_output=True, cwd=root,
                )
                assert completed.returncode == 0, (completed.stdout, completed.stderr)
                done = json.loads(completed.stdout)
            else:
                done = complete_dispatch(
                    root, command, command, "SUCCESS", execution_id=eid,
                )
            assert done["status"] == "DONE", done
            assert not any(e["executionId"] == eid for e in load_status(root)["executions"])

            # Устаревший semantic SUCCESS не принадлежит новой invocation.
            another = start_execution(root, command)
            new_id = another["executionId"]
            stale = complete_dispatch(root, command, command, "SUCCESS", execution_id=eid)
            assert stale["status"] == "BLOCKED", stale
            denied = complete_dispatch(root, command, command, "SUCCESS", execution_id=new_id)
            assert denied["reasonCode"] == "OPERATIONAL_REPORT_MISSING", denied

            # Crash-window: orphan immutable report после create, до receipt.
            before = set(report.parent.glob(report.name.split("-20")[0] + "*.md"))
            with patch("operational_reports.record_operational_report", side_effect=OSError("crash before receipt")):
                try:
                    write_operational_report(root, kind, value, execution_id=new_id)
                except OSError:
                    pass
                else:
                    raise AssertionError("writer failure was swallowed")
            assert complete_dispatch(
                root, command, command, "SUCCESS", execution_id=new_id,
            )["reasonCode"] == "OPERATIONAL_REPORT_MISSING"
            after = set(report.parent.glob(report.name.split("-20")[0] + "*.md"))
            assert len(after) >= len(before) + 1, (before, after)

            recovered = write_operational_report(root, kind, value, execution_id=new_id)
            assert recovered["report"] != result["report"]
            assert complete_dispatch(
                root, command, command, "SUCCESS", execution_id=new_id,
            )["status"] == "DONE"

        # Custom template topology: path comes from manifest, not planning/*.
        changed = manifest.read_text(encoding="utf-8")
        for old, new in (
            ("planning/audits", "work/custom-audits"),
            ("planning/releases", "work/custom-releases"),
            ("planning/skill-searches", "work/custom-skill-searches"),
        ):
            assert old in changed, old
            changed = changed.replace(old, new)
            folder = root / new
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / old / "TEMPLATE.md", folder / "TEMPLATE.md")
        manifest.write_text(changed, encoding="utf-8")
        for command, kind, value, destination in (
            ("PROJECT RECONCILE", "audit", audit("project"), "work/custom-audits/"),
            ("RELEASE CHECK", "release_check", release(), "work/custom-releases/"),
            ("SKILL FIND: testing skill", "skill_search", search(), "work/custom-skill-searches/"),
        ):
            execution = start_execution(root, command)
            custom = write_operational_report(
                root, kind, value, execution_id=execution["executionId"],
            )
            assert custom["report"].startswith(destination), custom
            assert complete_dispatch(
                root, command, command, "SUCCESS",
                execution_id=execution["executionId"],
            )["status"] == "DONE"

        # Нельзя подменять payload модельным YAML или незаполненным TBD.
        execution = start_execution(root, "RELEASE CHECK")
        value = release()
        for wrong in (
            {**value, "created_at": "2100-01-01T00:00:00Z"},
            {**value, "sections": {**value["sections"], "Evidence": "TBD"}},
        ):
            try:
                write_operational_report(
                    root, "release_check", wrong, execution_id=execution["executionId"],
                )
            except OperationalReportError:
                pass
            else:
                raise AssertionError("invalid report became a durable PASS")
        assert complete_dispatch(
            root, "RELEASE CHECK", "RELEASE CHECK", "SUCCESS",
            execution_id=execution["executionId"],
        )["reasonCode"] == "OPERATIONAL_REPORT_MISSING"

    print("operational-integration-self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
