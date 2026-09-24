#!/usr/bin/env python3
"""Crash-safe журнал HARNESS UPDATE hop и детерминированный rollback.

Модуль намеренно зависит только от Python stdlib. Во время hop файлы
`.harness/tools/**` могут оказаться частично из BASE, частично из target:
recovery не имеет права импортировать другие Harness-модули, иначе
прерванный update мог бы сделать невозможным собственный откат.

Журнал — это единственная граница транзакции hop:

1. до первой записи сохраняются backup всех затрагиваемых paths (включая lock
   и local runtime state) и `journal.json` со state `applying`;
2. hop пишет файлы, lock и report;
3. после PASS target validator журнал удаляется — это commit point;
4. если процесс прерван, следующий APPLY (или `harness-update.py recover`)
   откатывает hop byte-for-byte по журналу.

Формат журнала — schema 1. Любой будущий engine обязан читать его, потому что
прерванный hop мог уже установить target engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import argparse
import json
import os
import shutil
import socket
import sys
from typing import Any, Iterable


JOURNAL_DIR = ".harness/local/update-journal"
JOURNAL_FILE = "journal.json"
JOURNAL_SCHEMA = 1

# Local runtime state не принадлежит updater-у, но target code (validator)
# может мигрировать его во время hop. Такой файл сохраняется в журнал и
# восстанавливается только если его schemaVersion изменилась.
LOCAL_STATE_PATHS = (".harness/local/execution/execution-status.json",)


class JournalError(RuntimeError):
    """Fail-closed ошибка журнала update transaction."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_relative_path(path: str) -> str:
    """Проверить repository-relative POSIX path без traversal/.git."""
    if not isinstance(path, str) or not path or "\0" in path or "\\" in path:
        raise JournalError("UNSAFE_PATH", f"unsafe repository path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise JournalError("UNSAFE_PATH", f"absolute path is not allowed: {path}")
    for part in pure.parts:
        if part in {"", ".", ".."} or part.lower() == ".git":
            raise JournalError("UNSAFE_PATH", f"unsafe path component in: {path}")
    return pure.as_posix()


def ensure_no_symlink_parents(root: Path, path: str) -> Path:
    """Вернуть target path, если ни один parent внутри root не является symlink."""
    rel = safe_relative_path(path)
    root = root.resolve()
    current = root
    parts = PurePosixPath(rel).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise JournalError("UNSAFE_LOCAL_PATH", f"symlinked parent directory: {rel}")
    return root.joinpath(*parts)


def _fsync_dir(path: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(target: Path, content: bytes, *, mode: int) -> None:
    """Записать файл через temp + fsync + os.replace с exact permissions."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.harness-tmp-{os.getpid()}"
    try:
        with open(temp, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp, mode)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    _fsync_dir(target.parent)


def _file_mode(path: Path) -> int:
    return 0o755 if path.stat().st_mode & 0o111 else 0o644


def prune_empty_parents(path: Path, root: Path) -> None:
    root = root.resolve()
    while path != root and root in path.parents:
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def journal_dir(root: Path) -> Path:
    return root / JOURNAL_DIR


def load_journal(root: Path) -> dict[str, Any] | None:
    """Вернуть pending journal или None. Повреждённый журнал — fail-closed."""
    directory = journal_dir(root)
    if not directory.exists() and not directory.is_symlink():
        return None
    if directory.is_symlink() or not directory.is_dir():
        raise JournalError("UPDATE_JOURNAL_INVALID", f"{JOURNAL_DIR} must be a directory")
    path = directory / JOURNAL_FILE
    if not path.is_file():
        # Crash между mkdir и записью journal.json: mutation ещё не начиналась.
        return {"schemaVersion": JOURNAL_SCHEMA, "state": "preparing", "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JournalError("UPDATE_JOURNAL_INVALID", f"cannot read update journal: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != JOURNAL_SCHEMA:
        raise JournalError("UPDATE_JOURNAL_INVALID", "unsupported update journal schema")
    if not isinstance(data.get("entries"), list):
        raise JournalError("UPDATE_JOURNAL_INVALID", "update journal entries must be a list")
    return data


def _write_journal(root: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_bytes(journal_dir(root) / JOURNAL_FILE, payload.encode("utf-8"), mode=0o644)


def owner_alive(journal: dict[str, Any]) -> bool:
    """Жив ли процесс, создавший журнал, на этом же host (POSIX)."""
    owner = journal.get("owner")
    if not isinstance(owner, dict) or owner.get("host") != socket.gethostname():
        return False
    pid = owner.get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    if os.name != "posix":
        # Без надёжной проверки процесса считаем владельца живым: автоматический
        # rollback чужого идущего hop опаснее, чем ручной `recover --force`.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def begin_journal(
    root: Path,
    *,
    operation: str,
    source: str | None,
    target: str | None,
    paths: Iterable[str],
) -> dict[str, Any]:
    """Сохранить backup всех затрагиваемых paths до первой mutation."""
    directory = journal_dir(root)
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
    except FileExistsError as exc:
        raise JournalError(
            "UPDATE_JOURNAL_PENDING",
            "another Harness update transaction is pending; run HARNESS UPDATE APPLY "
            "or python3 .harness/tools/harness-update.py recover",
        ) from exc
    blobs = directory / "blobs"
    blobs.mkdir()

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered = [safe_relative_path(item) for item in paths]
    ordered += [item for item in LOCAL_STATE_PATHS]
    for index, rel in enumerate(ordered):
        if rel in seen:
            continue
        seen.add(rel)
        target_path = ensure_no_symlink_parents(root, rel)
        entry: dict[str, Any] = {
            "path": rel,
            "kind": "local-state" if rel in LOCAL_STATE_PATHS else "managed",
        }
        if target_path.is_symlink() or (target_path.exists() and not target_path.is_file()):
            raise JournalError("UNSAFE_LOCAL_PATH", f"journaled path must be a regular file: {rel}")
        if target_path.is_file():
            blob_name = f"{index:06d}"
            data = target_path.read_bytes()
            with open(blobs / blob_name, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            entry.update(existed=True, mode=_file_mode(target_path), backup=blob_name)
            if entry["kind"] == "local-state":
                entry["schemaVersion"] = _schema_version(data)
        else:
            entry.update(existed=False, mode=None, backup=None)
        entries.append(entry)
    _fsync_dir(blobs)

    journal = {
        "schemaVersion": JOURNAL_SCHEMA,
        "state": "applying",
        "operation": operation,
        "source": source,
        "target": target,
        "createdAt": _now(),
        "owner": {"pid": os.getpid(), "host": socket.gethostname()},
        "entries": entries,
        "createdReports": [],
    }
    _write_journal(root, journal)
    _fsync_dir(directory.parent)
    return journal


def update_journal(root: Path, journal: dict[str, Any], **changes: Any) -> None:
    journal.update(changes)
    _write_journal(root, journal)


def record_created_report(root: Path, journal: dict[str, Any], rel: str) -> None:
    reports = list(journal.get("createdReports") or [])
    reports.append(safe_relative_path(rel))
    update_journal(root, journal, createdReports=reports)


def finish_journal(root: Path) -> None:
    """Commit point: hop признан успешным, backup больше не нужен."""
    directory = journal_dir(root)
    shutil.rmtree(directory)
    _fsync_dir(directory.parent)


def _schema_version(data: bytes) -> Any:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value.get("schemaVersion") if isinstance(value, dict) else None


def rollback_journal(root: Path, journal: dict[str, Any] | None = None) -> dict[str, Any]:
    """Byte-for-byte восстановить состояние до hop и удалить журнал."""
    if journal is None:
        journal = load_journal(root)
    if journal is None:
        return {"rolledBack": False}
    directory = journal_dir(root)
    blobs = directory / "blobs"
    restored: list[str] = []
    removed: list[str] = []

    for entry in journal.get("entries", []):
        if not isinstance(entry, dict):
            raise JournalError("UPDATE_JOURNAL_INVALID", "journal entry must be an object")
        rel = safe_relative_path(str(entry.get("path")))
        target_path = ensure_no_symlink_parents(root, rel)
        existed = entry.get("existed") is True

        if entry.get("kind") == "local-state":
            # Restore только если target code изменил schema local state.
            if not existed:
                continue
            backup = (blobs / str(entry.get("backup"))).read_bytes()
            current = target_path.read_bytes() if target_path.is_file() else None
            if current is not None and _schema_version(current) == entry.get("schemaVersion"):
                continue
            atomic_write_bytes(target_path, backup, mode=int(entry.get("mode") or 0o644))
            restored.append(rel)
            continue

        if existed:
            backup = (blobs / str(entry.get("backup"))).read_bytes()
            mode = int(entry.get("mode") or 0o644)
            current_ok = (
                target_path.is_file()
                and not target_path.is_symlink()
                and target_path.read_bytes() == backup
                and _file_mode(target_path) == mode
            )
            if not current_ok:
                if target_path.is_symlink():
                    target_path.unlink()
                atomic_write_bytes(target_path, backup, mode=mode)
                restored.append(rel)
        elif target_path.exists() or target_path.is_symlink():
            if target_path.is_dir() and not target_path.is_symlink():
                raise JournalError("UNSAFE_LOCAL_PATH", f"cannot remove directory during rollback: {rel}")
            target_path.unlink()
            prune_empty_parents(target_path.parent, root)
            removed.append(rel)

    for rel in journal.get("createdReports") or []:
        report = ensure_no_symlink_parents(root, safe_relative_path(str(rel)))
        if report.is_file() and not report.is_symlink():
            report.unlink()
            removed.append(str(rel))

    shutil.rmtree(directory)
    _fsync_dir(directory.parent)
    return {
        "rolledBack": True,
        "operation": journal.get("operation"),
        "source": journal.get("source"),
        "target": journal.get("target"),
        "state": journal.get("state"),
        "restoredPaths": restored,
        "removedPaths": removed,
    }


def recover_pending(root: Path, *, force: bool = False) -> dict[str, Any] | None:
    """Откатить прерванный hop, если его владелец больше не работает."""
    journal = load_journal(root)
    if journal is None:
        return None
    if not force and owner_alive(journal):
        raise JournalError(
            "UPDATE_IN_PROGRESS",
            "another HARNESS UPDATE APPLY is still running for this repository",
        )
    return rollback_journal(root, journal)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness-update.py recover",
        description="Roll back an interrupted Harness update transaction (stdlib only).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--force",
        action="store_true",
        help="roll back even if the recorded owner process still looks alive",
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        result = recover_pending(root, force=args.force)
    except (JournalError, OSError) as exc:
        code = exc.code if isinstance(exc, JournalError) else "CONFIG_OR_IO_ERROR"
        payload = {"status": "BLOCKED", "reasonCode": code, "message": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.as_json else f"BLOCKED {code}: {exc}")
        return 2
    payload = {"status": "RECOVERED" if result else "NO_JOURNAL", **(result or {})}
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
