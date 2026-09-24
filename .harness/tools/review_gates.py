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
#
# Canonical REVIEW может получить explicit durable implementation baseline из
# execution layer. Тогда surface = baseline..HEAD + current worktree. Без proof
# сохраняется legacy/diagnostic fallback, но он не выдаётся за exact STEP diff.
# ---------------------------------------------------------------------------
_AUTO_BASELINE = object()


def _git_paths_z(root: Path, *args: str) -> list[str]:
    """Прочитать Git path list без quoting/line splitting.

    Git path может содержать Unicode, пробелы, tab и даже newline. Поэтому
    line-oriented stdout (`splitlines()`/`strip()`) не является корректным
    transport. Все callers обязаны запрашивать `-z`, а здесь stdout остаётся
    bytes до NUL-splitting.
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


def _git_name_status_paths_z(root: Path, *args: str) -> list[str]:
    """Вернуть обе стороны rename/copy из Git --name-status -z.

    --name-only теряет source path rename/copy и может скрыть security/test
    surface при переносе sensitive файла в нейтральный destination. Parser
    fail-closed: malformed stream не интерпретируется как безопасно пустой diff.
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

    fields = [item for item in proc.stdout.split(b"\0") if item]
    paths: list[str] = []
    index = 0
    try:
        while index < len(fields):
            status = fields[index].decode("ascii", errors="strict")
            index += 1
            code = status[:1]
            if code in {"R", "C"}:
                source = fields[index].decode("utf-8")
                destination = fields[index + 1].decode("utf-8")
                index += 2
                paths.extend([source, destination])
            else:
                path = fields[index].decode("utf-8")
                index += 1
                paths.append(path)
    except (IndexError, UnicodeDecodeError):
        # Unexpected Git transport must not silently shrink review surface.
        raise ValueError("malformed git --name-status -z output")
    return paths


