#!/usr/bin/env python3
"""Issue #331: scoped delta references preserve full completion safety."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import subprocess
from pathlib import Path
import tempfile
from unittest.mock import patch

from completion_gate import CompletionGateError, normalize_semantic_completion
from fix_delta_completion import validate_fix_delta_coverage_reuse


HASH = "sha256:" + "a" * 64
SUBJECT = "sha256:" + "b" * 64
STEP = "STEP-017"
REVIEW_BASE = "planning/reviews/STEP-017"
FULL = REVIEW_BASE + "/REVIEW-20261015T080000Z.md"
DELTA = REVIEW_BASE + "/REVIEW-20261015T090000Z.md"
CRITERIA = ["Original behavior remains correct.", "FIX closes the timeout bug."]


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def full_report(*, verdict: str = "fail", marker: bool = True) -> str:
    scope = "- Initial full implementation review" if marker else "- FIX delta only: forged"
    return f"""---
schema: 1
kind: step_review
step_id: {STEP}
contract_basis: {HASH}
verdict: {verdict}
---
# STEP REVIEW {STEP} — fixture
## Scope checked
{scope}
## Findings
A known timeout was detected.
"""


def delta_report(source: str) -> str:
    return f"""---
schema: 1
kind: step_review
step_id: {STEP}
contract_basis: {HASH}
verdict: fail
---
# STEP REVIEW {STEP} — delta
## Scope checked
- FIX delta only
## FIX delta provenance

