#!/usr/bin/env python3
"""Deterministic HARNESS HELP catalog renderer."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from command_transitions import load_transition_table, validate_transition_table

def help_catalog(root: Path) -> list[dict[str, Any]]:
    table = load_transition_table(root)
    errors = validate_transition_table(table)
    if errors:
        raise RuntimeError("invalid command transition table: " + "; ".join(errors))
    result: list[dict[str, Any]] = []
    for domain_name, domain in table["domains"].items():
        commands = [
            {"canonical": spec["canonical"], "summary": spec["summary"], "documentation": spec["documentation"]}
            for spec in domain["commands"].values()
        ]
        result.append({"domain": domain_name, "commands": commands})
    return result

def render_text(catalog: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for domain in catalog:
        lines.append(domain["domain"])
        for command in domain["commands"]:
            lines.append(f"  {command['canonical']}")
            lines.append(f"    {command['summary']}")
            lines.append(f"    Docs: {command['documentation']}")
        lines.append("")
    return "\n".join(lines).rstrip()

def main() -> int:
    parser = argparse.ArgumentParser(description="Render canonical Harness command help")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        catalog = help_catalog(root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status":"BLOCKED","message":str(exc)}, ensure_ascii=False) if args.as_json else f"HARNESS HELP: BLOCKED: {exc}")
        return 2
    if args.as_json:
        print(json.dumps({"status":"PASS","domains":catalog}, ensure_ascii=False, indent=2))
    else:
        print(render_text(catalog))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
