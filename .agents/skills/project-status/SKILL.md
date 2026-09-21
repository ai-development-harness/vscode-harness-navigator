---
name: project-status
description: Reconcile status projections with canonical tasks, requirements and evidence, then report current blockers and unblocked work.
---
# project-status

Используй для `PROJECT STATUS`. Все paths разрешай через `.harness/manifest.yaml`. Проверь canonical STEP/REQ/ADR/OQ, type-specific completion proofs, latest validated reviews и blockers. Projection-файлы не интерпретируй как independent state: сначала выполни `python3 .harness/tools/sync-projections.py`, затем `python3 .harness/tools/validate.py --mode manual`. Lifecycle-status REQ выводится только из canonical REQ + STEP completion proofs. Не меняй смысл REQ/ADR и не пиши product code. Покажи in-progress, blocked, recent completed и unblocked high-priority work.
