#!/usr/bin/env python3
"""Synthetic end-to-end regression deterministic Harness self-update engine."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile

from harness_update import UpdateError, adopt_legacy, apply_update, check_update


def run(root: Path, *args: str) -> str:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def policy(*, precise_skills: bool) -> str:
    skills = (
        '  ".agents/skills/core/**",\n  ".agents/skills/new-core/**",'
        if precise_skills
        else '  ".agents/skills/**",'
    )
    return f'''[source]
repository = "example/harness"
default_branch = "main"
tag_pattern = '^v\\d+\\.\\d+\\.\\d+$'
update_manifest = ".harness/harness-update-graph.json"

[state]
lock_file = ".harness/harness.lock.json"
report_directory = "reports"

[ownership]
harness_owned = [
  ".harness/harness-update-graph.json",
  ".harness/harness-update.toml",
  ".harness/tools/**",
{skills}
]
shared = [".harness/manifest.yaml", "shared.txt"]
marker_merge = ["AGENTS.md"]

[markers."AGENTS.md"]
blocks = ["PROJECT"]
'''


def manifest(release: str, initialized: bool = False) -> str:
    return f'''harness:
  version: "1"
  release: "{release}"
project:
  initialized: {'true' if initialized else 'false'}
repository:
  harnessUpdatePolicy: .harness/harness-update.toml
'''


def graph(latest: str, transitions: list[tuple[str, str]]) -> str:
    payload = {
        "schemaVersion": 1,
        "latest": latest,
        "transitions": [
            {"from": source, "to": target, "kind": "standard", "reloadRequired": False}
            for source, target in transitions
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def agents(before: str, project: str, after: str) -> str:
    return f'''# Agents\n\n{before}\n<!-- PROJECT:START -->{project}<!-- PROJECT:END -->\n{after}\n'''


def validator() -> str:
    return '''#!/usr/bin/env python3\nimport sys\nprint("HARNESS VALIDATION: PASS")\nraise SystemExit(0)\n'''


def source_repo(root: Path) -> tuple[Path, dict[str, str], str, str]:
    source = root / "source"
    source.mkdir()
    run(source, "git", "init", "-q", "-b", "main")
    run(source, "git", "config", "user.email", "harness-test@example.invalid")
    run(source, "git", "config", "user.name", "Harness Test")

    base_files = {
        ".harness/harness-update.toml": policy(precise_skills=False),
        ".harness/harness-update-graph.json": graph("v1.0.0", []),
        ".harness/manifest.yaml": manifest("1.0.0"),
        ".harness/tools/validate.py": validator(),
        ".harness/tools/harness_update.py": "# stable updater runtime\n",
        ".harness/tools/harness-update.py": "# stable updater cli\n",
        ".agents/skills/core/SKILL.md": "core v1\n",
        "shared.txt": "local-target-base-1\nline-2\nbase-target-line-3\n",
        "AGENTS.md": agents("before v1", "\nbase project\n", "after v1"),
    }
    for path, text in base_files.items():
        write(source, path, text)
    run(source, "git", "add", ".")
    run(source, "git", "commit", "-qm", "v1.0.0")
    run(source, "git", "tag", "v1.0.0")
    base_oid = run(source, "git", "rev-parse", "v1.0.0^{commit}")

    write(source, ".harness/harness-update.toml", policy(precise_skills=True))
    write(source, ".harness/harness-update-graph.json", graph("v1.1.0", [("v1.0.0", "v1.1.0")]))
    write(source, ".harness/manifest.yaml", manifest("1.1.0"))
    write(source, ".agents/skills/core/SKILL.md", "core v2\n")
    write(source, ".agents/skills/new-core/SKILL.md", "new core v1\n")
    write(source, "shared.txt", "local-target-base-1\nline-2\ntarget-line-3\n")
    write(source, "AGENTS.md", agents("before v2", "\nbase project\n", "after v2"))
    run(source, "git", "add", ".")
    run(source, "git", "commit", "-qm", "v1.1.0")
    run(source, "git", "tag", "v1.1.0")
    target_oid = run(source, "git", "rev-parse", "v1.1.0^{commit}")
    # Git позволяет branch и tag с одинаковым именем. Release reads обязаны
    # выбирать refs/tags/*, а не moving branch.
    run(source, "git", "branch", "v1.0.0", "v1.1.0")
    return source, base_files, base_oid, target_oid


def project_from_base(root: Path, base_files: dict[str, str], base_oid: str) -> Path:
    project = root
    for path, text in base_files.items():
        write(project, path, text)
    # Project-owned state changes must survive shared/marker merge.
    write(project, ".harness/manifest.yaml", manifest("1.0.0", initialized=True))
    write(project, "shared.txt", "local-line-1\nline-2\nbase-target-line-3\n")
    write(project, "AGENTS.md", agents("before v1", "\nLOCAL PROJECT CONTEXT\n", "after v1"))
    write(project, ".agents/skills/custom/SKILL.md", "project custom skill\n")
    write(
        project,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "harnessVersion": "1",
                "release": "1.0.0",
                "source": {"repository": "example/harness", "ref": "v1.0.0"},
                "updatedAt": None,
            },
            indent=2,
        )
        + "\n",
    )
    run(project, "git", "init", "-q", "-b", "main")
    run(project, "git", "config", "user.email", "project@example.invalid")
    run(project, "git", "config", "user.name", "Project")
    run(project, "git", "add", ".")
    run(project, "git", "commit", "-qm", "project base")
    return project


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-update-engine-") as tmp:
        temp = Path(tmp)
        source, base_files, base_oid, target_oid = source_repo(temp)

        legacy = project_from_base(temp / "legacy", base_files, base_oid)
        (legacy / ".harness/harness.lock.json").unlink()
        # Missing lock должен классифицироваться раньше общего validator failure.
        write(
            legacy,
            ".harness/tools/validate.py",
            '#!/usr/bin/env python3\nprint("HARNESS VALIDATION: FAIL")\nraise SystemExit(1)\n',
        )
        try:
            check_update(legacy, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "LEGACY_ADOPTION_REQUIRED", (exc.code, exc)
        else:
            raise AssertionError("legacy project without lock bypassed adoption boundary")
        write(legacy, ".harness/tools/validate.py", validator())
        adopted = adopt_legacy(legacy, baseline="v1.0.0", source_url=str(source))
        assert adopted["status"] == "ADOPTED", adopted
        adopted_lock = json.loads((legacy / ".harness/harness.lock.json").read_text())
        assert adopted_lock["source"]["commit"] == base_oid, adopted_lock
        assert any("custom/SKILL.md" in item for item in adopted["divergences"]), adopted

        project = project_from_base(temp / "project", base_files, base_oid)
        checked = check_update(project, target="v1.1.0", source_url=str(source))
        assert checked["status"] == "PASS", checked
        assert checked["route"] == ["v1.0.0", "v1.1.0"], checked
        assert checked["checkedThrough"] == "v1.1.0", checked
        changed = {item["path"] for item in checked["hops"][0]["changes"]}
        assert ".agents/skills/custom/SKILL.md" not in changed, changed
        assert ".agents/skills/new-core/SKILL.md" in changed, changed

        applied = apply_update(project, target="v1.1.0", source_url=str(source))
        assert applied["status"] == "UPDATED", applied
        assert (project / ".agents/skills/custom/SKILL.md").read_text() == "project custom skill\n"
        assert (project / ".agents/skills/core/SKILL.md").read_text() == "core v2\n"
        assert (project / ".agents/skills/new-core/SKILL.md").read_text() == "new core v1\n"
        shared = (project / "shared.txt").read_text()
        assert "local-line-1" in shared and "target-line-3" in shared, shared
        merged_agents = (project / "AGENTS.md").read_text()
        assert "before v2" in merged_agents and "after v2" in merged_agents, merged_agents
        assert "LOCAL PROJECT CONTEXT" in merged_agents, merged_agents
        updated_lock = json.loads((project / ".harness/harness.lock.json").read_text())
        assert updated_lock["source"]["ref"] == "v1.1.0", updated_lock
        assert updated_lock["source"]["commit"] == target_oid, updated_lock
        assert list((project / "reports").glob("UPDATE-*.md"))

        # Lock/ref equality недостаточна: Harness-owned OURS должен точно
        # соответствовать pinned release даже когда route пустой.
        core_path = project / ".agents/skills/core/SKILL.md"
        core_clean = core_path.read_text(encoding="utf-8")
        write(project, ".agents/skills/core/SKILL.md", "locally drifted core\n")
        try:
            check_update(project, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "CURRENT_RELEASE_DRIFT", (exc.code, exc)
        else:
            raise AssertionError("CHECK accepted Harness-owned drift with empty route")
        try:
            apply_update(project, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "CURRENT_RELEASE_DRIFT", (exc.code, exc)
        else:
            raise AssertionError("APPLY returned NO_UPDATE for drifted Harness-owned state")
        write(project, ".agents/skills/core/SKILL.md", core_clean)

        # Новый core slug не может молча захватить существующий project skill.
        collision = project_from_base(temp / "collision", base_files, base_oid)
        write(collision, ".agents/skills/new-core/SKILL.md", "project owns this slug\n")
        run(collision, "git", "add", ".agents/skills/new-core/SKILL.md")
        run(collision, "git", "commit", "-qm", "project skill with future core slug")
        try:
            check_update(collision, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "NEW_MANAGED_PATH_COLLISION", (exc.code, exc)
        else:
            raise AssertionError("target core skill captured existing project skill")

        # Изменение bootstrap source/state topology требует отдельного bridge,
        # а не неявной интерпретации текущим updater.
        target_policy = policy(precise_skills=True).replace(
            'report_directory = "reports"',
            'report_directory = "reports-v2"',
        )
        write(source, ".harness/harness-update.toml", target_policy)
        write(
            source,
            ".harness/harness-update-graph.json",
            graph("v1.2.0", [("v1.0.0", "v1.1.0"), ("v1.1.0", "v1.2.0")]),
        )
        write(source, ".harness/manifest.yaml", manifest("1.2.0"))
        run(source, "git", "add", ".")
        run(source, "git", "commit", "-qm", "v1.2.0 topology change")
        run(source, "git", "tag", "v1.2.0")
        try:
            check_update(project, target="v1.2.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "UPDATE_POLICY_TOPOLOGY_CHANGE", (exc.code, exc)
        else:
            raise AssertionError("bootstrap update topology changed without explicit bridge support")

        # Once lock pins a tag OID, moved tags fail closed.
        run(source, "git", "tag", "-f", "v1.1.0", "v1.0.0")
        try:
            check_update(project, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "SOURCE_TAG_MOVED", (exc.code, exc)
        else:
            raise AssertionError("moved release tag was accepted")

    print("HARNESS UPDATE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
