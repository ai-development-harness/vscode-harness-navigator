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

from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

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


def _failing_state_writer(payload: str | None) -> str:
    """Target validator, который пишет local state (или нет) и падает."""
    write_state = (
        f"Path({STATE!r}).parent.mkdir(parents=True, exist_ok=True)\n"
        f"Path({STATE!r}).write_text({payload!r})\n"
        if payload is not None else ""
    )
    return "from pathlib import Path\n" + write_state + "raise SystemExit(1)\n"


def test_local_state_rollback_is_byte_exact(tmp: Path) -> None:
    """#132: failed hop возвращает local state байт-в-байт и удаляет созданный."""
    # Mutation без смены schemaVersion.
    same = tmp / "same"
    same.mkdir()
    source, project = synthetic_pair(
        same, base={}, target={".harness/tools/validate.py": _failing_state_writer('{"schemaVersion": 1, "x": 2}')},
    )
    original = '{"schemaVersion": 1, "x": 1}\n'
    write(project, STATE, original)
    if os.name == "posix":
        os.chmod(project / STATE, 0o600)
        original_mode = stat.S_IMODE((project / STATE).stat().st_mode)
    else:
        original_mode = None
    expect_error("POSTCONDITION_FAILED", apply_update, project, source_url=str(source))
    assert (project / STATE).read_text() == original
    if original_mode is not None:
        assert stat.S_IMODE((project / STATE).stat().st_mode) == original_mode, (
            "rollback changed execution-status permissions"
        )

    # Файла не было — созданный hop-ом файл удаляется.
    created = tmp / "created"
    created.mkdir()
    source, project = synthetic_pair(
        created, base={}, target={".harness/tools/validate.py": _failing_state_writer('{"schemaVersion": 2}')},
    )
    assert not (project / STATE).exists()
    expect_error("POSTCONDITION_FAILED", apply_update, project, source_url=str(source))
    assert not (project / STATE).exists(), "state created by failed hop survived rollback"

    # Успешный hop сохраняет намеренную миграцию.
    ok = tmp / "ok"
    ok.mkdir()
    migrating = (
        "from pathlib import Path\n"
        f"Path({STATE!r}).write_text('{{\"schemaVersion\": 2}}')\n" + PASS_VALIDATOR
    )
    source, project = synthetic_pair(ok, base={}, target={".harness/tools/validate.py": migrating})
    write(project, STATE, original)
    assert apply_update(project, source_url=str(source))["status"] == "UPDATED"
    assert json.loads((project / STATE).read_text())["schemaVersion"] == 2


def test_update_blocks_concurrent_execution_state(tmp: Path) -> None:
    """#132: pending update journal блокирует canonical execution-state writers."""
    import execution_status
    import update_recovery

    source, project = synthetic_pair(tmp, base={}, target={})
    write(project, STATE, '{"schemaVersion": 2, "executions": [], "stepRecovery": {}, "recentTerminals": [], "nextOrdinal": 1}\n')
    journal = update_recovery.begin_journal(
        project,
        operation="concurrency-test",
        source="v1.0.0",
        target="v1.1.0",
        paths=[],
    )
    try:
        try:
            with execution_status.execution_state_lock(project):
                raise AssertionError("foreign execution state lock unexpectedly acquired")
        except ValueError as exc:
            assert "UPDATE_IN_PROGRESS" in str(exc), exc

        # Target validator с exact transactionId может использовать execution
        # layer только пока hop active. Recovery durable-отзывает capability
        # state=recovering до ожидания lock, чтобы surviving child не смог
        # reacquire lock после restore.
        old_token = os.environ.get(update_recovery.UPDATE_TRANSACTION_ENV)
        os.environ[update_recovery.UPDATE_TRANSACTION_ENV] = journal["transactionId"]
        try:
            with execution_status.execution_state_lock(project):
                pass
            update_recovery.update_journal(project, journal, state="recovering")
            try:
                with execution_status.execution_state_lock(project):
                    raise AssertionError("recovering transaction unexpectedly retained validator access")
            except ValueError as exc:
                assert "UPDATE_IN_PROGRESS" in str(exc), exc
        finally:
            if old_token is None:
                os.environ.pop(update_recovery.UPDATE_TRANSACTION_ENV, None)
            else:
                os.environ[update_recovery.UPDATE_TRANSACTION_ENV] = old_token
    finally:
        update_recovery.rollback_journal(project, journal)


