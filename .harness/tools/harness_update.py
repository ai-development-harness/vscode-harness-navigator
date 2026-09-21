#!/usr/bin/env python3
"""Deterministic core безопасного self-update AI Development Harness.

Модуль не исполняет код из release-тегов. Источник читается как Git data:
update graph — из configured default branch, содержимое hop — только из immutable tags.
LLM/agent остаётся orchestration layer, но ownership, 3-way merge, collisions,
filesystem mutation и продвижение lock выполняются здесь детерминированно.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from typing import Any, Iterable

from document_contract import durable_report_timestamp
from harness_config import (
    ConfigError,
    get,
    load_manifest,
    load_update_policy,
    update_lock_path,
    update_report_directory,
)


MISSING = object()
UPDATE_POLICY_PATH = ".harness/harness-update.toml"
UPDATER_RUNTIME_PATHS = {
    ".harness/tools/harness_update.py",
    ".harness/tools/harness-update.py",
}
OWNERSHIP_CLASSES = ("harness_owned", "shared", "marker_merge")


class UpdateError(RuntimeError):
    """Fail-closed blocker deterministic update engine."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Hop:
    source: str
    target: str
    kind: str
    reload_required: bool
    reason: str | None = None


@dataclass
class PathPlan:
    path: str
    base_class: str | None
    target_class: str | None
    action: str
    content: bytes | None
    mode: int | None = None
    detail: str | None = None


@dataclass
class HopPlan:
    hop: Hop
    paths: list[PathPlan]
    introduced: list[str]
    retired: list[str]
    reclassified: list[str]
    reload_required: bool


