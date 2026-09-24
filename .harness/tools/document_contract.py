#!/usr/bin/env python3
"""Низкоуровневый parser/validator machine-readable Markdown Harness.

Модуль задаёт единый syntax contract для schema-v1 active documents и durable
reports. Более высокоуровневые validators не должны реализовывать собственный
YAML/Markdown parser: иначе одинаковый artifact мог бы PASS в одном месте и
FAIL в другом.

Основные обязанности:
- ограниченный YAML frontmatter через harness_config.parse_yaml_subset;
- H1/## section parsing и duplicate detection;
- common schema/kind/required-section checks;
- stable/content hashes;
- canonical durable timestamp identity;
- immutable report create через O_EXCL;
- crash-safe atomic UTF-8 writes.

Legacy document без frontmatter разрешён только caller-у, который явно передал
require_frontmatter=False. Новые mutations обязаны использовать schema=1.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable

from harness_config import ConfigError, parse_yaml_subset


STEP_ID_RE = re.compile(r"STEP-\d{3,}")
REQ_ID_RE = re.compile(r"REQ-\d{3,}")
ADR_ID_RE = re.compile(r"ADR-\d{3,}")
OQ_ID_RE = re.compile(r"OQ-\d{3,}")

STEP_STATUSES = {"planned", "in_progress", "blocked", "completed", "deferred", "cancelled"}
STEP_TYPES = {
    "implementation",
    "bugfix",
    "refactor",
    "research",
    "adr",
    "audit",
    "review",
    "hardening",
    "documentation",
    "release",
}
PRIORITIES = {"critical", "high", "medium", "low"}
ADR_STATUSES = {"proposed", "accepted", "superseded", "rejected"}
OQ_STATUSES = {"open", "resolved", "deferred"}
REVIEW_VERDICTS = {"pass", "fail", "blocked"}
PLAN_STATUSES = {"not_planned", "draft", "ready"}

UNRESOLVED_LINE_RE = re.compile(
    r"(?mi)^\s*(?:[-*]\s*)?(?:TBD|TODO|\?\?\?)\s*$"
)


class DocumentError(ValueError):
    """Ошибка parsing/contract boundary machine-readable Markdown.

    Caller должен трактовать её как invalid/blocked artifact, а не как пустой
    документ. Это ключевой fail-closed invariant всех document validators.
    """


# ---------------------------------------------------------------------------
# Canonicalization и hashes.
# Нормализация убирает только внешние пустые строки и trailing whitespace,
# сохраняя смысловое содержимое. Hashes используются как durable fingerprints.
# ---------------------------------------------------------------------------
def normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def content_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Durable report identity.
# Filename и created_at вычисляются из одного logical UTC instant. Если second
# уже занят, выбирается следующий свободный second — без overwrite/suffix.
# ---------------------------------------------------------------------------
def durable_report_timestamp(
    prefix: str,
    *,
    directory: Path | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Получить canonical filename + created_at из одного UTC logical instant.

    Если в durable directory уже занят текущий whole-second timestamp, выбирается
    следующий свободный UTC second. Это сохраняет sortable canonical naming и
    исключает overwrite без альтернативных suffix-форматов.
    """
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    while True:
        filename = prefix + instant.strftime("%Y%m%dT%H%M%SZ") + ".md"
        if directory is None:
            break
        candidate = directory / filename
        if not candidate.exists() and not candidate.is_symlink():
            break
        instant += timedelta(seconds=1)
    created_at = instant.isoformat(timespec="seconds").replace("+00:00", "Z")
    return filename, created_at


def create_durable_report(
    prefix: str,
    *,
    directory: Path,
    content_factory: Callable[[str], str],
    now: datetime | None = None,
) -> tuple[Path, str]:
    """Атомарно создать immutable timestamped report без overwrite race.

    Filename reservation и create — одна операция O_EXCL. Если другой writer
    успел занять тот же UTC second между вычислением имени и записью, caller не
    перезаписывает его report, а пробует следующий canonical second.
    """
    directory.mkdir(parents=True, exist_ok=True)
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)

    while True:
        filename = prefix + instant.strftime("%Y%m%dT%H%M%SZ") + ".md"
        path = directory / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(path, flags, 0o666)
        except FileExistsError:
            instant += timedelta(seconds=1)
            continue

        created_at = instant.isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            content = content_factory(created_at)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            path.unlink(missing_ok=True)
            raise
        return path, created_at

