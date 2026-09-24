#!/usr/bin/env python3
"""Public CLI for deterministic semantic artifact writers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from semantic_artifacts import (
    SemanticArtifactError,
    write_plan_draft,
    write_planning_review,
    write_step_review,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_local_payload_path(root: Path, value: str) -> Path:
    """Разрешить lexical local path без symlink traversal.

    Cleanup обязан удалить ровно тот transport path, который был передан
    writer-у. Проверка после Path.resolve() недостаточна: leaf/parent symlink
    уже превращается в target и unlink может удалить чужой recovery state.
    """
    base = root.resolve()
    allowed = base / ".harness" / "local"
    raw = Path(value)
    if ".." in raw.parts:
        raise SemanticArtifactError(
            "payload file must stay under .harness/local/** without '..'"
        )
    candidate = raw if raw.is_absolute() else base / raw
    candidate = Path(os.path.abspath(str(candidate)))

    try:
        rel_root = candidate.relative_to(base)
        rel_local = candidate.relative_to(allowed)
    except ValueError as exc:
        raise SemanticArtifactError(
            "payload file must stay under .harness/local/**"
        ) from exc
    if not rel_local.parts:
        raise SemanticArtifactError(
            "payload file must be a regular file under .harness/local/**"
        )

    cursor = base
    for part in rel_root.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SemanticArtifactError(
                "payload file path must not contain symlinks"
            )

    if not candidate.is_file():
        raise SemanticArtifactError(
            "payload file must be a regular file under .harness/local/**"
        )
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise SemanticArtifactError(
            "payload file escapes .harness/local/**"
        ) from exc
    return candidate


def _path_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat(follow_symlinks=False)
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _cleanup_consumed_payload(
    path: Path,
    identity: tuple[int, int, int, int],
) -> str | None:
    """Best-effort cleanup без превращения успешного writer в failure."""
    try:
        if path.is_symlink():
            return "payload cleanup skipped: path became a symlink"
        if not path.exists():
            return None
        if _path_identity(path) != identity:
            return "payload cleanup skipped: path changed after it was consumed"
        path.unlink()
    except OSError as exc:
        return f"payload cleanup failed: {exc}"
    return None


def load_payload(
    root: Path,
    value: str,
) -> tuple[dict, Path | None, tuple[int, int, int, int] | None]:
    """Прочитать semantic payload и вернуть exact path + identity для cleanup."""
    payload_path: Path | None = None
    payload_identity: tuple[int, int, int, int] | None = None
    if value == "-":
        raw = sys.stdin.read()
    else:
        path = _safe_local_payload_path(root, value)
        before = _path_identity(path)
        raw = path.read_text(encoding="utf-8")
        after = _path_identity(path)
        if before != after:
            raise SemanticArtifactError("payload file changed while being read")
        payload_path = path
        payload_identity = after
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticArtifactError(f"invalid payload JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SemanticArtifactError("payload JSON must be an object")
    return data, payload_path, payload_identity



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write canonical PLAN/REVIEW artifacts from semantic JSON payloads."
    )
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan-draft", "planning-review", "step-review"):
        item = sub.add_parser(action)
        item.add_argument("step_id")
        item.add_argument("--payload-file", required=True)

    args = parser.parse_args()
    root = repo_root()
    payload_path: Path | None = None
    payload_identity: tuple[int, int, int, int] | None = None
    try:
        payload, payload_path, payload_identity = load_payload(
            root,
            args.payload_file,
        )
        if args.action == "plan-draft":
            result = write_plan_draft(root, args.step_id, payload)
        elif args.action == "planning-review":
            result = write_planning_review(root, args.step_id, payload)
        else:
            result = write_step_review(root, args.step_id, payload)

        # Payload — transport, а не recovery/evidence. После нормального возврата
        # deterministic writer он больше не нужен независимо от semantic verdict.
        # При exception файл сохраняется для диагностики/retry.
        if payload_path is not None and payload_identity is not None:
            warning = _cleanup_consumed_payload(payload_path, payload_identity)
            if warning is not None:
                result.setdefault("cleanupWarnings", []).append(warning)
    except (OSError, ValueError) as exc:
        result = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "reasonCode": getattr(exc, "code", "SEMANTIC_ARTIFACT_BLOCKED"),
            "message": str(exc),
        }

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result.get("status") in {"PASS", "FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
