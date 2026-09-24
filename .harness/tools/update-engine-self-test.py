#!/usr/bin/env python3
"""Regressions транзакционного update engine: журнал, recovery, ownership.

Покрывает defects, закрытые переработкой engine:

- #98  target validator исполняется только внутри журналированной транзакции;
- #99  harness_owned path, переданный проекту, сохраняется;
- #100 новый marker block target-релиза не блокирует update;
- #101 pre-INIT template change: UPDATED/NO_UPDATE оставляют проект валидным;
- #102 изменение загруженного модуля — reload boundary;
- #103 failure/interrupt откатывают hop byte-for-byte, включая local state;
- #104 adopt fail-closed, graph не читается из tag, unsafe tree paths.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from harness_update import UpdateError, adopt_legacy, apply_update, check_update


SOURCE_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = Path(__file__).resolve().parent
JOURNAL = ".harness/local/update-journal"
STATE = ".harness/local/execution/execution-status.json"


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return proc


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def git_init(root: Path) -> None:
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "update-engine@example.invalid")
    run(root, "git", "config", "user.name", "Update Engine")


def commit_all(root: Path, message: str) -> None:
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-qm", message)


def expect_error(code: str, fn, *args, **kwargs) -> UpdateError:
    try:
        fn(*args, **kwargs)
    except UpdateError as exc:
        assert exc.code == code, (exc.code, exc.message)
        return exc
    raise AssertionError(f"expected UpdateError {code}")


# --- Synthetic minimal release pair ------------------------------------------

def policy(*, harness_owned: list[str], markers: dict[str, list[str]], shared: list[str] | None = None) -> str:
    owned = "\n".join(f'  "{item}",' for item in harness_owned)
    shared_items = ", ".join(f'"{item}"' for item in [".harness/manifest.yaml", *(shared or [])])
    marker_paths = ", ".join(f'"{path}"' for path in markers)
    marker_tables = "\n".join(
        f'[markers."{path}"]\nblocks = [{", ".join(json.dumps(b) for b in blocks)}]\n'
        for path, blocks in markers.items()
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
{owned}
]
shared = [{shared_items}]
marker_merge = [{marker_paths}]

{marker_tables}'''


def manifest(release: str, *, initialized: bool = True) -> str:
    return f'''harness:
  version: "1"
  release: "{release}"
project:
  initialized: {'true' if initialized else 'false'}
repository:
  harnessUpdatePolicy: .harness/harness-update.toml
'''


def graph(latest: str, transitions: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "latest": latest,
            "transitions": [
                {"from": a, "to": b, "kind": "standard", "reloadRequired": False}
                for a, b in transitions
            ],
        },
        indent=2,
    ) + "\n"


PASS_VALIDATOR = 'print("HARNESS VALIDATION: PASS")\n'
DEFAULT_POLICY = policy(harness_owned=[], markers={})


def synthetic_pair(
    tmp: Path,
    *,
    base: dict[str, str],
    target: dict[str, str | None],
    project_overrides: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Source v1.0.0 → v1.1.0 (standard, без reload) и project на v1.0.0."""
    source = tmp / "source"
    source.mkdir()
    git_init(source)
    base_files = {
        ".harness/harness-update.toml": DEFAULT_POLICY,
        ".harness/manifest.yaml": manifest("1.0.0"),
        ".harness/harness-update-graph.json": graph("v1.0.0", []),
        ".harness/tools/validate.py": PASS_VALIDATOR,
        **base,
    }
    for path, text in base_files.items():
        write(source, path, text)
    commit_all(source, "v1.0.0")
    run(source, "git", "tag", "v1.0.0")

    target_files: dict[str, str | None] = {
        ".harness/manifest.yaml": manifest("1.1.0"),
        ".harness/harness-update-graph.json": graph("v1.1.0", [("v1.0.0", "v1.1.0")]),
        **target,
    }
    for path, text in target_files.items():
        if text is None:
            (source / path).unlink()
        else:
            write(source, path, text)
    commit_all(source, "v1.1.0")
    run(source, "git", "tag", "v1.1.0")

    project = tmp / "project"
    project.mkdir()
    for path, text in {**base_files, **(project_overrides or {})}.items():
        write(project, path, text)
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
    git_init(project)
    commit_all(project, "project base")
    return source, project


def snapshot(root: Path) -> dict[str, bytes]:
    """Все файлы проекта вне .git, включая untracked и local state."""
    result: dict[str, bytes] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/") or not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        result[rel] = path.read_bytes()
    return result


