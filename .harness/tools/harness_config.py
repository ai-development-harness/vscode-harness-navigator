#!/usr/bin/env python3
"""Единый dependency-free config/validation boundary AI Development Harness.

Все core tools читают manifest/path/policy values через этот module, чтобы:
- одинаково интерпретировать restricted YAML subset;
- одинаково запрещать path escape;
- не дублировать hard-coded repository topology;
- не иметь разных fallback semantics у разных validators.

YAML parser намеренно поддерживает только используемый Harness subset.
Unsupported syntax не "угадывается": ConfigError делает boundary fail-closed.

TOML parsing использует stdlib tomllib. Этот module проверяет синтаксис и
базовые typed accessors; exact schema конкретных policies проверяют validators,
которые владеют их semantics.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import tomllib
from typing import Any


class ConfigError(ValueError):
    """Недоказуемая/невалидная Harness configuration boundary.

    Caller не должен подменять ConfigError default-значением, если параметр
    является safety/identity invariant.
    """


# ---------------------------------------------------------------------------
# Restricted YAML lexer/parser.
# Реализован здесь, а не через external dependency, чтобы baseline validator
# работал сразу после checkout.
# ---------------------------------------------------------------------------
def _strip_comment(raw: str) -> str:
    """Удалить YAML comment вне кавычек только после separation whitespace.

    В plain scalar символ ``#`` является частью значения, если перед ним нет
    whitespace. Поэтому ``C#`` и ``docs/architecture.md#auth`` должны
    сохраняться, а ``value # comment`` — обрезаться до ``value``.
    """
    quote: str | None = None
    escaped = False
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if (
            char == "#"
            and quote is None
            and (index == 0 or raw[index - 1].isspace())
        ):
            return raw[:index].rstrip()
    return raw.rstrip()


def _scalar(raw: str) -> Any:
    value = raw.strip()
    if value in {"", "~", "null", "Null", "NULL"}:
        return None
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"invalid quoted YAML scalar: {value}") from exc
            if not isinstance(parsed, str):
                raise ConfigError(f"quoted YAML scalar must be a string: {value}")
            return parsed
        # Restricted single-quoted YAML: doubled apostrophe encodes one apostrophe.
        return value[1:-1].replace("''", "'")
    # Harness не использует YAML anchors/tags/flow collections: их лучше
    # отвергнуть, чем интерпретировать иначе в разных tools.
    if value.startswith(("[", "{", "&", "*", "!")):
        raise ConfigError(f"unsupported YAML scalar syntax: {value}")
    return value


def parse_yaml_subset(text: str) -> dict[str, Any]:
    """Разобрать строго ограниченный mapping/list subset YAML.

    Duplicate keys, tabs, odd indentation, anchors/tags, flow collections и
    list-of-maps отвергаются. Такой fail-closed subset лучше частичной поддержки
    YAML, которая могла бы интерпретироваться по-разному разными tools.


    Поддерживаются nested mappings, scalar values и block lists из scalar
    элементов. Tabs, multiline scalars, anchors/tags и list-of-maps запрещены.
    """
    tokens: list[tuple[int, str, int]] = []
    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ConfigError(f"tabs are not allowed for YAML indentation: line {number}")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2:
            raise ConfigError(f"YAML indentation must use 2-space levels: line {number}")
        tokens.append((indent, line.strip(), number))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(tokens):
            return {}, index
        if tokens[index][0] != indent:
            raise ConfigError(f"unexpected YAML indentation at line {tokens[index][2]}")
        is_list = tokens[index][1].startswith("- ")
        container: Any = [] if is_list else {}
        while index < len(tokens):
            current_indent, body, number = tokens[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ConfigError(f"unexpected nested YAML block at line {number}")
            if is_list:
                if not body.startswith("- "):
                    raise ConfigError(f"mixed mapping/list YAML block at line {number}")
                item = body[2:].strip()
                if not item or re.match(r"^[A-Za-z0-9_.-]+:\s*", item):
                    raise ConfigError(
                        f"frontmatter/config lists support scalar items only: line {number}"
                    )
                container.append(_scalar(item))
                index += 1
                continue

            if body.startswith("- "):
                raise ConfigError(f"mixed mapping/list YAML block at line {number}")
            match = re.fullmatch(r"([A-Za-z0-9_.-]+):(?:\s+(.*))?", body)
            if not match:
                raise ConfigError(f"invalid YAML mapping entry at line {number}: {body}")
            key, raw_value = match.groups()
            if key in container:
                raise ConfigError(f"duplicate YAML key {key!r} at line {number}")
            index += 1
            if raw_value is not None:
                container[key] = _scalar(raw_value)
                continue
            if index < len(tokens) and tokens[index][0] > indent:
                if tokens[index][0] != indent + 2:
                    raise ConfigError(
                        f"YAML nesting must increase by 2 spaces at line {tokens[index][2]}"
                    )
                value, index = parse_block(index, indent + 2)
                container[key] = value
            else:
                container[key] = {}
        return container, index

    if not tokens:
        return {}
    if tokens[0][0] != 0:
        raise ConfigError("YAML root must start at indentation 0")
    value, consumed = parse_block(0, 0)
    if consumed != len(tokens) or not isinstance(value, dict):
        raise ConfigError("YAML root must be a mapping")
    return value


# ---------------------------------------------------------------------------
# Manifest access.
# Чтение всегда идёт из fixed bootstrap path; последующие project paths уже
# разрешаются из manifest через resolve_repo_path().
# ---------------------------------------------------------------------------
def load_manifest(root: Path) -> dict[str, Any]:
    path = root / ".harness" / "manifest.yaml"
    try:
        return parse_yaml_subset(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ConfigError) as exc:
        raise ConfigError(f"cannot read Harness manifest {path}: {exc}") from exc


def get(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def require(config: dict[str, Any], dotted: str) -> Any:
    value = get(config, dotted)
    if value is None:
        raise ConfigError(f"missing required config value: {dotted}")
    return value


def resolve_repo_path(root: Path, value: str, *, label: str) -> Path:
    """Разрешить repository-relative path и запретить absolute/.. / symlink escape."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty repository-relative path")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ConfigError(f"{label} must stay inside repository: {value}")
    base = root.resolve()
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ConfigError(f"{label} escapes repository: {value}") from exc
    return candidate


