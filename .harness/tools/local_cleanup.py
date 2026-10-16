#!/usr/bin/env python3
"""Управляемые временные файлы execution: контракт описан в LOCAL_CLEANUP.md."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import unquote
from typing import Any

from execution_status import execution_state_lock, load_status
from harness_config import load_manifest, update_report_directory, task_directory
from document_contract import parse_document
from planning_contract import step_completion_proof

BASE = Path('.harness/local/tmp')
MARKER = '.harness-owner.json'
EXECUTION_ID = re.compile(r'exec-[0-9a-f]{32}\Z')


class CleanupError(ValueError):
    """Короткая причина сохранения, без необработанных путей и ошибок ОС."""


def identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def safe_info(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise CleanupError('UNSAFE_LINK')
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise CleanupError('UNSAFE_FILE_TYPE')
    return info


def safe_path(root: Path, relative: Path, *, create: bool = False) -> Path:
    if relative.is_absolute() or '..' in relative.parts:
        raise CleanupError('UNSAFE_PATH')
    path = root
    safe_info(path)
    for part in relative.parts:
        path = path / part
        try:
            info = safe_info(path)
        except FileNotFoundError:
            if not create:
                raise
            path.mkdir()
            info = safe_info(path)
        if not stat.S_ISDIR(info.st_mode):
            raise CleanupError('UNSAFE_PARENT')
    return path


def records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [*state['executions'], *state['recentTerminals']]


def owner_marker(path: Path, execution_id: str) -> dict[str, Any]:
    marker_path = path / MARKER
    info = safe_info(marker_path)
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise CleanupError('UNKNOWN_OWNER')
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise CleanupError('UNKNOWN_OWNER') from None
    if not isinstance(marker, dict) or marker != {
        'schemaVersion': 1, 'executionId': execution_id,
        'directoryIdentity': list(identity(safe_info(path))),
    }:
        raise CleanupError('UNKNOWN_OWNER')
    return marker


def temporary_directory(root: Path, execution_id: str) -> str:
    """Выдать только зарегистрированному владельцу каталог; повторный handoff его сохраняет."""
    root = root.resolve()
    if not EXECUTION_ID.fullmatch(execution_id):
        raise CleanupError('INVALID_EXECUTION_ID')
    with execution_state_lock(root):
        state = load_status(root, read_only=True)
        if not any(item['executionId'] == execution_id and item['status'] == 'running'
                   for item in state['executions']):
            raise CleanupError('OWNER_NOT_RUNNING')
        from contextlib import ExitStack
        with ExitStack() as stack:
            # Закрепляем всю цепочку родителей до mkdir/open, чтобы подмена
            # пути не перенаправила создание маркера за пределы tmp.
            if os.name == 'nt':
                current = root
                stack.enter_context(windows_handle(current))
                for part in BASE.parts:
                    current = current / part
                    current.mkdir(exist_ok=True)
                    stack.enter_context(windows_handle(current))
                path = current / execution_id
                try:
                    path.mkdir()
                    created = True
                except FileExistsError:
                    created = False
                stack.enter_context(windows_handle(path))
                if created:
                    marker_file = stack.enter_context((path / MARKER).open('x', encoding='utf-8'))
                else:
                    owner_marker(path, execution_id)
            else:
                def open_dir(name: str, parent_fd: int | None = None) -> int:
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    stack.callback(os.close, fd)
                    return fd
                parent_fd = open_dir(str(root))
                for part in BASE.parts:
                    try:
                        os.mkdir(part, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    parent_fd = open_dir(part, parent_fd)
                try:
                    os.mkdir(execution_id, dir_fd=parent_fd)
                    created = True
                except FileExistsError:
                    created = False
                directory_fd = open_dir(execution_id, parent_fd)
                path = root / BASE / execution_id
                if identity(os.fstat(directory_fd)) != identity(safe_info(path)):
                    raise CleanupError('CANDIDATE_CHANGED')
                if created:
                    marker_fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                        0o600, dir_fd=directory_fd)
                    marker_file = stack.enter_context(os.fdopen(marker_fd, 'w', encoding='utf-8'))
                else:
                    owner_marker(path, execution_id)
            if created:
                marker_file.write(json.dumps({
                    'schemaVersion': 1, 'executionId': execution_id,
                    'directoryIdentity': list(identity(safe_info(path))),
                }) + '\n')
                marker_file.flush()
            safe_path(root, BASE / execution_id)
            owner_marker(path, execution_id)

        return (BASE / execution_id).as_posix()


def tree_snapshot(path: Path) -> dict[str, tuple[int, int, int, int, int]]:
    result = {}
    def visit(current: Path, relative: str) -> None:
        info = safe_info(current)
        if current.name.lower().endswith('.lock'):
            raise CleanupError('LOCK_FILE')
        result[relative] = (*identity(info), info.st_mode, info.st_size, info.st_mtime_ns)
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(current.iterdir()):
                visit(child, f'{relative}/{child.name}' if relative else child.name)
    visit(path, '')
    return result


def canonical_texts(root: Path) -> list[tuple[Path, str]]:
    """Читать configured artifacts без следования ссылкам; неизвестный формат запрещает уборку."""
    manifest = load_manifest(root)
    paths = []
    for section in ('sources', 'protocol'):
        values = manifest.get(section)
        if not isinstance(values, dict):
            raise CleanupError('REFERENCES_UNAVAILABLE')
        for value in values.values():
            if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
                raise CleanupError('REFERENCES_UNAVAILABLE')
            paths.append(Path(value))
    paths.append(update_report_directory(root).relative_to(root))
    texts = []
    seen = set()
    def visit(path: Path) -> None:
        if path in seen:
            return
        seen.add(path)
        info = safe_info(path)
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                visit(child)
        else:
            texts.append((path, path.read_text(encoding='utf-8')))
    for relative in paths:
        try:
            safe_path(root, relative.parent)
            visit(root / relative)
        except FileNotFoundError:
            # Не созданный optional artifact не содержит ссылок. Ошибка
            # чтения существующего artifact обрабатывается fail-closed ниже.
            if (root / relative).exists():
                raise CleanupError('REFERENCES_UNAVAILABLE') from None
    # STEP может явно подключать subsystem docs вне configured roots.
    # Это canonical context, поэтому его ссылки тоже удерживают tmp (#334).
    tasks = task_directory(root)
    for path in list(seen):
        if path.parent != tasks or not re.fullmatch(r'STEP-[0-9]+\.md', path.name):
            continue
        refs = parse_document(path)['frontmatter'].get('architecture_refs')
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise CleanupError('REFERENCES_UNAVAILABLE')
        for ref in refs:
            value = ref.partition('#')[0]
            relative = Path(value)
            if not value or relative.is_absolute() or '..' in relative.parts:
                raise CleanupError('REFERENCES_UNAVAILABLE')
            safe_path(root, relative.parent)
            visit(root / relative)
    return texts


def step_ids(item: dict[str, Any]) -> set[str]:
    # Root хранит всю explicit chain даже после compaction terminal record.
    return set(re.findall(r'\bSTEP-\d+\b', item['rootCommand']))


def eligibility(root: Path, state: dict[str, Any], execution_id: str, texts: list[tuple[Path, str]]) -> str:
    owner = next((item for item in records(state) if item['executionId'] == execution_id), None)
    if owner is None:
        return 'OWNER_PROOF_MISSING'
    if owner['status'] != 'complete' or owner.get('current', {}).get('result') not in {'PASS', 'SUCCESS'}:
        return 'OWNER_NOT_COMPLETE'
    steps = step_ids(owner)
    for active in state['executions']:
        if steps & step_ids(active) or execution_id in json.dumps(active, ensure_ascii=False):
            return 'ACTIVE_DEPENDENCY'
    for step_id in sorted(steps):
        if step_completion_proof(root, step_id).get('complete') is not True:
            return 'STEP_NOT_COMPLETE'
    candidate = root / BASE / execution_id
    for document, text in texts:
        normalized = re.sub('/+', '/', text.replace('\\', '/'))
        if (BASE / execution_id).as_posix() in unquote(normalized):
            return 'CANONICAL_REFERENCE'
        # Metadata execution_id не ссылка. Токен с path-разделителем
        # проверяем и как repository path, и относительно исходного документа.
        for token in re.findall(r"[^\s<>\"'`()]*" + re.escape(execution_id) + r"[^\s<>\"'`()]*", normalized):
            token = unquote(token.split('#', 1)[0].split('?', 1)[0])
            if '/' not in token:
                continue
            target = Path(token)
            for base in (root, document.parent):
                resolved = (base / target).resolve()
                if resolved == candidate or candidate in resolved.parents:
                    return 'CANONICAL_REFERENCE'
    return 'ELIGIBLE'


def inspect(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    report: dict[str, Any] = {'schemaVersion': 1, 'status': 'PASS', 'candidates': [], 'files': 0, 'bytes': 0}
    snapshots = {}
    try:
        parent = safe_path(root, BASE)
    except FileNotFoundError:
        return report, snapshots
    state = load_status(root, read_only=True)
    try:
        texts = canonical_texts(root)
    except (OSError, ValueError, UnicodeError):
        texts = None
    for path in sorted(parent.iterdir()):
        entry = {'path': (BASE / path.name).as_posix(), 'files': 0, 'bytes': 0, 'eligible': False}
        try:
            if not EXECUTION_ID.fullmatch(path.name):
                raise CleanupError('UNKNOWN_OWNER')
            safe_path(root, BASE / path.name)
            owner_marker(path, path.name)
            snapshot = tree_snapshot(path)
            entry['files'] = sum(stat.S_ISREG(item[2]) for item in snapshot.values())
            entry['bytes'] = sum(item[3] for item in snapshot.values() if stat.S_ISREG(item[2]))
            reason = 'REFERENCES_UNAVAILABLE' if texts is None else eligibility(root, state, path.name, texts)
            entry['reasonCode'] = reason
            entry['eligible'] = reason == 'ELIGIBLE'
            snapshots[path.name] = snapshot
        except (OSError, ValueError, UnicodeError) as exc:
            entry['reasonCode'] = str(exc) if isinstance(exc, CleanupError) else 'PROOF_UNAVAILABLE'
        if entry['eligible']:
            report['files'] += entry['files']
            report['bytes'] += entry['bytes']
        report['candidates'].append(entry)
    return report, snapshots


@contextmanager
def windows_handle(path: Path, *, delete: bool = False):
    """Удержать Windows path от rename/reparse-подмены до удаления через тот же handle."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # Предкам достаточно LIST_DIRECTORY + READ_ATTRIBUTES: DELETE конфликтует с cwd handle.
    # LIST_DIRECTORY включает share accounting, в отличие от одного metadata access.
    # DELETE запрашиваем только для удаляемого объекта; sharing запрещает подмену/запись.
    access = 0x81 | (0x10000 if delete else 0)
    handle = create(str(path), access, 1, None, 3, 0x02000000 | 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise CleanupError('HANDLE_UNAVAILABLE:' + str(ctypes.get_last_error()))
    try:
        safe_info(path)
        yield kernel, handle
    finally:
        close(handle)


def remove_tree(root: Path, name: str, expected: dict[str, Any]) -> None:
    """Удаление по проверенным identity, без переходов через изменившиеся родители."""
    path = safe_path(root, BASE / name)
    if tree_snapshot(path) != expected:
        raise CleanupError('CANDIDATE_CHANGED')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        from contextlib import ExitStack
        # Предки удерживаются handles без FILE_SHARE_DELETE. Потомки удаляются
        # по своим handles, поэтому rename не перенаправит удаление наружу.
        with ExitStack() as stack:
            current = root
            stack.enter_context(windows_handle(current))
            for part in BASE.parts:
                current = current / part
                stack.enter_context(windows_handle(current))
            def remove(current: Path, rel: str) -> None:
                with windows_handle(current, delete=True) as (kernel, handle):
                    info = safe_info(current)
                    if (*identity(info), info.st_mode, info.st_size, info.st_mtime_ns) != expected[rel]:
                        raise CleanupError('CANDIDATE_CHANGED')
                    if stat.S_ISDIR(info.st_mode):
                        for child in sorted(current.iterdir()):
                            child_rel = f'{rel}/{child.name}' if rel else child.name
                            if child_rel not in expected:
                                raise CleanupError('CANDIDATE_CHANGED')
                            remove(child, child_rel)
                    disposition = ctypes.c_ubyte(1)
                    setter = kernel.SetFileInformationByHandle
                    setter.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                    setter.restype = wintypes.BOOL
                    if not setter(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
                        raise CleanupError('DELETE_UNAVAILABLE')
            remove(path, '')
    else:
        from contextlib import ExitStack
        with ExitStack() as stack:
            def open_dir(name: str, parent: int | None = None) -> int:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                stack.callback(os.close, fd)
                return fd
            parent = open_dir(str(root))
            for part in BASE.parts:
                parent = open_dir(part, parent)
            # POSIX не имеет unlink-by-inode. Атомарно захватываем candidate
            # в приватный случайный namespace, затем проверяем захваченное дерево.
            # Обычный writer исходного имени больше не может подменить leaf.
            quarantine = '.cleanup-' + uuid.uuid4().hex
            os.mkdir(quarantine, 0o700, dir_fd=parent)
            quarantine_fd = open_dir(quarantine, parent)
            os.rename(name, 'candidate', src_dir_fd=parent, dst_dir_fd=quarantine_fd)
            captured = root / BASE / quarantine / 'candidate'
            if tree_snapshot(captured) != expected:
                raise CleanupError('CAPTURE_CHANGED:' + (BASE / quarantine).as_posix())
            def remove(parent_fd: int, leaf: str, rel: str) -> None:
                info = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                if (*identity(info), info.st_mode, info.st_size, info.st_mtime_ns) != expected[rel]:
                    raise CleanupError('CANDIDATE_CHANGED')
                if stat.S_ISDIR(info.st_mode):
                    with ExitStack() as directory_stack:
                        fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                        directory_stack.callback(os.close, fd)
                        if identity(os.fstat(fd)) != identity(info):
                            raise CleanupError('CANDIDATE_CHANGED')
                        for child in sorted(os.listdir(fd)):
                            child_rel = f'{rel}/{child}' if rel else child
                            if child_rel not in expected:
                                raise CleanupError('CANDIDATE_CHANGED')
                            remove(fd, child, child_rel)
                        if identity(os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)) != identity(info):
                            raise CleanupError('CANDIDATE_CHANGED')
                        os.rmdir(leaf, dir_fd=parent_fd)
                else:
                    os.unlink(leaf, dir_fd=parent_fd)
            try:
                remove(quarantine_fd, 'candidate', '')
                os.rmdir(quarantine, dir_fd=parent)
            except (OSError, ValueError):
                # Не возвращаем каталог на уже занятое исходное имя. Остаток
                # сохраняется как unknown для ручной диагностики, без усыновления.
                raise CleanupError('DELETE_RETAINED:' + (BASE / quarantine).as_posix()) from None


def cleanup(root: Path, *, apply: bool = False) -> dict[str, Any]:
    """CHECK ничего не пишет. APPLY удерживает общий lock вместе с повторной проверкой."""
    root = root.resolve()
    try:
        if not apply:
            return inspect(root)[0]
        with execution_state_lock(root):
            report, snapshots = inspect(root)
            for entry in report['candidates']:
                if not entry['eligible']:
                    continue
                name = Path(entry['path']).name
                try:
                    # CHECK не является разрешением. Даже внутри lock повторяем
                    # reference/proof проверку перед каждым отдельным удалением.
                    fresh, current = inspect(root)
                    candidate = next((item for item in fresh['candidates'] if item['path'] == entry['path']), None)
                    if not candidate or not candidate['eligible'] or current.get(name) != snapshots[name]:
                        raise CleanupError('CANDIDATE_CHANGED')
                    remove_tree(root, name, snapshots[name])
                    entry['removed'] = True
                except (OSError, ValueError) as exc:
                    entry['removed'] = False
                    entry['reasonCode'] = str(exc) if isinstance(exc, CleanupError) else 'DELETE_UNAVAILABLE'
                    report['status'] = 'WARNING'
            return report
    except (OSError, ValueError, RuntimeError):
        return {'schemaVersion': 1, 'status': 'WARNING', 'reasonCode': 'CLEANUP_UNAVAILABLE',
                'candidates': [], 'files': 0, 'bytes': 0}


def main() -> int:
    parser = argparse.ArgumentParser(description='Проверить или удалить завершённые временные каталоги Harness')
    parser.add_argument('action', choices=('check', 'apply'))
    args = parser.parse_args()
    report = cleanup(Path(__file__).resolve().parents[2], apply=args.action == 'apply')
    print(json.dumps(report, ensure_ascii=False, separators=(',', ':')))
    return 0 if report['status'] == 'PASS' else 2
