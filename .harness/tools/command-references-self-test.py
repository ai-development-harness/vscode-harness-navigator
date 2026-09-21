#!/usr/bin/env python3
"""Regression self-test manifest-driven command reference scan."""
from __future__ import annotations

from pathlib import Path
import tempfile

from command_references import project_live_document_paths, scan_files


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-command-refs-") as tmp:
        root = Path(tmp)
        write(
            root / ".harness/manifest.yaml",
            """sources:
  projectOverview: spec/PROJECT.md
  requirements: spec/requirements
  adrDirectory: docs
  architecture: spec/architecture.md
  openQuestions: spec/questions
  openQuestionsIndex: spec/QUESTIONS.md
  roadmap: work/ROADMAP.md
  status: work/STATUS.md
protocol:
  taskDirectory: work/tasks
""",
        )
        write(root / "README.md", "# Repo\n")
        write(root / "spec/PROJECT.md", "# Project\n")
        write(root / "spec/requirements/REQ-001-test.md", "# REQ\n\nPLAN STEP-001\n")
        write(root / "spec/architecture.md", "# Architecture\n")
        write(root / "spec/questions/OQ-001-test.md", "# OQ\n\nFIX STEP-001\n")
        write(root / "spec/QUESTIONS.md", "# Questions\n")
        write(root / "work/ROADMAP.md", "# Roadmap\n")
        write(root / "work/STATUS.md", "# Status\n")
        write(root / "work/tasks/STEP-001.md", "# STEP-001\n")
        # Даже если adrDirectory совпадает с широким docs/, историческим
        # исключением является только canonical ADR, а не весь subtree.
        write(root / "docs/ADR-001-old.md", "# ADR\n\nREVIEW STEP-001\n")
        # Обычный subsystem doc в том же configured directory обязан сканироваться.
        write(root / "docs/subsystem.md", "# Subsystem\n\nCOMMIT\n")
        # Symlink с ADR-shaped именем вне canonical ADR root не является
        # historical ADR только из-за target и обязан остаться scan surface.
        (root / "docs/subsystem").mkdir(parents=True)
        (root / "docs/subsystem/ADR-999-linked.md").symlink_to("../ADR-001-old.md")

        paths = project_live_document_paths(root)
        rels = {
            path.relative_to(root).as_posix()
            for path in paths
            if path.is_file()
        }
        assert "docs/ADR-001-old.md" not in rels, rels
        assert "spec/questions/OQ-001-test.md" in rels, rels
        assert "spec/requirements/REQ-001-test.md" in rels, rels
        assert "docs/subsystem.md" in rels, rels
        assert "docs/subsystem/ADR-999-linked.md" in rels, rels

        findings = scan_files(root, paths)
        pairs = {(item.path, item.legacy) for item in findings}
        assert ("spec/requirements/REQ-001-test.md", "PLAN STEP-NNN") in pairs, pairs
        assert ("spec/questions/OQ-001-test.md", "FIX STEP-NNN") in pairs, pairs
        assert ("docs/subsystem.md", "COMMIT") in pairs, pairs
        assert ("docs/subsystem/ADR-999-linked.md", "REVIEW STEP-NNN") in pairs, pairs
        assert ("docs/ADR-001-old.md", "REVIEW STEP-NNN") not in pairs, pairs

    print("COMMAND REFERENCES SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
