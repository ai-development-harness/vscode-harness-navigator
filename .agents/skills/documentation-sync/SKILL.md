---
name: documentation-sync
description: Synchronize verified implementation changes into project documentation and projections without inventing behavior.
---
# documentation-sync

Обновляй только затронутые docs после подтверждённой реализации. Source — фактический code/tests/evidence + Accepted ADR/REQ. Все project paths бери из manifest. Не придумывай API. Меняй canonical REQ/ADR/STEP traceability и relevant subsystem docs, затем пересобирай projections через `python3 .harness/tools/sync-projections.py`; PLAN/STATUS/requirements SPEC+STATUS/Open Questions index руками не редактируй. Accepted ADR immutable. Используй `docs` agent для механической части.
