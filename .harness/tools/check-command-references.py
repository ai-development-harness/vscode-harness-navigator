#!/usr/bin/env python3
"""Публичный read-only checker устаревших Harness command references.

Checker сканирует только live project documentation, вычисленную через manifest.
Он ничего не переписывает и не решает, является ли match фактической ошибкой:
DRIFT — наблюдение для PROJECT RECONCILE/аудита.

Exit codes:
- 0 — scan выполнен, как для PASS, так и для DRIFT;
- 2 — BLOCKED: scope нельзя безопасно прочитать или разрешить.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from command_references import project_live_document_paths, scan_files


# ---------------------------------------------------------------------------
# Bootstrap repository root.
# Git root предпочтителен, потому что findings должны быть repository-relative.
# Fallback относительно tool нужен только для ограниченного окружения без Git.
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    here = Path(__file__).resolve()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=here.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        proc = None
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return here.parents[2]


# ---------------------------------------------------------------------------
# CLI flow:
# - разрешить live-document scope;
# - просканировать UTF-8 files;
# - вывести PASS/DRIFT/BLOCKED;
# - не превращать DRIFT в tool failure.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect deprecated pre-namespace Harness commands in live project documents."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    root = repo_root()

    # Ошибка чтения хотя бы одного live document делает результат неполным.
    # Fail-closed: unreadable file даёт BLOCKED, а не тихо исключается из scope.
    try:
        findings = scan_files(root, project_live_document_paths(root))
    except RuntimeError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "scope": "live-project-documents",
                        "error": str(exc),
                        "findings": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"COMMAND REFERENCE CHECK: BLOCKED — {exc}")
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "status": "PASS" if not findings else "DRIFT",
                    "scope": "live-project-documents",
                    "findings": [
                        {
                            "path": item.path,
                            "line": item.line,
                            "legacy": item.legacy,
                            "canonical": item.canonical,
                            "excerpt": item.excerpt,
                        }
                        for item in findings
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif findings:
        print("COMMAND REFERENCE CHECK: DRIFT")
        for item in findings:
            print(
                f"  - {item.path}:{item.line}: "
                f"{item.legacy} -> {item.canonical} | {item.excerpt}"
            )
    else:
        print("COMMAND REFERENCE CHECK: PASS")

    # DRIFT — валидный audit result для PROJECT RECONCILE, а не tool failure.
    # Ненулевой код зарезервирован для BLOCKED/ошибки выполнения checker.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
