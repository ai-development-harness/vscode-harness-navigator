#!/usr/bin/env python3
"""Проверки безопасного чтения и записи локальных execution checkpoints (#285).

Каждый сценарий использует отдельный временный проект. При повреждении state
проверяем не только ошибку, но и сохранность исходных bytes: повторный запуск
не должен перезаписать последнее состояние пустой историей.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from execution_status import (
    ExecutionCheckpointError,
    empty_status,
    load_status,
    save_status,
    status_path,
)


def rejected(root: Path, reason: str) -> None:
    """Недоступный или повреждённый checkpoint нельзя считать новым."""
    try:
        load_status(root)
    except ExecutionCheckpointError as exc:
        assert exc.kind == reason, (reason, exc.kind, str(exc))
    else:
        raise AssertionError(f"checkpoint unexpectedly accepted as fresh: {reason}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="checkpoint-recovery-") as tmp:
        root = Path(tmp)
        path = status_path(root)
        path.parent.mkdir(parents=True)

        # Первое обращение к действительно отсутствующему состоянию допустимо.
        assert load_status(root) == empty_status()
        save_status(root, empty_status())
        original = path.read_bytes()
        assert load_status(root) == empty_status()

        # Некорректный JSON/тип корня/схема — не повод обнулять state.
        for payload, kind in (
            (b'{"schemaVersion":2,"executions":', "CORRUPTED"),
            (b'[]\n', "CORRUPTED"),
            (b'{"schemaVersion":999}\n', "INCOMPATIBLE"),
        ):
            path.write_bytes(payload)
            rejected(root, kind)
            # Даже прямой save_status не должен затереть corrupted checkpoint.
            try:
                save_status(root, empty_status())
            except ExecutionCheckpointError as exc:
                assert exc.kind == kind, (kind, exc.kind)
            else:
                raise AssertionError("direct writer overwrote corrupt state")
            assert path.read_bytes() == payload
        path.write_bytes(original)

        # Отсутствие доступа, в том числе ошибка чтения после lstat, —
        # это UNAVAILABLE, а не честный NOT_FOUND.
        with patch("execution_status.json.load", side_effect=PermissionError("denied")):
            rejected(root, "UNAVAILABLE")
        assert path.read_bytes() == original
        with patch("execution_status.Path.lstat", side_effect=PermissionError("denied")):
            rejected(root, "UNAVAILABLE")
        assert path.read_bytes() == original

        # Каталог, появившийся вместо status-файла, не должен быть
        # распознан как пустая история. Данные восстанавливаем после теста.
        path.unlink()
        path.mkdir()
        rejected(root, "INCOMPATIBLE")
        path.rmdir()

        # dangling symlink и symlink на чужой файл — тоже не fresh start.
        if hasattr(os, "symlink"):
            link_target = root / "external-checkpoint.json"
            link_target.write_bytes(original)
            try:
                path.symlink_to("nonexistent.json")
            except (OSError, NotImplementedError):
                pass  # Некоторые Windows окружения запрещают создание symlink.
            else:
                rejected(root, "INCOMPATIBLE")
                path.unlink()
                path.symlink_to(link_target)
                rejected(root, "INCOMPATIBLE")
                assert link_target.read_bytes() == original
                path.unlink()

        path.write_bytes(original)
        # Не разыменовываем symlink в пути .harness/local/execution.
        external_dir = root / "external-store"
        external_dir.mkdir()
        path.unlink()
        (path.parent / "execution-status.lock").unlink(missing_ok=True)
        path.parent.rmdir()
        try:
            path.parent.symlink_to(external_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            path.parent.mkdir()
        else:
            rejected(root, "INCOMPATIBLE")
            assert not list(external_dir.iterdir())
            path.parent.unlink()
            path.parent.mkdir()
        path.write_bytes(original)

        # Crash до os.replace оставляет последнюю корректную запись byte-for-byte.
        changed = {**empty_status(), "nextOrdinal": 2}
        with patch("execution_status.os.replace", side_effect=OSError("crash before replace")):
            try:
                save_status(root, changed)
            except OSError as exc:
                assert "crash" in str(exc)
            else:
                raise AssertionError("injected write crash did not fail")
        assert path.read_bytes() == original
        assert not list(path.parent.glob("execution-status.json.*.tmp"))
        assert load_status(root) == empty_status()

        # Маркер вне .harness/local отличает новое checkout от ранее
        # работавшего проекта с временно пропавшим каталогом/томом.
        marker = root / ".harness/.execution-checkpoint-known"
        assert marker.is_file()
        original_bytes = path.read_bytes()
        original_directory = path.parent
        hidden = original_directory.with_name("execution-hidden")
        original_directory.rename(hidden)
        try:
            rejected(root, "UNAVAILABLE")
            try:
                save_status(root, empty_status())
            except ExecutionCheckpointError as exc:
                assert exc.kind == "UNAVAILABLE", exc
            else:
                raise AssertionError("lost execution directory was initialized again")
            assert not original_directory.exists()
        finally:
            hidden.rename(original_directory)
        assert path.read_bytes() == original_bytes
        assert load_status(root) == empty_status()

        local = root / ".harness/local"
        missing_local = root / ".harness/local-hidden"
        local.rename(missing_local)
        try:
            rejected(root, "UNAVAILABLE")
            assert not local.exists()
        finally:
            missing_local.rename(local)
        assert load_status(root) == empty_status()

        # В реальном fresh checkout маркера нет; это разрешённый init без
        # дополнительных действий и без привязки к выбранному runtime.
        with tempfile.TemporaryDirectory(prefix="fresh-checkout-") as fresh_tmp:
            fresh_root = Path(fresh_tmp)
            assert load_status(fresh_root) == empty_status()
            save_status(fresh_root, empty_status())
            assert (fresh_root / ".harness/.execution-checkpoint-known").is_file()
            assert load_status(fresh_root) == empty_status()

    print("CHECKPOINT RECOVERY SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
