#!/usr/bin/env python3
"""Ранние output gates: ADD, PLAN draft, review, stamp и completion."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile

from command_dispatch import complete_dispatch
from execution_status import start_execution, stamp_plan
from planning_contract import output_declaration_issues, read_task
from semantic_artifacts import write_plan_draft, write_planning_review, SemanticArtifactError


def fixtures():
    spec = importlib.util.spec_from_file_location("output_fixtures", Path(__file__).with_name("intent-resume-self-test.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    fixture = fixtures()
    with tempfile.TemporaryDirectory(prefix="harness-output-contract-") as directory:
        root = Path(directory)
        fixture.prepare(root)
        path = root / "planning/tasks/STEP-001.md"
        original = fixture.task()
        assert not output_declaration_issues(root, read_task(root, "STEP-001"))
        adr_step = original.replace("type: implementation", "type: adr")
        fixture.write(path, adr_step)
        assert any("adr_outputs" in issue for issue in output_declaration_issues(root, read_task(root, "STEP-001")))
        try:
            start_execution(root, "STEP PLAN STEP-001")
        except ValueError as exc:
            assert "OUTPUT_DECLARATIONS_REQUIRED" in str(exc), exc
        else:
            raise AssertionError("PLAN разрешил ADR-STEP без объявленного результата")
        assert not (root / ".harness/local/execution/execution-status.json").exists()

        declared_adr = adr_step.replace("architecture_refs: []", "adr_outputs:\n  - ADR-002\narchitecture_refs: []")
        fixture.write(path, declared_adr)
        assert not output_declaration_issues(root, read_task(root, "STEP-001"))
        for output in ("ADR-003", "`docs/adr/ADR-003-result.md`", "[Решение](docs/adr/ADR-003-result.md)"):
            fixture.write(path, declared_adr.replace("- Resume guard.", f"- {output}"))
            assert any("ADR-003" in issue for issue in output_declaration_issues(root, read_task(root, "STEP-001")))

        refs = "architecture_refs:\n  - docs/architecture.md#input\n  - docs/architecture.md#output"
        architecture_step = original.replace("architecture_refs: []", refs)
        fixture.write(root / "docs/architecture.md", "# Architecture\n\n## Input\n\nВход.\n\n## Output\n\nРезультат.\n")
        for bullet in ("-", "*", "+", "1."):
            fixture.write(path, architecture_step.replace("## Deliverables\n", f"## Deliverables\n\n{bullet} docs/architecture.md\n"))
            assert output_declaration_issues(root, read_task(root, "STEP-001"))
        fixture.write(path, original)
        assert output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=["docs/adr/ADR-001.md#decision"])
        fixture.write(path, architecture_step)
        payload = {"implementationPlan": [{"title": "Обновить описание", "actions": ["Синхронизировать результат."], "files": ["docs/architecture.md#output"]}], "verification": [{"kind": "command", "value": "python3 -V"}]}
        before = path.read_bytes()
        try:
            write_plan_draft(root, "STEP-001", payload)
        except SemanticArtifactError as exc:
            assert "architecture_outputs" in str(exc)
        else:
            raise AssertionError("draft записан с неявным изменением входа")
        assert path.read_bytes() == before

        # Ссылки на вход в Context/Actions не означают его изменение.
        assert not output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=["src/runtime.py"])
        # Структурированный Files path с пробелом не требует backticks.
        spaced = "docs/architecture baseline.md#output"
        fixture.write(path, original.replace("architecture_refs: []", f"architecture_refs:\n  - {spaced}"))
        fixture.write(root / "docs/architecture baseline.md", "# Architecture\n\n## Output\n\nРезультат.\n")
        assert output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=[spaced])
        spaced_payload = {**payload, "implementationPlan": [{"title": "Обновить описание", "actions": ["Синхронизировать результат."], "files": [spaced]}]}
        before_spaced = path.read_bytes()
        try:
            write_plan_draft(root, "STEP-001", spaced_payload)
        except SemanticArtifactError as exc:
            assert "architecture_outputs" in str(exc)
        else:
            raise AssertionError("путь с пробелом обошёл output gate")
        assert path.read_bytes() == before_spaced
        # Anchor результата пересекается и со whole-file входом.
        fixture.write(path, original.replace("architecture_refs: []", "architecture_refs:\n  - docs/architecture.md"))
        assert output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=["docs/architecture.md#output"])
        # Fenced examples не являются настоящими Deliverables/Files.
        example = architecture_step.replace("## Deliverables\n", "## Deliverables\n\n```markdown\n- ADR-999\n```\n")
        example = example.replace("## Implementation plan\n", "## Implementation plan\n\n```markdown\n**Files:**\n- docs/architecture.md#output\n```\n")
        fixture.write(path, example)
        assert not output_declaration_issues(root, read_task(root, "STEP-001"))
        declared = architecture_step.replace(refs, refs + "\narchitecture_outputs:\n  - docs/architecture.md#output")
        fixture.write(path, declared)
        assert not output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=["docs/architecture.md"])
        assert output_declaration_issues(root, read_task(root, "STEP-001"), planned_files=["docs/architecture.md#input"])
        drafted = write_plan_draft(root, "STEP-001", payload)
        assert drafted["status"] == "PASS", drafted

        # Ручная запись Files не обходит stamp и dispatcher complete PLAN.
        fixture.write(path, architecture_step)
        execution = start_execution(root, "STEP PLAN STEP-001")
        fixture.write(path, architecture_step.replace("## Implementation plan\n", "## Implementation plan\n\n**Files:**\n- docs/architecture.md#output\n"))
        try:
            stamp_plan(root, "STEP-001")
        except ValueError as exc:
            assert "OUTPUT_DECLARATIONS_REQUIRED" in str(exc)
        else:
            raise AssertionError("stamp обошёл output gate")
        outcome = complete_dispatch(root, execution["rootCommand"], execution["rootCommand"], "SUCCESS", execution_id=execution["executionId"])
        assert outcome["reasonCode"] == "OUTPUT_DECLARATIONS_REQUIRED", outcome

        # Добавить declaration в уже начатый PLAN и повторить SUCCESS нельзя.
        fixture.write(path, path.read_text(encoding="utf-8").replace(refs, refs + "\narchitecture_outputs:\n  - docs/architecture.md#output"))
        late = complete_dispatch(root, execution["rootCommand"], execution["rootCommand"], "SUCCESS", execution_id=execution["executionId"])
        assert late["status"] == "BLOCKED" and late["reasonCode"] in {"TASK_CONTRACT_CHANGED", "ARCHITECTURE_BASIS_CHANGED"}, late

        fixture.clear_execution(root)
        fixture.write(path, original)
        command = "STEP ADD: Создать решение"
        execution = start_execution(root, command)
        new_path = root / "planning/tasks/STEP-002.md"
        fixture.write(new_path, adr_step.replace("STEP-001", "STEP-002"))
        outcome = complete_dispatch(root, command, command, "SUCCESS", execution_id=execution["executionId"])
        assert outcome["reasonCode"] == "OUTPUT_DECLARATIONS_REQUIRED", outcome
        fixture.write(new_path, declared_adr.replace("STEP-001", "STEP-002"))
        outcome = complete_dispatch(root, command, command, "SUCCESS", execution_id=execution["executionId"])
        assert outcome["status"] == "DONE", outcome

        # Чужой ранее созданный ADR-STEP не блокирует создание новой задачи.
        fixture.clear_execution(root)
        fixture.write(path, adr_step)
        command = "STEP ADD: Обычная задача"
        execution = start_execution(root, command)
        fixture.write(root / "planning/tasks/STEP-003.md", original.replace("STEP-001", "STEP-003"))
        outcome = complete_dispatch(root, command, command, "SUCCESS", execution_id=execution["executionId"])
        assert outcome["status"] == "DONE", outcome

    with tempfile.TemporaryDirectory(prefix="harness-output-plan-success-") as directory:
        root = Path(directory)
        fixture.prepare(root)
        config = root / ".harness/manifest.yaml"
        config.write_text(config.read_text(encoding="utf-8") + "execution:\n  maxPlanReviewCycles: 3\n", encoding="utf-8")
        execution = start_execution(root, "STEP PLAN STEP-001")
        payload = {"implementationPlan": [{"title": "Обновить модуль", "actions": ["Исправить поведение."], "files": ["src/runtime.py"]}], "verification": [{"kind": "command", "value": "python3 -V"}]}
        assert write_plan_draft(root, "STEP-001", payload)["status"] == "PASS"
        review = write_planning_review(root, "STEP-001", {"verdict": "pass", "findings": [], "rationale": "План покрывает критерии."})
        assert review["status"] == "PASS", review
        outcome = complete_dispatch(root, "STEP PLAN STEP-001", "STEP PLAN STEP-001", "SUCCESS", execution_id=execution["executionId"])
        assert outcome["status"] == "DONE", outcome
        assert read_task(root, "STEP-001")["frontmatter"]["plan"]["status"] == "ready"

    print("OUTPUT CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