# --- Cases --------------------------------------------------------------------

def test_handover_keeps_file(tmp: Path) -> None:
    """#99: path, переданный из harness_owned проекту, сохраняется."""
    source, project = synthetic_pair(
        tmp,
        base={
            ".harness/harness-update.toml": policy(harness_owned=["docs/notes.md"], markers={}),
            "docs/notes.md": "handed over v1\n",
        },
        target={
            ".harness/harness-update.toml": DEFAULT_POLICY,
            "docs/notes.md": "handed over final\n",
        },
    )
    checked = check_update(project, source_url=str(source))
    assert checked["hops"][0]["handedOver"] == ["docs/notes.md"], checked
    result = apply_update(project, source_url=str(source))
    assert result["status"] == "UPDATED", result
    assert (project / "docs/notes.md").read_text() == "handed over final\n"


def agents_text(project_body: str, *, badges: bool) -> str:
    extra = "\n<!-- BADGES:START -->\ntarget badges\n<!-- BADGES:END -->\n" if badges else ""
    return f"# Agents\n\n<!-- PROJECT:START -->{project_body}<!-- PROJECT:END -->\n{extra}"


def test_new_marker_block(tmp: Path) -> None:
    """#100: новый marker block берётся из target, local blocks сохраняются."""
    source, project = synthetic_pair(
        tmp,
        base={
            ".harness/harness-update.toml": policy(harness_owned=[], markers={"AGENTS.md": ["PROJECT"]}),
            "AGENTS.md": agents_text("\ntemplate\n", badges=False),
        },
        target={
            ".harness/harness-update.toml": policy(harness_owned=[], markers={"AGENTS.md": ["PROJECT", "BADGES"]}),
            "AGENTS.md": agents_text("\ntemplate\n", badges=True),
        },
        project_overrides={"AGENTS.md": agents_text("\nLOCAL PROJECT\n", badges=False)},
    )
    result = apply_update(project, source_url=str(source))
    assert result["status"] == "UPDATED", result
    text = (project / "AGENTS.md").read_text()
    assert "LOCAL PROJECT" in text and "target badges" in text, text

    # Block, который был в BASE, но удалён проектом, остаётся fail-closed drift.
    removed_tmp = tmp / "removed"
    removed_tmp.mkdir()
    source, project = synthetic_pair(
        removed_tmp,
        base={
            ".harness/harness-update.toml": policy(harness_owned=[], markers={"AGENTS.md": ["PROJECT"]}),
            "AGENTS.md": agents_text("\ntemplate\n", badges=False),
        },
        target={"AGENTS.md": agents_text("\ntemplate v2\n", badges=False) + "tail\n"},
        project_overrides={"AGENTS.md": "# Agents\n\nproject removed markers\n"},
    )
    expect_error("MARKER_DRIFT", apply_update, project, source_url=str(source))


def test_validator_failure_rolls_back_everything(tmp: Path) -> None:
    """#103: failed target validator откатывает files, lock, report и local state."""
    legacy_state = json.dumps({"schemaVersion": 1, "executions": []}) + "\n"
    source, project = synthetic_pair(
        tmp,
        base={"docs/core.md": "core v1\n", ".harness/harness-update.toml": policy(harness_owned=["docs/**"], markers={})},
        target={
            "docs/core.md": "core v2\n",
            "docs/new.md": "introduced\n",
            # Target code мигрирует local state и затем падает.
            ".harness/tools/validate.py": (
                "from pathlib import Path\n"
                f"Path({STATE!r}).write_text('{{\"schemaVersion\": 2}}')\n"
                "print('synthetic failure')\n"
                "raise SystemExit(1)\n"
            ),
        },
    )
    write(project, STATE, legacy_state)
    before = snapshot(project)
    expect_error("POSTCONDITION_FAILED", apply_update, project, source_url=str(source))
    assert snapshot(project) == before, sorted(set(snapshot(project)) ^ set(before))
    assert not (project / JOURNAL).exists()


