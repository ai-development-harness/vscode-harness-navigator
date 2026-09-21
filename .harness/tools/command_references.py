#!/usr/bin/env python3
"""Детерминированный поиск устаревших ссылок на Harness commands в тексте.

Модуль намеренно не решает, является ли найденное упоминание фактическим drift:
он только находит command-looking legacy forms и предлагает каноническую замену.
Решение о том, является ли упоминание исторически намеренным, принимает caller.

Один и тот же набор patterns используют Harness Integrity и PROJECT RECONCILE,
чтобы правила legacy syntax не расходились между двумя проверками.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from harness_config import (
    adr_directory,
    architecture_path,
    open_questions_directory,
    open_questions_index_path,
    project_overview_path,
    requirements_directory,
    roadmap_path,
    status_path,
    task_directory,
)


@dataclass(frozen=True)
class DeprecatedCommandPattern:
    pattern: re.Pattern[str]
    legacy: str
    canonical: str


@dataclass(frozen=True)
class DeprecatedCommandFinding:
    path: str
    line: int
    legacy: str
    canonical: str
    excerpt: str


# ---------------------------------------------------------------------------
# Closed mapping legacy syntax -> canonical syntax.
# Pattern должен быть достаточно узким, чтобы не ловить обычную prose, но
# достаточно широким для реально существовавших pre-namespace команд.
# ---------------------------------------------------------------------------
DEPRECATED_COMMAND_PATTERNS: tuple[DeprecatedCommandPattern, ...] = (
    DeprecatedCommandPattern(re.compile(r"\bINIT PROJECT\b"), "INIT PROJECT", "PROJECT INIT"),
    DeprecatedCommandPattern(re.compile(r"\bADD STEP(?=[:\s])"), "ADD STEP", "STEP ADD:"),
    DeprecatedCommandPattern(re.compile(r"\bFIND SKILL(?=[:\s])"), "FIND SKILL", "SKILL FIND:"),
    DeprecatedCommandPattern(re.compile(r"\bINSTALL SKILL(?=[:\s])"), "INSTALL SKILL", "SKILL INSTALL:"),
    DeprecatedCommandPattern(re.compile(r"\bCREATE SKILL(?=[:\s])"), "CREATE SKILL", "SKILL CREATE:"),
    DeprecatedCommandPattern(re.compile(r"\bGENERATE GITHUB TEMPLATES\b"), "GENERATE GITHUB TEMPLATES", "GITHUB GENERATE TEMPLATES"),
    DeprecatedCommandPattern(re.compile(r"\bSTATUS PROJECT\b"), "STATUS PROJECT", "PROJECT STATUS"),
    DeprecatedCommandPattern(re.compile(r"\bNEXT STEP\b"), "NEXT STEP", "STEP NEXT"),
    DeprecatedCommandPattern(re.compile(r"\bRECONCILE PROJECT\b"), "RECONCILE PROJECT", "PROJECT RECONCILE"),
    DeprecatedCommandPattern(re.compile(r"\bCHECK HARNESS UPDATE\b"), "CHECK HARNESS UPDATE", "HARNESS UPDATE CHECK"),
    DeprecatedCommandPattern(re.compile(r"\bUPDATE HARNESS(?:\s+TO\b|\b)"), "UPDATE HARNESS", "HARNESS UPDATE APPLY"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*QUICK FIX(?=[:\x60\s]|$)"), "QUICK FIX", "PROJECT QUICK FIX:"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bPLAN STEP-"), "PLAN STEP-NNN", "STEP PLAN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bIMPLEMENT STEP-"), "IMPLEMENT STEP-NNN", "STEP IMPLEMENT STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bREVIEW STEP-"), "REVIEW STEP-NNN", "STEP REVIEW STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bFIX STEP-"), "FIX STEP-NNN", "STEP FIX STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bRUN STEP-"), "RUN STEP-NNN", "STEP RUN STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?<!STEP )\bAUDIT STEP-"), "AUDIT STEP-NNN", "STEP AUDIT STEP-NNN"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*COMMIT(?=[:\x60\s]|$)"), "COMMIT", "GIT COMMIT"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*PUSH(?=[\x60\s]|$)"), "PUSH", "GIT PUSH"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*PR(?=[\x60\s]|$)"), "PR", "GIT PR"),
    DeprecatedCommandPattern(re.compile(r"(?m)(?:^|\x60)\s*SYNC(?=[\x60\s]|$)"), "SYNC", "GIT SYNC"),
)


def find_deprecated_commands(text: str) -> list[tuple[DeprecatedCommandPattern, re.Match[str]]]:
    """Вернуть все legacy command matches в порядке появления.

    Функция ничего не знает о path/history и не решает, допустим ли match как
    исторический пример. Она только детерминированно распознаёт syntax.
    """
    matches: list[tuple[DeprecatedCommandPattern, re.Match[str]]] = []
    for spec in DEPRECATED_COMMAND_PATTERNS:
        matches.extend((spec, match) for match in spec.pattern.finditer(text))
    matches.sort(key=lambda item: item[1].start())
    return matches


def scan_files(root: Path, paths: Iterable[Path]) -> list[DeprecatedCommandFinding]:
    """Просканировать UTF-8 text files и вернуть line-addressable findings.

    Duplicate paths дедуплицируются. Ошибка чтения любого файла блокирует весь
    scan, потому что частичный scope создавал бы ложный PASS.
    """
    findings: list[DeprecatedCommandFinding] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"cannot read live project document {path}: {exc}") from exc
        lines = text.splitlines()
        for spec, match in find_deprecated_commands(text):
            line = text.count("\n", 0, match.start()) + 1
            source_line = lines[line - 1] if lines else ""
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except ValueError:
                rel = str(path)
            findings.append(
                DeprecatedCommandFinding(
                    path=rel,
                    line=line,
                    legacy=spec.legacy,
                    canonical=spec.canonical,
                    excerpt=source_line.strip(),
                )
            )
    return findings


def _manifest_project_paths(root: Path) -> tuple[list[Path], Path]:
    """Разрешить manifest-controlled live paths через единый config layer.

    Любая ошибка config/path containment переводится в RuntimeError для
    публичного checker-а, который затем вернёт BLOCKED.
    """
    try:
        project_paths = [
            project_overview_path(root),
            requirements_directory(root),
            architecture_path(root),
            open_questions_directory(root),
            open_questions_index_path(root),
            roadmap_path(root),
            status_path(root),
        ]
        tasks = task_directory(root)
    except Exception as exc:
        raise RuntimeError(f"cannot resolve command-reference scan paths: {exc}") from exc
    return project_paths, tasks


def project_live_document_paths(root: Path) -> list[Path]:
    """Вернуть active project-owned docs, где command syntax должен быть текущим.

    Scope намеренно строится из manifest + live subsystem docs. Immutable
    canonical ADR history исключается только точечно по lexical identity, а не
    blanket-ignore всей configured ADR directory.


    Primary project paths, Open Questions и taskDirectory берутся через единый
    manifest config layer. Source path может быть файлом или каталогом. Дополнительно
    сканируются README и default live subsystem docs под docs/**. Из configured
    ADR directory исключаются только canonical ADR-файлы как decision history;
    сам directory не становится blanket ignore-root.
    """
    manifest_paths, task_directory = _manifest_project_paths(root)
    paths = [root / "README.md"]
    for path in manifest_paths:
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.md")))
        else:
            paths.append(path)

    # Default docs tree остаётся дополнительной scan surface для subsystem docs.
    # Configurable adrDirectory может быть широким (вплоть до docs), поэтому
    # исключаем только canonical ADR documents, а не весь subtree.
    docs_root = root / "docs"
    try:
        configured_adr = adr_directory(root)
    except Exception as exc:
        raise RuntimeError(f"cannot resolve configured ADR directory: {exc}") from exc
    if docs_root.exists():
        for path in sorted(docs_root.rglob("*.md")):
            # Исторический ADR определяется lexical repository path. Symlink
            # из другого subsystem path в ADR target остаётся live document и
            # не должен исчезать из command-reference scan.
            is_canonical_adr = (
                path.parent == configured_adr
                and re.fullmatch(r"ADR-\d{3,}(?:-.+)?\.md", path.name) is not None
            )
            if is_canonical_adr:
                continue
            paths.append(path)

    paths.extend(sorted(task_directory.glob("STEP-*.md")))
    return paths
