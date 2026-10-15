#!/usr/bin/env python3
"""#299: read-only восстановление кандидатов в двух независимых Git-клонах.

Тест использует локальный bare remote: push + clone, без доступа к сети.
Локальное состояние первого компьютера намеренно не переносится.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from repository_recovery import repository_recovery_preview
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> str:
    result = subprocess.run(
        args,
        cwd=root,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, (
        f"{' '.join(args)} failed: {result.stderr}\n{result.stdout}"
    )
    return result.stdout.strip()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def step(step_id: str, status: str = "in_progress") -> str:
    return f"""---
schema: 1
id: {step_id}
status: {status}
type: implementation
priority: medium
phase: P1
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Portable recovery fixture

## Goal

- Prove repository facts without local execution status.

## Context

- Published STEP.

## Scope

- Read-only recovery.

## Mutation policy

### Allowed

- none

### Conditional

- none

### Forbidden

- all

## Out of scope

- Restarting execution.

## Acceptance criteria

- No fabricated successful execution.

## Verification

- manual: inspect implementation

## Deliverables

- Diagnostic output.

## Implementation plan

—

## Evidence

—

## Blocker / Failure reason

—
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-portable-preview-") as tmp:
        root = Path(tmp)
        desktop = root / "desktop"
        laptop = root / "laptop"
        remote = root / "origin.git"
        desktop.mkdir()

        # Используем текущую Harness-конфигурацию: без самодельных путей
        # валидаторов/manifest в тесте и без зависимости от старого релиза.
        copy_effective_harness_checkout(SOURCE_ROOT, desktop)
        isolate_project_artifacts(desktop)

        manifest = desktop / ".harness/manifest.yaml"
        original = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in original
        write(manifest, original.replace("initialized: false", "initialized: true", 1))
        write(desktop / "planning/tasks/STEP-001.md", step("STEP-001"))
        write(desktop / "planning/tasks/STEP-002.md", step("STEP-002", "planned"))
        write(desktop / "planning/tasks/STEP-003.md", step("STEP-003", "completed"))

        # До Git-init никакого "автоматического RESUME" не существует.
        no_git = repository_recovery_preview(desktop)
        assert no_git["status"] == "BLOCKED", no_git
        assert no_git["safeToResume"] is False, no_git

        run(root, "git", "init", "--bare", "-q", "-b", "main", str(remote))
        run(desktop, "git", "init", "-q", "-b", "main")
        run(desktop, "git", "config", "user.email", "portable@example.invalid")
        run(desktop, "git", "config", "user.name", "Portable Fixture")
        run(desktop, "git", "remote", "add", "origin", str(remote))
        run(desktop, "git", "add", ".")
        run(desktop, "git", "commit", "-qm", "fixture")
        run(desktop, "git", "push", "-q", "-u", "origin", "main")

        # Локальный marker и испорченный status на desktop не должны
        # попадать в Git и не должны влиять на read-only диагностику.
        write(
            desktop / ".harness/.execution-checkpoint-known",
            "checkpoint-ever-written-v1\n",
        )
        write(
            desktop / ".harness/local/execution/execution-status.json",
            "{broken local status",
        )
        run(root, "git", "clone", "-q", "--branch", "main", str(remote), str(laptop))
        assert not (laptop / ".harness/.execution-checkpoint-known").exists()
        assert not (
            laptop / ".harness/local/execution/execution-status.json"
        ).exists()

        home = repository_recovery_preview(desktop)
        away = repository_recovery_preview(laptop)
        assert home == away, (home, away)
        assert away["status"] == "PASS", away
        assert away["candidateCount"] == 1, away
        assert away["candidates"][0]["stepId"] == "STEP-001", away
        assert away["candidates"][0]["reasonCode"] == "PLAN_NOT_READY", away
        assert away["safeToResume"] is False and away["nextCommand"] is None, away
        assert away["externalSideEffectsExecuted"] is False, away

        # Публичный CLI обязан сохранить те же read-only факты.
        raw = run(
            laptop, sys.executable, ".harness/tools/repository-recovery.py", "--json",
        )
        assert json.loads(raw) == away, raw

        explicit = repository_recovery_preview(laptop, "STEP-001")
        assert explicit["candidateCount"] == 1, explicit
        no_candidate = repository_recovery_preview(laptop, "STEP-002")
        assert no_candidate["candidateCount"] == 0, no_candidate
        bad_id = repository_recovery_preview(laptop, "STEP-1")
        assert bad_id["reasonCode"] == "INVALID_STEP_ID", bad_id
        missing = repository_recovery_preview(laptop, "STEP-999")
        assert missing["reasonCode"] == "STEP_DOCUMENT_UNAVAILABLE", missing

        # Даже при чистом опубликованном STEP наличие локального изменения
        # запрещает называть workspace подходящим для transfer.
        write(laptop / "unpublished.txt", "not committed\n")
        dirty = repository_recovery_preview(laptop)
        assert dirty["reasonCode"] == "WORKTREE_DIRTY", dirty
        assert dirty["safeToResume"] is False, dirty
        (laptop / "unpublished.txt").unlink()

        # .git/info/exclude скрывает локальный STEP от git status.
        # Его нельзя показывать как переносимый результат Git-публикации.
        exclude = laptop / ".git/info/exclude"
        original_exclude = exclude.read_text(encoding="utf-8")
        write(exclude, original_exclude + "\nplanning/tasks/STEP-004.md\n")
        write(laptop / "planning/tasks/STEP-004.md", step("STEP-004"))
        ignored = repository_recovery_preview(laptop)
        assert ignored["reasonCode"] == "STEP_NOT_TRACKED", ignored
        (laptop / "planning/tasks/STEP-004.md").unlink()
        write(exclude, original_exclude)

        # Изменение layout через manifest: старый путь не может оставаться
        # скрытым вторым источником STEP topology.
        custom_manifest = (laptop / ".harness/manifest.yaml").read_text(encoding="utf-8")
        assert "taskDirectory: planning/tasks" in custom_manifest
        write(
            laptop / ".harness/manifest.yaml",
            custom_manifest.replace(
                "taskDirectory: planning/tasks", "taskDirectory: custom/steps", 1
            ),
        )
        write(laptop / "custom/steps/STEP-004.md", step("STEP-004"))
        run(laptop, "git", "config", "user.email", "portable@example.invalid")
        run(laptop, "git", "config", "user.name", "Portable Fixture")
        run(laptop, "git", "add", ".harness/manifest.yaml", "custom/steps/STEP-004.md")
        run(laptop, "git", "commit", "-qm", "custom task layout")
        custom = repository_recovery_preview(laptop)
        assert [item["stepId"] for item in custom["candidates"]] == ["STEP-004"], custom
        assert custom["status"] == "PASS", custom

        # Два published in_progress STEP не дают права выбрать один
        # молча, даже при полностью чистом рабочем дереве.
        write(laptop / "custom/steps/STEP-006.md", step("STEP-006"))
        run(laptop, "git", "add", "custom/steps/STEP-006.md")
        run(laptop, "git", "commit", "-qm", "second in-progress candidate")
        multiple = repository_recovery_preview(laptop)
        assert multiple["status"] == "PASS", multiple
        assert multiple["reasonCode"] == "MULTIPLE_RECOVERY_CANDIDATES", multiple
        assert [item["stepId"] for item in multiple["candidates"]] == [
            "STEP-004", "STEP-006",
        ], multiple
        assert multiple["safeToResume"] is False, multiple

        # Современный Ready plan с неизвестными fingerprints не выглядит
        # доказанным; ошибка не становится правом auto-resume.
        target = laptop / "custom/steps/STEP-004.md"
        write(
            target,
            target.read_text(encoding="utf-8").replace(
                "status: not_planned", "status: ready", 1
            ),
        )
        stale = repository_recovery_preview(laptop)
        assert stale["candidates"][0]["reasonCode"] == "PLAN_BASIS_STALE", stale
        assert stale["safeToResume"] is False, stale

        # Missing REQ на неготовом STEP тоже является blocker: нельзя
        # объявить документ переносимым без разрешения canonical links.
        valid = target.read_text(encoding="utf-8")
        write(
            target,
            valid.replace(
                "requirements: []", "requirements:\n  - REQ-999", 1
            ),
        )
        missing_ref = repository_recovery_preview(laptop)
        assert missing_ref["reasonCode"] == "STEP_REFERENCES_UNPROVEN", missing_ref
        write(target, valid)

        # Schema-invalid, но синтаксически читаемый STEP тоже не может
        # исчезнуть как "не in_progress" или стать RESUME-кандидатом.
        valid = target.read_text(encoding="utf-8")
        write(target, valid.replace("schema: 1", "schema: 2", 1))
        bad_schema = repository_recovery_preview(laptop)
        assert bad_schema["reasonCode"] == "STEP_CONTRACT_INVALID", bad_schema
        write(target, valid)

        # Повреждённый STEP должен быть именно tracked в Git: иначе
        # первым корректным отказом станет STEP_NOT_TRACKED.
        write(laptop / "custom/steps/STEP-005.md", "broken document\n")
        run(laptop, "git", "add", "custom/steps/STEP-005.md")
        run(laptop, "git", "commit", "-qm", "malformed tracked step fixture")
        invalid = repository_recovery_preview(laptop)
        assert invalid["status"] == "BLOCKED", invalid
        assert invalid["reasonCode"] == "REPOSITORY_RECOVERY_UNPROVEN", invalid

    print("REPOSITORY RECOVERY SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