def parse_utc_timestamp(value: Any) -> datetime | None:
    """Разобрать timezone-aware ISO-8601 instant и нормализовать его в UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def timestamped_report_instant(name: str, prefix: str) -> datetime | None:
    """Извлечь canonical whole-second UTC timestamp из durable report filename."""
    match = re.fullmatch(rf"{re.escape(prefix)}(\d{{8}}T\d{{6}}Z)\.md", name)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


REPORT_CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def validate_report_timestamp_identity(
    path: Path,
    *,
    prefix: str,
    created_at: Any,
) -> list[str]:
    """Связать sortable filename и durable created_at одним UTC instant."""
    errors: list[str] = []
    filename_time = timestamped_report_instant(path.name, prefix)
    created = parse_utc_timestamp(created_at)
    if filename_time is None:
        errors.append(f"filename must be {prefix}<UTC timestamp>.md")
        return errors
    if created is None:
        errors.append("created_at must be timezone-aware ISO-8601")
        return errors
    if created.microsecond != 0:
        errors.append("created_at must use whole-second precision matching filename")
        return errors
    if created != filename_time:
        errors.append("created_at must match UTC timestamp encoded in filename")
    # Report «из будущего» навсегда занял бы место latest по sortable filename
    # и скрыл бы последующие реальные reports (#114). Небольшой допуск —
    # на расхождение часов между машинами.
    if created > datetime.now(timezone.utc) + REPORT_CLOCK_SKEW_TOLERANCE:
        errors.append("created_at must not be in the future")
    return errors


def stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    """Crash-safe заменить UTF-8 text artifact через fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    # mkstemp создаёт 0600: без этого каждое atomic rewrite тихо меняло бы
    # permissions tracked файла (#117). Новый файл получает обычный 0644.
    try:
        mode = path.stat().st_mode & 0o777 if path.is_file() else 0o644
    except OSError:
        mode = 0o644
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    if os.name == "posix":
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)


# ---------------------------------------------------------------------------
# Markdown parsing pipeline:
# split_frontmatter -> parse_sections -> parse_document -> higher-level checks.
# ---------------------------------------------------------------------------
def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise DocumentError("unterminated YAML frontmatter")
    raw = normalized[4:end]
    try:
        data = parse_yaml_subset(raw)
    except ConfigError as exc:
        raise DocumentError(f"invalid YAML frontmatter: {exc}") from exc
    return data, normalized[end + 5 :]


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def markdown_headings(body: str) -> list[tuple[int, int, str]]:
    """Вернуть ATX headings вне fenced code blocks.

    Harness использует headings как machine-readable boundaries. Regex по
    отдельным строкам недостаточен: ``##`` внутри fenced example не является
    структурой документа и не должен менять section/hash semantics.

    Поддерживаются backtick/tilde fences длиной >= 3: closing fence использует
    тот же символ и не короче opening fence. Незакрытый fence fail-safe
    трактует весь оставшийся текст как code content и не создаёт ложные
    machine-readable headings.
    """
    headings: list[tuple[int, int, str]] = []
    fence_char: str | None = None
    fence_length = 0

    for index, line in enumerate(body.replace("\r\n", "\n").split("\n")):
        if fence_char is not None:
            closing = re.fullmatch(
                rf" {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*",
                line,
            )
            if closing:
                fence_char = None
                fence_length = 0
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            marker = fence.group(1)
            suffix = fence.group(2)
            # Backtick info string по CommonMark не может содержать backtick.
            if marker[0] != "`" or "`" not in suffix:
                fence_char = marker[0]
                fence_length = len(marker)
                continue

        heading = _HEADING_RE.match(line)
        if heading:
            headings.append(
                (index, len(heading.group(1)), heading.group(2).strip())
            )

    return headings


def parse_sections(body: str) -> tuple[dict[str, str], list[str]]:
    """Разобрать реальные ``##`` sections и отдельно вернуть duplicate names."""
    lines = body.replace("\r\n", "\n").split("\n")
    section_headings = {
        index: title
        for index, level, title in markdown_headings(body)
        if level == 2
    }
    sections: dict[str, list[str]] = {}
    duplicates: list[str] = []
    current: str | None = None

    for index, line in enumerate(lines):
        heading = section_headings.get(index)
        if heading is not None:
            current = heading
            if current in sections:
                duplicates.append(current)
            else:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    return (
        {name: normalize_text("\n".join(value)) for name, value in sections.items()},
        duplicates,
    )

