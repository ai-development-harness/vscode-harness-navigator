#!/usr/bin/env python3
"""Synthetic structured reflection contract tests (#227)."""
from __future__ import annotations

from pathlib import Path
import tempfile

from reflection import ReflectionError, load_evidence, validate_lessons, write_reflection


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def evidence(explicit: bool = False) -> dict:
    return {
        "schemaVersion": 1,
        "explicitHumanRequest": explicit,
        "events": [
            {
                "id": "ev-1",
                "sourceKind": "review_finding",
                "classKey": "review:implementation:owner-bypass",
                "occurrenceId": "STEP-001@rev-a",
                "path": "planning/reviews/STEP-001/REVIEW-1.md",
                "fingerprint": "sha256:" + "1" * 64,
                "summary": "Direct write bypasses canonical owner.",
            },
            {
                "id": "ev-2",
                "sourceKind": "review_finding",
                "classKey": "review:implementation:owner-bypass",
                "occurrenceId": "STEP-002@rev-b",
                "path": "planning/reviews/STEP-002/REVIEW-2.md",
                "fingerprint": "sha256:" + "2" * 64,
                "summary": "Same owner bypass recurred in another STEP.",
            },
            {
                "id": "ev-3",
                "sourceKind": "verification_failure",
                "classKey": "verification:cli-output",
                "occurrenceId": "STEP-003@rev-c",
                "path": "planning/tasks/STEP-003.md",
                "fingerprint": "sha256:" + "3" * 64,
                "summary": "CLI output verification failed once.",
            },
        ],
    }


def payload() -> dict:
    return {
        "schemaVersion": 1,
        "lessons": [
            {
                "classKey": "review:implementation:owner-bypass",
                "summary": "Owner bypass should become mechanically impossible.",
                "scope": "core",
                "primaryTarget": "core-tool-gate-validator",
                "evidenceIds": ["ev-1", "ev-2"],
                "rationale": "Two distinct factual occurrences show a recurring class.",
                "proposedAction": "Add a deterministic ownership guard with regression coverage.",
            },
            {
                "classKey": "verification:cli-output",
                "summary": "The single CLI failure is not yet a durable rule.",
                "scope": "none",
                "primaryTarget": "no-action",
                "evidenceIds": ["ev-3"],
                "rationale": "One occurrence is insufficient for structuralization.",
                "proposedAction": "Keep as one-off evidence unless it recurs.",
            },
        ],
        "rationale": "Post-work learning pass over structured evidence only.",
    }


def expect_blocked(callable_, fragment: str) -> None:
    try:
        callable_()
    except ReflectionError as exc:
        assert fragment in str(exc), str(exc)
        return
    raise AssertionError(f"expected ReflectionError containing {fragment!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="reflection-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", "protocol:\n  auditDirectory: planning/audits\n")
        write(root, "planning/reviews/STEP-001/REVIEW-1.md", "# r1\n")
        write(root, "planning/reviews/STEP-002/REVIEW-2.md", "# r2\n")
        write(root, "planning/tasks/STEP-003.md", "# step\n")

        normalized = load_evidence(root, evidence())
        assert normalized["classOccurrences"]["review:implementation:owner-bypass"] == 2
        assert normalized["triggerRecommended"] is True

        lessons = validate_lessons(root, normalized, payload())
        assert lessons[0]["recurring"] is True
        assert lessons[1]["recurring"] is False
        assert lessons[0]["primaryTarget"] == "core-tool-gate-validator"

        one_off_rule = payload()
        one_off_rule["lessons"][1] = {
            "classKey": "verification:cli-output",
            "summary": "Turn one failure into a project rule.",
            "scope": "project",
            "primaryTarget": "project-principle",
            "evidenceIds": ["ev-3"],
            "rationale": "Only one observation exists.",
            "proposedAction": "Create PRN.",
        }
        expect_blocked(
            lambda: validate_lessons(root, normalized, one_off_rule),
            "one-off lesson cannot become durable rule",
        )

        explicit = load_evidence(root, evidence(explicit=True))
        explicit_lessons = validate_lessons(root, explicit, one_off_rule)
        assert explicit_lessons[1]["primaryTarget"] == "project-principle"

        report = write_reflection(root, normalized, payload())
        assert report["status"] == "PASS"
        assert report["automaticMutationAllowed"] is False
        report_path = root / report["report"]
        assert report_path.is_file()

        expect_blocked(
            lambda: validate_lessons(root, normalized, payload()),
            "duplicate lesson fingerprint",
        )

        bad = evidence()
        bad["events"][0]["sourceKind"] = "transcript"
        expect_blocked(lambda: load_evidence(root, bad), "sourceKind is unsupported")

        local = evidence()
        local["events"][0]["path"] = ".harness/local/chat.txt"
        write(root, ".harness/local/chat.txt", "no\n")
        expect_blocked(lambda: load_evidence(root, local), "durable evidence")

    print("reflection self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
