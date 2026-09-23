#!/usr/bin/env python3
"""Детерминированный parser и валидатор Command Transition System (CTS).

Этот модуль — низкоуровневая часть protocol layer. Он намеренно не читает Git,
STEP-файлы, runtime state и не вызывает LLM. Его задача ограничена структурой
команд: распознать canonical syntax, нормализовать shorthand chain и проверить,
что каждый переход явно существует в .harness/command-transitions.json.

Ключевой safety-инвариант: отсутствие edge означает запрет перехода. Здесь нет
эвристик вида «так логично» или «Git обычно работает именно так».
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

# ---------------------------------------------------------------------------
# Schema vocabulary.
# TABLE_PATH — единственный machine-readable source of truth command surface.
# ALLOWED_* и KNOWN_RUNTIME_PRECONDITIONS работают как closed sets: новое
# значение обязано сначала появиться в parser/validator, иначе graph считается
# несовместимым с текущим runtime.
# ---------------------------------------------------------------------------
TABLE_PATH = ".harness/command-transitions.json"
# Эти множества одновременно документируют и ограничивают schema vocabulary.
# Новое значение нельзя «просто начать использовать» в JSON — сначала нужно явно
# расширить parser/validator, иначе Harness Integrity обязан упасть.
ALLOWED_TARGETS = {"none", "step", "release-optional"}
ALLOWED_INPUTS = {"none", "optional", "required"}
ALLOWED_RESULTS = {"PASS", "SUCCESS", "FAIL", "BLOCKED"}
KNOWN_RUNTIME_PRECONDITIONS = {
    "matching-update-target-and-route",
    "git-push-ready",
    "git-pr-ready",
}



def load_transition_table(root: Path) -> dict[str, Any]:
    """Прочитать CTS table текущего repository без cache.

    Ошибки JSON/IO намеренно не маскируются: caller должен трактовать
    unreadable transition table как invalid protocol state.
    """
    path = root / TABLE_PATH
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)



def validate_transition_table(table: dict[str, Any]) -> list[str]:
    """Проверить schema и непротиворечивость всего transition graph.

    Проверка выполняется до parsing пользовательской команды. Это принципиально:
    команда не может считаться VALID на основании повреждённого source of truth.
    Ошибки агрегируются, чтобы CI показывал весь drift одним запуском.
    """
    errors: list[str] = []
    if table.get("schemaVersion") != 1:
        errors.append("command-transitions: schemaVersion must be 1")

    order = table.get("validationOrder")
    expected_order = [
        "tokenize",
        "normalize",
        "transition-table",
        "runtime-preconditions",
        "dispatch",
    ]
    if order != expected_order:
        errors.append(
            "command-transitions: validationOrder must be "
            + " -> ".join(expected_order)
        )

    if table.get("chainSeparator") != " > ":
        errors.append("command-transitions: chainSeparator must be ' > '")

    domains = table.get("domains")
    if not isinstance(domains, dict) or not domains:
        return errors + ["command-transitions: domains must be a non-empty object"]

    # Проверяем graph сверху вниз: DOMAIN → commands → aliases → transitions.
    # canonical_seen запрещает двум разным operations публиковать одинаковую
    # пользовательскую команду — иначе normalization была бы неоднозначной.
    canonical_seen: set[str] = set()
    for domain_name, domain in domains.items():
        if not isinstance(domain_name, str) or not re.fullmatch(r"[A-Z]+", domain_name):
            errors.append(f"command-transitions: invalid domain name {domain_name!r}")
            continue
        if not isinstance(domain, dict):
            errors.append(f"command-transitions: domain {domain_name} must be an object")
            continue

        chain_enabled = domain.get("chainEnabled")
        if not isinstance(chain_enabled, bool):
            errors.append(f"command-transitions: {domain_name}.chainEnabled must be boolean")

        inherit_target = domain.get("inheritTarget")
        if not isinstance(inherit_target, bool):
            errors.append(f"command-transitions: {domain_name}.inheritTarget must be boolean")

        aliases = domain.get("continuationAliases", {})
        if not isinstance(aliases, dict):
            errors.append(f"command-transitions: {domain_name}.continuationAliases must be an object")
            aliases = {}

        commands = domain.get("commands")
        if not isinstance(commands, dict) or not commands:
            errors.append(f"command-transitions: {domain_name}.commands must be a non-empty object")
            commands = {}

        for operation, spec in commands.items():
            if not isinstance(operation, str) or not operation:
                errors.append(f"command-transitions: {domain_name} has invalid operation name")
                continue
            if not isinstance(spec, dict):
                errors.append(f"command-transitions: {domain_name}.{operation} must be an object")
                continue

            canonical = spec.get("canonical")
            if not isinstance(canonical, str) or not canonical.startswith(domain_name + " "):
                errors.append(
                    f"command-transitions: {domain_name}.{operation}.canonical must start with '{domain_name} '"
                )
            elif canonical in canonical_seen:
                errors.append(f"command-transitions: duplicate canonical command {canonical}")
            else:
                canonical_seen.add(canonical)

            if not isinstance(spec.get("chainAllowed"), bool):
                errors.append(f"command-transitions: {domain_name}.{operation}.chainAllowed must be boolean")
            elif spec.get("chainAllowed") and chain_enabled is False:
                errors.append(
                    f"command-transitions: {domain_name}.{operation} cannot allow chain in standalone-only domain"
                )

            if spec.get("target") not in ALLOWED_TARGETS:
                errors.append(
                    f"command-transitions: {domain_name}.{operation}.target must be one of {sorted(ALLOWED_TARGETS)}"
                )
            if spec.get("input") not in ALLOWED_INPUTS:
                errors.append(
                    f"command-transitions: {domain_name}.{operation}.input must be one of {sorted(ALLOWED_INPUTS)}"
                )

            for metadata_key in ("summary", "documentation"):
                metadata_value = spec.get(metadata_key)
                if not isinstance(metadata_value, str) or not metadata_value.strip():
                    errors.append(
                        f"command-transitions: {domain_name}.{operation}.{metadata_key} "
                        "must be a non-empty string"
                    )

        for alias, operation in aliases.items():
            if operation not in commands:
                errors.append(
                    f"command-transitions: {domain_name} alias {alias!r} points to unknown operation {operation!r}"
                )
            if not isinstance(alias, str) or not alias:
                errors.append(f"command-transitions: {domain_name} has invalid continuation alias")

        transitions = domain.get("transitions")
        if not isinstance(transitions, list):
            errors.append(f"command-transitions: {domain_name}.transitions must be an array")
            transitions = []

        seen_edges: set[tuple[str, str]] = set()
        for edge in transitions:
            if not isinstance(edge, dict):
                errors.append(f"command-transitions: {domain_name} transition must be an object")
                continue
            source = edge.get("from")
            target = edge.get("to")
            if source not in commands or target not in commands:
                errors.append(
                    f"command-transitions: {domain_name} transition {source!r} -> {target!r} references unknown operation"
                )
                continue
            if not commands[source].get("chainAllowed") or not commands[target].get("chainAllowed"):
                errors.append(
                    f"command-transitions: {domain_name} transition {source} -> {target} uses standalone-only command"
                )
            pair = (source, target)
            if pair in seen_edges:
                errors.append(
                    f"command-transitions: duplicate {domain_name} transition {source} -> {target}"
                )
            seen_edges.add(pair)

            results = edge.get("onPreviousResult")
            if not isinstance(results, list) or not results:
                errors.append(
                    f"command-transitions: {domain_name} transition {source} -> {target} needs onPreviousResult"
                )
            elif any(result not in ALLOWED_RESULTS for result in results):
                errors.append(
                    f"command-transitions: {domain_name} transition {source} -> {target} has invalid result"
                )

            preconditions = edge.get("runtimePreconditions")
            if not isinstance(preconditions, list) or any(
                not isinstance(value, str) or not value for value in preconditions
            ):
                errors.append(
                    f"command-transitions: {domain_name} transition {source} -> {target} runtimePreconditions must be strings"
                )
            else:
                unknown = sorted(set(preconditions) - KNOWN_RUNTIME_PRECONDITIONS)
                if unknown:
                    errors.append(
                        f"command-transitions: {domain_name} transition {source} -> {target} "
                        "uses unknown runtimePreconditions: " + ", ".join(unknown)
                    )

        if chain_enabled is False and transitions:
            errors.append(
                f"command-transitions: standalone-only domain {domain_name} must not define transitions"
            )

    return errors



def canonical_commands(table: dict[str, Any]) -> list[str]:
    """Вернуть canonical command surface для policy/docs integrity checks."""
    result: list[str] = []
    for domain in table.get("domains", {}).values():
        for spec in domain.get("commands", {}).values():
            canonical = spec.get("canonical")
            if isinstance(canonical, str):
                result.append(canonical)
    return result



# Longest-match parser operation name. Короткий prefix не может перехватить
# более длинную operation вроде UPDATE CHECK / UPDATE APPLY.
def _operation_match(text: str, operations: list[str]) -> tuple[str | None, str]:
    stripped = text.strip()
    # Longest-first обязателен. Например, если когда-либо сосуществуют
    # "UPDATE" и "UPDATE CHECK", сначала должна проверяться длинная operation.
    for operation in sorted(operations, key=len, reverse=True):
        if stripped == operation:
            return operation, ""
        if stripped.startswith(operation):
            rest = stripped[len(operation):]
            if rest.startswith((" ", ":")):
                return operation, rest
    return None, stripped



# ---------------------------------------------------------------------------
# Segment parser.
# Разрешает только DOMAIN/operation/target/input grammar и inheritance. Здесь
# запрещено repository/runtime reasoning: factual preconditions выполняются
# после structural CTS gate отдельными tools.
# ---------------------------------------------------------------------------
def _parse_segment(
    raw_segment: str,
    table: dict[str, Any],
    *,
    expected_domain: str | None,
    inherited_target: str | None,
    first_segment: bool,
) -> dict[str, Any]:
    segment = raw_segment.strip()
    domains = table["domains"]
    domain_name: str | None = None
    remainder = segment

    for candidate in sorted(domains, key=len, reverse=True):
        if segment == candidate or segment.startswith(candidate + " "):
            domain_name = candidate
            remainder = segment[len(candidate):].strip()
            break

    # DOMAIN обязателен только в первом segment. Дальше shorthand наследует
    # DOMAIN, но явная попытка сменить его внутри chain считается ошибкой.
    if first_segment:
        if domain_name is None:
            return {
                "valid": False,
                "code": "MISSING_DOMAIN",
                "message": "first chain segment must contain an explicit canonical DOMAIN",
            }
    else:
        if domain_name is not None and domain_name != expected_domain:
            return {
                "valid": False,
                "code": "DOMAIN_MISMATCH",
                "message": f"chain domain changed from {expected_domain} to {domain_name}",
            }
        if domain_name is None:
            domain_name = expected_domain

    if domain_name is None or domain_name not in domains:
        return {
            "valid": False,
            "code": "UNKNOWN_DOMAIN",
            "message": f"unknown command domain in segment: {segment}",
        }

    domain = domains[domain_name]
    commands = domain["commands"]
    operation, rest = _operation_match(remainder, list(commands))

    if operation is None and not first_segment:
        aliases = domain.get("continuationAliases", {})
        alias, alias_rest = _operation_match(remainder, list(aliases))
        if alias is not None:
            operation = aliases[alias]
            rest = alias_rest

    if operation is None:
        return {
            "valid": False,
            "code": "UNKNOWN_OPERATION",
            "message": f"unknown {domain_name} operation in segment: {segment}",
        }

    spec = commands[operation]
    rest = rest.strip()
    target: str | None = None

    target_kind = spec["target"]
    # Target наследуется только там, где это разрешено schema конкретной
    # команды. STEP target не может внезапно появиться/измениться посередине chain.
    if target_kind == "step":
        if rest:
            token, _, tail = rest.partition(" ")
            if re.fullmatch(r"STEP-\d{3,}", token):
                target = token
                rest = tail.strip()
            elif re.fullmatch(r"\d{3,}", token):
                # Пользовательский shorthand нормализуется до canonical STEP-NNN
                # до inheritance/mismatch checks, поэтому 024 и STEP-024 равны.
                target = f"STEP-{token}"
                rest = tail.strip()
        if target is None:
            if inherited_target is not None:
                target = inherited_target
            else:
                return {
                    "valid": False,
                    "code": "MISSING_TARGET",
                    "message": f"{domain_name} {operation} requires STEP-NNN or NNN target",
                }

    elif target_kind == "release-optional":
        if rest:
            match = re.fullmatch(r"TO\s+(\S+)", rest)
            if not match:
                return {
                    "valid": False,
                    "code": "INVALID_TARGET_SYNTAX",
                    "message": f"{domain_name} {operation} accepts only optional 'TO <tag>' target",
                }
            target = match.group(1)
            rest = ""
        elif inherited_target is not None:
            target = inherited_target

    input_mode = spec["input"]
    input_value: str | None = None
    # Free-form input всегда отделяется двоеточием. Это не косметика:
    # без явного delimiter parser не смог бы надёжно отличить target от текста.
    if input_mode in {"optional", "required"}:
        if rest:
            if not rest.startswith(":"):
                return {
                    "valid": False,
                    "code": "INVALID_INPUT_SYNTAX",
                    "message": f"{domain_name} {operation} free-form input must follow ':'",
                }
            input_value = rest[1:].strip()
            rest = ""
        if input_mode == "required" and not input_value:
            return {
                "valid": False,
                "code": "MISSING_INPUT",
                "message": f"{domain_name} {operation} requires non-empty input after ':'",
            }
    elif rest:
        return {
            "valid": False,
            "code": "UNEXPECTED_ARGUMENTS",
            "message": f"unexpected arguments after {domain_name} {operation}: {rest}",
        }

    if rest:
        return {
            "valid": False,
            "code": "UNEXPECTED_ARGUMENTS",
            "message": f"unexpected arguments in segment: {segment}",
        }

    if inherited_target is not None and target is not None and target != inherited_target:
        return {
            "valid": False,
            "code": "TARGET_MISMATCH",
            "message": f"chain target changed from {inherited_target} to {target}",
        }

    normalized = f"{domain_name} {operation}"
    if target_kind == "step" and target:
        normalized += f" {target}"
    elif target_kind == "release-optional" and target:
        normalized += f" TO {target}"
    if input_value is not None:
        normalized += f": {input_value}"

    return {
        "valid": True,
        "domain": domain_name,
        "operation": operation,
        "target": target,
        "input": input_value,
        "chainAllowed": spec["chainAllowed"],
        "normalized": normalized,
    }



# Single-command parser для execution layer после normalization root command.
# Перед parsing снова проверяет table, чтобы caller не смог обойти schema gate.
def parse_canonical_command(raw: str, table: dict[str, Any]) -> dict[str, Any]:
    """Parse one canonical command without reading repository/runtime state."""
    table_errors = validate_transition_table(table)
    if table_errors:
        return {
            "valid": False,
            "code": "INVALID_TRANSITION_TABLE",
            "message": "command transition table is invalid",
            "errors": table_errors,
        }

    text = raw.strip()
    if not text:
        return {"valid": False, "code": "EMPTY_COMMAND", "message": "command is empty"}
    if table.get("chainSeparator", " > ") in text:
        return {
            "valid": False,
            "code": "CHAIN_NOT_ALLOWED",
            "message": "parse_canonical_command accepts exactly one command",
        }

    return _parse_segment(
        text,
        table,
        expected_domain=None,
        inherited_target=None,
        first_segment=True,
    )



# ---------------------------------------------------------------------------
# Главный structural gate.
# Вся chain разбирается и все соседние transitions проверяются ДО dispatch
# первого segment. Это предотвращает partial execution заведомо invalid chain.
# ---------------------------------------------------------------------------
def validate_command_text(raw: str, table: dict[str, Any]) -> dict[str, Any]:
    table_errors = validate_transition_table(table)
    if table_errors:
        return {
            "valid": False,
            "code": "INVALID_TRANSITION_TABLE",
            "message": "command transition table is invalid",
            "errors": table_errors,
        }

    text = raw.strip()
    if not text:
        return {"valid": False, "code": "EMPTY_COMMAND", "message": "command is empty"}

    separator = table["chainSeparator"]
    # Split выполняется только по зафиксированному separator " > ".
    # Оператор обязан быть отдельным token в canonical syntax.
    segments = [part.strip() for part in text.split(separator)]
    if any(not part for part in segments):
        return {
            "valid": False,
            "code": "EMPTY_SEGMENT",
            "message": "chain contains an empty segment",
        }

    parsed: list[dict[str, Any]] = []
    domain_name: str | None = None
    inherited_target: str | None = None

    for index, raw_segment in enumerate(segments):
        item = _parse_segment(
            raw_segment,
            table,
            expected_domain=domain_name,
            inherited_target=inherited_target,
            first_segment=index == 0,
        )
        if not item["valid"]:
            item["segmentIndex"] = index
            return item

        if domain_name is None:
            domain_name = item["domain"]
        if item["target"] is not None:
            if inherited_target is None:
                if index > 0:
                    return {
                        "valid": False,
                        "code": "TARGET_MISMATCH",
                        "message": "chain target cannot be introduced after the first segment",
                        "segmentIndex": index,
                    }
                inherited_target = item["target"]
            elif item["target"] != inherited_target:
                return {
                    "valid": False,
                    "code": "TARGET_MISMATCH",
                    "message": f"chain target changed from {inherited_target} to {item['target']}",
                    "segmentIndex": index,
                }
        parsed.append(item)

    if len(parsed) == 1:
        return {
            "valid": True,
            "code": "VALID_COMMAND",
            "domain": parsed[0]["domain"],
            "normalized": [parsed[0]["normalized"]],
            "transitions": [],
        }

    assert domain_name is not None
    domain = table["domains"][domain_name]
    if not domain.get("chainEnabled"):
        return {
            "valid": False,
            "code": "CHAIN_NOT_ALLOWED",
            "message": f"{domain_name} commands are standalone-only",
        }

    for index, item in enumerate(parsed):
        if not item["chainAllowed"]:
            return {
                "valid": False,
                "code": "CHAIN_NOT_ALLOWED",
                "message": f"{item['normalized']} is standalone-only",
                "segmentIndex": index,
            }

    # Closed-world transition rule: разрешены только пары, которые буквально
    # присутствуют в graph. Отсутствующая пара не восстанавливается эвристикой.
    edge_map = {
        (edge["from"], edge["to"]): edge
        for edge in domain.get("transitions", [])
    }
    resolved_edges: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(parsed, parsed[1:])):
        edge = edge_map.get((left["operation"], right["operation"]))
        if edge is None:
            return {
                "valid": False,
                "code": "INVALID_CHAIN",
                "message": (
                    f"transition {domain_name} {left['operation']} -> "
                    f"{domain_name} {right['operation']} is not allowed"
                ),
                "segmentIndex": index + 1,
            }
        resolved_edges.append(
            {
                "from": left["normalized"],
                "to": right["normalized"],
                "onPreviousResult": edge["onPreviousResult"],
                "runtimePreconditions": edge["runtimePreconditions"],
            }
        )

    return {
        "valid": True,
        "code": "VALID_CHAIN",
        "domain": domain_name,
        "normalized": [item["normalized"] for item in parsed],
        "transitions": resolved_edges,
    }



# Преобразовать graph в человекочитаемые строки документации. Это представление генерируется только из source-of-truth JSON.
def transition_rows(table: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for domain_name, domain in table.get("domains", {}).items():
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in domain.get("transitions", []):
            outgoing.setdefault(edge["from"], []).append(edge)

        for operation, spec in domain.get("commands", {}).items():
            edges = outgoing.get(operation, [])
            if not spec.get("chainAllowed"):
                next_value = "—"
                condition = "standalone-only"
            elif not edges:
                next_value = "—"
                condition = "terminal chain segment"
            else:
                next_value = "<br>".join(
                    f"{domain_name} {edge['to']}" for edge in edges
                )
                parts: list[str] = []
                for edge in edges:
                    result = "/".join(edge["onPreviousResult"])
                    pre = ", ".join(edge["runtimePreconditions"]) or "—"
                    parts.append(f"{edge['to']}: result={result}; pre={pre}")
                condition = "<br>".join(parts)

            rows.append(
                {
                    "command": spec["canonical"],
                    "chain": "yes" if spec.get("chainAllowed") else "no",
                    "next": next_value,
                    "condition": condition,
                }
            )
    return rows



# Сгенерировать Markdown-таблицу CTS. CI сравнивает её с generated block документа буквально, поэтому ручной drift обнаруживается автоматически.
def render_transition_markdown(table: dict[str, Any]) -> str:
    lines = [
        "| Command | Chain segment | Allowed next | Transition condition |",
        "|---|:---:|---|---|",
    ]
    for row in transition_rows(table):
        lines.append(
            f"| `{row['command']}` | {row['chain']} | {row['next']} | {row['condition']} |"
        )
    return "\n".join(lines)
