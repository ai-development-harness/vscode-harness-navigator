#!/usr/bin/env python3
"""Проверка установки Harness без чтения рабочих артефактов проекта.

Это не подтверждение готовности проекта или STEP. Здесь проверяются только
служебные файлы и настройки, которыми действительно управляет updater.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import subprocess
from pathlib import Path
import tomllib

from harness_config import get, load_manifest, load_update_policy, update_lock_path
from update_recovery import ensure_no_symlink_parents, load_journal, UPDATE_TRANSACTION_ENV


def update_transaction_active(root: Path) -> bool:
    """Совместимость со старыми updater: они вызывают --mode manual.

    Старый engine уже передаёт идентификатор своей транзакции. Только точное
    совпадение с текущим журналом выбирает профиль установки автоматически.
    Обычная ручная диагностика и проверки STEP остаются полными.
    """
    identity = os.environ.get(UPDATE_TRANSACTION_ENV)
    if not identity:
        return False
    journal = load_journal(root)
    return (isinstance(journal, dict) and journal.get('transactionId') == identity
            and journal.get('state') == 'verifying')


def installation_errors(root: Path) -> list[str]:
    """Не открывает STEP/REQ/ADR/REVIEW, projections или их templates."""
    errors: list[str] = []
    manifest = load_manifest(root)
    policy = load_update_policy(root)
    ownership = policy.get('ownership', {})
    patterns = [item for name in ('harness_owned', 'shared', 'marker_merge')
                for item in ownership.get(name, [])]
    # Concrete scope only: Git index + entries written by the transaction.
    # Unknown ignored files below broad service globs are never captured.
    indexed = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root,
                             capture_output=True, check=True).stdout
    concrete = set(os.fsdecode(indexed).split("\0")) - {""}
    journal = load_journal(root)
    if journal:
        concrete.update(entry["path"] for entry in journal.get("entries", []))
    paths = {rel for rel in concrete if any(fnmatch.fnmatchcase(rel, pattern) for pattern in patterns)
             and (root / rel).exists()}
    paths.update({".harness/manifest.yaml", ".harness/harness-update.toml"})
    harness_policy = root / '.harness/harness-policy.toml'
    if harness_policy.is_file():
        required = tomllib.loads(harness_policy.read_text(encoding='utf-8')).get('required_files', [])
        for rel in required:
            if any(fnmatch.fnmatchcase(rel, pattern) for pattern in patterns):
                path = ensure_no_symlink_parents(root, rel)
                paths.add(rel)
                if not path.is_file() or path.is_symlink():
                    errors.append(f'missing managed installation file: {rel}')
    for rel in sorted(paths):
        path = ensure_no_symlink_parents(root, rel)
        if path.is_symlink() or not path.is_file():
            errors.append(f'unsafe managed installation file: {rel}')
            continue
        # Пользовательские .github templates не являются конфигурацией runtime.
        # Проверяем синтаксис только служебного кода и runtime/control-plane config.
        try:
            if rel.startswith('.harness/tools/') and path.suffix == '.py':
                ast.parse(path.read_text(encoding='utf-8'), filename=rel)
            elif rel.startswith(('.harness/', '.codex/', '.claude/')) and path.suffix == '.toml':
                tomllib.loads(path.read_text(encoding='utf-8'))
            elif rel.startswith(('.harness/', '.claude/')) and path.suffix == '.json':
                json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            errors.append(f'invalid managed installation file {rel}: {exc}')
    lock = json.loads(update_lock_path(root).read_text(encoding='utf-8'))
    source = lock.get('source')
    release = get(manifest, 'harness.release')
    if (lock.get('schemaVersion') != 1 or lock.get('release') != release
            or not isinstance(source, dict) or source.get('ref') != f'v{release}'
            or source.get('repository') != get(policy, 'source.repository')):
        errors.append('installation lock does not match manifest/source')
    return errors
