#!/usr/bin/env python3
"""Восстановить точные trees измерения #363; --run повторяет три пары."""
from pathlib import Path
import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    artifacts = Path(__file__).resolve().parent
    metadata = json.loads((artifacts / "metadata.json").read_text(encoding="utf-8"))
    patch = json.loads((artifacts / "snapshot-diff.json").read_text(encoding="utf-8"))["patch"]
    with tempfile.TemporaryDirectory(prefix="hardening-363-reproduce-") as temporary:
        root = Path(temporary)
        baseline = root / "baseline"
        baseline.mkdir()
        archive = git(Path.cwd(), "archive", metadata["sourceRevision"])
        # Архив — конкретный tracked Git snapshot этого upstream, а не внешний
        # пользовательский tar. Рабочее дерево исходного репозитория не меняется.
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(baseline, filter="data")
        payload = metadata["productPayload"]
        for number in range(payload["files"]):
            path = baseline / "apps/fixture" / f"file-{number:04}.ts"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"// fixture\n" + b"x" * (payload["bytesPerFile"] - 12) + b"\n")
        candidate = root / "candidate"
        shutil.copytree(baseline, candidate)
        for arm in (baseline, candidate):
            git(arm, "init", "-q")
            git(arm, "config", "user.email", "benchmark@example.invalid")
            git(arm, "config", "user.name", "Harness Benchmark")
            git(arm, "add", ".")
        subprocess.run(["git", "apply", "--binary", "-"], cwd=candidate, input=patch, text=True, check=True)
        git(candidate, "add", ".")
        for arm in (baseline, candidate):
            tree = git(arm, "write-tree").decode().strip()
            assert tree == metadata["fixtureTrees"][arm.name], (arm.name, tree)
            git(arm, "commit", "-qm", "Восстановленный снимок измерения")
        print("Измеренные Git trees восстановлены: PASS", flush=True)
        if args.run:
            wrapper = root / "measure363.py"
            shutil.copyfile(artifacts / "measure.py.txt", wrapper)
            for number in range(1, 4):
                for arm in (baseline, candidate):
                    done = subprocess.run([sys.executable, str(wrapper), "."], cwd=arm, check=True, capture_output=True, text=True, timeout=300)
                    print(arm.name, number, done.stdout.splitlines()[-1], flush=True)


if __name__ == "__main__":
    main()