def test_target_code_runs_inside_journal(tmp: Path) -> None:
    """#98: target validator исполняется только внутри журналированной транзакции."""
    probe = (
        "import json\n"
        "from pathlib import Path\n"
        f"journal = Path({JOURNAL!r}) / 'journal.json'\n"
        "state = json.loads(journal.read_text())['state'] if journal.is_file() else None\n"
        "Path('journal-state.txt').write_text(str(state))\n"
        + PASS_VALIDATOR
    )
    source, project = synthetic_pair(tmp, base={}, target={".harness/tools/validate.py": probe})
    result = apply_update(project, source_url=str(source))
    assert result["status"] == "UPDATED", result
    assert (project / "journal-state.txt").read_text() == "verifying"
    assert not (project / JOURNAL).exists()


def _spawn_apply(project: Path, source: Path) -> subprocess.Popen[str]:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        "from pathlib import Path\n"
        "from harness_update import apply_update\n"
        f"apply_update(Path({str(project)!r}), source_url={str(source)!r})\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=project,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_interrupted_hop_recovers(tmp: Path) -> None:
    """#103: SIGKILL посреди hop → CHECK blocked → recover/APPLY откатывают."""
    if os.name != "posix":
        return
    hanging_validator = (
        "import time\n"
        "from pathlib import Path\n"
        "Path('validator-started').write_text('1')\n"
        "time.sleep(60)\n"
    )
    source, project = synthetic_pair(
        tmp,
        base={"docs/core.md": "core v1\n", ".harness/harness-update.toml": policy(harness_owned=["docs/**"], markers={})},
        target={
            "docs/core.md": "core v2\n",
            "docs/new.md": "introduced\n",
            ".harness/tools/validate.py": hanging_validator,
        },
    )
    before = snapshot(project)
    proc = _spawn_apply(project, source)
    deadline = time.time() + 60
    while not (project / "validator-started").exists():
        if time.time() > deadline or proc.poll() is not None:
            proc.kill()
            raise AssertionError("interrupted-hop fixture did not reach validator")
        time.sleep(0.05)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    (project / "validator-started").unlink()
    assert (project / JOURNAL / "journal.json").is_file()
    assert (project / "docs/new.md").exists(), "fixture did not interrupt mid-hop"

    expect_error("UPDATE_JOURNAL_PENDING", check_update, project, source_url=str(source))

    # Recovery CLI обязан работать без остальных Harness-модулей: в проекте
    # есть только entrypoint и stdlib-only update_recovery.py.
    for name in ("harness-update.py", "update_recovery.py"):
        shutil.copy2(TOOLS_DIR / name, project / ".harness/tools" / name)
    recovered = run(project, sys.executable, ".harness/tools/harness-update.py", "recover", "--json")
    payload = json.loads(recovered.stdout)
    assert payload["status"] == "RECOVERED" and payload["rolledBack"] is True, payload
    for name in ("harness-update.py", "update_recovery.py"):
        (project / ".harness/tools" / name).unlink()
    assert snapshot(project) == before, sorted(set(snapshot(project)) ^ set(before))


def test_apply_rolls_back_pending_journal(tmp: Path) -> None:
    """#103: APPLY сначала откатывает pending журнал, затем обновляет."""
    from update_recovery import begin_journal

    source, project = synthetic_pair(
        tmp,
        base={"docs/core.md": "core v1\n", ".harness/harness-update.toml": policy(harness_owned=["docs/**"], markers={})},
        target={"docs/core.md": "core v2\n"},
    )
    before = snapshot(project)
    journal = begin_journal(project, operation="hop", source="v1.0.0", target="v1.1.0", paths=["docs/core.md"])
    journal["owner"]["pid"] = 999999  # умерший владелец
    (project / JOURNAL / "journal.json").write_text(json.dumps(journal))
    write(project, "docs/core.md", "half-written\n")
    result = apply_update(project, source_url=str(source))
    assert result["status"] == "UPDATED", result
    assert result["recoveredInterruptedUpdate"]["rolledBack"] is True, result
    assert (project / "docs/core.md").read_text() == "core v2\n"
    assert before["docs/core.md"] == b"core v1\n"


def test_loaded_module_change_requires_reload(tmp: Path) -> None:
    """#102: изменение модуля, загруженного в процесс engine, — reload boundary."""
    source, project = synthetic_pair(
        tmp,
        base={".harness/tools/harness_config.py": "# base config\n"},
        target={".harness/tools/harness_config.py": "# target config\n"},
    )
    checked = check_update(project, source_url=str(source))
    assert checked["reloadBoundary"] == "v1.1.0", checked
    assert checked["hops"][0]["runtimeChanges"] == [".harness/tools/harness_config.py"], checked
    result = apply_update(project, source_url=str(source))
    assert result["status"] == "UPDATER_RELOAD_REQUIRED", result

    # Модуль, не загруженный в процесс, не требует reload.
    other = tmp / "other"
    other.mkdir()
    source, project = synthetic_pair(
        other,
        base={".harness/tools/not_loaded_helper.py": "# v1\n"},
        target={".harness/tools/not_loaded_helper.py": "# v2\n"},
    )
    assert apply_update(project, source_url=str(source))["status"] == "UPDATED"


