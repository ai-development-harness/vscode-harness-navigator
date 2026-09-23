#!/usr/bin/env python3
"""Regression self-test durable operational report contracts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from document_contract import create_durable_report, durable_report_timestamp
from report_contract import (
    validate_all_operational_reports,
    validate_audit_report,
    validate_release_report,
    validate_skill_search_report,
    validate_harness_update_report,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def manifest() -> str:
    return """skills:
  search:
    maxResults: 3
protocol:
  auditDirectory: work/audits
  releaseDirectory: work/releases
  skillSearchDirectory: work/skill-searches
repository:
  harnessUpdatePolicy: .harness/harness-update.toml
"""


def valid_audit() -> str:
    return """---
schema: 1
kind: audit
scope: STEP-001
mode: audit
created_at: 2026-09-21T08:00:00+00:00
result: complete
---

# Audit — 2026-09-21

## Sources checked

- STEP-001

## Actual state

Observed.

## Drift / findings

None.

## Evidence

Checked.

## Corrective actions

- none
"""


def valid_release() -> str:
    return """---
schema: 1
kind: release_check
target: v1.0.0
verdict: ready
created_at: 2026-09-21T08:00:00+00:00
---

# Release Check — 2026-09-21

## Requirements / scope

REQ-001.

## Verification gates

PASS.

## Security / migrations / compatibility

Checked.

## Unresolved blockers

None.

## Evidence

Build/test PASS.
"""


def valid_update() -> str:
    return """---
schema: 1
kind: harness_update
initial_release: v1.0.0
final_target: v1.1.0
route:
  - v1.0.0
  - v1.1.0
created_at: 2026-09-21T08:00:00Z
result: success
---

# Harness Update — v1.0.0 → v1.1.0

## Route

v1.0.0 → v1.1.0

## Managed path changes

- none

## Verification

PASS.

## Follow-up

None.
"""


def valid_search(count: int = 1) -> str:
    candidate = """### #1 — docker-skill

- Repository: owner/repo
- Path: skills/docker
- URL: https://github.com/owner/repo/tree/main/skills/docker
- Ref/commit inspected: abcdef
- License: MIT
- Why it fits: Docker workflow.
- Limitations: None found.
- Safety notes: Static inspection only.
- Recommendation: Suitable.
"""
    return f"""---
schema: 1
kind: skill_search
query: Docker workflow
status: complete
created_at: 2026-09-21T08:00:00+00:00
candidate_count: {count}
---

# SKILL SEARCH — 2026-09-21T080000Z

## Search strategy

GitHub source inspection.

## Ranking criteria

Relevance and safety.

## Candidates

{candidate}
## Rejected / notable alternatives

None.

## Next command

SKILL INSTALL: #1
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-report-contract-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(
            root / ".harness/harness-update.toml",
            """[state]
report_directory = "work/harness-updates"
""",
        )

        update = root / "work/harness-updates/UPDATE-20260921T080000Z.md"
        audit = root / "work/audits/AUDIT-20260921T080000Z.md"
        release = root / "work/releases/RELEASE-20260921T080000Z.md"
        search = root / "work/skill-searches/SKILL-SEARCH-20260921T080000Z.md"
        write(update, valid_update())
        write(audit, valid_audit())
        write(release, valid_release())
        write(search, valid_search())

        errors = validate_all_operational_reports(root)
        assert not errors, errors

        # Same-second durable collision не создаёт suffix-format и не
        # перезаписывает history: выбирается следующий canonical UTC second.
        collision_dir = root / "work/collision"
        collision_dir.mkdir(parents=True, exist_ok=True)
        fixed = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)
        first_name, first_created = durable_report_timestamp(
            "UPDATE-",
            directory=collision_dir,
            now=fixed,
        )
        assert first_name == "UPDATE-20260921T080000Z.md", first_name
        assert first_created == "2026-09-21T08:00:00Z", first_created
        write(collision_dir / first_name, "occupied\n")
        second_name, second_created = durable_report_timestamp(
            "UPDATE-",
            directory=collision_dir,
            now=fixed,
        )
        assert second_name == "UPDATE-20260921T080001Z.md", second_name
        assert second_created == "2026-09-21T08:00:01Z", second_created

        # Проверка actual create race: каждый concurrent writer резервирует
        # canonical filename через O_EXCL и не может перезаписать соседа.
        concurrent_dir = root / "work/concurrent-reports"
        def create_one(index: int) -> str:
            path, created_at = create_durable_report(
                "UPDATE-",
                directory=concurrent_dir,
                now=fixed,
                content_factory=lambda stamp: f"writer={index}; created_at={stamp}\n",
            )
            assert created_at in path.read_text(encoding="utf-8")
            return path.name

        with ThreadPoolExecutor(max_workers=8) as pool:
            names = list(pool.map(create_one, range(8)))
        assert len(set(names)) == 8, names
        assert set(names) == {
            f"UPDATE-20260921T0800{second:02d}Z.md"
            for second in range(8)
        }, names
        assert len(list(concurrent_dir.glob("UPDATE-*.md"))) == 8
        write(
            update,
            valid_update().replace(
                "created_at: 2026-09-21T08:00:00Z",
                "created_at: 2026-09-21T08:00:01Z",
            ),
        )
        update_errors = validate_harness_update_report(root, update)
        assert any(
            "created_at must match UTC timestamp encoded in filename" in item
            for item in update_errors
        ), update_errors
        write(update, valid_update())

        write(search, valid_search(count=2))
        errors = validate_skill_search_report(root, search)
        assert any("contiguous #1..#candidate_count" in item for item in errors), errors
        write(search, valid_search())

        write(release, valid_release().replace("verdict: ready", "verdict: maybe"))
        errors = validate_release_report(root, release)
        assert any("verdict must be ready|blocked" in item for item in errors), errors
        write(release, valid_release())

        # Sortable filename не может лгать о времени создания report.
        mismatch_release = root / "work/releases/RELEASE-20260921T081500Z.md"
        write(mismatch_release, valid_release())
        mismatch_errors = validate_release_report(root, mismatch_release)
        assert any(
            "created_at must match UTC timestamp encoded in filename" in item
            for item in mismatch_errors
        ), mismatch_errors
        mismatch_release.unlink()

        write(audit, valid_audit().replace("## Evidence\n\nChecked.\n", ""))
        errors = validate_audit_report(root, audit)
        assert any("Evidence" in item for item in errors), errors
        write(audit, valid_audit())

        # Durable operational report не может быть symlink trust anchor.
        symlink_release = root / "work/releases/RELEASE-20260921T081500Z.md"
        symlink_release.symlink_to(release.name)
        symlink_errors = validate_release_report(root, symlink_release)
        assert any("must not be a symlink" in item for item in symlink_errors), symlink_errors
        symlink_release.unlink()

        # Regex-похожий, но календарно невозможный UTC timestamp не является
        # canonical durable filename и не должен участвовать в sortable history.
        invalid_date = root / "work/releases/RELEASE-20261340T256199Z.md"
        write(invalid_date, valid_release())
        errors = validate_release_report(root, invalid_date)
        assert any("filename must be RELEASE-<UTC timestamp>.md" in item for item in errors), errors
        invalid_date.unlink()

        # Report directories fail closed on typo/unknown durable Markdown.
        write(root / "work/releases/RELASE-typo.md", valid_release())
        errors = validate_all_operational_reports(root)
        assert any("unexpected durable artifact name" in item for item in errors), errors

    print("REPORT CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