def _update_reports(project: Path) -> list[str]:
    directory = project / "reports"
    return sorted(p.name for p in directory.glob("UPDATE-*.md")) if directory.is_dir() else []


def test_update_report_only_after_validator_pass(tmp: Path) -> None:
    """#130: report не существует без PASS и не переживает rollback/recovery."""
    import harness_update
    import update_recovery

    failing = tmp / "failing"
    failing.mkdir()
    source, project = synthetic_pair(
        failing, base={}, target={".harness/tools/validate.py": "raise SystemExit(1)\n"},
    )
    expect_error("POSTCONDITION_FAILED", apply_update, project, source_url=str(source))
    assert _update_reports(project) == [], "report written before validator PASS"

    # Сбой записи journal при регистрации report (OSError/crash): report не
    # должен существовать незарегистрированным — иначе rollback его не удалит.
    reserve_fail = tmp / "reserve"
    reserve_fail.mkdir()
    source, project = synthetic_pair(reserve_fail, base={}, target={})
    original_reserve = update_recovery.ReportLedger.reserve

    def failing_reserve(self, path, staging, digest):
        raise RuntimeError("journal write failed while registering report")

    update_recovery.ReportLedger.reserve = failing_reserve
    try:
        try:
            apply_update(project, source_url=str(source))
        except RuntimeError:
            pass
        else:
            raise AssertionError("fixture did not fail")
    finally:
        update_recovery.ReportLedger.reserve = original_reserve
    assert _update_reports(project) == [], "orphan report after failed registration"
    assert not (project / JOURNAL).exists()

    # Crash после создания report, до commit point: recovery удаляет report.
    crash = tmp / "crash"
    crash.mkdir()
    source, project = synthetic_pair(crash, base={}, target={})
    original_finish = harness_update.finish_journal

    def crashing_finish(root):
        raise KeyboardInterrupt("simulated crash before commit point")

    harness_update.finish_journal = crashing_finish
    try:
        try:
            apply_update(project, source_url=str(source))
        except KeyboardInterrupt:
            pass
    finally:
        harness_update.finish_journal = original_finish
    assert len(_update_reports(project)) == 1, "fixture did not create report"
    assert update_recovery.recover_pending(project, force=True)["rolledBack"] is True
    assert _update_reports(project) == [], "report survived recovery"

    # Успешный hop — ровно один report.
    good = tmp / "good"
    good.mkdir()
    source, project = synthetic_pair(good, base={}, target={})
    assert apply_update(project, source_url=str(source))["status"] == "UPDATED"
    assert len(_update_reports(project)) == 1


def _report_artifacts(project: Path) -> list[str]:
    directory = project / "reports"
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def _crash_hop(project: Path, source: Path, patches: dict[str, Any]) -> None:
    """apply_update с подменёнными методами ReportLedger и crash до commit point."""
    import harness_update
    import update_recovery

    originals = {name: getattr(update_recovery.ReportLedger, name) for name in patches}
    original_finish = harness_update.finish_journal

    def crashing_finish(root):
        raise KeyboardInterrupt("simulated crash before commit point")

    for name, factory in patches.items():
        setattr(update_recovery.ReportLedger, name, factory(originals[name]))
    harness_update.finish_journal = crashing_finish
    try:
        try:
            apply_update(project, source_url=str(source))
        except KeyboardInterrupt:
            pass
    finally:
        for name, original in originals.items():
            setattr(update_recovery.ReportLedger, name, original)
        harness_update.finish_journal = original_finish
    # Crash внутри транзакции откатывает сам apply; crash на commit point
    # оставляет journal, который откатывает recovery.
    if (project / JOURNAL).exists():
        assert update_recovery.recover_pending(project, force=True)["rolledBack"] is True
    assert not (project / JOURNAL).exists()