def test_adopt_blocks_harness_owned_drift(tmp: Path) -> None:
    """#104: adopt не закрепляет lock поверх Harness-owned drift."""
    source, project = synthetic_pair(tmp, base={".harness/tools/tool.py": "# v1\n"}, target={})
    (project / ".harness/harness.lock.json").unlink()
    write(project, ".harness/tools/tool.py", "# locally patched\n")
    expect_error("ADOPTION_BASELINE_DRIFT", adopt_legacy, project, baseline="v1.0.0", source_url=str(source))
    assert not (project / ".harness/harness.lock.json").exists()
    write(project, ".harness/tools/tool.py", "# v1\n")
    assert adopt_legacy(project, baseline="v1.0.0", source_url=str(source))["status"] == "ADOPTED"


def test_graph_ignores_tag_named_like_branch(tmp: Path) -> None:
    """#104: tag `main` не подменяет default-branch update graph."""
    source, project = synthetic_pair(tmp, base={}, target={})
    run(source, "git", "tag", "main", "v1.0.0")
    checked = check_update(project, source_url=str(source))
    assert checked["route"] == ["v1.0.0", "v1.1.0"], checked


def test_unsafe_source_tree_path(tmp: Path) -> None:
    """#104: `..`/`.git` в target tree блокируются до чтения содержимого."""
    source, project = synthetic_pair(
        tmp,
        base={},
        target={".harness/tools/validate.py": PASS_VALIDATOR + "# v1.1.0\n"},
    )
    evil_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=source, input="evil\n",
        text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    inner = subprocess.run(
        ["git", "mktree"], cwd=source, input=f"100644 blob {evil_blob}\tpwned.txt\n",
        text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    tools_tree = run(source, "git", "rev-parse", "v1.1.0:.harness/tools").stdout.strip()
    listing = run(source, "git", "ls-tree", tools_tree).stdout
    evil_tools = subprocess.run(
        ["git", "mktree"], cwd=source, input=listing + f"040000 tree {inner}\t..\n",
        text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    harness_tree = run(source, "git", "rev-parse", "v1.1.0:.harness").stdout.strip()
    harness_listing = run(source, "git", "ls-tree", harness_tree).stdout
    harness_listing = re.sub(r"(040000 tree )[0-9a-f]+(\ttools)", rf"\g<1>{evil_tools}\2", harness_listing)
    evil_harness = subprocess.run(
        ["git", "mktree"], cwd=source, input=harness_listing, text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    root_listing = run(source, "git", "ls-tree", "v1.1.0").stdout
    root_listing = re.sub(r"(040000 tree )[0-9a-f]+(\t\.harness)", rf"\g<1>{evil_harness}\2", root_listing)
    evil_root = subprocess.run(
        ["git", "mktree"], cwd=source, input=root_listing, text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.strip()
    evil_commit = run(source, "git", "commit-tree", evil_root, "-p", "v1.1.0", "-m", "evil").stdout.strip()
    run(source, "git", "tag", "-f", "v1.1.0", evil_commit)
    expect_error("UNSAFE_SOURCE_PATH", check_update, project, source_url=str(source))
    assert not (tmp / "pwned.txt").exists() and not (project.parent / "pwned.txt").exists()


# --- Real template copy: pre-INIT template change (#101) ----------------------

def copy_tracked(target: Path) -> None:
    raw = run(SOURCE_ROOT, "git", "ls-files", "-z").stdout
    for rel in raw.split("\0"):
        if not rel:
            continue
        source = SOURCE_ROOT / rel
        if not source.is_file():
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def set_release(root: Path, release: str, edge: tuple[str, str]) -> None:
    manifest_path = root / ".harness/manifest.yaml"
    manifest_path.write_text(
        re.sub(r'release: "[0-9.]+"', f'release: "{release}"', manifest_path.read_text(encoding="utf-8"), count=1),
        encoding="utf-8",
    )
    lock_path = root / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["release"] = release
    lock["source"]["ref"] = f"v{release}"
    # Fixture-релизы — новые локальные tags; pinned commit исходного checkout
    # (в пользовательском проекте это commit реального release) к ним не относится
    # и дал бы ложный SOURCE_TAG_MOVED (#119).
    lock["source"].pop("commit", None)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    graph_path = root / ".harness/harness-update-graph.json"
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    data["latest"] = f"v{release}"
    data["transitions"].append({"from": edge[0], "to": edge[1], "kind": "standard", "reloadRequired": False})
    graph_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_preinit_template_change(tmp: Path) -> None:
    """#101: pre-INIT project после template change проходит commit validation."""
    import template_contract

    # Release без alignment API (например, v0.8.0) не меняет templates этим путём:
    # сценарий относится только к releases, которые реально меняют их.
    if not hasattr(template_contract, "preinit_template_alignment_state"):
        print("SKIP: test_preinit_template_change (release has no pre-INIT alignment API)")
        return
    # Fixture строится из tracked-дерева текущего checkout. В initialized
    # проекте (self-test после update) это product state, а не pre-INIT шаблон:
    # сценарий там неприменим и покрывается CI template-репозитория (#119).
    manifest_text = (SOURCE_ROOT / ".harness/manifest.yaml").read_text(encoding="utf-8")
    if re.search(r"(?m)^  initialized:\s*true\s*$", manifest_text):
        print("SKIP: test_preinit_template_change (checkout is an initialized project)")
        return
    data = json.loads((SOURCE_ROOT / ".harness/harness-update-graph.json").read_text(encoding="utf-8"))
    current = data["latest"]
    major, minor, _patch = (int(part) for part in current.removeprefix("v").split("."))
    first = f"{major}.{minor + 1}.0"
    second = f"{major}.{minor + 2}.0"

    source = tmp / "source"
    source.mkdir()
    copy_tracked(source)
    git_init(source)
    set_release(source, first, (current, f"v{first}"))
    commit_all(source, f"v{first}")
    run(source, "git", "tag", f"v{first}")

    project = tmp / "project"
    shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git"))
    git_init(project)
    commit_all(project, "project baseline")

    contract_path = source / ".harness/tools/template_contract.py"
    contract = contract_path.read_text(encoding="utf-8")
    start = contract.index('ADR_TEMPLATE = """')
    end = contract.index('"""', start + len('ADR_TEMPLATE = """'))
    contract_path.write_text(
        contract[:end].rstrip("\n") + "\n\n## Follow-up\n\n- ...\n" + contract[end:],
        encoding="utf-8",
    )
    adr_template = source / "docs/adr/TEMPLATE.md"
    adr_template.write_text(
        adr_template.read_text(encoding="utf-8").rstrip("\n") + "\n\n## Follow-up\n\n- ...\n",
        encoding="utf-8",
    )
    set_release(source, second, (f"v{first}", f"v{second}"))
    commit_all(source, f"v{second}")
    run(source, "git", "tag", f"v{second}")

    # Каждый шаг — новый процесс установленного в проекте engine, как у агента.
    def apply_cli() -> dict:
        proc = run(
            project, sys.executable, ".harness/tools/harness-update.py", "apply",
            "--json", "--source-url", str(source), check=False,
        )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(proc.stdout + proc.stderr) from exc

    result = apply_cli()
    for _ in range(3):
        if result.get("status") != "UPDATER_RELOAD_REQUIRED":
            break
        result = apply_cli()
    assert result.get("status") in {"UPDATED", "NO_UPDATE"}, result
    gate = run(project, sys.executable, ".harness/tools/validate.py", "--mode", "commit", check=False)
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert "## Follow-up" in (project / "docs/adr/TEMPLATE.md").read_text(encoding="utf-8")


CASES = [
    test_handover_keeps_file,
    test_new_marker_block,
    test_validator_failure_rolls_back_everything,
    test_target_code_runs_inside_journal,
    test_interrupted_hop_recovers,
    test_apply_rolls_back_pending_journal,
    test_loaded_module_change_requires_reload,
    test_adopt_blocks_harness_owned_drift,
    test_graph_ignores_tag_named_like_branch,
    test_unsafe_source_tree_path,
    test_preinit_template_change,
]


def main() -> int:
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="harness-update-engine-") as tmp:
            case(Path(tmp))
        print(f"PASS: {case.__name__}")
    print(f"UPDATE ENGINE SELF-TEST: PASS ({len(CASES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