```json
{json.dumps({"schemaVersion": 1, "mode": "fix_delta", "sourceReport": source})}
```
"""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert result.returncode == 0, (args, result.stderr)
    return result.stdout.strip()


def completion(root: Path) -> dict:
    return {
        "disposition": "pass",
        "coverage": [
            {
                "criterion": CRITERIA[0],
                "status": "covered",
                "evidence": [
                    "previous-review:" + FULL,
                    "verification:" + SUBJECT,
                ],
            },
            {
                "criterion": CRITERIA[1],
                "status": "covered",
                "evidence": ["Post-FIX timeout regression test PASS"],
            },
        ],
        "assertions": {
            "requirementObligations": {"status": "covered", "evidence": ["REQ accepted"]},
            "plannedScope": {"status": "covered", "evidence": ["Ready plan matched"]},
            "specializedObligations": {
                "status": "not_applicable", "evidence": ["No extra NFR gate applies"],
            },
        },
        "findings": [],
        "rationale": "Scoped FIX findings closed; remaining current prechecks PASS.",
    }


def blocked(action, expected: str) -> None:
    try:
        action()
    except CompletionGateError as exc:
        assert expected in str(exc), (expected, str(exc))
    else:
        raise AssertionError(f"invalid coverage unexpectedly accepted: {expected}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-fix-review-completion-") as td:
        root = Path(td)
        write(root, ".harness/manifest.yaml",
              "protocol:\n  reviewDirectory: planning/reviews\n")
        write(root, FULL, full_report())
        write(root, DELTA, delta_report(FULL))
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "fix-delta@example.invalid")
        git(root, "config", "user.name", "Scoped Completion Fixture")
        git(root, "add", ".")
        git(root, "commit", "-qm", "before FIX")
        before_tree = git(root, "rev-parse", "HEAD^{tree}")
        scope = {"mode": "fix_delta", "sourceReport": DELTA,
                 "beforeTree": before_tree}
        fresh = {
            "status": "PASS", "fresh": True,
            "contractBasis": HASH, "subjectContentHash": SUBJECT,
        }

        # Real filesystem/provenance chain, with only canonical structural
        # report validation and semantic basis providers stubbed.
        with (
            patch("fix_delta_completion.validate_review_report", return_value=[]),
            patch("fix_delta_completion.planning_context_basis", return_value=HASH),
            patch("fix_delta_completion.verification_freshness", return_value=fresh),
        ):
            candidate = completion(root)
            proven = validate_fix_delta_coverage_reuse(root, STEP, candidate, scope)
            assert proven == {
                "fullReview": FULL,
                "fullReviewSha256": "sha256:" + hashlib.sha256(
                    (root / FULL).read_bytes()
                ).hexdigest(),
                "verificationSubjectContentHash": SUBJECT,
                "contractBasis": HASH,
            }, proven
            complete = normalize_semantic_completion(candidate, CRITERIA)
            assert complete["disposition"] == "pass", complete

            # No completion or an unreviewed criterion may be auto-inferred.
            without = deepcopy(candidate)
            without["coverage"] = without["coverage"][:1]
            assert validate_fix_delta_coverage_reuse(root, STEP, without, scope)
            blocked(
                lambda: normalize_semantic_completion(without, CRITERIA),
                "complete coverage",
            )

            # Plain direct evidence is accepted as before, without reuse.
            direct = deepcopy(candidate)
            direct["coverage"][0]["evidence"] = ["Independent direct test PASS"]
            assert validate_fix_delta_coverage_reuse(root, STEP, direct, scope) is None
            assert normalize_semantic_completion(direct, CRITERIA)

            blocked(
                lambda: validate_fix_delta_coverage_reuse(
                    root, STEP, candidate, {"mode": "initial"},
                ),
                "only for FIX delta",
            )
            invalid = deepcopy(candidate)
            invalid["coverage"][0]["evidence"][0] = (
                "previous-review:planning/reviews/STEP-999/REVIEW-20261015T080000Z.md"
            )
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, invalid, scope),
                "exact full REVIEW",
            )
            invalid = deepcopy(candidate)
            invalid["coverage"][0]["evidence"][1] = "verification:" + HASH
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, invalid, scope),
                "current Verification",
            )
            invalid = deepcopy(candidate)
            invalid["coverage"][0]["evidence"].pop()
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, invalid, scope),
                "exact full REVIEW",
            )
            invalid = deepcopy(candidate)
            invalid["coverage"][0]["status"] = "missing"
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, invalid, scope),
                "must be covered",
            )
            with patch("fix_delta_completion.verification_freshness",
                       return_value={"status": "PASS", "fresh": False}):
                blocked(
                    lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                    "fresh Verification PASS",
                )
            with patch("fix_delta_completion.planning_context_basis",
                       return_value="sha256:" + "c" * 64):
                blocked(
                    lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                    "stale after FIX",
                )
            with patch("fix_delta_completion.validate_review_report",
                       return_value=["report invalid"]):
                blocked(
                    lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                    "previous review is invalid",
                )

            # Fail-closed ancestry: no arbitrary paths, no missing/forged
            # full-scope report and no cyclic or too-deep delta chains.
            blocked(
                lambda: validate_fix_delta_coverage_reuse(
                    root, STEP, candidate,
                    {"mode": "fix_delta", "sourceReport": "../" + FULL},
                ),
                "not canonical",
            )
            write(root, FULL, full_report() + "\nTAMPERED after FIX\n")
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                "differs from pre-FIX Git tree",
            )
            write(root, FULL, full_report(marker=False))
            with patch("fix_delta_completion._unchanged_pre_fix_full_report", return_value=True):
                blocked(
                    lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                    "initial/full_explicit",
                )
            write(root, FULL, full_report(verdict="blocked"))
            with patch("fix_delta_completion._unchanged_pre_fix_full_report", return_value=True):
                blocked(
                    lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                    "full baseline has no reviewable verdict",
                )
            write(root, FULL, full_report())
            write(root, DELTA, delta_report(DELTA))
            blocked(
                lambda: validate_fix_delta_coverage_reuse(root, STEP, candidate, scope),
                "cycle",
            )
            write(root, DELTA, delta_report(FULL))
            assert validate_fix_delta_coverage_reuse(root, STEP, candidate, scope)

    print("FIX DELTA COMPLETION REUSE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