def _git_ok(root: Path, *args: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _included_path(root: Path, rel: str) -> bool:
    try:
        review_root = (
            review_directory(root)
            .relative_to(root.resolve())
            .as_posix()
            .rstrip("/")
        )
    except ValueError:
        review_root = "__invalid_review_root__"

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
    # Исключаем только report-shaped artifacts, не symlink targets.
    if normalized == review_root:
        review_rel = ""
    elif normalized.startswith(review_root + "/"):
        review_rel = normalized[len(review_root) + 1 :]
    else:
        return True
    return re.fullmatch(r"STEP-\d{3,}/REVIEW-.+\.md", review_rel) is None


def _worktree_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for args in (
        ("diff", "--name-status", "-z", "-M", "-C", "--find-copies-harder", "HEAD", "--"),
        ("diff", "--cached", "--name-status", "-z", "-M", "-C", "--find-copies-harder", "--"),
    ):
        try:
            paths.update(_git_name_status_paths_z(root, *args))
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
    return {path for path in paths if _included_path(root, path)}


def _diagnostic_last_commit_paths(root: Path) -> set[str]:
    try:
        paths = _git_paths_z(
            root,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            "HEAD",
            "--",
        )
    except OSError:
        return set()
    return {path for path in paths if _included_path(root, path)}


def _review_surface(
    root: Path,
    *,
    implementation_baseline: str | None | object = _AUTO_BASELINE,
) -> dict[str, Any]:
    worktree = _worktree_paths(root)

    # Legacy direct callers сохраняют прежнее поведение: dirty tree считается
    # worktree surface, clean tree использует последний commit diagnostic-only.
    if implementation_baseline is _AUTO_BASELINE:
        if worktree:
            paths = sorted(worktree)
            return {
                "changedPaths": paths,
                "surfaceMode": "worktree",
                "implementationBaseline": None,
                "baselineStatus": "legacy-auto",
                "baselineReason": None,
                "changedPathsHash": stable_hash({"paths": paths}),
            }
        paths = sorted(_diagnostic_last_commit_paths(root))
        return {
            "changedPaths": paths,
            "surfaceMode": "clean-tree-fallback",
            "implementationBaseline": None,
            "baselineStatus": "legacy-auto",
            "baselineReason": "clean tree has no exact implementation baseline",
            "changedPathsHash": stable_hash({"paths": paths}),
        }

    baseline = implementation_baseline if isinstance(implementation_baseline, str) else None
    reason: str | None = None
    if baseline is None:
        reason = "implementation baseline is missing"
    elif not _git_ok(root, "rev-parse", "--verify", f"{baseline}^{{commit}}"):
        reason = "implementation baseline commit is unavailable"
    elif not _git_ok(root, "rev-parse", "--verify", "HEAD^{commit}"):
        reason = "current HEAD commit is unavailable"
    elif not _git_ok(root, "merge-base", "--is-ancestor", baseline, "HEAD"):
        reason = "implementation baseline is not an ancestor of HEAD"

    if reason is None:
        committed = {
            path
            for path in _git_name_status_paths_z(
                root,
                "diff",
                "--name-status",
                "-z",
                "-M",
                "-C",
                "--find-copies-harder",
                f"{baseline}..HEAD",
                "--",
            )
            if _included_path(root, path)
        }
        paths = sorted(committed | worktree)
        return {
            "changedPaths": paths,
            "surfaceMode": "implementation-baseline",
            "implementationBaseline": baseline,
            "baselineStatus": "valid",
            "baselineReason": None,
            "changedPathsHash": stable_hash({"paths": paths}),
        }

    # Missing/invalid baseline нельзя заменять только текущим dirty diff:
    # committed часть STEP могла существовать раньше. Оставляем видимые
    # worktree paths + последний commit как diagnostics и требуем fail-closed
    # specialized review.
    paths = sorted(worktree | _diagnostic_last_commit_paths(root))
    return {
        "changedPaths": paths,
        "surfaceMode": "clean-tree-fallback",
        "implementationBaseline": baseline,
        "baselineStatus": "missing" if baseline is None else "invalid",
        "baselineReason": reason,
        "changedPathsHash": stable_hash({"paths": paths}),
    }


def _git_changed_paths(
    root: Path,
    *,
    implementation_baseline: str | None | object = _AUTO_BASELINE,
) -> tuple[list[str], str]:
    """Compatibility wrapper для existing tests/tooling."""
    surface = _review_surface(
        root,
        implementation_baseline=implementation_baseline,
    )
    return list(surface["changedPaths"]), str(surface["surfaceMode"])



# ---------------------------------------------------------------------------
# Главный gate.
# Порядок решения:
# 1. прочитать canonical STEP;
# 2. собрать factual changed surface;
# 3. применить manifest policy;
# 4. добавить requirements из risk flags/type/path heuristics;
# 5. fingerprint-нуть входы в stable basis.
# ---------------------------------------------------------------------------
def required_reviewers(
    root: Path,
    step_id: str,
    *,
    implementation_baseline: str | None | object = _AUTO_BASELINE,
) -> dict[str, Any]:
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    flags = set(meta.get("risk_flags", [])) if isinstance(meta.get("risk_flags"), list) else set()
    step_type = meta.get("type")
    surface = _review_surface(
        root,
        implementation_baseline=implementation_baseline,
    )
    paths = list(surface["changedPaths"])
    surface_mode = str(surface["surfaceMode"])

    required: set[str] = set()
    reasons: dict[str, list[str]] = {"security": [], "tests": []}
    security_policy = review_policy(root, "security")
    tests_policy = review_policy(root, "tests")

    # Fallback означает, что полный STEP surface не доказан. Не важно, clean
    # сейчас worktree или dirty: без валидного baseline committed часть могла
    # потеряться, поэтому policy остаётся fail-closed.
    if surface_mode == "clean-tree-fallback":
        required.update({"security", "tests"})
        fallback_reason = str(
            surface.get("baselineReason")
            or "exact implementation baseline is unavailable"
        )
        reasons["security"].append(fallback_reason)
        reasons["tests"].append(fallback_reason)

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
        "schema": 2,
        "stepId": step_id,
        "stepType": step_type,
        "riskFlags": sorted(flags),
        "securityPolicy": security_policy,
        "testsPolicy": tests_policy,
        "changedPaths": paths,
        "changedPathsHash": surface["changedPathsHash"],
        "surfaceMode": surface_mode,
        "implementationBaseline": surface["implementationBaseline"],
        "baselineStatus": surface["baselineStatus"],
        "baselineReason": surface["baselineReason"],
    }
    return {
        "stepId": step_id,
        "required": sorted(required),
        "reasons": reasons,
        "changedPaths": paths,
        "changedPathsHash": surface["changedPathsHash"],
        "surfaceMode": surface_mode,
        "implementationBaseline": surface["implementationBaseline"],
        "baselineStatus": surface["baselineStatus"],
        "baselineReason": surface["baselineReason"],
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
