#!/usr/bin/env python3
"""Synthetic matrix for third-party skill provenance/update planning (#225)."""
from __future__ import annotations

from pathlib import Path
import tempfile

from skill_provenance import (
    PROVENANCE_FILE,
    SkillProvenanceError,
    plan_update,
    record_install,
)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def reset_candidate(root: Path, files: dict[str, str]) -> str:
    path = root / ".harness/local/update/candidate"
    if path.exists():
        for item in sorted(path.rglob("*"), reverse=True):
            if item.is_symlink() or item.is_file():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
    path.mkdir(parents=True, exist_ok=True)
    for rel, value in files.items():
        write(path, rel, value)
    return ".harness/local/update/candidate"


def assert_no_product_mutation(root: Path, expected_skill: dict[str, str], registry: str) -> None:
    for rel, text in expected_skill.items():
        assert (root / ".agents/skills/demo" / rel).read_text(encoding="utf-8") == text
    assert (root / "docs/skills/REGISTRY.md").read_text(encoding="utf-8") == registry


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="skill-provenance-") as tmp:
        root = Path(tmp)
        installed = {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v1\n",
        }
        upstream = {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v1\n",
        }
        for rel, value in installed.items():
            write(root, f".agents/skills/demo/{rel}", value)
        for rel, value in upstream.items():
            write(root, f".harness/local/install/upstream/{rel}", value)
        registry = "# registry\nunchanged\n"
        write(root, "docs/skills/REGISTRY.md", registry)

        provenance = record_install(
            root,
            "demo",
            ".harness/local/install/upstream",
            repository="owner/repo",
            source_path="skills/demo",
            inspected_revision="1111111",
            installed_revision="1111111",
            license_value="MIT",
            adaptation_rationale=[],
        )
        assert provenance["installation"]["localModified"] is False
        assert (root / ".agents/skills/demo" / PROVENANCE_FILE).is_file()

        candidate = reset_candidate(root, {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v2\n",
        })
        plan = plan_update(
            root, "demo", candidate_dir=candidate, candidate_revision="2222222"
        )
        assert plan["status"] == "upstream-changed", plan
        assert plan["safeToAutoApply"] is True
        assert plan["conflicts"] == []
        assert_no_product_mutation(root, installed, registry)

        write(root, ".agents/skills/demo/rules.txt", "local-rules\n")
        candidate = reset_candidate(root, {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v1\n",
            "reference.md": "new upstream reference\n",
        })
        plan = plan_update(
            root, "demo", candidate_dir=candidate, candidate_revision="3333333"
        )
        assert plan["status"] == "local-fork", plan
        assert plan["conflicts"] == []
        by_path = {item["path"]: item for item in plan["paths"]}
        assert by_path["rules.txt"]["action"] == "keep-local"
        assert by_path["reference.md"]["action"] == "take-upstream"
        expected = {**installed, "rules.txt": "local-rules\n"}
        assert_no_product_mutation(root, expected, registry)

        candidate = reset_candidate(root, {
            "SKILL.md": "# demo\n",
            "rules.txt": "upstream-rules\n",
        })
        plan = plan_update(
            root, "demo", candidate_dir=candidate, candidate_revision="4444444"
        )
        assert plan["status"] == "conflict", plan
        assert plan["conflicts"] == ["rules.txt"]
        assert_no_product_mutation(root, expected, registry)

        candidate = reset_candidate(root, {"SKILL.md": "# demo\n"})
        plan = plan_update(
            root, "demo", candidate_dir=candidate, candidate_revision="5555555"
        )
        assert plan["status"] == "conflict", plan
        assert "rules.txt" in plan["conflicts"]
        assert_no_product_mutation(root, expected, registry)

        write(root, ".agents/skills/demo/local.txt", "local\n")
        candidate = reset_candidate(root, {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v1\n",
            "local.txt": "upstream-new\n",
        })
        plan = plan_update(
            root, "demo", candidate_dir=candidate, candidate_revision="6666666"
        )
        assert plan["status"] == "conflict", plan
        assert "local.txt" in plan["conflicts"]

        plan = plan_update(
            root,
            "demo",
            candidate_dir=None,
            candidate_revision=None,
            unavailable=True,
        )
        assert plan["status"] == "unavailable", plan
        assert plan["paths"] == []

        candidate_path = root / reset_candidate(root, {
            "SKILL.md": "# demo\n",
            "rules.txt": "rules-v1\n",
        })
        target = root / ".harness/local/update/target.txt"
        target.write_text("secret\n", encoding="utf-8")
        link = candidate_path / "unsafe-link"
        try:
            link.symlink_to(target)
        except OSError:
            pass
        else:
            try:
                plan_update(
                    root,
                    "demo",
                    candidate_dir=".harness/local/update/candidate",
                    candidate_revision="7777777",
                )
            except SkillProvenanceError as exc:
                assert "symlink" in str(exc)
            else:
                raise AssertionError("unsafe symlink candidate must fail closed")

        assert (root / "docs/skills/REGISTRY.md").read_text(encoding="utf-8") == registry
        assert (root / ".agents/skills/demo/SKILL.md").read_text(encoding="utf-8") == "# demo\n"

    print("skill provenance self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