def test_report_rollback_never_removes_foreign_report(tmp: Path) -> None:
    """#130 review: rollback удаляет только report, владение которым доказано."""
    foreign_text = "foreign report\n"

    def foreign_after_reserve(original):
        state = {"done": False}

        def reserve(self, path, staging, digest):
            original(self, path, staging, digest)
            if not state["done"]:
                # Другой writer выигрывает O_EXCL/link на то же имя после reserve.
                state["done"] = True
                path.write_text(foreign_text)
        return reserve

    # Гонка за имя: первый writer уходит на следующий second, rollback
    # удаляет только свой report и не трогает чужой.
    race = tmp / "race"
    race.mkdir()
    source, project = synthetic_pair(race, base={}, target={})
    _crash_hop(project, source, {"reserve": foreign_after_reserve})
    artifacts = _report_artifacts(project)
    assert len(artifacts) == 1, artifacts
    assert (project / "reports" / artifacts[0]).read_text() == foreign_text

    # Crash сразу после reserve, пока имя занято чужим файлом.
    def crash_after_reserve(original):
        def reserve(self, path, staging, digest):
            original(self, path, staging, digest)
            path.write_text(foreign_text)
            raise KeyboardInterrupt("crash after reserve")
        return reserve

    early = tmp / "early"
    early.mkdir()
    source, project = synthetic_pair(early, base={}, target={})
    _crash_hop(project, source, {"reserve": crash_after_reserve})
    artifacts = _report_artifacts(project)
    assert len(artifacts) == 1 and (project / "reports" / artifacts[0]).read_text() == foreign_text, artifacts

    # Crash после публикации, до confirm: staging доказывает владение.
    def crash_before_confirm(original):
        def confirm(self, path, stat):
            raise KeyboardInterrupt("crash before confirm")
        return confirm

    linked = tmp / "linked"
    linked.mkdir()
    source, project = synthetic_pair(linked, base={}, target={})
    _crash_hop(project, source, {"confirm": crash_before_confirm})
    assert _report_artifacts(project) == [], "own report or staging survived rollback"

    # Report подменён после confirm (тот же путь, другой файл) — не наш.
    def replace_after_confirm(original):
        def confirm(self, path, stat):
            original(self, path, stat)
            path.unlink()
            path.write_text(foreign_text)
        return confirm

    replaced = tmp / "replaced"
    replaced.mkdir()
    source, project = synthetic_pair(replaced, base={}, target={})
    _crash_hop(project, source, {"confirm": replace_after_confirm})
    artifacts = _report_artifacts(project)
    assert len(artifacts) == 1 and (project / "reports" / artifacts[0]).read_text() == foreign_text, artifacts


def _interrupting_rmtree(original, *, match: str):
    """rmtree, который удаляет один файл внутри каталога и «падает» (crash в cleanup)."""
    state = {"fired": False}

    def rmtree(path, *args, **kwargs):
        if not state["fired"] and match in Path(path).name:
            state["fired"] = True
            victims = sorted(p for p in Path(path).rglob("*") if p.is_file())
            if victims:
                victims[0].unlink()
            raise KeyboardInterrupt("simulated crash inside journal cleanup")
        return original(path, *args, **kwargs)

    return rmtree


