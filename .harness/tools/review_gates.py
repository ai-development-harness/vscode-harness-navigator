#!/usr/bin/env python3
"""Deterministic preselector обязательных specialized reviewers.

Tool не выполняет semantic review. Он только вычисляет, нужны ли `security`
и/или `tests` reviewers для конкретного STEP на основании machine-readable
facts: manifest policy, STEP type/risk flags и factual Git changed surface.

Результат содержит stable `basis`, чтобы persisted review metadata можно было
сопоставить с теми же exact inputs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import stable_hash
from harness_config import review_directory, review_policy
from planning_contract import read_task


SECURITY_FLAGS = {
    "security-sensitive",
    "data-migration",
    "destructive",
    "public-api",
    "external-integration",
}
TEST_TYPES = {"implementation", "bugfix", "refactor", "hardening"}
SECURITY_PATH_RE = re.compile(
    r"(?i)(auth|security|crypto|permission|session|token|secret|migration|iam|oauth)"
)
TEST_SURFACE_RE = re.compile(
    r"(?i)(\.(py|ts|tsx|js|jsx|go|rs|java|kt|cs|rb|php)$|(^|/)(src|lib|app|tests?|spec)(/|$))"
)


# ---------------------------------------------------------------------------
# Changed-surface collector.
# При dirty tree объединяет staged + unstaged + untracked paths.
# При clean tree использует последний commit только как diagnostic fallback и
# помечает surfaceMode=clean-tree-fallback, потому что exact STEP diff потерян.
# ---------------------------------------------------------------------------
def _git_paths_z(root: Path, *args: str) -> list[str]:
    """Прочитать Git path list без quoting/line splitting.

    Git path может содержать Unicode, пробелы, tab и даже newline. Поэтому
    line-oriented stdout (`splitlines()`/`strip()`) не является корректным
    transport. Все callers обязаны запрашивать `-z`, а здесь stdout остаётся
    bytes до NUL-splitting. `core.quotepath=false` — defense-in-depth для
    читаемого/raw path output; `-z` остаётся основным framing contract.

    Invalid UTF-8 path fail-closed через UnicodeDecodeError: Harness не должен
    классифицировать и fingerprint-ить путь, который не может однозначно
    представить в своём UTF-8 document/JSON contract.
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [
        item.decode("utf-8")
        for item in proc.stdout.split(b"\0")
        if item
    ]


def _git_changed_paths(root: Path) -> tuple[list[str], str]:
    paths: set[str] = set()
    for args in (
        ("diff", "--name-only", "-z", "HEAD", "--"),
        ("diff", "--cached", "--name-only", "-z", "--"),
    ):
        try:
            paths.update(_git_paths_z(root, *args))
        except OSError:
            continue

    try:
        paths.update(
            _git_paths_z(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
            )
        )
    except OSError:
        pass

    # STEP REVIEW обычно идёт до Git publication. Если worktree clean, exact
    # implementation baseline уже не доказуем из одного HEAD: последний commit
    # — только diagnostic fallback, а не полный STEP surface.
    surface_mode = "worktree"
    if not paths:
        surface_mode = "clean-tree-fallback"
        try:
            paths.update(
                _git_paths_z(
                    root,
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    "-z",
                    "HEAD",
                    "--",
                )
            )
        except OSError:
            pass

    try:
        review_root = review_directory(root).relative_to(root.resolve()).as_posix().rstrip("/")
    except ValueError:
        # Config layer уже должен запрещать escape. Если invariant нарушен,
        # ничего не скрываем из factual changed surface.
        review_root = "__invalid_review_root__"

    def included(rel: str) -> bool:
        normalized = rel.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if (
            not normalized
            or normalized.startswith("/")
            or any(part == ".." for part in normalized.split("/"))
        ):
            # Неожиданный Git path нельзя безопасно классифицировать как ignored.
            return True

        # Git path identity лексическая. Symlink из product path в .harness/local
        # остаётся product change и не должен исчезать из review surface.
        if normalized == ".harness/local" or normalized.startswith(".harness/local/"):
            return False

        # Configurable reviewDirectory не является blanket ignore-root.
        # Исключаем только lexical report-shaped artifacts, не symlink targets.
        if normalized == review_root:
            review_rel = ""
        elif normalized.startswith(review_root + "/"):
            review_rel = normalized[len(review_root) + 1 :]
        else:
            return True
        return re.fullmatch(r"STEP-\d{3,}/REVIEW-.+\.md", review_rel) is None

    return sorted(path for path in paths if included(path)), surface_mode


# ---------------------------------------------------------------------------
# Главный gate.
# Порядок решения:
# 1. прочитать canonical STEP;
# 2. собрать factual changed surface;
# 3. применить manifest policy;
# 4. добавить requirements из risk flags/type/path heuristics;
# 5. fingerprint-нуть входы в stable basis.
# ---------------------------------------------------------------------------
def required_reviewers(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    flags = set(meta.get("risk_flags", [])) if isinstance(meta.get("risk_flags"), list) else set()
    step_type = meta.get("type")
    paths, surface_mode = _git_changed_paths(root)

    required: set[str] = set()
    reasons: dict[str, list[str]] = {"security": [], "tests": []}
    security_policy = review_policy(root, "security")
    tests_policy = review_policy(root, "tests")

    # Чистый post-commit review — исключительный путь вне canonical
    # REVIEW-before-GIT workflow. Без durable implementation baseline нельзя
    # доказать, что последний commit содержит весь STEP diff, поэтому auto
    # policy fail-closed требует обе specialized проверки.
    if surface_mode == "clean-tree-fallback":
        required.update({"security", "tests"})
        reasons["security"].append("clean tree has no exact implementation baseline")
        reasons["tests"].append("clean tree has no exact implementation baseline")

    if security_policy == "always":
        required.add("security")
        reasons["security"].append("manifest review.security=always")
    else:
        matched_flags = sorted(flags.intersection(SECURITY_FLAGS))
        if matched_flags:
            required.add("security")
            reasons["security"].append("risk_flags=" + ",".join(matched_flags))
        sensitive_paths = [path for path in paths if SECURITY_PATH_RE.search(path)]
        if sensitive_paths:
            required.add("security")
            reasons["security"].append("security-relevant changed paths")

    if tests_policy == "always":
        required.add("tests")
        reasons["tests"].append("manifest review.tests=always")
    else:
        if step_type in TEST_TYPES:
            required.add("tests")
            reasons["tests"].append(f"step type={step_type}")
        if any(TEST_SURFACE_RE.search(path) for path in paths):
            required.add("tests")
            reasons["tests"].append("code/test surface changed")

    basis_payload = {
        "schema": 1,
        "stepId": step_id,
        "stepType": step_type,
        "riskFlags": sorted(flags),
        "securityPolicy": security_policy,
        "testsPolicy": tests_policy,
        "changedPaths": paths,
        "surfaceMode": surface_mode,
    }
    return {
        "stepId": step_id,
        "required": sorted(required),
        "reasons": reasons,
        "changedPaths": paths,
        "surfaceMode": surface_mode,
        "basis": stable_hash(basis_payload),
    }


# ---------------------------------------------------------------------------
# CLI только отображает deterministic decision; mutations отсутствуют.
# Text mode удобен человеку, --json — review orchestration/persistence.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step_id")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = required_reviewers(root, args.step_id)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(", ".join(result["required"]) or "none")
        for kind in ("security", "tests"):
            if result["reasons"][kind]:
                print(f"{kind}: " + "; ".join(result["reasons"][kind]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
