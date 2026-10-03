#!/usr/bin/env python3
"""Synthetic regressions for Requirements Quality Gate transport contract."""
from __future__ import annotations

from requirements_quality import RequirementsQualityError, normalize_result, render_json


BASE_QUALITY = {
    "completeness": "pass",
    "clarity": "pass",
    "measurability": "pass",
    "scenarioCoverage": "pass",
}


def finding(
    *,
    code: str,
    owner: str,
    severity: str = "blocking",
    question: str = "Какое решение требуется?",
) -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "owner": owner,
        "question": question,
        "rationale": "Ответ materially меняет implementation или validation.",
        "sourceRefs": [f"{owner}#Contract"] if owner != "PROJECT" else ["PROJECT"],
    }


def expect_error(payload: object, needle: str) -> None:
    try:
        normalize_result(payload)
    except RequirementsQualityError as exc:
        if needle not in str(exc):
            raise AssertionError(f"unexpected error: {exc}") from exc
    else:
        raise AssertionError("expected RequirementsQualityError")


def main() -> int:
    passed_payload = {
        "schemaVersion": 1,
        "status": "PASS",
        "quality": dict(BASE_QUALITY),
        "findings": [],
    }
    assert normalize_result(passed_payload)["status"] == "PASS"

    needs_input_payload = {
        "schemaVersion": 1,
        "status": "NEEDS_INPUT",
        "quality": {**BASE_QUALITY, "measurability": "fail"},
        "findings": [
            finding(
                code="AMBIGUOUS_RECOVERY_POLICY",
                owner="REQ-014",
                question="Какой recovery behavior обязателен после timeout?",
            )
        ],
    }
    needs_input = normalize_result(needs_input_payload)
    assert needs_input["status"] == "NEEDS_INPUT"
    assert needs_input["findings"][0]["owner"] == "REQ-014"

    warning_only = normalize_result(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": {**BASE_QUALITY, "clarity": "warn"},
            "findings": [
                finding(
                    code="MINOR_TERMINOLOGY_DRIFT",
                    owner="STEP-024",
                    severity="warning",
                    question="Унифицировать термин при следующем редактировании?",
                )
            ],
        }
    )
    assert warning_only["status"] == "PASS"

    multiple = normalize_result(
        {
            "schemaVersion": 1,
            "status": "NEEDS_INPUT",
            "quality": {
                **BASE_QUALITY,
                "completeness": "fail",
                "scenarioCoverage": "fail",
            },
            "findings": [
                finding(code="RECOVERY_POLICY_UNDEFINED", owner="REQ-014"),
                finding(code="ERROR_STATE_UNDEFINED", owner="STEP-024"),
            ],
        }
    )
    assert len(multiple["findings"]) == 2
    assert {item["owner"] for item in multiple["findings"]} == {"REQ-014", "STEP-024"}

    blocked = normalize_result(
        {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "quality": {**BASE_QUALITY, "completeness": "fail"},
            "findings": [
                finding(
                    code="OWNER_UNRESOLVED",
                    owner="PROJECT",
                    question="Какой canonical artifact владеет этим решением?",
                )
            ],
        }
    )
    assert blocked["status"] == "BLOCKED"

    # Runtime adapters receive the same canonical transport result. Validation
    # is deterministic and must never add runtime-local/session state.
    assert normalize_result(needs_input_payload) == needs_input
    assert render_json(needs_input_payload) == render_json(needs_input_payload)

    expect_error(
        {
            "schemaVersion": 1,
            "status": "NEEDS_INPUT",
            "quality": dict(BASE_QUALITY),
            "findings": [
                finding(code="WRONG_OWNER", owner="docs/requirements/foo.md")
            ],
        },
        "owner must be PROJECT or canonical",
    )
    expect_error(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": dict(BASE_QUALITY),
            "findings": [
                finding(code="BLOCKER_IN_PASS", owner="PROJECT")
            ],
        },
        "PASS cannot contain blocking",
    )
    expect_error(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": {**BASE_QUALITY, "clarity": "fail"},
            "findings": [],
        },
        "PASS cannot contain failed quality dimensions",
    )

    print("requirements-quality contract self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
