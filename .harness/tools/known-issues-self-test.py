#!/usr/bin/env python3
"""Known-issue regressions для ещё не исправленных defects.

Каждый known case описывает **правильное** поведение и сейчас обязан падать
ровно известным symptom-ом (XFAIL). Если case начинает проходить (XPASS),
self-test падает: defect исправлен, и case нужно перенести в постоянный
regression suite, удалив его из KNOWN_ISSUES. Любой другой исход (сломанный
fixture, новый symptom) является обычным FAIL.

Update engine defects #98–#101 закрыты и покрыты `update-engine-self-test.py`;
bridge-ограничения для проектов на v0.8.0 проверяет
`update-migration-self-test.py`.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable


SOURCE_ROOT = Path(__file__).resolve().parents[2]


class KnownFailure(Exception):
    """Наблюдаемый symptom совпал с known defect."""


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def git_init(root: Path) -> None:
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "known-issues@example.invalid")
    run(root, "git", "config", "user.name", "Known Issues")


def commit_all(root: Path, message: str) -> None:
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", message)


# --- Real template copy -------------------------------------------------------

def copy_tracked(target: Path) -> None:
    raw = run(SOURCE_ROOT, "git", "ls-files", "-z").stdout
    for rel in raw.split("\0"):
        if not rel:
            continue
        source = SOURCE_ROOT / rel
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def case_setext_heading_merge_marker(tmp: Path) -> None:
    """#110: Markdown setext heading не является merge-conflict marker."""
    copy_tracked(tmp)
    git_init(tmp)
    write(tmp, "docs/setext.md", "Title\n=======\n\ntext\n")
    commit_all(tmp, "baseline with setext heading")
    proc = run(tmp, "python3", ".harness/tools/validate.py", "--mode", "manual", check=False)
    if proc.returncode == 0:
        return
    if "merge-conflict marker detected: docs/setext.md" in proc.stdout:
        raise KnownFailure("setext heading reported as merge-conflict marker")
    raise AssertionError(proc.stdout + proc.stderr)


KNOWN_ISSUES: list[tuple[int, str, Callable[[Path], None]]] = [
    (110, "setext heading reported as merge marker", case_setext_heading_merge_marker),
]



def main() -> int:
    failed = False
    for number, title, case in KNOWN_ISSUES:
        label = f"#{number} {title}"
        with tempfile.TemporaryDirectory(prefix=f"harness-known-{number}-") as tmp:
            try:
                case(Path(tmp))
            except KnownFailure as exc:
                print(f"XFAIL {label}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - любой другой исход = broken case
                failed = True
                print(f"FAIL {label}: unexpected outcome: {type(exc).__name__}: {exc}")
                continue
        failed = True
        print(
            f"XPASS {label}: defect no longer reproduces; move the case to a permanent "
            "regression suite and remove it and its release freeze from known-issues-self-test.py"
        )

    print(f"KNOWN ISSUES SELF-TEST: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
