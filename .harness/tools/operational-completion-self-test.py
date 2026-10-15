#!/usr/bin/env python3
"""#317: exact execution-bound operational report completion gates."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile

from command_dispatch import complete_dispatch
from execution_status import load_status, start_execution
from operational_reports import (
    operational_completion_blocker,
    write_operational_report,
)
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    p = subprocess.run(args, cwd=root, text=True, capture_output=True)
    assert p.returncode == 0, (args, p.stdout, p.stderr)


def audit_payload() -> dict:
    return {
        "scope": "project",
        "sections": {
            "Sources checked": "Current acceptance and source files inspected.",
            "Actual state": "One requirement has a known product discrepancy.",
            "Drift / findings": "Material drift: missing required behavior.",
            "Evidence": "Compared actual behavior with canonical REQ.",
            "Corrective actions": "Create follow-up STEP for the discrepancy.",
        },
    }


def main() -> int:
    # Disposable Git fixture: на Python 3.11 фоновые процессы Git могут
    # удерживать .git при удалении temp-каталога; это не report failure.
    with tempfile.TemporaryDirectory(
        prefix="operational-completion-", ignore_cleanup_errors=True,
    ) as directory:
        root = Path(directory).resolve()
        copy_effective_harness_checkout(SOURCE, root)
        isolate_project_artifacts(root)
        manifest = root / ".harness/manifest.yaml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "initialized: false", "initialized: true", 1,
            ),
            encoding="utf-8",
        )
        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "maintenance.auto", "false")
        run(root, "git", "config", "gc.auto", "0")
        run(root, "git", "config", "user.email", "completion@example.invalid")
        run(root, "git", "config", "user.name", "Completion Contract")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "project fixture")

        execution = start_execution(root, "PROJECT RECONCILE")
        execution_id = execution["executionId"]
        blocked = complete_dispatch(
            root, "PROJECT RECONCILE", "PROJECT RECONCILE", "SUCCESS",
            execution_id=execution_id,
        )
        assert blocked["status"] == "BLOCKED", blocked
        assert blocked["reasonCode"] == "OPERATIONAL_REPORT_MISSING", blocked
        state = load_status(root)
        assert state["executions"][0]["current"]["status"] == "running", state

        # Writer создаёт report даже с real drift: это не ошибка schema.
        written = write_operational_report(
            root, "audit", audit_payload(), execution_id=execution_id,
        )
        assert written["status"] == "PASS", written
        evidence = root / written["report"]
        state = load_status(root)
        active = next(e for e in state["executions"] if e["executionId"] == execution_id)
        assert operational_completion_blocker(root, active, "PROJECT RECONCILE") is None
        assert "Material drift:" in evidence.read_text(encoding="utf-8")

        # Путь отчёта, содержание, provenance и исходники защищены отдельно.
        def failure(override: dict, expected: str) -> None:
            copy = deepcopy(active)
            copy["current"]["context"]["operationalReport"].update(override)
            result = operational_completion_blocker(root, copy, "PROJECT RECONCILE")
            assert result is not None and result["reasonCode"] == expected, result

        failure({"executionId": "exec-other"}, "OPERATIONAL_REPORT_IDENTITY_MISMATCH")
        failure({"kind": "release_check"}, "OPERATIONAL_REPORT_IDENTITY_MISMATCH")
        failure({"path": "planning/releases/RELEASE-20000101T000000Z.md"},
                "OPERATIONAL_REPORT_PATH_INVALID")
        failure({"sha256": "0" * 64}, "OPERATIONAL_REPORT_CHANGED")

        original = evidence.read_bytes()
        evidence.write_bytes(original.replace(b"Material drift:", b"Falsified drift:"))
        changed = operational_completion_blocker(root, active, "PROJECT RECONCILE")
        assert changed["reasonCode"] == "OPERATIONAL_REPORT_CHANGED", changed
        evidence.write_bytes(original)

        product = root / "src" / "changed.ts"
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text("export const changed = true;\n", encoding="utf-8")
        stale = operational_completion_blocker(root, active, "PROJECT RECONCILE")
        assert stale["reasonCode"] == "OPERATIONAL_REPORT_CONTEXT_STALE", stale
        product.unlink()

        # Гарантированно свежий report можно завершить штатно.
        assert operational_completion_blocker(root, active, "PROJECT RECONCILE") is None
        done = complete_dispatch(
            root, "PROJECT RECONCILE", "PROJECT RECONCILE", "SUCCESS",
            execution_id=execution_id,
        )
        assert done["status"] == "DONE", done
        assert load_status(root)["recentTerminals"][-1]["current"]["result"] == "SUCCESS"

        # Нельзя подставить чужой старый PASS вместо нового report.
        later = start_execution(root, "PROJECT RECONCILE")
        fresh_blocked = complete_dispatch(
            root, "PROJECT RECONCILE", "PROJECT RECONCILE", "PASS",
            execution_id=later["executionId"],
        )
        assert fresh_blocked["status"] == "BLOCKED", fresh_blocked
        assert fresh_blocked["reasonCode"] == "OPERATIONAL_REPORT_MISSING", fresh_blocked

    print("operational-completion-self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
