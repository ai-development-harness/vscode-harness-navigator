#!/usr/bin/env python3
"""Synthetic end-to-end regression deterministic Harness self-update engine."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile

from execution_status import load_status
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


def graph(
    latest: str,
    transitions: list[tuple[str, str]],
    *,
    reload_edges: set[tuple[str, str]] | None = None,
) -> str:
    reload_edges = reload_edges or set()
    payload = {
        "schemaVersion": 1,
        "latest": latest,
        "transitions": [
            {
                "from": source,
                "to": target,
                "kind": "standard",
                "reloadRequired": (source, target) in reload_edges,
            }
            for source, target in transitions
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def agents(before: str, project: str, after: str) -> str:
    return f'''# Agents\n\n{before}\n<!-- PROJECT:START -->{project}<!-- PROJECT:END -->\n{after}\n'''


def validator() -> str:
    return '''#!/usr/bin/env python3\nimport sys\nprint("HARNESS VALIDATION: PASS")\nraise SystemExit(0)\n'''


def legacy_execution_state() -> dict:
    """Schema-v1 fixture: update engine не должен трогать local runtime state."""
    timestamp = "2026-09-24T00:00:00+00:00"
    baseline = {
        "stepId": "STEP-001",
        "gitHead": "a" * 40,
        "capturedAt": timestamp,
        "sourceExecutionId": "exec-update-implement",
    }

    def record(
        execution_id: str,
        root_command: str,
        *,
        status: str,
        current_status: str,
        result: str | None,
        implementation_baseline: dict | None = None,
    ) -> dict:
        value = {
            "executionId": execution_id,
            "mode": "single",
            "requestedCommand": root_command,
            "rootCommand": root_command,
            "sequence": [root_command],
            "currentIndex": 0,
            "status": status,
            "current": {
                "command": root_command,
                "status": current_status,
                "result": result,
                "attempt": 1,
                "startedAt": timestamp,
                "completedAt": (
                    None if current_status == "running" else timestamp
                ),
                "context": {},
            },
            "notExecuted": [],
            "fixReviewCycles": 0,
            "startedAt": timestamp,
            "completedAt": None if status == "running" else timestamp,
            "updatedAt": timestamp,
        }
        if implementation_baseline is not None:
            value["implementationBaseline"] = implementation_baseline
        return value

    return {
        "schemaVersion": 1,
        "executions": [
            record(
                "exec-update-implement",
                "STEP IMPLEMENT STEP-001",
                status="complete",
                current_status="complete",
                result="SUCCESS",
                implementation_baseline=baseline,
            ),
            record(
                "exec-update-running",
                "HARNESS CONFIG",
                status="running",
                current_status="running",
                result=None,
            ),
        ],
    }


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


def supported_floor_source(root: Path) -> tuple[Path, dict[str, str], dict[str, str]]:
    """Собрать synthetic v0.6.0 → v0.7.0 → v0.8.0 release source."""

    source = root / "supported-floor-source"
    source.mkdir()
    run(source, "git", "init", "-q", "-b", "main")
    run(source, "git", "config", "user.email", "harness-test@example.invalid")
    run(source, "git", "config", "user.name", "Harness Test")

    transitions = [("v0.6.0", "v0.7.0"), ("v0.7.0", "v0.8.0")]
    reload_edges = {("v0.6.0", "v0.7.0")}
    base_files = {
        ".harness/harness-update.toml": policy(precise_skills=True),
        ".harness/harness-update-graph.json": graph(
            "v0.6.0",
            [],
        ),
        ".harness/manifest.yaml": manifest("0.6.0"),
        ".harness/tools/validate.py": validator(),
        ".harness/tools/harness_update.py": "# updater runtime v0.6.0\n",
        ".harness/tools/harness-update.py": "# updater cli v0.6.0\n",
        ".agents/skills/core/SKILL.md": "core v0.6.0\n",
        "shared.txt": "base-line-1\nstable-line-2\nstable-line-3\nstable-line-4\nbase-line-5\n",
        "AGENTS.md": agents("before v0.6.0", "\nbase project\n", "after v0.6.0"),
    }
    for path, text in base_files.items():
        write(source, path, text)
    run(source, "git", "add", ".")
    run(source, "git", "commit", "-qm", "v0.6.0")
    run(source, "git", "tag", "v0.6.0")
    oids = {"v0.6.0": run(source, "git", "rev-parse", "v0.6.0^{commit}")}

    # v0.7.0 меняет сам updater и вводит новый Harness-owned файл.
    # Это заставляет первый APPLY завершиться на reload boundary.
    write(
        source,
        ".harness/harness-update-graph.json",
        graph(
            "v0.7.0",
            [("v0.6.0", "v0.7.0")],
            reload_edges=reload_edges,
        ),
    )
    write(source, ".harness/manifest.yaml", manifest("0.7.0"))
    write(source, ".harness/tools/harness_update.py", "# updater runtime v0.7.0\n")
    write(source, ".harness/tools/harness-update.py", "# updater cli v0.7.0\n")
    write(source, ".harness/tools/v070-only.py", "# introduced in v0.7.0\n")
    write(source, ".agents/skills/core/SKILL.md", "core v0.7.0\n")
    write(source, "shared.txt", "base-line-1\nstable-line-2\nstable-line-3\nstable-line-4\nv070-line-5\n")
    write(source, "AGENTS.md", agents("before v0.7.0", "\nbase project\n", "after v0.7.0"))
    run(source, "git", "add", ".")
    run(source, "git", "commit", "-qm", "v0.7.0")
    run(source, "git", "tag", "v0.7.0")
    oids["v0.7.0"] = run(source, "git", "rev-parse", "v0.7.0^{commit}")

    # v0.8.0 сохраняет topology updater-а, поэтому после перезагрузки маршрут
    # должен завершиться без ещё одной reload boundary.
    write(
        source,
        ".harness/harness-update-graph.json",
        graph("v0.8.0", transitions, reload_edges=reload_edges),
    )
    write(source, ".harness/manifest.yaml", manifest("0.8.0"))
    write(source, ".harness/tools/v070-only.py", "# updated in v0.8.0\n")
    write(source, ".agents/skills/core/SKILL.md", "core v0.8.0\n")
    write(source, "shared.txt", "base-line-1\nstable-line-2\nv080-line-3\nstable-line-4\nv070-line-5\n")
    write(source, "AGENTS.md", agents("before v0.8.0", "\nbase project\n", "after v0.8.0"))
    run(source, "git", "add", ".")
    run(source, "git", "commit", "-qm", "v0.8.0")
    run(source, "git", "tag", "v0.8.0")
    oids["v0.8.0"] = run(source, "git", "rev-parse", "v0.8.0^{commit}")
    return source, base_files, oids


def project_from_v060(
    root: Path,
    base_files: dict[str, str],
    base_oid: str,
) -> Path:
    """Создать реальный Git project с Harness v0.6.0 и локальными изменениями."""

    for path, text in base_files.items():
        write(root, path, text)
    write(root, ".harness/manifest.yaml", manifest("0.6.0", initialized=True))
    write(root, "shared.txt", "local-line-1\nstable-line-2\nstable-line-3\nstable-line-4\nbase-line-5\n")
    write(
        root,
        "AGENTS.md",
        agents("before v0.6.0", "\nLOCAL PROJECT CONTEXT\n", "after v0.6.0"),
    )
    write(root, ".agents/skills/custom/SKILL.md", "project custom skill\n")
    write(
        root,
        ".harness/harness.lock.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "harnessVersion": "1",
                "release": "0.6.0",
                "source": {
                    "repository": "example/harness",
                    "ref": "v0.6.0",
                    "commit": base_oid,
                },
                "updatedAt": None,
            },
            indent=2,
        )
        + "\n",
    )
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "project@example.invalid")
    run(root, "git", "config", "user.name", "Project")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "project on v0.6.0")
    return root


def test_supported_floor_reload_chain(temp: Path) -> None:
    """Доказать v0.6.0 → v0.7.0 → reload → v0.8.0 одним final target."""

    source, base_files, oids = supported_floor_source(temp)
    project = project_from_v060(
        temp / "supported-floor-project",
        base_files,
        oids["v0.6.0"],
    )

    checked = check_update(project, target="v0.8.0", source_url=str(source))
    assert checked["status"] == "PASS", checked
    assert checked["route"] == ["v0.6.0", "v0.7.0", "v0.8.0"], checked
    assert checked["checkedThrough"] == "v0.7.0", checked
    assert checked["reloadBoundary"] == "v0.7.0", checked
    assert len(checked["hops"]) == 1, checked

    first = apply_update(project, target="v0.8.0", source_url=str(source))
    assert first["status"] == "UPDATER_RELOAD_REQUIRED", first
    assert first["current"] == "v0.7.0", first
    assert first["resolvedTarget"] == "v0.8.0", first
    assert first["route"] == ["v0.6.0", "v0.7.0"], first

    lock = json.loads((project / ".harness/harness.lock.json").read_text())
    assert lock["release"] == "0.7.0", lock
    assert lock["source"]["ref"] == "v0.7.0", lock
    assert lock["source"]["commit"] == oids["v0.7.0"], lock
    assert "updater runtime v0.7.0" in (
        project / ".harness/tools/harness_update.py"
    ).read_text(encoding="utf-8")

    # Новый файл v0.7.0 намеренно ещё не tracked: пользователь не должен
    # коммитить промежуточный hop только ради продолжения после reload.
    status = run(
        project,
        "git",
        "status",
        "--porcelain",
        "--",
        ".harness/tools/v070-only.py",
    )
    assert status.startswith("??"), status

    # Имитация перезагрузки: следующий вызов уже опирается на lock v0.7.0 и
    # установленный control plane v0.7.0, но сохраняет исходный final target.
    resumed_check = check_update(
        project,
        target="v0.8.0",
        source_url=str(source),
    )
    assert resumed_check["route"] == ["v0.7.0", "v0.8.0"], resumed_check
    assert resumed_check["checkedThrough"] == "v0.8.0", resumed_check
    assert resumed_check["reloadBoundary"] is None, resumed_check

    second = apply_update(project, target="v0.8.0", source_url=str(source))
    assert second["status"] == "UPDATED", second
    assert second["current"] == "v0.8.0", second
    assert second["route"] == ["v0.7.0", "v0.8.0"], second

    final_lock = json.loads((project / ".harness/harness.lock.json").read_text())
    assert final_lock["release"] == "0.8.0", final_lock
    assert final_lock["source"]["ref"] == "v0.8.0", final_lock
    assert final_lock["source"]["commit"] == oids["v0.8.0"], final_lock

    manifest_text = (project / ".harness/manifest.yaml").read_text(encoding="utf-8")
    assert 'release: "0.8.0"' in manifest_text, manifest_text
    assert (project / ".harness/tools/v070-only.py").read_text() == "# updated in v0.8.0\n"
    assert (project / ".agents/skills/custom/SKILL.md").read_text() == "project custom skill\n"

    shared = (project / "shared.txt").read_text(encoding="utf-8")
    assert shared == "local-line-1\nstable-line-2\nv080-line-3\nstable-line-4\nv070-line-5\n", shared
    merged_agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "before v0.8.0" in merged_agents and "after v0.8.0" in merged_agents
    assert "LOCAL PROJECT CONTEXT" in merged_agents

    reports = sorted((project / "reports").glob("UPDATE-*.md"))
    assert len(reports) == 2, reports


def test_stale_release_snapshot_pin_recovery(temp: Path) -> None:
    """Stale release self-pin блокируется, точечная замена на tag OID восстанавливает route."""

    source, base_files, oids = supported_floor_source(temp)
    project = project_from_v060(
        temp / "stale-release-pin-project",
        base_files,
        oids["v0.6.0"],
    )
    lock_path = project / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["source"]["commit"] = "e366c48777150a9e9d2f6d670d8976b8a8df2d5c"
    write(project, ".harness/harness.lock.json", json.dumps(lock, indent=2) + "\n")

    try:
        check_update(project, target="v0.8.0", source_url=str(source))
    except UpdateError as exc:
        assert exc.code == "SOURCE_TAG_MOVED", (exc.code, exc)
    else:
        raise AssertionError("stale release snapshot pin bypassed SOURCE_TAG_MOVED")

    # Recovery не отключает tag pinning: заменяется только известный stale OID
    # на доказанный OID текущего immutable tag.
    lock["source"]["commit"] = oids["v0.6.0"]
    write(project, ".harness/harness.lock.json", json.dumps(lock, indent=2) + "\n")

    checked = check_update(project, target="v0.8.0", source_url=str(source))
    assert checked["status"] == "PASS", checked
    assert checked["route"] == ["v0.6.0", "v0.7.0", "v0.8.0"], checked
    assert checked["checkedThrough"] == "v0.7.0", checked
    assert checked["reloadBoundary"] == "v0.7.0", checked


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

        # Current updater больше не принимает operational baselines ниже v0.6.0,
        # даже если historical graph хранит старые release edges.
        unsupported = project_from_base(temp / "unsupported", base_files, base_oid)
        write(unsupported, ".harness/manifest.yaml", manifest("0.5.3", initialized=True))
        unsupported_lock = json.loads(
            (unsupported / ".harness/harness.lock.json").read_text(encoding="utf-8")
        )
        unsupported_lock["release"] = "0.5.3"
        unsupported_lock["source"]["ref"] = "v0.5.3"
        unsupported_lock["source"].pop("commit", None)
        write(
            unsupported,
            ".harness/harness.lock.json",
            json.dumps(unsupported_lock, indent=2) + "\n",
        )
        try:
            check_update(unsupported, target="v1.1.0", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "UNSUPPORTED_HARNESS_RELEASE", (exc.code, exc)
        else:
            raise AssertionError("current updater accepted current release below v0.6.0")

        unsupported_legacy = project_from_base(
            temp / "unsupported-legacy",
            base_files,
            base_oid,
        )
        (unsupported_legacy / ".harness/harness.lock.json").unlink()
        write(
            unsupported_legacy,
            ".harness/manifest.yaml",
            manifest("0.5.3", initialized=True),
        )
        try:
            adopt_legacy(
                unsupported_legacy,
                baseline="v0.5.3",
                source_url=str(source),
            )
        except UpdateError as exc:
            assert exc.code == "UNSUPPORTED_HARNESS_RELEASE", (exc.code, exc)
        else:
            raise AssertionError("legacy adoption accepted baseline below v0.6.0")

        project = project_from_base(temp / "project", base_files, base_oid)
        try:
            check_update(project, target="v0.5.3", source_url=str(source))
        except UpdateError as exc:
            assert exc.code == "UNSUPPORTED_HARNESS_RELEASE", (exc.code, exc)
        else:
            raise AssertionError("current updater accepted target release below v0.6.0")

        # Regression #85: HARNESS UPDATE владеет control plane, но не local
        # runtime schema. Старый v1 state должен остаться byte-for-byte прежним
        # на CHECK/APPLY; migration выполняет только новый execution layer после
        # simulated reload.
        execution_state_path = (
            project / ".harness/local/execution/execution-status.json"
        )
        write(
            project,
            ".harness/local/execution/execution-status.json",
            json.dumps(legacy_execution_state(), ensure_ascii=False, indent=2)
            + "\n",
        )
        legacy_execution_bytes = execution_state_path.read_bytes()

        checked = check_update(project, target="v1.1.0", source_url=str(source))
        assert checked["status"] == "PASS", checked
        assert execution_state_path.read_bytes() == legacy_execution_bytes
        assert checked["route"] == ["v1.0.0", "v1.1.0"], checked
        assert checked["checkedThrough"] == "v1.1.0", checked
        changed = {item["path"] for item in checked["hops"][0]["changes"]}
        assert ".agents/skills/custom/SKILL.md" not in changed, changed
        assert ".agents/skills/new-core/SKILL.md" in changed, changed

        applied = apply_update(project, target="v1.1.0", source_url=str(source))
        assert applied["status"] == "UPDATED", applied
        assert execution_state_path.read_bytes() == legacy_execution_bytes

        # Simulated runtime reload: только теперь current execution layer читает
        # legacy bytes и выполняет validated atomic v1 -> v2 migration.
        migrated_execution = load_status(project)
        assert migrated_execution["schemaVersion"] == 2, migrated_execution
        assert [
            item["executionId"] for item in migrated_execution["executions"]
        ] == ["exec-update-running"], migrated_execution
        assert (
            migrated_execution["stepRecovery"]["STEP-001"][
                "implementationBaseline"
            ]["gitHead"]
            == "a" * 40
        ), migrated_execution
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

        stale_pin_case = temp / "stale-pin-case"
        stale_pin_case.mkdir()
        test_stale_release_snapshot_pin_recovery(stale_pin_case)

        reload_chain_case = temp / "reload-chain-case"
        reload_chain_case.mkdir()
        test_supported_floor_reload_chain(reload_chain_case)

    print("HARNESS UPDATE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
