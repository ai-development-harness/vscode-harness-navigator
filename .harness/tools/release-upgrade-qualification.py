#!/usr/bin/env python3
"""Qualification initialized downstream upgrade against an exact Harness candidate.

The caller supplies already-authenticated local checkouts. This tool performs all
mutations only inside disposable clones and never needs network credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Sequence


SCHEMA_VERSION = 1
MAX_RELOAD_REPEATS = 12
DEFAULT_PROTECTED_PATHS = (
    "planning/reviews/TEMPLATE.md",
    "docs/canary-state.md",
    "docs/canary-baseline.md",
    "docs/canary-qualification.md",
)


class QualificationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _git(root: Path, *args: str, expect: int = 0) -> str:
    proc = _run(["git", *args], cwd=root)
    if proc.returncode != expect:
        raise QualificationError(
            "GIT_ERROR",
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )
    return proc.stdout.strip()


def _resolve_commit(root: Path, revision: str) -> str:
    value = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not value:
        raise QualificationError("REVISION_MISSING", f"cannot resolve {revision}")
    return value


def _status(root: Path) -> str:
    return _git(root, "status", "--porcelain=v1", "--untracked-files=all")


def _require_clean_exact(root: Path, revision: str, *, label: str) -> str:
    actual = _resolve_commit(root, "HEAD")
    expected = _resolve_commit(root, revision)
    if actual != expected:
        raise QualificationError(
            "REVISION_MISMATCH",
            f"{label} HEAD {actual} != expected {expected}",
        )
    dirty = _status(root)
    if dirty:
        raise QualificationError("CHECKOUT_NOT_CLEAN", f"{label} checkout is dirty")
    return actual


def _git_show(root: Path, revision: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise QualificationError(
            "CANDIDATE_METADATA_MISSING",
            proc.stderr.decode("utf-8", errors="replace").strip()
            or f"cannot read {path} from {revision}",
        )
    return proc.stdout


def _candidate_identity(source: Path, candidate_sha: str) -> tuple[str, str, str]:
    exact_sha = _resolve_commit(source, candidate_sha)
    try:
        lock = json.loads(
            _git_show(source, exact_sha, ".harness/harness.lock.json").decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("CANDIDATE_METADATA_INVALID", str(exc)) from exc
    source_meta = lock.get("source")
    release = lock.get("release")
    if not isinstance(source_meta, dict) or not isinstance(release, str):
        raise QualificationError(
            "CANDIDATE_METADATA_INVALID",
            "candidate lock must contain release and source",
        )
    tag = source_meta.get("ref")
    if not isinstance(tag, str) or tag != f"v{release}":
        raise QualificationError(
            "CANDIDATE_METADATA_INVALID",
            "candidate lock source.ref must match release",
        )
    graph_raw = _git_show(
        source,
        exact_sha,
        ".harness/harness-update-graph.json",
    )
    try:
        graph = json.loads(graph_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("CANDIDATE_GRAPH_INVALID", str(exc)) from exc
    if graph.get("latest") != tag:
        raise QualificationError(
            "CANDIDATE_NOT_RELEASE_PREPARED",
            f"candidate graph latest {graph.get('latest')!r} != {tag!r}",
        )

    policy_raw = _git_show(
        source,
        exact_sha,
        ".harness/harness-update.toml",
    )
    try:
        policy = tomllib.loads(policy_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise QualificationError("CANDIDATE_POLICY_INVALID", str(exc)) from exc
    source_policy = policy.get("source")
    default_branch = (
        source_policy.get("default_branch")
        if isinstance(source_policy, dict)
        else None
    )
    if not isinstance(default_branch, str) or not default_branch.strip():
        raise QualificationError(
            "CANDIDATE_POLICY_INVALID",
            "candidate source.default_branch must be non-empty string",
        )
    default_branch = default_branch.strip()
    return exact_sha, tag, default_branch


def _baseline_tag(project: Path) -> str:
    path = project / ".harness" / "harness.lock.json"
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("BASELINE_LOCK_INVALID", str(exc)) from exc
    source = lock.get("source")
    ref = source.get("ref") if isinstance(source, dict) else None
    if not isinstance(ref, str) or not ref.startswith("v"):
        raise QualificationError("BASELINE_LOCK_INVALID", "baseline source.ref missing")
    return ref


def _prepare_mirror(
    candidate_source: Path,
    candidate_sha: str,
    candidate_tag: str,
    baseline_tag: str,
    default_branch: str,
    target: Path,
) -> None:
    proc = _run(
        ["git", "clone", "--quiet", "--mirror", "--no-local", str(candidate_source), str(target)],
        cwd=candidate_source,
    )
    if proc.returncode != 0:
        raise QualificationError(
            "SOURCE_MIRROR_FAILED",
            proc.stderr.strip() or "cannot create candidate mirror",
        )
    branch_ref = f"refs/heads/{default_branch}"
    remote_branch_ref = f"refs/remotes/origin/{default_branch}"
    check_ref = _run(
        ["git", "check-ref-format", branch_ref],
        cwd=target,
    )
    if check_ref.returncode != 0:
        raise QualificationError(
            "CANDIDATE_POLICY_INVALID",
            f"invalid source.default_branch: {default_branch!r}",
        )

    # git clone --mirror сохраняет refs/remotes/origin/* source checkout.
    # Updater resolve_branch() предпочитает remote-tracking ref локальному
    # refs/heads/*, поэтому оба candidate-routing refs обязаны быть exact SHA.
    _git(target, "update-ref", branch_ref, candidate_sha)
    _git(target, "update-ref", remote_branch_ref, candidate_sha)
    for ref in (remote_branch_ref, branch_ref):
        observed = _resolve_commit(target, ref)
        if observed != candidate_sha:
            raise QualificationError(
                "SOURCE_MIRROR_FAILED",
                f"candidate routing ref {ref} resolved to {observed}, expected {candidate_sha}",
            )

    try:
        existing = _resolve_commit(target, f"refs/tags/{candidate_tag}")
    except QualificationError:
        existing = None
    if existing is not None and existing != candidate_sha:
        raise QualificationError(
            "CANDIDATE_TAG_COLLISION",
            f"{candidate_tag} already points to {existing}, expected {candidate_sha}",
        )
    if existing is None:
        _git(target, "update-ref", f"refs/tags/{candidate_tag}", candidate_sha)
    _resolve_commit(target, f"refs/tags/{baseline_tag}")


def _clone_baseline(project: Path, baseline_sha: str, target: Path) -> None:
    proc = _run(
        ["git", "clone", "--quiet", "--no-local", str(project), str(target)],
        cwd=project,
    )
    if proc.returncode != 0:
        raise QualificationError(
            "BASELINE_CLONE_FAILED",
            proc.stderr.strip() or "cannot clone baseline project",
        )
    _git(target, "checkout", "--quiet", "--detach", baseline_sha)
    _git(target, "config", "gc.auto", "0")
    _git(target, "config", "maintenance.auto", "false")


def _capture_protected(root: Path) -> dict[str, str]:
    paths: set[str] = set()
    for prefix in ("docs/adr", "planning/init-reviews"):
        base = root / prefix
        if base.is_dir():
            paths.update(
                item.relative_to(root).as_posix()
                for item in base.rglob("*")
                if item.is_file()
            )
    for rel in DEFAULT_PROTECTED_PATHS:
        if (root / rel).is_file():
            paths.add(rel)
    return {
        rel: _sha256_bytes((root / rel).read_bytes())
        for rel in sorted(paths)
    }


def _stage(
    stage_id: str,
    command: Sequence[str],
    *,
    cwd: Path,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    proc = _run(command, cwd=cwd)
    item: dict[str, object] = {
        "id": stage_id,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exitCode": proc.returncode,
        "stdoutSha256": _sha256_text(proc.stdout),
        "stderrSha256": _sha256_text(proc.stderr),
        "stdoutBytes": len(proc.stdout.encode("utf-8")),
        "stderrBytes": len(proc.stderr.encode("utf-8")),
    }
    return proc, item


def _json_result(proc: subprocess.CompletedProcess[str], stage: str) -> dict[str, object]:
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise QualificationError(
            "INVALID_STAGE_RESULT",
            f"{stage} did not return JSON: stdout={proc.stdout[:200]!r} "
            f"stderr={proc.stderr[:400]!r}",
        ) from exc
    if not isinstance(value, dict):
        raise QualificationError("INVALID_STAGE_RESULT", f"{stage} JSON must be object")
    return value


def _apply_until_settled(
    root: Path,
    *,
    candidate_tag: str,
    mirror: Path,
    stages: list[dict[str, object]],
) -> tuple[dict[str, object], bool]:
    """Довести updater до конечного статуса и подтвердить реальное продвижение.

    На последнем hop updater может сначала вернуть UPDATER_RELOAD_REQUIRED:
    обновление уже применено, но процесс нужно запустить заново. Поэтому
    последующий NO_UPDATE допустим, только если ранее подтверждён переход
    lock на новую версию и в итоге достигнут точный candidate_tag.
    """
    command = [
        sys.executable,
        ".harness/tools/harness-update.py",
        "apply",
        "--to",
        candidate_tag,
        "--source-url",
        str(mirror),
        "--json",
    ]
    previous_release = _baseline_tag(root)
    advanced = False
    for attempt in range(1, MAX_RELOAD_REPEATS + 1):
        proc, item = _stage(f"apply-{attempt}", command, cwd=root)
        result = _json_result(proc, f"apply-{attempt}")
        item["result"] = result.get("status")
        stages.append(item)
        if proc.returncode != 0:
            raise QualificationError(
                "UPDATE_FAILED",
                f"apply attempt {attempt}: {result.get('reasonCode') or result.get('status')}",
            )
        status = result.get("status")
        if status not in {"UPDATER_RELOAD_REQUIRED", "UPDATED", "NO_UPDATE"}:
            raise QualificationError("UNKNOWN_UPDATE_RESULT", f"unexpected updater status: {status}")

        installed_release = _baseline_tag(root)
        reported_release = result.get("current")
        if reported_release is not None and reported_release != installed_release:
            raise QualificationError(
                "UPDATE_STATE_MISMATCH",
                f"updater reported {reported_release!r}, lock contains {installed_release!r}",
            )

        if status == "UPDATER_RELOAD_REQUIRED":
            if installed_release == previous_release:
                raise QualificationError(
                    "RELOAD_DID_NOT_ADVANCE",
                    "reload requested without an applied release transition",
                )
            advanced = True
            previous_release = installed_release
            continue

        if status == "UPDATED":
            if installed_release == previous_release:
                raise QualificationError(
                    "UPDATE_DID_NOT_ADVANCE",
                    "UPDATED reported without advancing the installed release",
                )
            advanced = True

        if installed_release != candidate_tag:
            raise QualificationError(
                "TARGET_NOT_REACHED",
                f"installed release {installed_release!r} != candidate {candidate_tag!r}",
            )
        return result, advanced

    raise QualificationError(
        "RELOAD_LIMIT_EXCEEDED",
        f"more than {MAX_RELOAD_REPEATS} reload repeats",
    )

def _reconcile_schema(
    root: Path,
    *,
    stages: list[dict[str, object]],
) -> dict[str, object]:
    check_cmd = [
        sys.executable,
        ".harness/tools/migrate-project-schema.py",
        "--check",
        "--json",
    ]
    proc, item = _stage("schema-check-before", check_cmd, cwd=root)
    result = _json_result(proc, "schema-check-before")
    item["result"] = result.get("status")
    if proc.returncode not in {0, 1}:
        item["status"] = "FAIL"
        stages.append(item)
        raise QualificationError("SCHEMA_CHECK_FAILED", str(result))
    item["status"] = "PASS"
    stages.append(item)
    if result.get("status") != "MIGRATION_REQUIRED":
        return {"required": False, "result": result}

    migrate_cmd = [
        sys.executable,
        ".harness/tools/migrate-project-schema.py",
        "--json",
    ]
    migrate_proc, migrate_item = _stage("schema-reconcile", migrate_cmd, cwd=root)
    migrate_result = _json_result(migrate_proc, "schema-reconcile")
    migrate_item["result"] = migrate_result.get("status")
    stages.append(migrate_item)
    if migrate_proc.returncode != 0:
        raise QualificationError("SCHEMA_RECONCILE_FAILED", str(migrate_result))

    after_proc, after_item = _stage("schema-check-after", check_cmd, cwd=root)
    after_result = _json_result(after_proc, "schema-check-after")
    after_item["result"] = after_result.get("status")
    stages.append(after_item)
    if after_proc.returncode != 0 or after_result.get("status") != "CURRENT":
        raise QualificationError("SCHEMA_RECONCILE_INCOMPLETE", str(after_result))
    return {"required": True, "result": migrate_result}


def qualify(
    *,
    baseline_project: Path,
    baseline_sha: str,
    candidate_source: Path,
    candidate_sha: str,
) -> tuple[int, dict[str, object]]:
    stages: list[dict[str, object]] = []
    baseline_project = baseline_project.resolve()
    candidate_source = candidate_source.resolve()
    try:
        exact_baseline = _require_clean_exact(
            baseline_project, baseline_sha, label="baseline"
        )
        candidate_host_head = _resolve_commit(candidate_source, "HEAD")
        candidate_host_status = _status(candidate_source)
        if candidate_host_status:
            raise QualificationError("CHECKOUT_NOT_CLEAN", "candidate source checkout is dirty")
        exact_candidate, candidate_tag, default_branch = _candidate_identity(
            candidate_source,
            candidate_sha,
        )
        baseline_tag = _baseline_tag(baseline_project)
        protected_before = _capture_protected(baseline_project)

        with tempfile.TemporaryDirectory(prefix="harness-upgrade-qualification-") as td:
            temp = Path(td)
            mirror = temp / "source.git"
            work = temp / "project"
            _prepare_mirror(
                candidate_source,
                exact_candidate,
                candidate_tag,
                baseline_tag,
                default_branch,
                mirror,
            )
            _clone_baseline(baseline_project, exact_baseline, work)

            first, first_applied = _apply_until_settled(
                work,
                candidate_tag=candidate_tag,
                mirror=mirror,
                stages=stages,
            )
            if not first_applied:
                raise QualificationError(
                    "PRIMARY_UPGRADE_WAS_NOOP",
                    "previous stable -> candidate did not perform an update",
                )

            migration = _reconcile_schema(work, stages=stages)

            checks = [
                (
                    "status",
                    [sys.executable, ".harness/tools/harness-ux.py", "status", "--json"],
                ),
                (
                    "doctor",
                    [sys.executable, ".harness/tools/harness-ux.py", "doctor", "--json"],
                ),
                (
                    "validate",
                    [sys.executable, ".harness/tools/validate.py", "--mode", "manual"],
                ),
                (
                    "self-tests",
                    [sys.executable, ".harness/tools/run-self-tests.py"],
                ),
            ]
            for stage_id, command in checks:
                proc, item = _stage(stage_id, command, cwd=work)
                stages.append(item)
                if proc.returncode != 0:
                    raise QualificationError("POST_UPDATE_GATE_FAILED", stage_id)

            protected_after = _capture_protected(work)
            if protected_after != protected_before:
                changed = sorted(
                    set(protected_before)
                    | set(protected_after)
                )
                changed = [
                    path
                    for path in changed
                    if protected_before.get(path) != protected_after.get(path)
                ]
                raise QualificationError(
                    "PROJECT_OWNED_STATE_CHANGED",
                    ", ".join(changed),
                )
            stages.append(
                {
                    "id": "project-owned-preservation",
                    "status": "PASS",
                    "count": len(protected_before),
                }
            )

            repeat, repeated_apply = _apply_until_settled(
                work,
                candidate_tag=candidate_tag,
                mirror=mirror,
                stages=stages,
            )
            if repeated_apply or repeat.get("status") != "NO_UPDATE":
                raise QualificationError(
                    "REPEATED_APPLY_NOT_NO_UPDATE",
                    f"repeat status={repeat.get('status')}",
                )
            if repeat.get("repositoryMutated"):
                raise QualificationError(
                    "REPEATED_APPLY_MUTATED_PROJECT",
                    "NO_UPDATE reported repository mutation",
                )

        baseline_after = _require_clean_exact(
            baseline_project, exact_baseline, label="baseline"
        )
        candidate_after = _resolve_commit(candidate_source, "HEAD")
        if candidate_after != candidate_host_head or _status(candidate_source):
            raise QualificationError(
                "HOST_CHECKOUT_MUTATED",
                "candidate source checkout changed during qualification",
            )

        payload: dict[str, object] = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "harness_initialized_upgrade_qualification",
            "status": "PASS",
            "baselineRevision": baseline_after,
            "baselineRelease": baseline_tag,
            "candidateRevision": exact_candidate,
            "candidateRelease": candidate_tag,
            "migration": migration,
            "stages": stages,
        }
        return 0, payload
    except QualificationError as exc:
        return 1, {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "harness_initialized_upgrade_qualification",
            "status": "FAIL",
            "reasonCode": exc.code,
            "message": str(exc),
            "baselineRevision": baseline_sha,
            "candidateRevision": candidate_sha,
            "stages": stages,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify initialized downstream upgrade to an exact candidate SHA."
    )
    parser.add_argument("--baseline-project", required=True, type=Path)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate-source", required=True, type=Path)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    code, payload = qualify(
        baseline_project=args.baseline_project,
        baseline_sha=args.baseline_sha,
        candidate_source=args.candidate_source,
        candidate_sha=args.candidate_sha,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(
            f"HARNESS INITIALIZED UPGRADE QUALIFICATION: {payload['status']}"
        )
        if payload.get("reasonCode"):
            print(
                f"{payload['reasonCode']}: {payload.get('message', '')}",
                file=sys.stderr,
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