def test_journal_commit_point_is_crash_atomic(tmp: Path) -> None:
    """Final review P1: crash внутри cleanup журнала не превращается в pending rollback."""
    import update_recovery

    original_rmtree = update_recovery.shutil.rmtree

    # (1) Crash внутри cleanup после commit point: hop остаётся применённым,
    # pending journal нет, tombstone удаляется следующей транзакцией.
    committed = tmp / "committed"
    committed.mkdir()
    source, project = synthetic_pair(committed, base={}, target={})
    update_recovery.shutil.rmtree = _interrupting_rmtree(original_rmtree, match=update_recovery.TOMBSTONE_PREFIX)
    try:
        try:
            apply_update(project, source_url=str(source))
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("fixture did not interrupt cleanup")
    finally:
        update_recovery.shutil.rmtree = original_rmtree
    assert update_recovery.load_journal(project) is None, "committed hop looks pending after cleanup crash"
    assert update_recovery.recover_pending(project) is None
    assert apply_update(project, source_url=str(source))["status"] == "NO_UPDATE"
    assert not list((project / JOURNAL).parent.glob(update_recovery.TOMBSTONE_PREFIX + "*"))

    # (2) Crash внутри cleanup после rollback: state уже восстановлен, повторного
    # rollback по неполному journal нет.
    rolled = tmp / "rolled"
    rolled.mkdir()
    source, project = synthetic_pair(rolled, base={}, target={".harness/tools/validate.py": "raise SystemExit(1)\n"})
    before = snapshot(project)
    update_recovery.shutil.rmtree = _interrupting_rmtree(original_rmtree, match=update_recovery.TOMBSTONE_PREFIX)
    try:
        try:
            apply_update(project, source_url=str(source))
        except (KeyboardInterrupt, UpdateError):
            pass
    finally:
        update_recovery.shutil.rmtree = original_rmtree
    assert update_recovery.load_journal(project) is None
    update_recovery.discard_retired_journals(project)
    assert snapshot(project) == before, sorted(set(snapshot(project)) ^ set(before))

    # (3) Неполный journal (backup blob пропал): rollback fail-closed и ничего
    # не восстанавливает частично.
    partial = tmp / "partial"
    partial.mkdir()
    source, project = synthetic_pair(partial, base={}, target={})
    import harness_update
    original_finish = harness_update.finish_journal

    def crashing_finish(root):
        raise KeyboardInterrupt("simulated crash before commit point")

    harness_update.finish_journal = crashing_finish
    try:
        try:
            apply_update(project, source_url=str(source))
        except KeyboardInterrupt:
            pass
    finally:
        harness_update.finish_journal = original_finish
    blobs = sorted((project / JOURNAL / "blobs").iterdir())
    assert len(blobs) >= 2, blobs
    blobs[-1].unlink()
    applied = snapshot(project)
    try:
        update_recovery.recover_pending(project, force=True)
    except update_recovery.JournalError as exc:
        assert exc.code == "UPDATE_JOURNAL_INVALID", exc.code
    else:
        raise AssertionError("incomplete journal was rolled back")
    assert snapshot(project) == applied, "partial rollback from incomplete journal"


def test_rollback_removes_lock_created_inside_hop(tmp: Path) -> None:
    """Final review P2: validator-created lock ждётся и не переживает rollback."""
    import update_recovery

    lock = ".harness/local/execution/execution-status.lock"
    validator = (
        "from pathlib import Path\n"
        f"Path({lock!r}).parent.mkdir(parents=True, exist_ok=True)\n"
        f"Path({lock!r}).touch()\n"
        "raise SystemExit(1)\n"
    )
    source, project = synthetic_pair(tmp, base={}, target={".harness/tools/validate.py": validator})
    assert not (project / lock).exists()

    original_lock = update_recovery.execution_state_lock
    entered = {"value": False}

    @contextmanager
    def tracking_lock(root):
        entered["value"] = True
        with original_lock(root):
            yield

    update_recovery.execution_state_lock = tracking_lock
    try:
        expect_error("POSTCONDITION_FAILED", apply_update, project, source_url=str(source))
    finally:
        update_recovery.execution_state_lock = original_lock

    assert entered["value"], "rollback did not serialize against validator-created execution lock"
    assert not (project / lock).exists(), "execution lock created inside failed hop survived rollback"


