#!/usr/bin/env python3
"""Review Contract v3: evidence-gated structured findings for REVIEW → FIX.

Human-readable immutable Markdown remains the durable review artifact. This
module owns the machine-readable finding envelope embedded into that report and
provides a parser that FIX/orchestration can consume without reparsing prose.

Schema v3 adds an explicit evidence basis. A reviewer-derived risk is not a
material finding until its necessary preconditions and a project-specific
verification have confirmed the scenario. Invalidated hypotheses never enter
the durable findings array.

Historical schema-v1 reports remain readable by review_contract.py through the
legacy Markdown parser. Schema-v2 machine findings remain valid immutable
history, while new reports emit finding_contract=3.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from document_contract import parse_document
from harness_config import review_directory

FINDING_CONTRACT_VERSION = 3
SUPPORTED_FINDING_CONTRACT_VERSIONS = {2, 3}
MACHINE_SECTION = "Machine-readable findings"
SEVERITIES = {"critical", "high", "medium", "low"}
CATEGORIES = {"implementation", "evidence", "contract"}
EVIDENCE_KINDS = {"contract", "reproduced", "inferred"}


class FindingContractError(ValueError):
    """Malformed or unsupported structured review finding."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FindingContractError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\r" in result:
        result = result.replace("\r\n", "\n").replace("\r", "\n")
    return result