class GitSource:
    """Read-only view Harness source repository without checkout/execution."""

    def __init__(self, location: str, *, owned_temp: tempfile.TemporaryDirectory[str] | None = None):
        self.location = location
        self._owned_temp = owned_temp

    @classmethod
    def open(cls, repository: str, *, source_url: str | None = None) -> "GitSource":
        if source_url:
            return cls(source_url)
        temp = tempfile.TemporaryDirectory(prefix="harness-update-source-")
        target = Path(temp.name) / "source.git"
        url = f"https://github.com/{repository}.git"
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(target)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode:
            shutil.rmtree(target, ignore_errors=True)
            proc = subprocess.run(
                ["git", "clone", "--quiet", "--no-checkout", url, str(target)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        if proc.returncode:
            temp.cleanup()
            raise UpdateError("SOURCE_UNAVAILABLE", f"cannot clone Harness source: {proc.stderr.strip()}")
        return cls(str(target), owned_temp=temp)

    def close(self) -> None:
        if self._owned_temp is not None:
            self._owned_temp.cleanup()
            self._owned_temp = None
    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        proc = subprocess.run(
            ["git", "-C", self.location, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and proc.returncode:
            message = proc.stderr.decode("utf-8", errors="replace").strip()
            raise UpdateError("SOURCE_GIT_ERROR", message or f"git {' '.join(args)} failed")
        return proc

    def resolve_ref(self, ref: str) -> str:
        if ref.startswith("refs/"):
            candidates = [ref]
        elif ref.startswith("origin/"):
            candidates = [f"refs/remotes/{ref}", ref]
        else:
            candidates = [f"refs/tags/{ref}", f"refs/remotes/origin/{ref}", ref]
        for candidate in candidates:
            proc = self._git("rev-parse", "--verify", f"{candidate}^{{commit}}", check=False)
            if proc.returncode == 0:
                return proc.stdout.decode("ascii", errors="strict").strip()
        raise UpdateError("SOURCE_REF_MISSING", f"source ref does not exist: {ref}")

    def resolve_tag(self, tag: str) -> str:
        proc = self._git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
        if proc.returncode != 0:
            raise UpdateError("SOURCE_TAG_MISSING", f"immutable release tag does not exist: {tag}")
        return proc.stdout.decode("ascii", errors="strict").strip()

    def list_entries(self, ref: str) -> dict[str, str]:
        oid = self.resolve_ref(ref)
        proc = self._git("ls-tree", "-r", "-z", oid)
        result: dict[str, str] = {}
        for raw in proc.stdout.split(b"\0"):
            if not raw:
                continue
            header, sep, raw_path = raw.partition(b"\t")
            parts = header.split()
            if not sep or len(parts) < 3:
                raise UpdateError("SOURCE_TREE_ERROR", f"cannot parse source tree entry for {ref}")
            mode = parts[0].decode("ascii", errors="strict")
            path = raw_path.decode("utf-8")
            result[path] = mode
        return result

    def list_files(self, ref: str) -> set[str]:
        return set(self.list_entries(ref))

    def read_bytes(self, ref: str, path: str) -> bytes | object:
        oid = self.resolve_ref(ref)
        proc = self._git("show", f"{oid}:{path}", check=False)
        if proc.returncode:
            return MISSING
        data = proc.stdout
        if b"\0" in data:
            raise UpdateError("BINARY_MANAGED_PATH", f"managed source path is binary: {ref}:{path}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateError("NON_UTF8_MANAGED_PATH", f"managed source path is not UTF-8: {ref}:{path}") from exc
        return data

    def read_text(self, ref: str, path: str) -> str:
        data = self.read_bytes(ref, path)
        if data is MISSING:
            raise UpdateError("SOURCE_PATH_MISSING", f"source path missing: {ref}:{path}")
        assert isinstance(data, bytes)
        return data.decode("utf-8")


class WorkingTree:
    """Git-aware local project state used by the update engine."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and proc.returncode:
            message = proc.stderr.decode("utf-8", errors="replace").strip()
            raise UpdateError("LOCAL_GIT_ERROR", message or f"git {' '.join(args)} failed")
        return proc

    def tracked(self) -> set[str]:
        proc = self.git("ls-files", "-z")
        return {item.decode("utf-8") for item in proc.stdout.split(b"\0") if item}

    def ignored(self, path: str) -> bool:
        proc = self.git("check-ignore", "-q", "--no-index", "--", path, check=False)
        return proc.returncode == 0

    def read_bytes(self, path: str) -> bytes | object:
        target = self.root / path
        if not target.exists() and not target.is_symlink():
            return MISSING
        if target.is_symlink() or not target.is_file():
            raise UpdateError("UNSAFE_LOCAL_PATH", f"managed path must be a regular file: {path}")
        data = target.read_bytes()
        if b"\0" in data:
            raise UpdateError("BINARY_MANAGED_PATH", f"managed local path is binary: {path}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateError("NON_UTF8_MANAGED_PATH", f"managed local path is not UTF-8: {path}") from exc
        return data

    def mode(self, path: str) -> int | None:
        target = self.root / path
        if not target.exists() or target.is_symlink() or not target.is_file():
            return None
        return 0o755 if target.stat().st_mode & 0o111 else 0o644

    def tracks_filemode(self) -> bool:
        """Учитывает ли текущий Git filesystem executable-bit как diff."""
        proc = self.git("config", "--bool", "core.filemode", check=False)
        if proc.returncode != 0:
            return True
        return proc.stdout.decode("ascii", errors="ignore").strip().lower() != "false"

    def write_bytes(self, path: str, content: bytes | None, *, mode: int | None = None) -> None:
        target = self.root / path
        if content is None:
            if target.exists() or target.is_symlink():
                target.unlink()
            _prune_empty_parents(target.parent, self.root)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            os.chmod(temp_name, mode if mode is not None else 0o644)
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def _prune_empty_parents(path: Path, root: Path) -> None:
    while path != root:
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _run_merge_file(ours: bytes, base: bytes, theirs: bytes, *, path: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="harness-3way-") as tmp:
        tmp_root = Path(tmp)
        ours_path = tmp_root / "ours"
        base_path = tmp_root / "base"
        theirs_path = tmp_root / "theirs"
        ours_path.write_bytes(ours)
        base_path.write_bytes(base)
        theirs_path.write_bytes(theirs)
        proc = subprocess.run(
            ["git", "merge-file", "-p", str(ours_path), str(base_path), str(theirs_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise UpdateError("MERGE_CONFLICT", f"3-way merge conflict: {path}")
        return proc.stdout


def _three_way(ours: bytes | object, base: bytes | object, theirs: bytes | object, *, path: str) -> bytes | None:
    if ours is MISSING and base is MISSING:
        return None if theirs is MISSING else _as_bytes(theirs)
    if theirs is MISSING and base is MISSING:
        return None if ours is MISSING else _as_bytes(ours)
    if base is MISSING:
        if ours is MISSING:
            return None if theirs is MISSING else _as_bytes(theirs)
        if theirs is MISSING:
            return _as_bytes(ours)
        if ours == theirs:
            return _as_bytes(ours)
        raise UpdateError("MANAGED_PATH_COLLISION", f"both project and target added managed path: {path}")
    if ours is MISSING:
        if theirs == base:
            return None
        raise UpdateError("MERGE_CONFLICT", f"project deleted path changed by target: {path}")
    if theirs is MISSING:
        if ours == base:
            return None
        raise UpdateError("MERGE_CONFLICT", f"target deleted locally changed path: {path}")
    if ours == base:
        return _as_bytes(theirs)
    if theirs == base or ours == theirs:
        return _as_bytes(ours)
    return _run_merge_file(_as_bytes(ours), _as_bytes(base), _as_bytes(theirs), path=path)


def _as_bytes(value: bytes | object) -> bytes:
    if not isinstance(value, bytes):
        raise AssertionError("expected bytes")
    return value


def _load_toml_text(text: str, *, label: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UpdateError("INVALID_UPDATE_POLICY", f"invalid {label}: {exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("INVALID_UPDATE_POLICY", f"{label} must be a TOML table")
    return data


def _ownership(policy: dict[str, Any]) -> dict[str, list[str]]:
    raw = policy.get("ownership")
    if not isinstance(raw, dict):
        raise UpdateError("INVALID_UPDATE_POLICY", "update policy missing [ownership]")
    unexpected = sorted(set(raw) - set(OWNERSHIP_CLASSES))
    if unexpected:
        raise UpdateError("INVALID_UPDATE_POLICY", "unsupported ownership classes: " + ", ".join(unexpected))
    result: dict[str, list[str]] = {}
    for key in OWNERSHIP_CLASSES:
        value = raw.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise UpdateError("INVALID_UPDATE_POLICY", f"ownership.{key} must be string list")
        for pattern in value:
            probe = Path(pattern)
            if probe.is_absolute() or ".." in probe.parts:
                raise UpdateError("INVALID_UPDATE_POLICY", f"unsafe ownership pattern: {pattern}")
        result[key] = list(value)
    return result


def _update_topology(policy: dict[str, Any]) -> dict[str, Any]:
    """Поля bootstrap/routing state не мигрируются неявно текущим engine."""
    return {
        "source.repository": get(policy, "source.repository"),
        "source.default_branch": get(policy, "source.default_branch"),
        "source.tag_pattern": get(policy, "source.tag_pattern"),
        "source.update_manifest": get(policy, "source.update_manifest"),
        "state.lock_file": get(policy, "state.lock_file"),
        "state.report_directory": get(policy, "state.report_directory"),
    }


def _markers(policy: dict[str, Any]) -> dict[str, list[str]]:
    raw = policy.get("markers", {})
    if not isinstance(raw, dict):
        raise UpdateError("INVALID_UPDATE_POLICY", "[markers] must be mapping")
    result: dict[str, list[str]] = {}
    for path, item in raw.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            raise UpdateError("INVALID_UPDATE_POLICY", "invalid marker mapping")
        blocks = item.get("blocks", [])
        if not isinstance(blocks, list) or not all(isinstance(block, str) and block for block in blocks):
            raise UpdateError("INVALID_UPDATE_POLICY", f"markers.{path}.blocks must be string list")
        result[path] = list(blocks)
    return result


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def _classify(path: str, ownership: dict[str, list[str]]) -> str | None:
    matches = [key for key in OWNERSHIP_CLASSES if any(_matches(path, pat) for pat in ownership[key])]
    if len(matches) > 1:
        raise UpdateError("OWNERSHIP_OVERLAP", f"managed path matches multiple ownership classes: {path}: {matches}")
    return matches[0] if matches else None


def _managed_paths(files: Iterable[str], ownership: dict[str, list[str]]) -> set[str]:
    return {path for path in files if _classify(path, ownership) is not None}


def _extract_marker(text: str, block: str) -> str:
    start = f"<!-- {block}:START -->"
    end = f"<!-- {block}:END -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise UpdateError("MARKER_DRIFT", f"marker block {block} missing/duplicated")
    left, rest = text.split(start, 1)
    body, right = rest.split(end, 1)
    if left is None or right is None:
        raise UpdateError("MARKER_DRIFT", f"marker block {block} invalid")
    return body


def _replace_marker(text: str, block: str, body: str) -> str:
    start = f"<!-- {block}:START -->"
    end = f"<!-- {block}:END -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise UpdateError("MARKER_DRIFT", f"target marker block {block} missing/duplicated")
    left, rest = text.split(start, 1)
    _, right = rest.split(end, 1)
    return left + start + body + end + right


def _preserve_markers(ours: bytes | object, theirs: bytes | object, *, path: str, blocks: list[str]) -> bytes | object:
    if ours is MISSING or theirs is MISSING or not blocks:
        return theirs
    ours_text = _as_bytes(ours).decode("utf-8")
    target_text = _as_bytes(theirs).decode("utf-8")
    for block in blocks:
        target_text = _replace_marker(target_text, block, _extract_marker(ours_text, block))
    return target_text.encode("utf-8")


def _semver(tag: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
    if match is None:
        raise UpdateError("INVALID_RELEASE_TAG", f"not a semantic release tag: {tag}")
    return tuple(int(part) for part in match.groups())


def _validate_graph(data: dict[str, Any], tag_pattern: str) -> tuple[str, dict[str, Hop]]:
    if data.get("schemaVersion") != 1:
        raise UpdateError("INVALID_UPDATE_GRAPH", "update graph schemaVersion must be 1")
    try:
        tag_re = re.compile(tag_pattern)
    except re.error as exc:
        raise UpdateError("INVALID_UPDATE_POLICY", f"invalid source.tag_pattern: {exc}") from exc
    latest = data.get("latest")
    if not isinstance(latest, str) or tag_re.fullmatch(latest) is None:
        raise UpdateError("INVALID_UPDATE_GRAPH", "graph latest does not match tag pattern")
    transitions = data.get("transitions")
    if not isinstance(transitions, list):
        raise UpdateError("INVALID_UPDATE_GRAPH", "graph transitions must be list")
    outgoing: dict[str, Hop] = {}
    for raw in transitions:
        if not isinstance(raw, dict):
            raise UpdateError("INVALID_UPDATE_GRAPH", "transition must be object")
        source = raw.get("from")
        target = raw.get("to")
        kind = raw.get("kind")
        reload_required = raw.get("reloadRequired")
        reason = raw.get("reason")
        if not all(isinstance(item, str) for item in (source, target, kind)):
            raise UpdateError("INVALID_UPDATE_GRAPH", "transition from/to/kind must be strings")
        if tag_re.fullmatch(source) is None or tag_re.fullmatch(target) is None:
            raise UpdateError("INVALID_UPDATE_GRAPH", f"transition tag does not match policy: {source} -> {target}")
        if kind not in {"standard", "bridge"} or not isinstance(reload_required, bool):
            raise UpdateError("INVALID_UPDATE_GRAPH", f"invalid transition metadata: {source} -> {target}")
        if kind == "bridge" and (not isinstance(reason, str) or not reason.strip()):
            raise UpdateError("INVALID_UPDATE_GRAPH", f"bridge transition requires reason: {source} -> {target}")
        if _semver(target) <= _semver(source):
            raise UpdateError("INVALID_UPDATE_GRAPH", f"transition must move forward: {source} -> {target}")
        if source in outgoing:
            raise UpdateError("INVALID_UPDATE_GRAPH", f"multiple outgoing transitions from {source}")
        outgoing[source] = Hop(source, target, kind, reload_required, reason if isinstance(reason, str) else None)
    return latest, outgoing


def _route(current: str, target: str, outgoing: dict[str, Hop]) -> list[Hop]:
    if current == target:
        return []
    result: list[Hop] = []
    seen = {current}
    cursor = current
    while cursor != target:
        hop = outgoing.get(cursor)
        if hop is None:
            raise UpdateError("NO_UPDATE_PATH", f"no update route from {current} to {target}")
        if hop.target in seen:
            raise UpdateError("INVALID_UPDATE_GRAPH", "update route contains cycle")
        result.append(hop)
        seen.add(hop.target)
        cursor = hop.target
        if len(result) > len(outgoing) + 1:
            raise UpdateError("INVALID_UPDATE_GRAPH", "update route is not finite")
    return result


def _load_lock(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    path = update_lock_path(root)
    if not path.is_file():
        raise UpdateError("LEGACY_ADOPTION_REQUIRED", f"update lock missing: {path.relative_to(root)}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("INVALID_UPDATE_LOCK", f"cannot read update lock: {exc}") from exc
    source = data.get("source")
    expected_repo = get(policy, "source.repository")
    if data.get("schemaVersion") != 1 or not isinstance(source, dict):
        raise UpdateError("INVALID_UPDATE_LOCK", "update lock schema is invalid")
    if source.get("repository") != expected_repo or not isinstance(source.get("ref"), str):
        raise UpdateError("INVALID_UPDATE_LOCK", "update lock source does not match policy")
    return data


def _read_graph(source: GitSource, policy: dict[str, Any]) -> dict[str, Any]:
    default_branch = get(policy, "source.default_branch")
    graph_path = get(policy, "source.update_manifest")
    if not isinstance(default_branch, str) or not default_branch:
        raise UpdateError("INVALID_UPDATE_POLICY", "source.default_branch must be non-empty string")
    if not isinstance(graph_path, str) or not graph_path:
        raise UpdateError("INVALID_UPDATE_POLICY", "source.update_manifest must be non-empty string")
    last_error: UpdateError | None = None
    for graph_ref in (f"origin/{default_branch}", default_branch):
        try:
            text = source.read_text(graph_ref, graph_path)
            break
        except UpdateError as exc:
            last_error = exc
    else:
        assert last_error is not None
        raise last_error
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpdateError("INVALID_UPDATE_GRAPH", f"cannot parse update graph: {exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("INVALID_UPDATE_GRAPH", "update graph root must be object")
    return data


def resolve_update(root: Path, target: str | None, source: GitSource) -> tuple[dict[str, Any], list[Hop], dict[str, Any]]:
    policy = load_update_policy(root)
    repository = get(policy, "source.repository")
    tag_pattern = get(policy, "source.tag_pattern")
    if not isinstance(repository, str) or not repository or not isinstance(tag_pattern, str):
        raise UpdateError("INVALID_UPDATE_POLICY", "source.repository/tag_pattern missing")
    lock = _load_lock(root, policy)
    current = lock["source"]["ref"]
    graph = _read_graph(source, policy)
    latest, outgoing = _validate_graph(graph, tag_pattern)
    requested = target or latest
    if re.fullmatch(tag_pattern, requested) is None:
        raise UpdateError("INVALID_RELEASE_TAG", f"target does not match source.tag_pattern: {requested}")
    if re.fullmatch(tag_pattern, current) is None:
        raise UpdateError("INVALID_UPDATE_LOCK", f"lock source.ref does not match tag pattern: {current}")
    manifest = load_manifest(root)
    manifest_release = get(manifest, "harness.release")
    if lock.get("release") != manifest_release or current != f"v{manifest_release}":
        raise UpdateError("INVALID_UPDATE_LOCK", "lock release/ref differs from current manifest")
    current_oid = source.resolve_tag(current)
    pinned_oid = lock.get("source", {}).get("commit")
    if pinned_oid is not None and pinned_oid != current_oid:
        raise UpdateError("SOURCE_TAG_MOVED", f"current release tag moved since lock was written: {current}")
    source.resolve_tag(requested)
    route = _route(current, requested, outgoing)
    for hop in route:
        source.resolve_tag(hop.source)
        source.resolve_tag(hop.target)
    return lock, route, policy


def verify_current_release_state(
    root: Path,
    source: GitSource,
    lock: dict[str, Any],
) -> dict[str, Any]:
    """Доказать, что Harness-owned OURS соответствует immutable release из lock.

    Shared/marker_merge paths специально не сравниваются byte-for-byte: они
    могут содержать разрешённые project modifications. Но Harness-owned слой
    обязан быть exact BASE, иначе lock больше не описывает текущий protocol.
    """
    current = lock["source"]["ref"]
    base_policy = _load_toml_text(
        source.read_text(current, UPDATE_POLICY_PATH),
        label=f"{current}:{UPDATE_POLICY_PATH}",
    )
    ownership = _ownership(base_policy)
    if _classify(UPDATE_POLICY_PATH, ownership) != "harness_owned":
        raise UpdateError(
            "INVALID_UPDATE_POLICY",
            f"{current} must classify {UPDATE_POLICY_PATH} as harness_owned",
        )
    entries = source.list_entries(current)
    tree = WorkingTree(root)
    tracked = tree.tracked()
    concrete = _managed_paths(entries, ownership) | _managed_paths(tracked, ownership)
    drift: list[str] = []
    checked = 0
    compare_modes = tree.tracks_filemode()

    for path in sorted(concrete):
        if _classify(path, ownership) != "harness_owned":
            continue
        checked += 1
        base = source.read_bytes(current, path) if path in entries else MISSING
        ours = tree.read_bytes(path)
        base_mode = (
            _source_permissions(entries.get(path), path=path, ref=current)
            if path in entries
            else None
        )
        ours_mode = tree.mode(path)

        if base is MISSING and ours is not MISSING:
            # До P1 historical policy ошибочно владела blanket
            # ".agents/skills/**". Project/third-party skill, которого нет в
            # immutable BASE, не должен превращаться в ложный release drift.
            # Исключение действует только для exact legacy blanket pattern;
            # современные concrete core-skill globs остаются строгими.
            legacy_skill_blanket = ".agents/skills/**" in ownership["harness_owned"]
            if legacy_skill_blanket and path.startswith(".agents/skills/"):
                continue
            drift.append(f"{path}: tracked Harness-owned path absent from pinned release")
        elif base is not MISSING and ours is MISSING:
            drift.append(f"{path}: pinned Harness-owned path is missing locally")
        elif base != ours:
            drift.append(f"{path}: content differs from pinned release")
        elif compare_modes and base_mode != ours_mode:
            drift.append(
                f"{path}: file mode differs from pinned release "
                f"({oct(ours_mode or 0)} != {oct(base_mode or 0)})"
            )

    if drift:
        preview = "; ".join(drift[:8])
        suffix = f"; +{len(drift) - 8} more" if len(drift) > 8 else ""
        raise UpdateError(
            "CURRENT_RELEASE_DRIFT",
            f"current Harness-owned state does not match {current}: {preview}{suffix}",
        )
    return {"release": current, "checkedHarnessOwnedPaths": checked}


def _local_untracked_collision(tree: WorkingTree, tracked: set[str], path: str) -> bool:
    target = tree.root / path
    if path in tracked or (not target.exists() and not target.is_symlink()):
        return False
    return not tree.ignored(path)


def _source_permissions(mode: str | None, *, path: str, ref: str) -> int | None:
    if mode is None:
        return None
    if mode == "100644":
        return 0o644
    if mode == "100755":
        return 0o755
    raise UpdateError(
        "UNSUPPORTED_MANAGED_MODE",
        f"managed source path must be regular 100644/100755 file: {ref}:{path} mode={mode}",
    )


def _path_plan(
    *,
    path: str,
    base_class: str | None,
    target_class: str | None,
    ours: bytes | object,
    base: bytes | object,
    theirs: bytes | object,
    target_mode: int | None,
    target_markers: list[str],
) -> PathPlan:
    # Если immutable BASE файла не содержал, а target release впервые
    # приносит этот concrete path, существующий OURS является collision даже
    # когда старый broad glob формально матчился с ним. Это критично для
    # миграции от legacy `.agents/skills/**`: project skill не становится
    # Harness-owned только из-за широкого historical pattern.
    if base is MISSING and theirs is not MISSING and ours is not MISSING:
        raise UpdateError("NEW_MANAGED_PATH_COLLISION", f"target introduces existing project path: {path}")

    if target_class is None:
        if base_class == "harness_owned" and base is not MISSING:
            if ours is not MISSING and ours != base:
                raise UpdateError("LOCAL_HARNESS_MODIFICATION", f"locally modified retired Harness path: {path}")
            if theirs is MISSING:
                return PathPlan(path, base_class, None, "delete", None, None, "retired Harness path")
        return PathPlan(path, base_class, None, "preserve", None, None, "path leaves managed ownership")

    if base_class is None:
        if ours is not MISSING:
            raise UpdateError("NEW_MANAGED_PATH_COLLISION", f"target newly manages existing project path: {path}")
        if theirs is MISSING:
            return PathPlan(path, None, target_class, "preserve", None, None)
        return PathPlan(path, None, target_class, "write", _as_bytes(theirs), target_mode, "new managed path")

    if base_class != target_class and ours != base:
        raise UpdateError("OWNERSHIP_CLASS_CHANGE", f"locally changed path changes ownership class: {path}: {base_class} -> {target_class}")

    if target_class == "harness_owned":
        if ours != base:
            raise UpdateError("LOCAL_HARNESS_MODIFICATION", f"Harness-owned path differs from immutable BASE: {path}")
        if theirs is MISSING:
            return PathPlan(path, base_class, target_class, "delete", None, None)
        return PathPlan(path, base_class, target_class, "write", _as_bytes(theirs), target_mode)

    merge_theirs = theirs
    if target_class == "marker_merge":
        merge_theirs = _preserve_markers(ours, theirs, path=path, blocks=target_markers)
    merged = _three_way(ours, base, merge_theirs, path=path)
    if merged is None:
        return PathPlan(path, base_class, target_class, "delete", None)
    return PathPlan(path, base_class, target_class, "write", merged, target_mode)


def analyze_hop(
    root: Path,
    hop: Hop,
    source: GitSource,
    *,
    overrides: dict[str, bytes | object] | None = None,
) -> HopPlan:
    tree = WorkingTree(root)
    tracked = tree.tracked()
    base_policy = _load_toml_text(source.read_text(hop.source, UPDATE_POLICY_PATH), label=f"{hop.source}:{UPDATE_POLICY_PATH}")
    target_policy = _load_toml_text(source.read_text(hop.target, UPDATE_POLICY_PATH), label=f"{hop.target}:{UPDATE_POLICY_PATH}")
    if _update_topology(base_policy) != _update_topology(target_policy):
        raise UpdateError(
            "UPDATE_POLICY_TOPOLOGY_CHANGE",
            f"bootstrap update topology changes across {hop.source} -> {hop.target}; explicit bridge support is required",
        )
    base_ownership = _ownership(base_policy)
    target_ownership = _ownership(target_policy)
    target_marker_map = _markers(target_policy)
    base_entries = source.list_entries(hop.source)
    target_entries = source.list_entries(hop.target)
    base_files = set(base_entries)
    target_files = set(target_entries)
    concrete = (
        _managed_paths(base_files, base_ownership)
        | _managed_paths(target_files, target_ownership)
        | _managed_paths(tracked, base_ownership)
        | _managed_paths(tracked, target_ownership)
    )

    plans: list[PathPlan] = []
    introduced: list[str] = []
    retired: list[str] = []
    reclassified: list[str] = []
    updater_changed = False
    for path in sorted(concrete):
        base_class = _classify(path, base_ownership)
        target_class = _classify(path, target_ownership)
        if base_class is None and target_class is None:
            continue
        base = source.read_bytes(hop.source, path) if base_class is not None else MISSING
        theirs = source.read_bytes(hop.target, path) if target_class is not None else MISSING
        base_mode = _source_permissions(base_entries.get(path), path=path, ref=hop.source) if path in base_entries else None
        target_mode = _source_permissions(target_entries.get(path), path=path, ref=hop.target) if path in target_entries else None
        ours = overrides[path] if overrides is not None and path in overrides else tree.read_bytes(path)
        if target_class is not None and _local_untracked_collision(tree, tracked, path):
            raise UpdateError("UNTRACKED_MANAGED_COLLISION", f"untracked non-ignored managed path collision: {path}")
        blocks = target_marker_map.get(path, []) if target_class == "marker_merge" else []
        if target_class == "marker_merge" and not blocks:
            raise UpdateError("INVALID_UPDATE_POLICY", f"marker_merge path has no configured marker blocks: {path}")
        plan = _path_plan(
            path=path,
            base_class=base_class,
            target_class=target_class,
            ours=ours,
            base=base,
            theirs=theirs,
            target_mode=target_mode,
            target_markers=blocks,
        )
        plans.append(plan)
        if base_class is None and target_class is not None:
            introduced.append(path)
        if base_class is not None and target_class is None:
            retired.append(path)
        if base_class is not None and target_class is not None and base_class != target_class:
            reclassified.append(path)
        if path in UPDATER_RUNTIME_PATHS and (base != theirs or base_mode != target_mode):
            updater_changed = True

    return HopPlan(
        hop=hop,
        paths=plans,
        introduced=introduced,
        retired=retired,
        reclassified=reclassified,
        reload_required=hop.reload_required or updater_changed,
    )


def _plan_json(lock: dict[str, Any], target: str, plans: list[HopPlan]) -> dict[str, Any]:
    route = [lock["source"]["ref"]] + [plan.hop.target for plan in plans]
    reload_at = next((plan.hop.target for plan in plans if plan.reload_required), None)
    return {
        "status": "PASS",
        "current": lock["source"]["ref"],
        "resolvedTarget": target,
        "route": route,
        "reloadBoundary": reload_at,
        "hops": [
            {
                "from": plan.hop.source,
                "to": plan.hop.target,
                "kind": plan.hop.kind,
                "reloadRequired": plan.reload_required,
                "introduced": plan.introduced,
                "retired": plan.retired,
                "reclassified": plan.reclassified,
                "changes": [
                    {"path": item.path, "action": item.action, "detail": item.detail}
                    for item in plan.paths
                    if item.action != "preserve"
                ],
            }
            for plan in plans
        ],
    }


def _project_overrides(overrides: dict[str, bytes | object], plan: HopPlan) -> None:
    for item in plan.paths:
        if item.action == "write":
            assert item.content is not None
            overrides[item.path] = item.content
        elif item.action == "delete":
            overrides[item.path] = MISSING


def _preflight_route(root: Path, route: list[Hop], source: GitSource) -> list[HopPlan]:
    """Проверить route без mutation до первого reload boundary включительно."""
    overrides: dict[str, bytes | object] = {}
    plans: list[HopPlan] = []
    for hop in route:
        plan = analyze_hop(root, hop, source, overrides=overrides)
        plans.append(plan)
        _project_overrides(overrides, plan)
        if plan.reload_required:
            break
    return plans


def check_update(root: Path, *, target: str | None = None, source_url: str | None = None) -> dict[str, Any]:
    policy = load_update_policy(root)
    repository = get(policy, "source.repository")
    if not isinstance(repository, str) or not repository:
        raise UpdateError("INVALID_UPDATE_POLICY", "source.repository missing")
    source = GitSource.open(repository, source_url=source_url)
    try:
        # Сначала resolve lock: legacy project без lock должен получить
        # LEGACY_ADOPTION_REQUIRED, а не общий CURRENT_HARNESS_INVALID.
        lock, route, _ = resolve_update(root, target, source)
        _run_validator(root, phase="preflight")
        current_state = verify_current_release_state(root, source, lock)
        resolved_target = target or (route[-1].target if route else lock["source"]["ref"])
        plans = _preflight_route(root, route, source)
        result = _plan_json(lock, resolved_target, plans)
        result["route"] = [lock["source"]["ref"]] + [hop.target for hop in route]
        result["checkedThrough"] = plans[-1].hop.target if plans else lock["source"]["ref"]
        result["currentReleaseState"] = current_state
        return result
    finally:
        source.close()


def _backup_paths(tree: WorkingTree, plans: list[PathPlan]) -> dict[str, tuple[bytes | object, int | None]]:
    return {
        item.path: (tree.read_bytes(item.path), tree.mode(item.path))
        for item in plans
        if item.action != "preserve"
    }


def _restore_paths(tree: WorkingTree, backup: dict[str, tuple[bytes | object, int | None]]) -> None:
    for path, (value, mode) in backup.items():
        tree.write_bytes(path, None if value is MISSING else _as_bytes(value), mode=mode)


def _write_lock(root: Path, target: str, target_commit: str) -> None:
    manifest = load_manifest(root)
    policy = load_update_policy(root)
    path = update_lock_path(root)
    payload = {
        "schemaVersion": 1,
        "harnessVersion": str(get(manifest, "harness.version")),
        "release": str(get(manifest, "harness.release")),
        "source": {
            "repository": get(policy, "source.repository"),
            "ref": target,
            "commit": target_commit,
        },
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # Target manifest release обязан совпасть с достигнутым immutable tag.
    if payload["release"] != target.removeprefix("v"):
        raise UpdateError("POSTCONDITION_FAILED", f"target manifest release {payload['release']} != {target}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _run_validator(root: Path, *, phase: str) -> None:
    validator = root / ".harness/tools/validate.py"
    if not validator.is_file():
        raise UpdateError("VALIDATOR_UNAVAILABLE", f"Harness validator missing during {phase}")
    proc = subprocess.run(
        ["python3", str(validator), "--mode", "manual"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        output = (proc.stdout + "\n" + proc.stderr).strip()
        code = "CURRENT_HARNESS_INVALID" if phase == "preflight" else "POSTCONDITION_FAILED"
        raise UpdateError(code, output or f"Harness validation failed during {phase}")


def _write_report(root: Path, *, initial: str, target: str, applied: list[HopPlan], status: str) -> str:
    directory = update_report_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    report_name, created_at = durable_report_timestamp(
        "UPDATE-",
        directory=directory,
    )
    path = directory / report_name
    route = [initial] + [item.hop.target for item in applied]
    introduced = sorted({p for item in applied for p in item.introduced})
    retired = sorted({p for item in applied for p in item.retired})
    reclassified = sorted({p for item in applied for p in item.reclassified})
    reached = route[-1] if route else initial
    route_yaml = "\n".join(f"  - {item}" for item in route)
    body = f"""---
schema: 1
kind: harness_update
initial_release: {initial}
final_target: {target}
route:
{route_yaml}
created_at: {created_at}
result: {'success' if status == 'UPDATED' else 'reload_required'}
---

# Harness Update — {initial} → {reached}

## Route

{' → '.join(route)}

## Managed path changes

Introduced:
{_bullet_list(introduced)}

Retired:
{_bullet_list(retired)}

Reclassified:
{_bullet_list(reclassified)}

## Verification

- Deterministic ownership/merge plan: PASS
- Target Harness validator: PASS for every applied hop

## Follow-up

{'Reload runtime and repeat HARNESS UPDATE APPLY.' if status != 'UPDATED' else 'No update-specific follow-up.'}
"""
    path.write_text(body, encoding="utf-8", newline="\n")
    return path.relative_to(root).as_posix()


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- `{item}`" for item in items) if items else "- none"


def apply_update(root: Path, *, target: str | None = None, source_url: str | None = None) -> dict[str, Any]:
    policy = load_update_policy(root)
    repository = get(policy, "source.repository")
    if not isinstance(repository, str) or not repository:
        raise UpdateError("INVALID_UPDATE_POLICY", "source.repository missing")
    source = GitSource.open(repository, source_url=source_url)
    tree = WorkingTree(root)
    try:
        lock, route, _ = resolve_update(root, target, source)
        initial = lock["source"]["ref"]
        resolved_target = target or (route[-1].target if route else initial)

        # Даже NO_UPDATE должен доказать, что lock действительно описывает
        # текущий Harness-owned protocol layer.
        _run_validator(root, phase="preflight")
        current_state = verify_current_release_state(root, source, lock)
        if not route:
            return {
                "status": "NO_UPDATE",
                "current": initial,
                "resolvedTarget": resolved_target,
                "route": [initial],
                "currentReleaseState": current_state,
            }

        # Read-only preflight до первой mutation. Если updater/reload boundary
        # встречается раньше final target, текущий runtime не делает вид, что
        # способен безопасно интерпретировать последующие release semantics.
        preflight_plans = _preflight_route(root, route, source)
        applied: list[HopPlan] = []
        for index, hop in enumerate(route):
            if index >= len(preflight_plans):
                raise UpdateError("UPDATER_RELOAD_REQUIRED", "route continues beyond checked reload boundary")
            plan = preflight_plans[index]
            backup = _backup_paths(tree, plan.paths)
            lock_path = update_lock_path(root)
            lock_backup = lock_path.read_bytes() if lock_path.is_file() else None
            try:
                for item in plan.paths:
                    if item.action == "write":
                        assert item.content is not None
                        tree.write_bytes(item.path, item.content, mode=item.mode)
                    elif item.action == "delete":
                        tree.write_bytes(item.path, None)
                # Lock участвует в target validator, поэтому обновляется внутри
                # транзакции до postcondition и откатывается вместе с файлами.
                _write_lock(root, hop.target, source.resolve_tag(hop.target))
                _run_validator(root, phase="postcondition")
            except Exception:
                _restore_paths(tree, backup)
                if lock_backup is not None:
                    lock_path.write_bytes(lock_backup)
                raise
            applied.append(plan)
            if plan.reload_required:
                report = _write_report(
                    root,
                    initial=initial,
                    target=resolved_target,
                    applied=applied,
                    status="UPDATER_RELOAD_REQUIRED",
                )
                return {
                    "status": "UPDATER_RELOAD_REQUIRED",
                    "current": hop.target,
                    "resolvedTarget": resolved_target,
                    "route": [initial] + [item.hop.target for item in applied],
                    "report": report,
                }

        report = _write_report(root, initial=initial, target=resolved_target, applied=applied, status="UPDATED")
        return {
            "status": "UPDATED",
            "current": route[-1].target,
            "resolvedTarget": resolved_target,
            "route": [initial] + [item.hop.target for item in applied],
            "report": report,
        }
    finally:
        source.close()



def adopt_legacy(root: Path, *, baseline: str, source_url: str | None = None) -> dict[str, Any]:
    """Создать первый pinned lock только для явно указанного immutable baseline."""
    policy = load_update_policy(root)
    repository = get(policy, "source.repository")
    tag_pattern = get(policy, "source.tag_pattern")
    if not isinstance(repository, str) or not repository or not isinstance(tag_pattern, str):
        raise UpdateError("INVALID_UPDATE_POLICY", "source.repository/tag_pattern missing")
    lock_path = update_lock_path(root)
    if lock_path.exists():
        raise UpdateError("LOCK_ALREADY_EXISTS", f"update lock already exists: {lock_path.relative_to(root)}")
    if re.fullmatch(tag_pattern, baseline) is None:
        raise UpdateError("INVALID_RELEASE_TAG", f"baseline does not match source.tag_pattern: {baseline}")

    manifest = load_manifest(root)
    if get(manifest, "harness.release") != baseline.removeprefix("v"):
        raise UpdateError("BASELINE_MISMATCH", "explicit baseline differs from current manifest release")

    source = GitSource.open(repository, source_url=source_url)
    try:
        baseline_oid = source.resolve_tag(baseline)
        baseline_policy = _load_toml_text(
            source.read_text(baseline, UPDATE_POLICY_PATH),
            label=f"{baseline}:{UPDATE_POLICY_PATH}",
        )
        ownership = _ownership(baseline_policy)
        files = source.list_files(baseline)
        tree = WorkingTree(root)
        tracked = tree.tracked()
        concrete = _managed_paths(files, ownership) | _managed_paths(tracked, ownership)
        divergences: list[str] = []
        for path in sorted(concrete):
            base = source.read_bytes(baseline, path)
            ours = tree.read_bytes(path)
            if base is MISSING and ours is not MISSING:
                divergences.append(path + " (local-only under historical managed pattern)")
            elif base is not MISSING and ours != base:
                divergences.append(path + " (differs from baseline)")
        _write_lock(root, baseline, baseline_oid)
        return {
            "status": "ADOPTED",
            "current": baseline,
            "sourceCommit": baseline_oid,
            "divergences": divergences,
        }
    finally:
        source.close()

def _print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(result.get("status", "UNKNOWN"))
    for key in ("current", "resolvedTarget", "reloadBoundary", "report"):
        if result.get(key) is not None:
            print(f"{key}: {result[key]}")
    if result.get("route"):
        print("route: " + " -> ".join(result["route"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic AI Development Harness updater")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("check", "apply"):
        item = sub.add_parser(name)
        item.add_argument("--to", dest="target")
        item.add_argument("--json", action="store_true", dest="as_json")
    adopt = sub.add_parser("adopt")
    adopt.add_argument("--from", dest="baseline", required=True)
    adopt.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        if args.action == "check":
            result = check_update(root, target=args.target)
        elif args.action == "apply":
            result = apply_update(root, target=args.target)
        else:
            result = adopt_legacy(root, baseline=args.baseline)
    except (UpdateError, ConfigError, OSError) as exc:
        code = exc.code if isinstance(exc, UpdateError) else "CONFIG_OR_IO_ERROR"
        result = {"status": "BLOCKED", "reasonCode": code, "message": str(exc)}
        _print_result(result, as_json=args.as_json)
        return 2
    _print_result(result, as_json=args.as_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