STATE_DEPENDENT_VALIDATOR = (
    "from pathlib import Path\n"
    "import sys\n"
    "sys.exit(0 if Path('state-ok.txt').exists() else 1)\n"
)


def test_adopt_requires_postcondition(tmp: Path) -> None:
    """#133: ADOPTED только после PASS postcondition; при сбое lock не остаётся."""
    import harness_update

    source, project = synthetic_pair(
        tmp, base={".harness/tools/validate.py": STATE_DEPENDENT_VALIDATOR}, target={},
    )
    lock = project / ".harness/harness.lock.json"
    lock.unlink()
    expect_error("POSTCONDITION_FAILED", adopt_legacy, project, baseline="v1.0.0", source_url=str(source))
    assert not lock.exists(), "lock survived failed adoption postcondition"
    assert not (project / JOURNAL).exists()

    original = harness_update._run_validator

    def interrupted(root, *, phase):
        raise KeyboardInterrupt("interrupted adoption postcondition")

    harness_update._run_validator = interrupted
    try:
        try:
            adopt_legacy(project, baseline="v1.0.0", source_url=str(source))
        except KeyboardInterrupt:
            pass
    finally:
        harness_update._run_validator = original
    assert not lock.exists(), "lock survived interrupted adoption"

    write(project, "state-ok.txt", "1\n")
    assert adopt_legacy(project, baseline="v1.0.0", source_url=str(source))["status"] == "ADOPTED"
    assert lock.is_file()
    # Повторный CHECK после ADOPTED не находит adoption-specific inconsistency.
    checked = check_update(project, source_url=str(source))
    assert checked["status"] == "PASS", checked


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


def test_graph_connectivity(tmp: Path) -> None:
    """#105: каждый release графа обязан иметь маршрут до latest."""
    from harness_update import _validate_graph

    def edge(a: str, b: str) -> dict:
        return {"from": a, "to": b, "kind": "standard", "reloadRequired": False}

    pattern = r"v\d+\.\d+\.\d+"
    good = {"schemaVersion": 1, "latest": "v1.2.0", "transitions": [
        edge("v1.0.0", "v1.1.0"), edge("v1.0.5", "v1.1.0"), edge("v1.1.0", "v1.2.0"),
    ]}
    latest, outgoing = _validate_graph(good, pattern)
    assert latest == "v1.2.0" and len(outgoing) == 3, outgoing
    dead_end = {"schemaVersion": 1, "latest": "v1.2.0", "transitions": [
        edge("v1.0.0", "v1.1.0"), edge("v1.0.5", "v1.0.9"), edge("v1.1.0", "v1.2.0"),
    ]}
    error = expect_error("INVALID_UPDATE_GRAPH", _validate_graph, dead_end, pattern)
    assert "v1.0.5" in str(error), error
    past_latest = {"schemaVersion": 1, "latest": "v1.1.0", "transitions": [
        edge("v1.0.0", "v1.1.0"), edge("v1.1.0", "v1.2.0"),
    ]}
    expect_error("INVALID_UPDATE_GRAPH", _validate_graph, past_latest, pattern)
    # Реальный graph репозитория связен.
    real = json.loads((SOURCE_ROOT / ".harness/harness-update-graph.json").read_text(encoding="utf-8"))
    _validate_graph(real, pattern)


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
    test_graph_connectivity,
    test_local_state_rollback_is_byte_exact,
    test_update_report_only_after_validator_pass,
    test_report_rollback_never_removes_foreign_report,
    test_adopt_requires_postcondition,
    test_journal_commit_point_is_crash_atomic,
    test_rollback_removes_lock_created_inside_hop,
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