def _single_line(value: Any, label: str) -> str:
    result = _text(value, label)
    if "\n" in result:
        raise FindingContractError(f"{label} must be a single line")
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise FindingContractError(f"{label} must be an array")
    return [_single_line(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _location(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FindingContractError(f"{label} must be an object")
    unknown = sorted(set(value) - {"path", "line"})
    if unknown:
        raise FindingContractError(f"{label} has unsupported keys: {', '.join(unknown)}")
    path = _single_line(value.get("path"), f"{label}.path")
    line = value.get("line")
    if line is not None and (
        isinstance(line, bool) or not isinstance(line, int) or line < 1
    ):
        raise FindingContractError(f"{label}.line must be null or a positive integer")
    return {"path": path, "line": line}


def _scenario(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FindingContractError(f"{label} must be an object")
    unknown = sorted(set(value) - {"given", "when", "then"})
    if unknown:
        raise FindingContractError(f"{label} has unsupported keys: {', '.join(unknown)}")
    return {
        "given": _text(value.get("given"), f"{label}.given"),
        "when": _text(value.get("when"), f"{label}.when"),
        "then": _text(value.get("then"), f"{label}.then"),
    }


def _repair(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FindingContractError("repair must be an object")
    unknown = sorted(set(value) - {"direction", "admissibleAlternatives"})
    if unknown:
        raise FindingContractError(
            "repair has unsupported keys: " + ", ".join(unknown)
        )
    return {
        "direction": _text(value.get("direction"), "repair.direction"),
        "admissibleAlternatives": _string_list(
            value.get("admissibleAlternatives"),
            "repair.admissibleAlternatives",
        ),
    }


def _evidence_basis(value: Any, label: str) -> dict[str, Any]:
    """Validate Review Contract v3 evidence gate for one material finding."""
    if not isinstance(value, dict):
        raise FindingContractError(f"{label} must be an object")
    unknown = sorted(set(value) - {"kind", "source", "preconditions", "verification"})
    if unknown:
        raise FindingContractError(
            f"{label} has unsupported keys: " + ", ".join(unknown)
        )

    kind = _single_line(value.get("kind"), f"{label}.kind")
    if kind not in EVIDENCE_KINDS:
        raise FindingContractError(
            f"{label}.kind must be one of {sorted(EVIDENCE_KINDS)}"
        )
    preconditions = _string_list(value.get("preconditions"), f"{label}.preconditions")
    if kind == "inferred" and not preconditions:
        raise FindingContractError(
            f"{label}.preconditions must not be empty for inferred findings"
        )

    verification = value.get("verification")
    if not isinstance(verification, dict):
        raise FindingContractError(f"{label}.verification must be an object")
    verification_unknown = sorted(set(verification) - {"method", "result", "outcome"})
    if verification_unknown:
        raise FindingContractError(
            f"{label}.verification has unsupported keys: "
            + ", ".join(verification_unknown)
        )
    outcome = _single_line(
        verification.get("outcome"),
        f"{label}.verification.outcome",
    )
    if outcome != "confirmed":
        raise FindingContractError(
            f"{label}.verification.outcome must be confirmed; "
            "invalidated/unverified hypotheses are not durable findings"
        )

    return {
        "kind": kind,
        "source": _text(value.get("source"), f"{label}.source"),
        "preconditions": preconditions,
        "verification": {
            "method": _text(
                verification.get("method"),
                f"{label}.verification.method",
            ),
            "result": _text(
                verification.get("result"),
                f"{label}.verification.result",
            ),
            "outcome": outcome,
        },
    }


def fingerprint_payload(finding: dict[str, Any]) -> dict[str, Any]:
    """Return semantic identity used to match a finding across repair cycles.

    ID/title/prose formatting and repair suggestions are intentionally excluded:
    a reviewer may rename a finding or improve guidance without creating a new
    defect identity. Expected/observed/location/scenario/category define the
    factual defect.
    """
    return {
        "category": finding["category"],
        "location": finding["location"],
        "scenario": finding["scenario"],
        "expected": finding["expected"],
        "observed": finding["observed"],
    }


def finding_fingerprint(finding: dict[str, Any]) -> str:
    canonical = json.dumps(
        fingerprint_payload(finding),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def normalize_finding(
    value: Any,
    index: int,
    *,
    contract_version: int = FINDING_CONTRACT_VERSION,
) -> dict[str, Any]:
    if contract_version not in SUPPORTED_FINDING_CONTRACT_VERSIONS:
        raise FindingContractError(
            f"unsupported finding contract version: {contract_version}"
        )
    if not isinstance(value, dict):
        raise FindingContractError(f"findings[{index}] must be an object")
    allowed = {
        "id",
        "title",
        "severity",
        "category",
        "location",
        "scenario",
        "expected",
        "observed",
        "impact",
        "repair",
        "constraints",
        "evidence",
        "fingerprint",
    }
    if contract_version >= 3:
        allowed.add("evidenceBasis")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FindingContractError(
            f"findings[{index}] has unsupported keys: " + ", ".join(unknown)
        )

    finding_id = value.get("id")
    expected_id = f"F-{index:03d}"
    if finding_id is None:
        finding_id = expected_id
    finding_id = _single_line(finding_id, f"findings[{index}].id")
    if finding_id != expected_id:
        raise FindingContractError(
            f"findings[{index}].id must be {expected_id}"
        )

    severity = _single_line(value.get("severity"), f"findings[{index}].severity")
    category = _single_line(value.get("category"), f"findings[{index}].category")
    if severity not in SEVERITIES:
        raise FindingContractError(
            f"findings[{index}].severity must be one of {sorted(SEVERITIES)}"
        )
    if category not in CATEGORIES:
        raise FindingContractError(
            f"findings[{index}].category must be one of {sorted(CATEGORIES)}"
        )

    title = _single_line(value.get("title"), f"findings[{index}].title")
    location = _location(value.get("location"), f"findings[{index}].location")
    scenario = _scenario(value.get("scenario"), f"findings[{index}].scenario")

    expected = _text(value.get("expected"), f"findings[{index}].expected")
    observed = _text(value.get("observed"), f"findings[{index}].observed")
    evidence = _string_list(
        value.get("evidence"), f"findings[{index}].evidence"
    )
    if contract_version >= 3 and not evidence:
        raise FindingContractError(
            f"findings[{index}].evidence must not be empty in Review Contract v3"
        )

    result: dict[str, Any] = {
        "id": finding_id,
        "title": title,
        "severity": severity,
        "category": category,
        "location": location,
        "scenario": scenario,
        "expected": expected,
        "observed": observed,
        "impact": _text(value.get("impact"), f"findings[{index}].impact"),
        "repair": _repair(value.get("repair")),
        "constraints": _string_list(
            value.get("constraints"), f"findings[{index}].constraints"
        ),
        "evidence": evidence,
    }
    if contract_version >= 3:
        result["evidenceBasis"] = _evidence_basis(
            value.get("evidenceBasis"),
            f"findings[{index}].evidenceBasis",
        )

    result["fingerprint"] = finding_fingerprint(result)

    supplied = value.get("fingerprint")
    if supplied is not None and supplied != result["fingerprint"]:
        raise FindingContractError(
            f"findings[{index}].fingerprint does not match deterministic fingerprint"
        )
    return result


def normalize_findings(
    values: Any,
    *,
    contract_version: int = FINDING_CONTRACT_VERSION,
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise FindingContractError("findings must be an array")
    result = [
        normalize_finding(item, index, contract_version=contract_version)
        for index, item in enumerate(values, 1)
    ]
    fingerprints = [item["fingerprint"] for item in result]
    if len(fingerprints) != len(set(fingerprints)):
        raise FindingContractError("findings must not contain duplicate fingerprints")
    return result


def machine_payload(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": FINDING_CONTRACT_VERSION,
        "findings": findings,
    }


def render_machine_findings(findings: list[dict[str, Any]]) -> str:
    return json.dumps(
        machine_payload(findings),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def parse_machine_findings(
    document: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> list[dict[str, Any]]:
    section = document.get("sections", {}).get(MACHINE_SECTION)
    if not isinstance(section, str) or not section.strip():
        raise FindingContractError(f"missing or empty section '## {MACHINE_SECTION}'")
    text = section.strip()
    if not (text.startswith("```json\n") and text.endswith("\n```")):
        raise FindingContractError(
            f"## {MACHINE_SECTION} must contain exactly one ```json fenced object"
        )
    raw = text[len("```json\n") : -len("\n```")]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FindingContractError(f"invalid machine findings JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FindingContractError("machine findings payload must be an object")
    if set(payload) != {"schemaVersion", "findings"}:
        raise FindingContractError(
            "machine findings payload keys must be schemaVersion, findings"
        )
    version = payload.get("schemaVersion")
    if version not in SUPPORTED_FINDING_CONTRACT_VERSIONS:
        raise FindingContractError(
            "machine findings schemaVersion must be one of "
            + str(sorted(SUPPORTED_FINDING_CONTRACT_VERSIONS))
        )
    if expected_version is not None and version != expected_version:
        raise FindingContractError(
            f"machine findings schemaVersion {version} does not match "
            f"frontmatter finding_contract {expected_version}"
        )
    return normalize_findings(
        payload.get("findings"),
        contract_version=int(version),
    )


def latest_structured_findings(root: Path, step_id: str) -> dict[str, Any]:
    directory = review_directory(root) / step_id
    reports = sorted(directory.glob("REVIEW-*.md")) if directory.is_dir() else []
    if not reports:
        raise FindingContractError(f"no review reports for {step_id}")
    path = reports[-1]
    document = parse_document(path)
    meta = document["frontmatter"]
    if meta.get("finding_contract") != FINDING_CONTRACT_VERSION:
        raise FindingContractError(
            "latest review does not provide current Review Contract v3 "
            "evidence-gated findings; run a fresh STEP REVIEW before FIX"
        )
    findings = parse_machine_findings(
        document,
        expected_version=FINDING_CONTRACT_VERSION,
    )
    return {
        "schemaVersion": FINDING_CONTRACT_VERSION,
        "stepId": step_id,
        "report": path.relative_to(root).as_posix(),
        "verdict": meta.get("verdict"),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        result = latest_structured_findings(root, args.step)
    except (FindingContractError, OSError, ValueError) as exc:
        payload = {"status": "BLOCKED", "reason": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for finding in result["findings"]:
            print(
                f"{finding['id']} {finding['fingerprint']} "
                f"{finding['severity']} {finding['category']} "
                f"{finding['location']['path']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
