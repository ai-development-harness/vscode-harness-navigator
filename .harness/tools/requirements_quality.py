#!/usr/bin/env python3
"""Fail-closed contract for semantic requirements-quality results.

Модель отвечает только за semantic judgement. Этот module валидирует стабильный
runtime-neutral payload, чтобы PROJECT INIT / STEP ADD / STEP PLAN одинаково
интерпретировали PASS, NEEDS_INPUT и BLOCKED.

Ответы пользователя не сохраняются здесь: canonical owner остаётся REQ/ADR/OQ/
STEP. После mutation owning artifact gate запускается заново и обязан учитывать
уже зафиксированный ответ.
"""
from __future__ import annotations

import json
import re
from typing import Any


SCHEMA_VERSION = 1
STATUSES = {"PASS", "NEEDS_INPUT", "BLOCKED"}
SEVERITIES = {"blocking", "warning"}
QUALITY_VALUES = {"pass", "warn", "fail"}
QUALITY_DIMENSIONS = ("completeness", "clarity", "measurability", "scenarioCoverage")
OWNER_RE = re.compile(r"(?:PROJECT|REQ-[0-9]{3,}|ADR-[0-9]{3,}|OQ-[0-9]{3,}|STEP-[0-9]{3,})")
CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{2,}")


class RequirementsQualityError(ValueError):
    """Semantic quality payload violates the deterministic contract."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RequirementsQualityError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequirementsQualityError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\n" in result or "\r" in result:
        raise RequirementsQualityError(f"{label} must be a single line")
    return result


def _exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise RequirementsQualityError(
            f"{label} has unsupported keys: " + ", ".join(unexpected)
        )


def _quality(value: Any) -> dict[str, str]:
    data = _object(value, "quality")
    _exact_keys(data, set(QUALITY_DIMENSIONS), "quality")
    result: dict[str, str] = {}
    for name in QUALITY_DIMENSIONS:
        raw = data.get(name)
        if raw not in QUALITY_VALUES:
            raise RequirementsQualityError(
                f"quality.{name} must be pass|warn|fail"
            )
        result[name] = raw
    return result


def _finding(value: Any, index: int) -> dict[str, Any]:
    data = _object(value, f"findings[{index}]")
    _exact_keys(
        data,
        {"code", "severity", "owner", "question", "rationale", "sourceRefs"},
        f"findings[{index}]",
    )
    code = _text(data.get("code"), f"findings[{index}].code")
    if CODE_RE.fullmatch(code) is None:
        raise RequirementsQualityError(
            f"findings[{index}].code must use stable UPPER_SNAKE_CASE"
        )
    severity = data.get("severity")
    if severity not in SEVERITIES:
        raise RequirementsQualityError(
            f"findings[{index}].severity must be blocking|warning"
        )
    owner = _text(data.get("owner"), f"findings[{index}].owner")
    if OWNER_RE.fullmatch(owner) is None:
        raise RequirementsQualityError(
            f"findings[{index}].owner must be PROJECT or canonical REQ/ADR/OQ/STEP id"
        )
    question = _text(data.get("question"), f"findings[{index}].question")
    rationale = _text(data.get("rationale"), f"findings[{index}].rationale")
    refs = data.get("sourceRefs", [])
    if not isinstance(refs, list) or any(
        not isinstance(item, str) or not item.strip() for item in refs
    ):
        raise RequirementsQualityError(
            f"findings[{index}].sourceRefs must be an array of non-empty strings"
        )
    return {
        "code": code,
        "severity": severity,
        "owner": owner,
        "question": question,
        "rationale": rationale,
        "sourceRefs": [item.strip() for item in refs],
    }


def normalize_result(payload: Any) -> dict[str, Any]:
    """Validate and canonicalize one semantic requirements-quality result."""
    data = _object(payload, "requirements quality payload")
    _exact_keys(data, {"schemaVersion", "status", "quality", "findings"}, "payload")
    version = data.get("schemaVersion")
    if version != SCHEMA_VERSION:
        raise RequirementsQualityError(
            f"schemaVersion must be {SCHEMA_VERSION}"
        )
    status = data.get("status")
    if status not in STATUSES:
        raise RequirementsQualityError(
            "status must be PASS|NEEDS_INPUT|BLOCKED"
        )
    quality = _quality(data.get("quality"))
    raw_findings = data.get("findings")
    if not isinstance(raw_findings, list):
        raise RequirementsQualityError("findings must be an array")
    findings = [_finding(item, index) for index, item in enumerate(raw_findings)]
    blocking = [item for item in findings if item["severity"] == "blocking"]

    if status == "PASS" and blocking:
        raise RequirementsQualityError("PASS cannot contain blocking findings")
    if status in {"NEEDS_INPUT", "BLOCKED"} and not blocking:
        raise RequirementsQualityError(
            f"{status} requires at least one blocking finding"
        )
    if status == "PASS" and any(value == "fail" for value in quality.values()):
        raise RequirementsQualityError(
            "PASS cannot contain failed quality dimensions"
        )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "quality": quality,
        "findings": findings,
    }


def render_json(payload: Any) -> str:
    return json.dumps(
        normalize_result(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
