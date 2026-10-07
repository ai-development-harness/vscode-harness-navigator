#!/usr/bin/env python3
"""Regression tests for the canonical bounded stress-suite runner."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


RUNNER = Path(__file__).with_name("run-stress-tests.py")


def run(
    command: list[str],
    *,
    cwd: Path,
    expect: int,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"expected {expect}, got {proc.returncode}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return proc


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def invoke(root: Path, manifest: Path, iterations: int, *, expect: int) -> dict:
    proc = run(
        [
            sys.executable,
            str(root / ".harness/tools/run-stress-tests.py"),
            "--manifest",
            str(manifest),
            "--iterations",
            str(iterations),
            "--json",
        ],
        cwd=root,
        expect=expect,
    )
    return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-stress-runner-") as td:
        root = Path(td)
        tools = root / ".harness" / "tools"
        tools.mkdir(parents=True)
        shutil.copy2(RUNNER, tools / RUNNER.name)

        counter = root / "counter.txt"
        write(
            tools / "fixture-self-test.py",
            (
                "import argparse\n"
                "from pathlib import Path\n"
                "p=argparse.ArgumentParser(); p.add_argument('--iterations', type=int, required=True); a=p.parse_args()\n"
                f"Path({str(counter)!r}).write_text(str(a.iterations), encoding='utf-8')\n"
            ),
        )
        manifest = root / "stress.json"
        write(
            manifest,
            json.dumps({
                "schemaVersion": 1,
                "defaultIterations": 20,
                "scenarios": [{
                    "id": "fixture",
                    "description": "fixture",
                    "tool": "fixture-self-test.py",
                    "args": ["--iterations", "{iterations}"],
                    "timeoutSeconds": 30,
                }],
            }),
        )
        payload = invoke(root, manifest, 7, expect=0)
        assert payload["status"] == "PASS", payload
        assert payload["iterations"] == 7, payload
        assert payload["results"][0]["iterations"] == 7, payload
        assert counter.read_text(encoding="utf-8") == "7"

        write(
            tools / "fixture-self-test.py",
            "import sys\nprint('diagnostic-out')\nprint('diagnostic-err', file=sys.stderr)\nraise SystemExit(9)\n",
        )
        failed = invoke(root, manifest, 3, expect=1)
        assert failed["status"] == "FAIL", failed
        item = failed["results"][0]
        assert item["exitCode"] == 9, item
        assert "diagnostic-out" in item["stdoutTail"], item
        assert "diagnostic-err" in item["stderrTail"], item

        invalid = root / "invalid.json"
        write(
            invalid,
            json.dumps({
                "schemaVersion": 1,
                "defaultIterations": 20,
                "scenarios": [{
                    "id": "unsafe",
                    "tool": "../other.py",
                    "args": ["{iterations}"],
                    "timeoutSeconds": 30,
                }],
            }),
        )
        blocked = invoke(root, invalid, 2, expect=2)
        assert blocked["status"] == "BLOCKED", blocked

    print("stress suite runner self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
