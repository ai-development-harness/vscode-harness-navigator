#!/usr/bin/env python3
"""Synthetic regression tests for Review Contract v2 structured findings."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".harness/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from document_contract import parse_document, render_document
from review_findings import (
    FindingContractError,
    finding_fingerprint,
    normalize_findings,
    parse_machine_findings,
    render_machine_findings,
)


def sample() -> dict[str, object]:
    return {
        "title": "Incorrect status transition",
        "severity": "high",
        "category": "implementation",
        "location": {"path": "src/state.py", "line": 42},
        "scenario": {
            "given": "execution is resumed after REVIEW FAIL",
            "when": "resolver selects the next command",
            "then": "FIX must be selected exactly once",
        },
        "expected": "Resolver returns STEP FIX STEP-001.",
        "observed": "Resolver returns STEP REVIEW STEP-001 again.",
        "impact": "RUN can loop without applying the required repair.",
        "repair": {
            "direction": "Use the persisted FAIL review as the FIX transition fact.",
            "admissibleAlternatives": [
                "Derive the same transition from an equivalent canonical state fact."
            ],
        },
        "constraints": ["Do not bypass CTS."],
        "evidence": ["execution-self-test reproducer"],
    }


def main() -> int:
    finding = normalize_findings([sample()])[0]
    assert finding["id"] == "F-001"
    assert finding["fingerprint"].startswith("sha256:")

    renamed = sample()
    renamed["title"] = "Same defect, clearer title"
    renamed["repair"] = {
        "direction": "Different wording for the same repair.",
        "admissibleAlternatives": [],
    }
    renamed_fp = normalize_findings([renamed])[0]["fingerprint"]
    assert renamed_fp == finding["fingerprint"], (renamed_fp, finding["fingerprint"])

    changed = sample()
    changed["observed"] = "Resolver returns PROJECT STATUS."
    changed_fp = normalize_findings([changed])[0]["fingerprint"]
    assert changed_fp != finding["fingerprint"]

    # Review Contract v2 обязан fail-closed отвергать legacy/partial формы.
    invalid_variants: list[tuple[str, dict[str, object]]] = []

    missing_expected = sample()
    missing_expected.pop("expected")
    invalid_variants.append(("missing expected", missing_expected))

    missing_observed = sample()
    missing_observed.pop("observed")
    invalid_variants.append(("missing observed", missing_observed))

    string_location = sample()
    string_location["location"] = "src/state.py"
    invalid_variants.append(("string location", string_location))

    string_scenario = sample()
    string_scenario["scenario"] = "legacy scenario"
    invalid_variants.append(("string scenario", string_scenario))

    legacy_repair = sample()
    legacy_repair.pop("repair")
    legacy_repair["fixDirection"] = "legacy repair direction"
    invalid_variants.append(("legacy fixDirection", legacy_repair))

    for label, invalid in invalid_variants:
        try:
            normalize_findings([invalid])
        except FindingContractError:
            pass
        else:
            raise AssertionError(f"{label} was accepted as Review Contract v2")

    try:
        normalize_findings([sample(), sample()])
    except FindingContractError as exc:
        assert "duplicate fingerprints" in str(exc)
    else:
        raise AssertionError("duplicate finding fingerprint was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "review.md"
        machine = render_machine_findings([finding])
        path.write_text(
            render_document(
                {
                    "schema": 1,
                    "kind": "step_review",
                    "finding_contract": 2,
                    "step_id": "STEP-001",
                },
                f"""# STEP REVIEW STEP-001 — 2026-09-30 12:00

## Findings

human-readable finding

## Machine-readable findings

```json
{machine}
```
""",
            ),
            encoding="utf-8",
        )
        parsed = parse_machine_findings(parse_document(path))
        assert parsed == [finding], json.dumps(parsed, ensure_ascii=False, indent=2)

        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(finding["fingerprint"], "sha256:" + "0" * 64),
            encoding="utf-8",
        )
        try:
            parse_machine_findings(parse_document(path))
        except FindingContractError as exc:
            assert "fingerprint" in str(exc)
        else:
            raise AssertionError("forged finding fingerprint was accepted")

    assert finding_fingerprint(finding) == finding["fingerprint"]
    print("REVIEW FINDINGS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
