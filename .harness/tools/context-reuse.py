#!/usr/bin/env python3
"""Optional local-only context hints. Never an authority or a completion gate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from context_reuse import ROLES, store, lookup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("record", "show"))
    parser.add_argument("step")
    parser.add_argument("--role", required=True, choices=sorted(ROLES))
    parser.add_argument("--payload-file")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    options = parser.parse_args()
    root = options.root.resolve()
    try:
        if options.action == "record":
            if not options.payload_file:
                raise ValueError("--payload-file required for record")
            payload_path = (root / options.payload_file).resolve()
            payload_path.relative_to((root / ".harness/local").resolve())
            if not payload_path.is_file() or payload_path.is_symlink():
                raise ValueError("payload must be regular local file")
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) - {"sources", "summary", "rejectedHypotheses"}:
                raise ValueError("unsupported context hint payload")
            store(
                root, options.step, options.role, payload["sources"],
                payload["summary"], payload.get("rejectedHypotheses"),
            )
            result = {"status": "PASS"}
        else:
            # This command is diagnostic; normal semantic handoff calculates
            # exact required paths from Context Contracts itself.
            from step_context import build_step_context
            phase = {"planner": "plan", "implementer": "implement", "reviewer": "review"}[options.role]
            context = build_step_context(root, options.step, phase)
            result = context.get("contextReuse", {"status": "MISSING"})
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("status") in {"PASS", "REUSE_CANDIDATE", "MISSING", "STALE"} else 1
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
