#!/usr/bin/env python3
"""Synthetic regression suite deterministic STEP Verification."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from command_dispatch import complete_dispatch, start_dispatch
import hashlib
import os
import time
from unittest.mock import patch

from document_contract import atomic_write_text
from verification import (
    CAPTURE_TAIL_BYTES,
    EVIDENCE_START,
    _run_command,
    run_step_verification,
    verification_command_evidence,
    verification_freshness,
    write_verification_evidence,
    VerificationInputsStale,
)


from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> str:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout.strip()


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)

def command_line(command: str) -> str:
    tick = chr(96)
    return f"- command: {tick}{command}{tick}"


def task(verification: str) -> str:
    return f"""---
schema: 1
id: STEP-001
status: in_progress
type: implementation
priority: medium
phase: test
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

# STEP-001 — Verification fixture

## Goal

Проверить deterministic verification.

## Context

Synthetic fixture.

## Scope

- verification runner.

## Mutation policy

### Allowed

- planning/tasks/STEP-001.md.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product changes.

## Acceptance criteria

- Verification PASS.

## Verification

{verification}

## Deliverables

- Evidence.

## Implementation plan

Synthetic.

## Evidence

—

## Blocker / Failure reason

—
"""


def prepare(root: Path) -> None:
    copy_tracked(root)
    isolate_project_artifacts(root)
    path = root / "planning/tasks/STEP-001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        task(
            command_line('python3 -c "print(123)"')
            + "\n- manual: Подтвердить semantic condition"
        ),
        encoding="utf-8",
        newline="\n",
    )
    run(root, "git", "init", "-q", "-b", "main")
    run(root, "git", "config", "user.email", "verification@example.invalid")
    run(root, "git", "config", "user.name", "Verification Test")
    # Не позволяем Git запускать background housekeeping внутри временного fixture:
    # процесс maintenance/gc может пережить git commit и конфликтовать с cleanup TemporaryDirectory.
    run(root, "git", "config", "gc.auto", "0")
    run(root, "git", "config", "maintenance.auto", "false")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "fixture")


def reset(root: Path) -> None:
    run(root, "git", "reset", "--hard", "HEAD")
    run(root, "git", "clean", "-fd")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-verification-") as tmp:
        root = Path(tmp)
        prepare(root)
        step = root / "planning/tasks/STEP-001.md"

        # Automated command runs without shell; unresolved manual check prevents
        # false PASS and writes factual generated Evidence.
        pending = run_step_verification(root, "STEP-001")
        assert pending["status"] == "MANUAL_REQUIRED", pending
        assert pending["manualPending"] == ["Подтвердить semantic condition"], pending
        evidence = step.read_text(encoding="utf-8")
        assert EVIDENCE_START in evidence
        assert "stdout sha256:" in evidence

        # Exact manual confirmation completes the same contract.
        passed = run_step_verification(
            root,
            "STEP-001",
            manual_results=[
                {
                    "check": "Подтвердить semantic condition",
                    "status": "PASS",
                    "observed": "Condition observed.",
                }
            ],
        )
        assert passed["status"] == "PASS", passed
        assert passed["automatedResumed"] is True, passed
        assert passed["commands"][0]["exitCode"] == 0, passed
        assert passed["manual"][0]["status"] == "PASS", passed
        evidence = step.read_text(encoding="utf-8")
        assert "Condition observed." in evidence
        assert "Status: PASS" in evidence
        fresh = verification_freshness(root, "STEP-001")
        assert fresh["status"] == "PASS" and fresh["fresh"] is True, fresh

        # Редактируемый STEP не является доверенным источником результатов.
        # Замена PASS/FAIL или manual observations должна инвалидировать
        # независимый proof, даже если код и acceptance остались неизменными.
        trusted_text = step.read_text(encoding="utf-8")
        for tampered in (
            trusted_text.replace("- Status: PASS", "- Status: FAIL", 1),
            trusted_text.replace("Condition observed.", "Imagined observation.", 1),
        ):
            step.write_text(tampered, encoding="utf-8", newline="\n")
            altered = verification_freshness(root, "STEP-001")
            assert altered["fresh"] is False, altered
            assert altered["reasonCode"] == "VERIFICATION_PROOF_MISMATCH", altered
        step.write_text(trusted_text, encoding="utf-8", newline="\n")

        # В другом checkout локальный proof не копируется: старый PASS должен
        # быть UNKNOWN, а обычная Verification автоматически восстановит proof.
        producer_proof = root / ".harness/local/verification-proofs/STEP-001.json"
        assert producer_proof.is_file()
        producer_proof.unlink()
        unproven = verification_freshness(root, "STEP-001")
        assert unproven["reasonCode"] == "VERIFICATION_PROOF_MISSING", unproven
        renewed = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Condition observed.",
            }],
        )
        assert renewed["status"] == "PASS" and producer_proof.is_file(), renewed
        assert verification_freshness(root, "STEP-001")["fresh"] is True

        exact = verification_command_evidence(
            root,
            "STEP-001",
            'python3 -c "print(123)"',
        )
        assert exact["status"] == "PASS" and exact["fresh"] is True, exact
        missing_command = verification_command_evidence(
            root,
            "STEP-001",
            "python3 missing.py",
        )
        assert missing_command["fresh"] is False, missing_command
        assert missing_command["reasonCode"] == "VERIFICATION_COMMAND_NOT_CONFIGURED"

        # Product/worktree mutation outside STEP makes previously PASS evidence stale.
        probe = root / "src/freshness-probe.txt"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("changed after verification\n", encoding="utf-8")
        stale = verification_freshness(root, "STEP-001")
        assert stale["fresh"] is False, stale
        assert stale["reasonCode"] == "VERIFICATION_SUBJECT_STALE", stale
        probe.unlink()

        # Verification contract mutation is also stale even though STEP Evidence
        # itself is excluded from subject revision.
        original_text = step.read_text(encoding="utf-8")
        step.write_text(
            original_text.replace(
                'python3 -c "print(123)"',
                'python3 -c "print(456)"',
                1,
            ),
            encoding="utf-8",
            newline="\n",
        )
        contract_stale = verification_freshness(root, "STEP-001")
        assert contract_stale["reasonCode"] == "VERIFICATION_CONTRACT_STALE", contract_stale
        step.write_text(original_text, encoding="utf-8", newline="\n")
        # Раньше изменения Acceptance criteria не инвалидировали PASS:
        # STEP целиком исключён из subject revision, а Verification commands
        # не менялись. Новый context basis обязан обнаружить этот случай.
        amended = original_text.replace(
            "- Verification PASS.",
            "- Verification PASS, включая новое обязательное условие.",
        )
        step.write_text(amended, encoding="utf-8", newline="\n")
        scope_stale = verification_freshness(root, "STEP-001")
        assert scope_stale["reasonCode"] == "VERIFICATION_CONTEXT_STALE", scope_stale
        command_stale = verification_command_evidence(
            root, "STEP-001", 'python3 -c "print(123)"',
        )
        assert command_stale["reasonCode"] == "VERIFICATION_CONTEXT_STALE", command_stale
        step.write_text(original_text, encoding="utf-8", newline="\n")

        # План входит в scope, а чисто административное изменение priority нет.
        step.write_text(original_text.replace("Synthetic.\n\n## Evidence", "Revised plan.\n\n## Evidence"),
                        encoding="utf-8", newline="\n")
        assert verification_freshness(root, "STEP-001")["reasonCode"] == "VERIFICATION_CONTEXT_STALE"
        step.write_text(original_text.replace("priority: medium", "priority: high"),
                        encoding="utf-8", newline="\n")
        assert verification_freshness(root, "STEP-001")["fresh"] is True
        step.write_text(original_text, encoding="utf-8", newline="\n")

        # Старый блок без context proof должен быть UNKNOWN, а не PASS.
        legacy = original_text.replace(
            next(line for line in original_text.splitlines()
                 if line.startswith("- Verification context basis: ")),
            "",
        )
        step.write_text(legacy, encoding="utf-8", newline="\n")
        legacy_freshness = verification_freshness(root, "STEP-001")
        assert legacy_freshness["reasonCode"] == "VERIFICATION_FRESHNESS_UNKNOWN", legacy_freshness
        step.write_text(original_text, encoding="utf-8", newline="\n")


        # Squash/rebase/commit могут менять HEAD без изменения фактических
        # проверенных файлов. В том числе до commit product-файл был untracked,
        # а после commit стал tracked — отпечаток должен остаться тем же.
        # Сохраняем базовый HEAD: остальные тесты НЕ должны работать на
        # временном squash-коммите, который уже содержит generated Evidence.
        squash_base_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        reset(root)
        product_path = root / "src" / "squash-fixture.ts"
        product_path.parent.mkdir(parents=True, exist_ok=True)
        product_path.write_text("export const answer = 42;\n", encoding="utf-8")
        uncommitted = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Squash test confirmed.",
            }],
        )
        assert uncommitted["status"] == "PASS", uncommitted
        subject_hash = uncommitted["subjectContentHash"]
        assert subject_hash.startswith("sha256:"), subject_hash
        assert "Subject content hash: " + subject_hash in step.read_text(encoding="utf-8")
        run(root, "git", "add", "-A")
        run(root, "git", "commit", "-qm", "validated product content")
        same_after_commit = verification_freshness(root, "STEP-001")
        assert same_after_commit["fresh"] is True, same_after_commit
        assert same_after_commit["subjectContentHash"] == subject_hash
        # Переписать identity коммита с тем же tree (эквивалент squash rewrite).
        run(root, "git", "commit", "--amend", "-qm", "squashed product result")
        after_squash = verification_freshness(root, "STEP-001")
        assert after_squash["fresh"] is True, after_squash
        command_after_squash = verification_command_evidence(
            root, "STEP-001", 'python3 -c "print(123)"',
        )
        assert command_after_squash["fresh"] is True, command_after_squash
        # Но изменение одного байта в коде по-прежнему invalidates PASS.
        product_path.write_text("export const answer = 43;\n", encoding="utf-8")
        changed_content = verification_freshness(root, "STEP-001")
        assert changed_content["fresh"] is False, changed_content
        assert changed_content["reasonCode"] == "VERIFICATION_SUBJECT_STALE"
        run(root, "git", "checkout", "--", "src/squash-fixture.ts")
        restored = verification_freshness(root, "STEP-001")
        assert restored["fresh"] is True, restored
        if os.name == "posix":
            product_path.chmod(0o755)
            chmod_stale = verification_freshness(root, "STEP-001")
            assert chmod_stale["fresh"] is False, chmod_stale
            product_path.chmod(0o644)

        # Legacy Evidence без отдельного content hash не объявляется PASS
        # после смены SHA по догадке: требуется exact прежняя revision.
        legacy_evidence = step.read_text(encoding="utf-8")
        step.write_text(
            "\n".join(line for line in legacy_evidence.splitlines()
                      if not line.startswith("- Subject content hash: ")) + "\n",
            encoding="utf-8",
        )
        legacy_same_head = verification_freshness(root, "STEP-001")
        assert legacy_same_head["fresh"] is False, legacy_same_head
        # Вернуть новый Evidence и исходную fixture для остальных проверок.
        step.write_text(legacy_evidence, encoding="utf-8")
        # Убрать именно тестовые коммиты и остаточные файлы, восстановив
        # исходный тестовый baseline без ранее созданного Evidence.
        run(root, "git", "reset", "--hard", squash_base_head)
        run(root, "git", "clean", "-fd")

        # A modified subject invalidates cached automation even if manual
        # observations arrive unchanged.
        reset(root)
        unconfirmed = run_step_verification(root, "STEP-001")
        assert unconfirmed["status"] == "MANUAL_REQUIRED", unconfirmed
        (root / "new-file.py").write_text("subject changed\\n", encoding="utf-8")
        stale_continuation = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Confirmed again.",
            }],
        )
        assert stale_continuation["automatedResumed"] is False, stale_continuation
        (root / "new-file.py").unlink()

        # Если во время ручного подтверждения изменился STEP contract,
        # прежний автоматический PASS не переиспользуем.
        reset(root)
        pending = run_step_verification(root, "STEP-001")
        assert pending["status"] == "MANUAL_REQUIRED", pending
        pending_text = step.read_text(encoding="utf-8")
        step.write_text(
            pending_text.replace("- Verification PASS.", "- Revised acceptance."),
            encoding="utf-8", newline="\n",
        )
        confirmed = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Re-checked new acceptance.",
            }],
        )
        assert confirmed["status"] == "PASS", confirmed
        assert confirmed["automatedResumed"] is False, confirmed

        # Direct evidence writer не должен сохранять результат для старой
        # ревизии, даже если проверки уже завершились успешно.
        reset(root)
        ready = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Confirmed.",
            }],
            write_evidence=False,
        )
        assert ready["status"] == "PASS", ready
        step.write_text(
            step.read_text(encoding="utf-8").replace(
                "- Verification PASS.", "- Verification PASS with amended scope."
            ),
            encoding="utf-8", newline="\n",
        )
        try:
            write_verification_evidence(root, "STEP-001", ready)
        except VerificationInputsStale:
            pass
        else:
            raise AssertionError("stale PASS was written into STEP Evidence")
        assert EVIDENCE_START not in step.read_text(encoding="utf-8")

        # Между чтением STEP и os.replace другой writer изменил Acceptance.
        # Оптимистичная проверка обязана сохранить его изменение, а не
        # перезаписать старым STEP вместе с Evidence.
        reset(root)
        ready_for_race = run_step_verification(
            root, "STEP-001",
            manual_results=[{
                "check": "Подтвердить semantic condition",
                "status": "PASS", "observed": "Race test.",
            }],
            write_evidence=False,
        )
        assert ready_for_race["status"] == "PASS", ready_for_race

        def competing_editor(path, content, *, expected_bytes=None):
            assert expected_bytes is not None
            newer = path.read_bytes().replace(
                b"- Verification PASS.", b"- Updated acceptance by another agent.",
            )
            path.write_bytes(newer)
            return atomic_write_text(path, content, expected_bytes=expected_bytes)

        with patch("verification.atomic_write_text", side_effect=competing_editor):
            try:
                write_verification_evidence(root, "STEP-001", ready_for_race)
            except VerificationInputsStale:
                pass
            else:
                raise AssertionError("concurrent STEP edit was overwritten")
        assert b"- Updated acceptance by another agent." in step.read_bytes()
        assert EVIDENCE_START not in step.read_text(encoding="utf-8")

        # Non-zero exit is factual FAIL, not LLM interpretation.
        reset(root)
        step.write_text(
            task(command_line('python3 -c "import sys; sys.exit(7)"')),
            encoding="utf-8",
            newline="\n",
        )
        failed = run_step_verification(root, "STEP-001")
        assert failed["status"] == "FAIL", failed
        assert failed["commands"][0]["exitCode"] == 7, failed

        # Подмена итогового FAIL на PASS не делает проваленный тест успешным.
        failed_block = step.read_text(encoding="utf-8")
        assert "- Status: FAIL" in failed_block
        step.write_text(
            failed_block.replace("- Status: FAIL", "- Status: PASS", 1),
            encoding="utf-8", newline="\n",
        )
        forged = verification_freshness(root, "STEP-001")
        assert forged["fresh"] is False, forged
        assert forged["reasonCode"] == "VERIFICATION_PROOF_MISMATCH", forged
        command_forged = verification_command_evidence(
            root, "STEP-001", 'python3 -c "import sys; sys.exit(7)"',
        )
        assert command_forged["fresh"] is False, command_forged
        assert command_forged["reasonCode"] == "VERIFICATION_PROOF_MISMATCH", command_forged

        # Verification is required to be read-only. Unexpected repository
        # mutation becomes BLOCKED and generated Evidence is not forged.
        reset(root)
        step.write_text(
            task(
                command_line(
                    'python3 -c "from pathlib import Path; '
                    + "Path('mutated.txt').write_text('x')"
                    + '"'
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        mutated = run_step_verification(root, "STEP-001")
        assert mutated["status"] == "BLOCKED", mutated
        assert mutated["reasonCode"] == "VERIFICATION_MUTATED_REPOSITORY", mutated
        assert (root / "mutated.txt").exists()
        assert EVIDENCE_START not in step.read_text(encoding="utf-8")

        # Shell control syntax is rejected instead of silently using shell=True.
        reset(root)
        step.write_text(
            task(command_line('python3 -c "print(1)" && echo unsafe')),
            encoding="utf-8",
            newline="\n",
        )
        unsafe = run_step_verification(root, "STEP-001")
        assert unsafe["status"] == "BLOCKED", unsafe
        assert unsafe["reasonCode"] == "VERIFICATION_RUNTIME_BLOCKED", unsafe

        # Regression #115: timeout убивает всю process group, включая внуков,
        # которые иначе продолжили бы работать после Verification.
        if os.name == "posix":
            reset(root)
            leak = root / "leaked-grandchild.txt"
            grandchild = (
                "import subprocess, sys, time; "
                "subprocess.Popen([sys.executable, '-c', "
                "'import time, pathlib; time.sleep(2); pathlib.Path(\\'leaked-grandchild.txt\\').write_text(\\'x\\')']); "
                "time.sleep(30)"
            )
            timed = _run_command(root, f'python3 -c "{grandchild}"', timeout_seconds=1)
            assert timed["status"] == "FAIL" and timed["reasonCode"] == "TIMEOUT", timed
            time.sleep(3)
            assert not leak.exists(), "grandchild survived verification timeout"

        # Regression #115: большой вывод учитывается полностью (hash/bytes),
        # но в памяти хранится только bounded tail.
        size = 5 * 1024 * 1024
        big = _run_command(
            root,
            f'python3 -c "import sys; sys.stdout.buffer.write(b\'a\' * {size}); sys.exit(3)"',
            timeout_seconds=60,
        )
        assert big["stdoutBytes"] == size, big["stdoutBytes"]
        assert big["stdoutSha256"] == hashlib.sha256(b"a" * size).hexdigest()
        assert big["status"] == "FAIL" and len(big["stdoutTail"] or "") <= CAPTURE_TAIL_BYTES

        # Regression #115: Verification не может создавать/двигать refs.
        reset(root)
        step.write_text(
            task(command_line("git tag verification-side-effect")),
            encoding="utf-8",
            newline="\n",
        )
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "refs fixture")
        refs_mutated = run_step_verification(root, "STEP-001")
        assert refs_mutated["status"] == "BLOCKED", refs_mutated
        assert refs_mutated["reasonCode"] == "VERIFICATION_MUTATED_REFS", refs_mutated
        run(root, "git", "tag", "-d", "verification-side-effect")
        run(root, "git", "reset", "-q", "--hard", "HEAD~1")

        # Dispatcher enforces the runner before FIX/IMPLEMENT SUCCESS. Manual
        # pending returns the same semantic command; confirmed checks allow DONE.
        reset(root)
        # This fixture isolates Verification, not REVIEW/FIX provenance.
        # FIX normally requires an immutable FAIL review; the actual baseline
        # capture has its own regression suite (incremental-review-self-test).
        # Bypass only the snapshot boundary here so that the manual
        # Verification continuation remains independently testable.
        with patch("command_dispatch.capture_fix", return_value={"testOnly": True}):
            dispatch = start_dispatch(root, "STEP FIX STEP-001")
            assert dispatch["status"] == "SEMANTIC", dispatch
            first_complete = complete_dispatch(
                root,
                dispatch["rootCommand"],
                dispatch["command"],
                "SUCCESS",
                execution_id=dispatch["executionId"],
            )
            assert first_complete["status"] == "SEMANTIC", first_complete
            assert first_complete["reasonCode"] == "VERIFICATION_MANUAL_REQUIRED", first_complete

            final = complete_dispatch(
                root,
                dispatch["rootCommand"],
                dispatch["command"],
                "SUCCESS",
                execution_id=dispatch["executionId"],
                details={
                    "manualVerification": [
                        {
                            "check": "Подтвердить semantic condition",
                            "status": "PASS",
                            "observed": "Confirmed by semantic reviewer.",
                        }
                    ]
                },
            )
            assert final["status"] == "DONE", final

            # Race после публикации Evidence, но до complete_command:
            # если изменились acceptance, dispatcher не принимает старый PASS.
            reset(root)
            next_dispatch = start_dispatch(root, "STEP FIX STEP-001")
            assert next_dispatch["status"] == "SEMANTIC", next_dispatch

            def write_then_change(root_value, step_id, verification):
                write_verification_evidence(root_value, step_id, verification)
                path = root_value / "planning/tasks/STEP-001.md"
                path.write_text(
                    path.read_text(encoding="utf-8").replace(
                        "- Verification PASS.", "- Verification PASS with new acceptance."
                    ),
                    encoding="utf-8", newline="\n",
                )

            with patch("command_dispatch.write_verification_evidence", side_effect=write_then_change):
                stale_completion = complete_dispatch(
                    root,
                    next_dispatch["rootCommand"],
                    next_dispatch["command"],
                    "SUCCESS",
                    execution_id=next_dispatch["executionId"],
                    details={
                        "manualVerification": [{
                            "check": "Подтвердить semantic condition",
                            "status": "PASS",
                            "observed": "Confirmed before concurrent change.",
                        }]
                    },
                )
            assert stale_completion["status"] == "BLOCKED", stale_completion
            assert stale_completion["reasonCode"] == "VERIFICATION_CONTEXT_STALE", stale_completion

    print("VERIFICATION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