def first_h1(body: str) -> str:
    return next((line.strip() for line in body.splitlines() if line.strip()), "")


def parse_document(path: Path, *, require_frontmatter: bool = True) -> dict[str, Any]:
    """Прочитать UTF-8 Markdown и вернуть единое parsed representation.

    require_frontmatter=True — canonical mode. Legacy text без schema допустим
    только migration/compatibility caller-ам, которые явно отключают требование.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DocumentError(f"cannot read {path}: {exc}") from exc
    frontmatter, body = split_frontmatter(text)
    if require_frontmatter and frontmatter is None:
        raise DocumentError(f"{path}: legacy document has no YAML frontmatter")
    sections, duplicates = parse_sections(body)
    return {
        "path": path,
        "text": text,
        "frontmatter": frontmatter or {},
        "body": body,
        "sections": sections,
        "duplicate_sections": duplicates,
        "h1": first_h1(body),
        "legacy": frontmatter is None,
    }


# ---------------------------------------------------------------------------
# Reusable validation primitives. Они не выбрасывают exception за обычный
# contract drift, а возвращают список ошибок для агрегирующих validators.
# ---------------------------------------------------------------------------
def require_schema(document: dict[str, Any], *, kind: str | None = None) -> list[str]:
    errors: list[str] = []
    meta = document["frontmatter"]
    if meta.get("schema") != 1:
        errors.append("frontmatter schema must be 1")
    if kind is not None and meta.get("kind") != kind:
        errors.append(f"frontmatter kind must be {kind}")
    for section in document["duplicate_sections"]:
        errors.append(f"duplicate section '## {section}'")
    return errors


def require_nonempty_sections(document: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for name in names:
        if name not in document["sections"]:
            errors.append(f"missing section '## {name}'")
        elif not document["sections"][name].strip():
            errors.append(f"empty section '## {name}'")
    return errors


def has_unresolved_placeholder(value: str) -> bool:
    return bool(UNRESOLVED_LINE_RE.search(value))


def _yaml_scalar(value: Any) -> str:
    """Сериализовать scalar так, чтобы restricted parser восстановил его тип.

    Plain form разрешается только если тот же canonical parser читает значение
    обратно как exact ``str``. Это защищает строки ``"1"``, ``"001"``,
    ``"true"`` и ``"null"`` от тихого превращения в int/bool/None.
    """
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise DocumentError(f"unsupported frontmatter scalar type: {type(value).__name__}")

    if re.fullmatch(r"[A-Za-z0-9_./:@+#\-]+", value):
        try:
            parsed = parse_yaml_subset(f"value: {value}\n").get("value")
        except ConfigError:
            parsed = None
        if isinstance(parsed, str) and parsed == value:
            return value

    # JSON double-quoted string входит в поддерживаемый subset parser-а и
    # корректно экранирует quote/backslash/control characters.
    return json.dumps(value, ensure_ascii=False)

def dump_yaml_subset(value: dict[str, Any], *, indent: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = " " * indent
    for key, item in value.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            raise DocumentError(f"unsupported YAML key: {key}")
        if isinstance(item, dict):
            lines.append(f"{prefix}{key}:")
            lines.extend(dump_yaml_subset(item, indent=indent + 2))
        elif isinstance(item, list):
            if not item:
                lines.append(f"{prefix}{key}: []")
            else:
                lines.append(f"{prefix}{key}:")
                for child in item:
                    if isinstance(child, (dict, list)):
                        raise DocumentError("frontmatter block lists support scalar items only")
                    lines.append(f"{prefix}  - {_yaml_scalar(child)}")
        else:
            lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
    return lines


def render_document(frontmatter: dict[str, Any], body: str) -> str:
    yaml_lines = dump_yaml_subset(frontmatter)
    normalized_body = normalize_text(body)
    return "---\n" + "\n".join(yaml_lines) + "\n---\n\n" + normalized_body + "\n"


def validate_id(value: Any, pattern: re.Pattern[str], label: str) -> str | None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        return f"{label} must match {pattern.pattern}"
    return None


def string_list(value: Any, label: str) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [], [f"{label} must be a list of strings"]
    if len(value) != len(set(value)):
        return value, [f"{label} must not contain duplicates"]
    return value, []


def exact_h1(document: dict[str, Any], id_value: str) -> bool:
    return bool(re.fullmatch(rf"# {re.escape(id_value)} — .+", document["h1"]))