# Все path accessors ниже intentionally проходят через один containment check.
# Ни один caller не должен вручную конкатенировать configured repository path.
def manifest_path(root: Path, dotted: str) -> Path:
    manifest = load_manifest(root)
    value = require(manifest, dotted)
    return resolve_repo_path(root, value, label=f"manifest {dotted}")


def task_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.taskDirectory")


def review_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.reviewDirectory")


def planning_review_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.planningReviewDirectory")


def init_review_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.initReviewDirectory")


def audit_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.auditDirectory")


def release_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.releaseDirectory")


def skill_search_directory(root: Path) -> Path:
    return manifest_path(root, "protocol.skillSearchDirectory")


def skill_registry_path(root: Path) -> Path:
    return manifest_path(root, "protocol.skillRegistry")


def requirements_directory(root: Path) -> Path:
    return manifest_path(root, "sources.requirements")


def adr_directory(root: Path) -> Path:
    return manifest_path(root, "sources.adrDirectory")


def architecture_path(root: Path) -> Path:
    return manifest_path(root, "sources.architecture")


def open_questions_directory(root: Path) -> Path:
    return manifest_path(root, "sources.openQuestions")


def open_questions_index_path(root: Path) -> Path:
    return manifest_path(root, "sources.openQuestionsIndex")


def roadmap_path(root: Path) -> Path:
    return manifest_path(root, "sources.roadmap")


def status_path(root: Path) -> Path:
    return manifest_path(root, "sources.status")


def project_overview_path(root: Path) -> Path:
    return manifest_path(root, "sources.projectOverview")


def local_brief_path(root: Path) -> Path:
    return manifest_path(root, "sources.localBrief")


def protocol_path(root: Path) -> Path:
    return manifest_path(root, "protocol.file")


def repository_path(root: Path, key: str) -> Path:
    return manifest_path(root, f"repository.{key}")


LANGUAGE_TAG_RE = re.compile(
    r"^(?:"
    r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*"
    r"|x(?:-[A-Za-z0-9]{1,8})+"
    r"|i(?:-[A-Za-z0-9]{1,8})+"
    r")$"
)


def _language_tag(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or LANGUAGE_TAG_RE.fullmatch(value.strip()) is None
    ):
        raise ConfigError(
            f"{label} must be a structurally valid BCP 47 language tag"
        )
    return value.strip()


# ---------------------------------------------------------------------------
# Typed semantic accessors manifest.
# Они проверяют значения в момент использования и возвращают только допустимый
# domain; invalid value превращается в ConfigError.
# ---------------------------------------------------------------------------
def language_value(root: Path, key: str) -> str:
    manifest = load_manifest(root)
    default = _language_tag(
        get(manifest, "language.default"),
        label="manifest language.default",
    )
    value = get(manifest, f"language.{key}", default)
    return _language_tag(value, label=f"manifest language.{key}")


def max_fix_review_cycles(root: Path) -> int:
    manifest = load_manifest(root)
    value = require(manifest, "execution.maxFixReviewCycles")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ConfigError("manifest execution.maxFixReviewCycles must be an integer from 1 to 5")
    return value


def verification_command_timeout_seconds(root: Path) -> int:
    """Timeout одной executable Verification command."""
    manifest = load_manifest(root)
    value = require(manifest, "execution.verificationCommandTimeoutSeconds")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 3600
    ):
        raise ConfigError(
            "manifest execution.verificationCommandTimeoutSeconds "
            "must be an integer from 1 to 3600"
        )
    return value


def review_policy(root: Path, kind: str) -> str:
    if kind not in {"security", "tests"}:
        raise ConfigError(f"unknown review policy: {kind}")
    manifest = load_manifest(root)
    value = require(manifest, f"review.{kind}")
    if value not in {"auto", "always"}:
        raise ConfigError(f"manifest review.{kind} must be auto or always")
    return value


def skill_search_max_results(root: Path) -> int:
    manifest = load_manifest(root)
    value = require(manifest, "skills.search.maxResults")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10:
        raise ConfigError("manifest skills.search.maxResults must be an integer from 1 to 10")
    return value


def load_git_policy(root: Path) -> dict[str, Any]:
    """Прочитать configured Git policy; exact safety schema проверяет git preflight/validator."""
    path = repository_path(root, "gitPolicy")
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read Git policy {path}: {exc}") from exc


def load_update_policy(root: Path) -> dict[str, Any]:
    """Прочитать configured Harness update policy с единым TOML error contract."""
    path = repository_path(root, "harnessUpdatePolicy")
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read Harness update policy {path}: {exc}") from exc


# Update policy paths получают ту же repository-containment защиту, что и
# manifest paths: remote/config value не может вывести tool за checkout.
def update_policy_path(root: Path, dotted: str) -> Path:
    policy = load_update_policy(root)
    value = require(policy, dotted)
    return resolve_repo_path(root, value, label=f"harness-update {dotted}")


def update_manifest_path(root: Path) -> Path:
    return update_policy_path(root, "source.update_manifest")


def update_lock_path(root: Path) -> Path:
    return update_policy_path(root, "state.lock_file")


def update_report_directory(root: Path) -> Path:
    return update_policy_path(root, "state.report_directory")
