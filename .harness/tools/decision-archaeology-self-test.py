#!/usr/bin/env python3
"""Synthetic regressions for Decision Archaeology."""
from __future__ import annotations

from pathlib import Path
import copy
import subprocess
import tempfile

from decision_archaeology import (
    DecisionArchaeologyError,
    decision_archaeology_preflight,
    validate_decision_archaeology_payload,
)
from review_contract import repository_revision


MANIFEST = """protocol:
  reviewDirectory: planning/reviews
"""

ADR = """---
schema: 1
id: ADR-001
status: accepted
date: 2026-10-01
deciders:
  - test
supersedes: []
superseded_by: []
requirements: []
steps: []
---

# ADR-001 — Retry policy

## Context

Provider calls can fail transiently.

## Problem

Recovery must be bounded.

## Decision

Use three retries before surfacing failure.

## Alternatives considered

- Unlimited retries.

## Consequences

Recovery latency remains bounded.

## Security implications

Not applicable.

## Data / migration implications

Not applicable.

## Compatibility / operational implications

Clients observe bounded retry latency.
"""

TARGET_V1 = """MAX_RETRIES = 3

def call_provider(operation):
    for attempt in range(MAX_RETRIES):
        try:
            return operation()
        except TimeoutError:
            if attempt == MAX_RETRIES - 1:
                raise
"""

TARGET_V2 = TARGET_V1.replace("MAX_RETRIES = 3", "MAX_RETRIES = 4")


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ("git", *args),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr}"
        )
    return proc.stdout.strip()


def init_repo(root: Path) -> tuple[str, str, str]:
    write(root, ".harness/manifest.yaml", MANIFEST)
    write(root, "docs/adr/ADR-001-retry.md", ADR)
    write(root, "src/retry.py", TARGET_V1)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "archaeology@example.invalid")
    git(root, "config", "user.name", "Archaeology Test")
    git(root, "config", "gc.auto", "0")
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Introduce bounded retry policy")
    first = git(root, "rev-parse", "HEAD")

    write(root, "src/retry.py", TARGET_V2)
    git(root, "add", "src/retry.py")
    git(root, "commit", "-qm", "Increase retry threshold after provider tuning")
    second = git(root, "rev-parse", "HEAD")

    write(root, "docs/unrelated.md", "# Unrelated\n")
    git(root, "add", "docs/unrelated.md")
    git(root, "commit", "-qm", "Add unrelated documentation")
    unrelated = git(root, "rev-parse", "HEAD")
    return first, second, unrelated


def context(root: Path) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "repositoryRevision": repository_revision(root),
        "required": [
            {
                "artifact": "ADR-001",
                "path": "docs/adr/ADR-001-retry.md",
                "sections": ["Decision", "Consequences"],
            }
        ],
        "metrics": {
            "artifactCount": 1,
            "sectionCount": 2,
            "manifestChars": 100,
            "fullRepositoryPreload": False,
        },
    }


def base_payload(
    root: Path,
    *,
    first: str,
    second: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "scope": "simple",
        "target": "src/retry.py",
        "repositoryRevision": repository_revision(root),
        "claims": [
            {
                "id": "R-001",
                "statement": "Retry behavior originated as a bounded recovery policy.",
                "basis": "documented",
                "confidence": "high",
                "evidence": [
                    {
                        "kind": "artifact",
                        "ref": "docs/adr/ADR-001-retry.md",
                    },
                    {
                        "kind": "commit",
                        "ref": first,
                    },
                ],
            },
            {
                "id": "R-002",
                "statement": "The later threshold change was probably operational tuning.",
                "basis": "inference",
                "confidence": "medium",
                "evidence": [
                    {
                        "kind": "commit",
                        "ref": second,
                    },
                    {
                        "kind": "supplied",
                        "ref": "E-001",
                    },
                ],
                "uncertainty": "No canonical ADR records the new numeric threshold.",
            },
        ],
        "conflicts": [],
        "gaps": [],
        "staleDecisions": [
            {
                "artifact": "docs/adr/ADR-001-retry.md",
                "assessment": "possibly-stale",
                "reason": "Current threshold differs from the accepted decision.",
                "evidence": [
                    {
                        "kind": "artifact",
                        "ref": "docs/adr/ADR-001-retry.md",
                    },
                    {
                        "kind": "commit",
                        "ref": second,
                    },
                ],
            }
        ],
        "suppliedEvidence": [
            {
                "id": "E-001",
                "sourceKind": "issue",
                "ref": "https://example.invalid/issues/17",
                "title": "Provider retry tuning",
                "observedAt": "2026-10-02T10:00:00Z",
            }
        ],
        "expansions": [],
    }


