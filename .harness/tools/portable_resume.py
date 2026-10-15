#!/usr/bin/env python3
"""Безопасный переносимый вход в HARNESS RESUME.

В отличие от local resume, Git handoff не содержит исполненного этапа и
не подтверждает чужой executionId. Поэтому первый переносимый шаг — только
повторная проверка STEP PLAN. IMPLEMENT/REVIEW/FIX не запускаются по снимку.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from execution_status import load_status, status_path
from portable_handoff import check_handoff
from repository_recovery import repository_recovery_preview


def portable_resume_candidate(root: Path) -> dict[str, Any]:
    """Проверить единственный published STEP и разрешить лишь fresh PLAN.

    Важно: локальный checkpoint проверяет load_status(). Если он исчез после
    прежней работы, штатная ошибка не превращается в «чистый» Git clone.
    """
    state = load_status(root)
    # Даже если tombstones уже вытеснены и массивы пусты, файл local state
    # доказывает, что clone ранее исполнял Harness. Его нельзя считать новым.
    if (
        status_path(root).exists()
        or state.get("executions")
        or state.get("recentTerminals")
        or state.get("stepRecovery")
        or state.get("nextOrdinal", 1) != 1
    ):
        return {
            "status": "BLOCKED",
            "reasonCode": "PORTABLE_LOCAL_HISTORY_PRESENT",
            "message": "Local history exists; portable handoff cannot replace it",
        }

    preview = repository_recovery_preview(root)
    if preview.get("status") != "PASS":
        return {
            "status": "BLOCKED",
            "reasonCode": preview.get("reasonCode", "PORTABLE_PREVIEW_BLOCKED"),
            "message": "Published repository state cannot be proved",
        }
    candidates = preview.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return {
            "status": "BLOCKED",
            "reasonCode": "PORTABLE_CANDIDATES_AMBIGUOUS" if candidates else "NO_RESUMABLE_EXECUTION",
            "message": "Expected exactly one in_progress STEP",
        }
    step_id = candidates[0]["stepId"]
    proof = check_handoff(root, step_id)
    if proof.get("status") != "PASS":
        # Старые проекты без handoff сохраняют прежнюю local-only семантику.
        # Не маскируем этим действительные ошибки существующего handoff.
        reason = proof.get("reasonCode", "PORTABLE_HANDOFF_UNPROVEN")
        if reason == "HANDOFF_NOT_FOUND":
            reason = "NO_RESUMABLE_EXECUTION"
        return {
            "status": "BLOCKED",
            "reasonCode": reason,
            "message": proof.get("message", "Portable handoff validation failed"),
        }
    if candidates[0].get("planFreshness") != "fresh":
        return {
            "status": "BLOCKED",
            "reasonCode": candidates[0].get("reasonCode", "PORTABLE_PLAN_UNPROVEN"),
            "message": "Ready plan and independent review must be proved before adoption",
        }

    # Переиспользуем штатный CTS/dispatcher. НЕ переносим локальный executionId,
    # verification proof, side effects или утверждение о выполненном IMPLEMENT.
    command = f"STEP PLAN {step_id}"
    return {
        "status": "PASS",
        "reasonCode": "PORTABLE_REPLAN_REQUIRED",
        "rootCommand": command,
        "command": command,
        "portable": True,
        "sourceHandoff": proof["path"],
        "publicationHead": proof["publicationHead"],
        "instruction": "start-new-local-plan-review; inspect published code before implementation",
    }


__all__ = ["portable_resume_candidate"]
