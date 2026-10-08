#!/usr/bin/env python3
"""Source-pinned context and negative hypothesis cache regression."""
from __future__ import annotations
from pathlib import Path
import tempfile
from context_reuse import store, lookup


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-context-reuse-") as temp:
        root = Path(temp)
        (root / "docs").mkdir()
        source = root / "docs" / "requirement.md"
        source.write_text("Stable contract.\n", encoding="utf-8")
        assert lookup(root, "STEP-101", "planner", ["docs/requirement.md"])["status"] == "MISSING"
        store(
            root, "STEP-101", "planner", ["docs/requirement.md"],
            "This is a source-pinned summary, not an authority.",
            [{"hypothesis": "Potential unauthorized user access",
              "falsification": "Missing route and no registered endpoint in current source."}],
        )
        cached = lookup(root, "STEP-101", "planner", ["docs/requirement.md"])
        assert cached["status"] == "REUSE_CANDIDATE", cached
        assert cached["rejectedHypotheses"], cached
        assert cached["authority"] == "untrusted-navigational-hint-only"
        assert lookup(root, "STEP-101", "planner", ["docs/requirement.md", "src/new.py"])["status"] == "STALE"
        source.write_text("Changed contract.\n", encoding="utf-8")
        assert lookup(root, "STEP-101", "planner", ["docs/requirement.md"])["status"] == "STALE"
        try:
            store(root, "STEP-101", "planner", ["../outside"], "Unsafe")
            raise AssertionError("Traversal accepted")
        except ValueError:
            pass
        try:
            store(root, "STEP-101", "planner", ["docs/requirement.md"], "text", [
                {"hypothesis": "Missing evidence", "falsification": "no"}
            ])
            raise AssertionError("Unproven rejected hypothesis accepted")
        except ValueError:
            pass
    print("CONTEXT REUSE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
