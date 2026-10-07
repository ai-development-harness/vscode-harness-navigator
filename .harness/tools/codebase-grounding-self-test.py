#!/usr/bin/env python3
"""Synthetic regressions for bounded Codebase Grounding payloads."""
from __future__ import annotations

from pathlib import Path
import tempfile

from codebase_grounding import (
    GroundingContractError,
    SCOPE_LIMITS,
    validate_grounding_payload,
)


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def context() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "repositoryRevision": {
            "git_head": "abc123",
            "worktree_hash": "sha256:worktree",
        },
        "required": [
            {
                "artifact": "STEP-001",
                "path": "planning/tasks/STEP-001.md",
                "sections": ["Goal", "Scope"],
            }
        ],
        "metrics": {
            "artifactCount": 1,
            "sectionCount": 2,
            "manifestChars": 123,
            "fullRepositoryPreload": False,
        },
    }


def payload() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "scope": "simple",
        "target": "request flow",
        "repositoryRevision": {
            "git_head": "abc123",
            "worktree_hash": "sha256:worktree",
        },
        "flow": [{"claim": "handler calls service", "evidence": ["src/service.py"]}],
        "ownership": [{"claim": "service owns state", "evidence": ["src/service.py"]}],
        "boundaries": [{"claim": "handler/service seam", "evidence": ["src/service.py"]}],
        "interfaces": [],
        "invariants": [],
        "gotchas": [],
        "unknowns": [],
        "evidencePaths": [
            "planning/tasks/STEP-001.md",
            "src/service.py",
        ],
        "expansions": [
            {
                "path": "src/service.py",
                "reason": "runtime flow implementation required",
            }
        ],
    }


def expect_blocked(root: Path, ctx: dict[str, object], value: dict[str, object]) -> None:
    try:
        validate_grounding_payload(root, ctx, value)
    except GroundingContractError:
        return
    raise AssertionError("grounding payload must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "planning/tasks/STEP-001.md", "# STEP\n")
        write(root, "src/service.py", "def run():\n    return 1\n")
        write(root, ".harness/tools/secret.py", "secret = True\n")

        valid = validate_grounding_payload(root, context(), payload())
        assert valid["status"] == "PASS"
        assert valid["contextBudget"]["expansionFiles"] == 1
        assert valid["contextBudget"]["expansionChars"] > 0
        assert valid["contextBudget"]["baseMetrics"]["fullRepositoryPreload"] is False

        stale = payload()
        stale["repositoryRevision"] = {
            "git_head": "different",
            "worktree_hash": "sha256:worktree",
        }
        expect_blocked(root, context(), stale)

        ungrounded = payload()
        ungrounded["evidencePaths"] = ["src/not-read.py"]
        expect_blocked(root, context(), ungrounded)

        nested_ungrounded = payload()
        nested_ungrounded["flow"] = [
            {
                "claim": "handler calls hidden subsystem",
                "evidence": ["src/not-read.py"],
            }
        ]
        expect_blocked(root, context(), nested_ungrounded)

        missing_from_index = payload()
        missing_from_index["evidencePaths"] = ["planning/tasks/STEP-001.md"]
        expect_blocked(root, context(), missing_from_index)

        no_reason = payload()
        no_reason["expansions"] = [{"path": "src/service.py", "reason": ""}]
        expect_blocked(root, context(), no_reason)

        forbidden = payload()
        forbidden["expansions"] = [
            {
                "path": ".harness/tools/secret.py",
                "reason": "inspect tool internals",
            }
        ]
        forbidden["evidencePaths"] = [".harness/tools/secret.py"]
        expect_blocked(root, context(), forbidden)

        too_large = payload()
        write(
            root,
            "src/large.py",
            "x" * (SCOPE_LIMITS["simple"]["maxExpansionChars"] + 1),
        )
        too_large["expansions"] = [
            {
                "path": "src/large.py",
                "reason": "large implementation required",
            }
        ]
        too_large["evidencePaths"] = ["src/large.py"]
        expect_blocked(root, context(), too_large)

        too_many = payload()
        expansions = []
        evidence = []
        for index in range(SCOPE_LIMITS["simple"]["maxExpansionFiles"] + 1):
            path = f"src/part_{index}.py"
            write(root, path, f"value = {index}\n")
            expansions.append({"path": path, "reason": "flow shard required"})
            evidence.append(path)
        too_many["expansions"] = expansions
        too_many["evidencePaths"] = evidence
        expect_blocked(root, context(), too_many)

    print("codebase-grounding self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
