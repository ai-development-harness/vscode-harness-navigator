#!/usr/bin/env python3
"""Crash-safe журнал HARNESS UPDATE hop и детерминированный rollback.

Модуль намеренно зависит только от Python stdlib. Во время hop файлы
`.harness/tools/**` могут оказаться частично из BASE, частично из target:
recovery не имеет права импортировать другие Harness-модули, иначе
прерванный update мог бы сделать невозможным собственный откат.

Журнал — это единственная граница транзакции hop:

1. до первой записи сохраняются backup всех затрагиваемых paths (включая lock
   и local runtime state) и `journal.json` со state `applying`;
2. hop пишет managed files и lock, затем выполняет target validator;
3. только после PASS validator публикуется durable report и журнал удаляется — это commit point;
4. если процесс прерван, следующий APPLY (или `harness-update.py recover`)
   откатывает hop byte-for-byte по журналу.

Формат журнала — schema 1. Любой будущий engine обязан читать его, потому что
прерванный hop мог уже установить target engine.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import sys
from typing import Any, Iterable


JOURNAL_DIR = ".harness/local/update-journal"
JOURNAL_FILE = "journal.json"
JOURNAL_SCHEMA = 1
EXECUTION_LOCK_PATH = ".harness/local/execution/execution-status.lock"
UPDATE_TRANSACTION_ENV = "HARNESS_UPDATE_TRANSACTION"

# Local runtime state не принадлежит updater-у, но target code (validator)
# может мигрировать его во время hop. Backup участвует в той же byte-exact
# rollback semantics, что и managed files.
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
    """Вернуть exact permission bits, а не Git-normalized 0644/0755."""
    return stat.S_IMODE(path.stat().st_mode)


@contextmanager
def execution_state_lock(root: Path):
    """Совместимый с execution_status.py cross-process lock local state.

    Update берёт его только на atomic snapshot/rollback boundary. После создания
    journal остальные canonical sessions видят pending transaction и не имеют
    права писать execution state до commit/rollback.
    """
    path = root / EXECUTION_LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b"\0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


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


# Commit point и конец rollback — атомарный rename journal directory в
# tombstone: после него pending journal больше не существует, а удаление
# tombstone (многооперационный rmtree) уже не участвует в решении
# commit/rollback. Crash внутри cleanup оставляет только tombstone, который
# следующая транзакция/recovery просто удаляет.
TOMBSTONE_PREFIX = "update-journal.discarded-"


def _retire_journal_dir(root: Path) -> None:
    directory = journal_dir(root)
    tombstone = directory.with_name(TOMBSTONE_PREFIX + secrets.token_hex(8))
    os.replace(directory, tombstone)
    _fsync_dir(directory.parent)
    shutil.rmtree(tombstone)
    _fsync_dir(directory.parent)


def discard_retired_journals(root: Path) -> list[str]:
    """Удалить tombstones, оставшиеся после crash внутри cleanup."""
    parent = journal_dir(root).parent
    removed: list[str] = []
    if not parent.is_dir():
        return removed
    for candidate in sorted(parent.glob(TOMBSTONE_PREFIX + "*")):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        shutil.rmtree(candidate)
        removed.append(candidate.name)
    if removed:
        _fsync_dir(parent)
    return removed


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
    """Сохранить backup всех затрагиваемых paths до первой mutation.

    Создание journal и snapshot execution-status сериализованы тем же advisory
    lock, что canonical execution layer: session либо успевает записать state
    до snapshot, либо после появления journal уже блокируется.
    """
    directory = journal_dir(root)
    discard_retired_journals(root)
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
    except FileExistsError as exc:
        raise JournalError(
            "UPDATE_JOURNAL_PENDING",
            "another Harness update transaction is pending; run HARNESS UPDATE APPLY "
            "or python3 .harness/tools/harness-update.py recover",
        ) from exc

    # Сам факт существования journal directory — gate для новых execution-state
    # transactions. Updater не создаёт execution-status.lock сам: если lock уже
    # существовал, ждём текущего owner и snapshot-им под ним; если lock не было,
    # новые sessions увидят journal до открытия lock, а повторная проверка после
    # acquire закрывает TOCTOU.
    execution_lock_existed = (root / EXECUTION_LOCK_PATH).is_file()
    lock_context = execution_state_lock(root) if execution_lock_existed else nullcontext()
    with lock_context:
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
            "transactionId": secrets.token_hex(16),
            "executionLockExisted": execution_lock_existed,
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


class ReportLedger:
    """Journal-backed доказательство владения report, созданным внутри hop (#130).

    Протокол вызывает `document_contract._create_owned_report`: reserve до
    записи на диск, release при проигранной гонке за имя, confirm с inode
    после публикации. Rollback удаляет report только если владение доказано
    (см. `_owned_report`), поэтому чужой файл с тем же именем не удаляется.
    """

    def __init__(self, root: Path, journal: dict[str, Any]) -> None:
        self.root = root
        self.journal = journal

    def _rel(self, path: Path) -> str:
        return safe_relative_path(path.relative_to(self.root).as_posix())

    def _save(self, reports: list[Any]) -> None:
        update_journal(self.root, self.journal, createdReports=reports)

    def reserve(self, path: Path, staging: Path, digest: str) -> None:
        reports = list(self.journal.get("createdReports") or [])
        reports.append({"path": self._rel(path), "staging": self._rel(staging), "sha256": digest})
        self._save(reports)

    def release(self, path: Path) -> None:
        rel = self._rel(path)
        self._save([
            item for item in self.journal.get("createdReports") or []
            if not (isinstance(item, dict) and item.get("path") == rel)
        ])

    def confirm(self, path: Path, stat: os.stat_result) -> None:
        rel = self._rel(path)
        reports = []
        for item in self.journal.get("createdReports") or []:
            if isinstance(item, dict) and item.get("path") == rel:
                item = {**item, "inode": [stat.st_dev, stat.st_ino]}
            reports.append(item)
        self._save(reports)


def finish_journal(root: Path) -> None:
    """Commit point: hop признан успешным, backup больше не нужен.

    Решение принимает атомарный rename journal → tombstone; см.
    `_retire_journal_dir`.
    """
    _retire_journal_dir(root)


def _schema_version(data: bytes) -> Any:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value.get("schemaVersion") if isinstance(value, dict) else None


def _validate_rollback_backups(root: Path, journal: dict[str, Any]) -> None:
    """Доказать полноту rollback input до любой recovery mutation."""
    blobs = journal_dir(root) / "blobs"
    for entry in journal.get("entries", []):
        if not isinstance(entry, dict):
            raise JournalError("UPDATE_JOURNAL_INVALID", "journal entry must be an object")
        if entry.get("existed") is not True:
            continue
        backup_name = entry.get("backup")
        if (
            not isinstance(backup_name, str)
            or not backup_name
            or Path(backup_name).name != backup_name
        ):
            raise JournalError(
                "UPDATE_JOURNAL_INVALID",
                f"invalid backup identity for {entry.get('path')}",
            )
        blob = blobs / backup_name
        if blob.is_symlink() or not blob.is_file():
            raise JournalError(
                "UPDATE_JOURNAL_INVALID",
                f"backup for {entry.get('path')} is missing; journal is incomplete, "
                "rollback not started",
            )


def rollback_journal(root: Path, journal: dict[str, Any] | None = None) -> dict[str, Any]:
    """Byte-for-byte восстановить состояние до hop и удалить журнал.

    Journal directory уже блокирует новые canonical execution transactions.
    Если execution lock существовал до hop, rollback ждёт его и восстанавливает
    state под тем же lock. Если lock отсутствовал, updater не создаёт новый
    persistent artifact только ради recovery.
    """
    if journal is None:
        journal = load_journal(root)
    if journal is None:
        return {"rolledBack": False}

    # Повреждённый journal не мутируем вообще: сначала доказываем наличие всех
    # backup blobs, и только после этого отзываем validator capability.
    _validate_rollback_backups(root, journal)

    # Recovery сначала отзывает transaction capability target-validator-а.
    # После durable state=recovering execution layer больше не разрешает новые
    # state transactions с прежним HARNESS_UPDATE_TRANSACTION; затем recovery
    # может безопасно дождаться уже удерживаемого lock и восстановить baseline.
    if journal.get("state") != "recovering":
        previous_state = journal.get("state")
        update_journal(root, journal, state="recovering")
        # На диске capability уже отозвана, но diagnostic result сохраняет
        # фазу, в которой исходная transaction была прервана.
        journal["state"] = previous_state

    recorded = journal.get("executionLockExisted")
    lock_path = root / EXECUTION_LOCK_PATH
    if lock_path.is_symlink():
        raise JournalError(
            "UNSAFE_LOCAL_PATH",
            f"execution state lock must not be a symlink: {EXECUTION_LOCK_PATH}",
        )
    if isinstance(recorded, bool):
        transaction_created_lock = not recorded and lock_path.is_file()
        # Parent updater мог погибнуть, пока target validator ещё держит lock.
        # В этом случае recovery обязан дождаться validator-а до restore.
        needs_lock = recorded or transaction_created_lock
    else:
        # Backward compatibility для schema-1 journal старого engine:
        # неизвестное происхождение существующего lock сохраняем.
        transaction_created_lock = False
        needs_lock = lock_path.is_file()

    lock_context = execution_state_lock(root) if needs_lock else nullcontext()
    with lock_context:
        result = _rollback_journal_locked(root, journal)

    # Journal gate всё ещё существует, поэтому после release lock-а foreign
    # canonical sessions не успеют открыть новую state transaction. Удаляем
    # только lock, которого доказанно не было до hop.
    if transaction_created_lock:
        if lock_path.exists():
            if not lock_path.is_file():
                raise JournalError(
                    "UNSAFE_LOCAL_PATH",
                    f"transaction-created lock must remain a regular file: {EXECUTION_LOCK_PATH}",
                )
            lock_path.unlink()
            result["removedPaths"].append(EXECUTION_LOCK_PATH)

    _retire_journal_dir(root)
    return result


def _rollback_journal_locked(root: Path, journal: dict[str, Any]) -> dict[str, Any]:
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

        # Local state, затронутый target code внутри hop, откатывается так же
        # byte-for-byte, как managed files: совпадение schemaVersion не повод
        # сохранять mutation, а созданный hop-ом файл удаляется (#132).
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

    for item in journal.get("createdReports") or []:
        if isinstance(item, dict):
            rel = _rollback_owned_report(root, item)
            if rel is not None:
                removed.append(rel)
            continue
        # Journal engine-а до ReportLedger: путь записывался только после
        # создания report этим hop-ом.
        report = ensure_no_symlink_parents(root, safe_relative_path(str(item)))
        if report.is_file() and not report.is_symlink():
            report.unlink()
            removed.append(str(item))

    return {
        "rolledBack": True,
        "operation": journal.get("operation"),
        "source": journal.get("source"),
        "target": journal.get("target"),
        "state": journal.get("state"),
        "restoredPaths": restored,
        "removedPaths": removed,
    }


def _rollback_owned_report(root: Path, item: dict[str, Any]) -> str | None:
    """Удалить report, только если journal доказывает, что его создал этот hop."""
    rel = safe_relative_path(str(item.get("path")))
    report = ensure_no_symlink_parents(root, rel)
    staging_value = item.get("staging")
    staging = ensure_no_symlink_parents(root, safe_relative_path(str(staging_value))) if staging_value else None
    report_is_file = report.is_file() and not report.is_symlink()
    owned = False
    if staging is not None and staging.is_file() and not staging.is_symlink():
        # До confirm/cleanup: report наш, только если это тот же inode (link).
        owned = report_is_file and os.path.samefile(staging, report)
        staging.unlink()
    elif report_is_file and isinstance(item.get("inode"), list):
        stat = report.stat()
        owned = (
            [stat.st_dev, stat.st_ino] == item["inode"]
            and _sha256_file(report) == item.get("sha256")
        )
    if not owned:
        return None
    report.unlink()
    return rel


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recover_pending(root: Path, *, force: bool = False) -> dict[str, Any] | None:
    """Откатить прерванный hop, если его владелец больше не работает."""
    discard_retired_journals(root)
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
