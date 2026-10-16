#!/usr/bin/env python3
"""#339: полный набор, три независимых job и отказ при неполном результате."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import windows_ci as ci

TOOLS = Path(__file__).resolve().parent

def invoke(root: Path, *args: str, expected: int = 0, needs: str = "null") -> str:
    result = subprocess.run([sys.executable, str(root / ".harness/tools/windows-ci.py"), *args], cwd=root,
                            capture_output=True, text=True, timeout=20, env=dict(os.environ, WINDOWS_NEEDS_JSON=needs))
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result.stdout

def main() -> int:
    expected = {"local-cleanup", "harness-config", "document-contract", "execution", "step-next", "verification",
                "reliable-orchestration-fault", "portable-handoff", "portable-resume",
                "portable-resume-matrix", "operational-reports", "operational-completion",
                "operational-integration", "update-engine"}
    names = [name for group in ci.GROUPS.values() for name in group]
    assert set(names) == expected and len(names) == len(expected) == 14
    ci.validate_groups()
    good = {"windows-" + name: {"result": "success"} for name in ci.GROUPS}
    assert ci.finalize(good)
    for group in good:
        for status in ("failure", "cancelled", "skipped", "pending", None):
            assert not ci.finalize({**good, group: {"result": status}})
        assert not ci.finalize({key: value for key, value in good.items() if key != group})
    for invalid in (None, [], {}, {**good, "extra": {"result": "success"}}):
        assert not ci.finalize(invalid)
    # Сверяем реальные workflow boundaries, а не только словарь Python.
    root = TOOLS.parents[1]
    workflow = (root / ".github/workflows/harness-integrity.yml").read_text()
    reusable = (root / ".github/workflows/harness-windows-group.yml").read_text()
    for group in ci.GROUPS:
        job = re.search(rf"(?ms)^  windows-{group}:\n(.*?)(?=^  [a-z][\w-]*:|\Z)", workflow)[1]
        assert "uses: ./.github/workflows/harness-windows-group.yml" in job
        assert f"group: {group}" in job
        assert not re.search(r"(?m)^    (needs|if|continue-on-error):", job)
    final = re.search(r"(?ms)^  validate-windows-boundaries:\n(.*?)(?=^  [a-z][\w-]*:|\Z)", workflow)[1]
    assert "name: Validate Windows boundaries" in final
    assert "if: ${{ always() }}" in final
    assert "needs: [windows-update, windows-resume, windows-execution]" in final
    assert "WINDOWS_NEEDS_JSON: ${{ toJSON(needs) }}" in final
    assert "windows-ci.py finalize" in final
    assert "continue-on-error:" not in final + reusable
    assert "runs-on: windows-2025" in reusable and "timeout-minutes: 15" in reusable
    assert "windows-ci.py run --group $env:GROUP" in reusable and "exit $LASTEXITCODE" in reusable
    with tempfile.TemporaryDirectory(prefix="harness-windows-ci-") as directory:
        fixture = Path(directory)
        tools = fixture / ".harness/tools"
        tools.mkdir(parents=True)
        for name in ("windows_ci.py", "windows-ci.py", "run-self-tests.py"):
            shutil.copy2(TOOLS / name, tools / name)
        for name in names:
            (tools / (name + "-self-test.py")).write_text("print('fixture PASS')\n")
        for group in ci.GROUPS:
            report = json.loads(invoke(fixture, "run", "--group", group).splitlines()[-1])
            assert report["status"] == "PASS"
            assert [r["test"] for r in report["results"]] == [n + "-self-test.py" for n in ci.GROUPS[group]]
            assert all(r["durationMs"] >= 0 and r["exitCode"] == 0 for r in report["results"])
        failed = tools / "harness-config-self-test.py"
        failed.write_text("raise SystemExit(7)\n")
        report = json.loads(invoke(fixture, "run", "--group", "update", expected=1).splitlines()[-1])
        assert report["results"][0]["exitCode"] == 7 and report["results"][-1]["status"] == "PASS"
        failed.write_text("import time\ntime.sleep(5)\n")
        report = json.loads(invoke(fixture, "run", "--group", "update", "--timeout-seconds", "0.5", expected=1).splitlines()[-1])
        assert report["results"][0]["status"] == "TIMEOUT"
        failed.unlink()
        invoke(fixture, "run", "--group", "update", expected=1)
        invoke(fixture, "finalize", needs=json.dumps(good))
        for invalid in ("{}", "null", "invalid json"):
            invoke(fixture, "finalize", needs=invalid, expected=1)
    print("WINDOWS CI SELF-TEST: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