def expect_rejected(
    root: Path,
    ctx: dict[str, object],
    payload: dict[str, object],
) -> None:
    try:
        validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            payload,
            ctx,
        )
    except DecisionArchaeologyError:
        return
    raise AssertionError("decision archaeology payload must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="decision-archaeology-") as tmp:
        root = Path(tmp)
        first, second, unrelated = init_repo(root)
        ctx = context(root)

        preflight = decision_archaeology_preflight(
            root,
            "src/retry.py",
            "simple",
            ctx,
        )
        assert preflight["status"] == "PASS", preflight
        assert preflight["repositoryRevision"] == repository_revision(root)
        history = preflight["history"]
        assert [item["sha"] for item in history] == [second, first], history
        assert unrelated not in {item["sha"] for item in history}, history
        assert len(history) <= 12

        payload = base_payload(root, first=first, second=second)
        validated = validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            payload,
            ctx,
        )
        assert validated["status"] == "PASS", validated
        assert validated["contextBudget"]["expansionFiles"] == 1, validated
        assert validated["expansions"][0]["implicitTarget"] is True, validated
        evidence = validated["evidenceMap"]["R-001"]
        assert evidence[0]["artifactKind"] == "adr", evidence
        assert evidence[0]["observedAt"], evidence
        assert evidence[1]["observedAt"], evidence
        assert validated["suppliedEvidence"][0]["verification"] == (
            "supplied-not-locally-verifiable"
        )

        # Conflicting explanations must remain explicit rather than being merged
        # into one synthetic narrative.
        conflicting = copy.deepcopy(payload)
        conflicting["claims"][1]["basis"] = "documented"
        conflicting["claims"][1]["confidence"] = "high"
        conflicting["claims"][1]["evidence"] = [
            {"kind": "commit", "ref": second}
        ]
        conflicting["conflicts"] = [
            {
                "claimIds": ["R-001", "R-002"],
                "summary": (
                    "Accepted ADR fixes the policy at three retries while a later "
                    "commit changes the threshold without a replacement ADR."
                ),
            }
        ]
        conflict_result = validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            conflicting,
            ctx,
        )
        assert conflict_result["conflicts"][0]["claimIds"] == [
            "R-001",
            "R-002",
        ]

        # Fetched PR/issue/docs can document rationale even though the local
        # validator marks them as externally supplied rather than repository-local.
        supplied_only = copy.deepcopy(payload)
        supplied_only["claims"][0]["evidence"] = [
            {"kind": "supplied", "ref": "E-001"}
        ]
        supplied_result = validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            supplied_only,
            ctx,
        )
        assert supplied_result["claims"][0]["basis"] == "documented"
        assert supplied_result["claims"][0]["evidence"][0]["verification"] == (
            "supplied-not-locally-verifiable"
        )

        documented_without_evidence = copy.deepcopy(payload)
        documented_without_evidence["claims"][0]["evidence"] = []
        expect_rejected(root, ctx, documented_without_evidence)

        # Commit evidence is bounded to history of the concrete target.
        wrong_commit = copy.deepcopy(payload)
        wrong_commit["claims"][0]["evidence"] = [
            {"kind": "commit", "ref": unrelated}
        ]
        expect_rejected(root, ctx, wrong_commit)

        # Transcript/session evidence is not a supported source category.
        transcript = copy.deepcopy(payload)
        transcript["suppliedEvidence"][0]["sourceKind"] = "transcript"
        expect_rejected(root, ctx, transcript)

        bad_timestamp = copy.deepcopy(payload)
        bad_timestamp["suppliedEvidence"][0]["observedAt"] = "yesterday"
        expect_rejected(root, ctx, bad_timestamp)

        # No-evidence inference is allowed only as low-confidence,
        # explicit INCONCLUSIVE knowledge gap.
        gap = copy.deepcopy(payload)
        gap["status"] = "INCONCLUSIVE"
        gap["claims"][1]["confidence"] = "low"
        gap["claims"][1]["evidence"] = []
        gap["claims"][1]["uncertainty"] = (
            "No retained source explains the threshold increase."
        )
        gap["gaps"] = [
            "Historical source for the threshold increase is unavailable."
        ]
        gap_result = validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            gap,
            ctx,
        )
        assert gap_result["status"] == "INCONCLUSIVE", gap_result

        false_pass = copy.deepcopy(gap)
        false_pass["status"] = "PASS"
        expect_rejected(root, ctx, false_pass)

        missing_gap = copy.deepcopy(gap)
        missing_gap["gaps"] = []
        expect_rejected(root, ctx, missing_gap)

        medium_guess = copy.deepcopy(gap)
        medium_guess["claims"][1]["confidence"] = "medium"
        expect_rejected(root, ctx, medium_guess)

        stale_without_evidence = copy.deepcopy(payload)
        stale_without_evidence["staleDecisions"][0]["evidence"] = []
        expect_rejected(root, ctx, stale_without_evidence)

        unknown_stale = copy.deepcopy(payload)
        unknown_stale["staleDecisions"][0]["assessment"] = "unknown"
        unknown_stale["staleDecisions"][0]["evidence"] = []
        unknown_result = validate_decision_archaeology_payload(
            root,
            "src/retry.py",
            "simple",
            unknown_stale,
            ctx,
        )
        assert unknown_result["staleDecisions"][0]["assessment"] == "unknown"

        # Context expansion is bounded. Target already consumes one slot here,
        # so six additional files exceed simple scope's total of six.
        over_budget = copy.deepcopy(payload)
        over_budget["expansions"] = []
        for index in range(6):
            rel = f"docs/extra-{index}.md"
            write(root, rel, f"# Extra {index}\n")
            over_budget["expansions"].append(
                {"path": rel, "reason": f"candidate rationale {index}"}
            )
        over_budget["repositoryRevision"] = repository_revision(root)
        over_ctx = context(root)
        expect_rejected(root, over_ctx, over_budget)

    print("decision-archaeology self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
