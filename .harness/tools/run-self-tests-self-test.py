#!/usr/bin/env python3
"""Regression bounded execution discoverable self-test runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import time


TOOLS_DIR = Path(__file__).resolve().parent
RUNNER_PATH = TOOLS_DIR / "run-self-tests.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("harness_self_test_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load run-self-tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    runner = load_runner()
    with tempfile.TemporaryDirectory(prefix="harness-self-test-runner-") as tmp:
        root = Path(tmp)
        hanging = root / "hanging-self-test.py"
        marker = root / "grandchild-survived.txt"
        hanging.write_text(
            "import pathlib, subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', "
            f"\"import pathlib,time; time.sleep(0.5); pathlib.Path({str(marker)!r}).write_text('x')\"])\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        following = root / "following-self-test.py"
        following.write_text("print('FOLLOWING PASS')\n", encoding="utf-8")

        timed, _stdout, _stderr = runner.run_one(
            hanging,
            repo_root=root,
            timeout_seconds=0.1,
        )
        assert timed["status"] == "TIMEOUT", timed
        assert timed["exitCode"] is None, timed

        passed, stdout, stderr = runner.run_one(
            following,
            repo_root=root,
            timeout_seconds=2,
        )
        assert passed["status"] == "PASS", (passed, stdout, stderr)
        assert "FOLLOWING PASS" in stdout, stdout

        time.sleep(0.8)
        assert not marker.exists(), "timeout left a descendant process running"

    print("SELF-TEST RUNNER SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
