#!/usr/bin/env python3
"""Regression self-test Harness update boundaries + project-owned schema migration."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import tomllib

from document_contract import parse_document
from harness_config import (
    load_update_policy,
    update_lock_path,
    update_manifest_path,
    update_report_directory,
)
from harness_update import (
    UpdateError,
    WorkingTree,
    _align_preinit_templates_after_reload,
)
from planning_contract import step_completion_proof
from project_migration import legacy_manual_bypass_allowed, legacy_schema_pending, migrate_project
from review_contract import legacy_review_pins, validate_all_review_reports
from template_contract import (
    REVIEW_TEMPLATE,
    align_preinit_project_templates,
    preinit_template_alignment_state,
    template_targets,
    validate_project_templates,
)


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")
    return proc


def repo_root() -> Path:
    here = Path(__file__).resolve()
    proc = run(here.parent, "git", "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip())


def preinit_manifest_text(source: Path) -> str:
    """Manifest fixture в состоянии до PROJECT INIT.

    Self-test запускается и в пользовательских проектах после update: там
    manifest уже initialized, а pre-INIT сценарий должен проверять именно
    pre-INIT контракт, а не состояние checkout-а (#119).
    """
    text = (source / ".harness/manifest.yaml").read_text(encoding="utf-8")
    return re.sub(r"(?m)^(  initialized:)\s*true\s*$", r"\1 false", text, count=1)


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_project_files(root: Path) -> dict[str, bytes]:
    """Byte snapshot tracked/project fixture без internal .git storage."""
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def route_to_latest(graph: dict, start: str) -> tuple[list[str], list[dict]]:
    latest = graph["latest"]
    outgoing = {edge["from"]: edge for edge in graph["transitions"]}
    route = [start]
    edges: list[dict] = []
    current = start
    seen: set[str] = set()
    while current != latest:
        require(current not in seen, f"update graph cycle from {start}")
        seen.add(current)
        edge = outgoing.get(current)
        require(edge is not None, f"no update path from {current} to {latest}")
        edges.append(edge)
        current = edge["to"]
        route.append(current)
    return route, edges


def test_policy_driven_paths(root: Path) -> None:
    policy = load_update_policy(root)
    require(update_manifest_path(root) == root / policy["source"]["update_manifest"], "update_manifest config ignored")
    require(update_lock_path(root) == root / policy["state"]["lock_file"], "lock_file config ignored")
    require(update_report_directory(root) == root / policy["state"]["report_directory"], "report_directory config ignored")


def require_post_v053_bridge(graph: dict) -> None:
    """Первый release с deterministic updater обязан перезагрузить runtime."""
    latest_tuple = tuple(int(part) for part in graph["latest"].removeprefix("v").split("."))
    if latest_tuple <= (0, 5, 3):
        return
    bootstrap = next(
        (edge for edge in graph["transitions"] if edge["from"] == "v0.5.3"),
        None,
    )
    require(bootstrap is not None, "first deterministic-updater bridge from v0.5.3 is missing")
    require(
        bootstrap["kind"] == "bridge" and bootstrap["reloadRequired"] is True,
        "first release after v0.5.3 must be bridge + reloadRequired=true",
    )
    require(
        isinstance(bootstrap.get("reason"), str) and bootstrap["reason"].strip(),
        "v0.5.3 deterministic-updater bridge requires reason",
    )


def test_routing(root: Path) -> None:
    canonical = load_json(update_manifest_path(root))

    # Поддерживаемый floor после удаления legacy namespace: current updater
    # обязан сохранять рабочий route для всех проектов начиная с v0.6.0.
    supported_route, _supported_edges = route_to_latest(canonical, "v0.6.0")
    require(
        supported_route[0] == "v0.6.0" and supported_route[-1] == canonical["latest"],
        f"supported v0.6.0 update route is broken: {supported_route}",
    )

    route, edges = route_to_latest(canonical, "v0.4.0")
    require(route[:3] == ["v0.4.0", "v0.4.1", "v0.4.2"], f"legacy bridge prefix changed: {route}")
    bridge = next(edge for edge in edges if edge["from"] == "v0.4.1")
    require(bridge["kind"] == "bridge" and bridge["reloadRequired"] is True, "v0.4.2 bridge contract changed")
    relocation = next(edge for edge in edges if edge["from"] == "v0.4.2")
    require(relocation["reloadRequired"] is True, "bootstrap relocation must require reload")

    # До первого post-v0.5.3 release synthetic graph доказывает будущую
    # publication boundary. После публикации canonical уже содержит этот edge,
    # поэтому нельзя добавлять второй v0.5.3 transition: negative case должен
    # портить именно bootstrap edge, который реально проверяет gate.
    require_post_v053_bridge(canonical)
    synthetic = json.loads(json.dumps(canonical))
    latest_tuple = tuple(
        int(part) for part in synthetic["latest"].removeprefix("v").split(".")
    )
    if latest_tuple <= (0, 5, 3):
        synthetic["latest"] = "v0.6.0"
        synthetic["transitions"].append(
            {
                "from": "v0.5.3",
                "to": "v0.6.0",
                "kind": "bridge",
                "reloadRequired": True,
                "reason": "install deterministic updater and reload runtime",
            }
        )
    require_post_v053_bridge(synthetic)

    bootstrap = next(
        edge for edge in synthetic["transitions"] if edge["from"] == "v0.5.3"
    )
    bootstrap["reloadRequired"] = False
    try:
        require_post_v053_bridge(synthetic)
    except AssertionError:
        pass
    else:
        raise AssertionError("post-v0.5.3 release gate accepted non-reload bridge")


def test_ownership_contract(root: Path) -> None:
    with (root / ".harness/harness-update.toml").open("rb") as fh:
        policy = tomllib.load(fh)
    ownership = policy["ownership"]
    managed = (
        list(ownership.get("harness_owned", []))
        + list(ownership.get("shared", []))
        + list(ownership.get("marker_merge", []))
    )
    project_templates = [
        "docs/requirements/TEMPLATE.md",
        "docs/adr/TEMPLATE.md",
        "docs/open-questions/TEMPLATE.md",
        "planning/tasks/TEMPLATE.md",
        "planning/reviews/TEMPLATE.md",
        "planning/plan-reviews/TEMPLATE.md",
        "planning/init-reviews/TEMPLATE.md",
        "planning/audits/TEMPLATE.md",
        "planning/releases/TEMPLATE.md",
        "planning/skill-searches/TEMPLATE.md",
    ]
    for path in project_templates:
        require(not matches_any(path, managed), f"PROJECT RECONCILE-owned template became updater-managed: {path}")

    harness_owned = list(ownership.get("harness_owned", []))
    require(".agents/skills/**" not in harness_owned, "broad skill ownership must not return")
    require(matches_any(".agents/skills/README.md", harness_owned), "core skill index must remain Harness-owned")
    with (root / ".harness/harness-policy.toml").open("rb") as fh:
        harness_policy = tomllib.load(fh)
    for skill in harness_policy.get("required_skills", []):
        path = f".agents/skills/{skill}/SKILL.md"
        require(matches_any(path, harness_owned), f"required core skill is not updater-managed: {path}")
    require(
        not matches_any(".agents/skills/project-native/SKILL.md", harness_owned),
        "project/third-party skill must stay outside Harness update ownership",
    )

    require(matches_any(".harness/manifest.yaml", ownership.get("shared", [])), "manifest must remain shared")
    require(matches_any(".harness/git-policy.toml", ownership.get("shared", [])), "git policy must remain shared")


def synthetic_manifest() -> str:
    return """harness:
  version: "1"
  release: "0.5.3"
project:
  initialized: true
  name: legacy-test
  initializedAt: "2026-09-20T00:00:00+00:00"
execution:
  maxFixReviewCycles: 2
review:
  security: auto
  tests: auto
skills:
  search:
    maxResults: 5
language:
  default: ru
sources:
  localBrief: PROJECT_BRIEF.local.md
  projectOverview: docs/PROJECT.md
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
  roadmap: planning/PLAN.md
  status: planning/STATUS.md
protocol:
  file: .harness/docs/EXECUTION_PROTOCOL.md
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
  auditDirectory: planning/audits
  releaseDirectory: planning/releases
  skillSearchDirectory: planning/skill-searches
  skillRegistry: docs/skills/REGISTRY.md
repository:
  gitPolicy: .harness/git-policy.toml
  harnessPolicy: .harness/harness-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
  harnessValidation: .harness/tools/validate.py
  harnessCI: .github/workflows/harness-integrity.yml
"""


def legacy_step() -> str:
    return """# STEP-001 — Legacy step

**Статус:** Выполнено
**Type:** IMPLEMENTATION
**Приоритет:** Средний
**Фаза:** Core
**Depends on:** —

## Requirements

- REQ-001

## ADR

- ADR-001

## Risk flags

- none

## Goal

Legacy goal.

## Context

Legacy context.

## Scope

- legacy.

## Mutation policy

### Allowed

- fixture

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- unrelated

## Acceptance criteria

- works

## Verification

- test

## Deliverables

- artifact

## Implementation plan

**Plan status:** Ready
**Plan revision:** 2
**Plan basis:** sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
**Planned at:** 2026-09-20T00:00:00+00:00

1. Old plan.

## Evidence

Legacy verification evidence.

## Review status

**Latest verdict:** NOT REVIEWED
**Latest report:** —

## Blocker / Failure reason

—
"""


def legacy_review() -> str:
    return """# REVIEW STEP-001

**Reviewer role:** reviewer
**Verdict:** PASS
**Reviewed revision:** legacy-revision

## Scope checked

Legacy fixture.

## Findings

none

## Verification observations

Legacy verification passed.

## Specialized reviews

- Security: not required
- Tests: pass

## Verdict rationale

Acceptance was proven at the time of review.
"""


def legacy_adr() -> str:
    return """# ADR-001 — Legacy accepted decision

**Status:** Accepted
**Date:** 2026-09-20
**Deciders:** team
**Supersedes:** —
**Superseded by:** —

## Context

Legacy.

## Problem

Problem.

## Decision

Keep decision.

## Alternatives considered

Other.

## Consequences

Known.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

None.

## Traceability

- REQ: REQ-001
- STEP: STEP-001
"""


def test_preinit_release_template_alignment() -> None:
    """Safe old-release drift aligns after reload; user drift never overwrites."""
    with tempfile.TemporaryDirectory(prefix="harness-preinit-template-alignment-") as tmp:
        root = Path(tmp)
        source = repo_root()

        manifest_path = root / ".harness/manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            preinit_manifest_text(source),
            encoding="utf-8",
        )

        targets = template_targets(root)
        for path, expected in targets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")

        review_path = root / "planning/reviews/TEMPLATE.md"
        old_release_review = REVIEW_TEMPLATE
        for line in (
            "  implementation_baseline: null\n",
            "  surface_mode: clean-tree-fallback\n",
            "  changed_paths_hash: sha256:...\n",
            "  baseline_status: missing\n",
            "  baseline_reason: implementation baseline is missing\n",
        ):
            old_release_review = old_release_review.replace(line, "")
        old_release_review = old_release_review.replace(
            "\n## Verdict rationale\n\n"
            "Кратко объяснить, почему verdict следует из findings и evidence.\n",
            "",
            1,
        )
        require(old_release_review != REVIEW_TEMPLATE, "old-release fixture did not drift")
        review_path.write_text(old_release_review, encoding="utf-8")
        old_bytes = review_path.read_bytes()

        strict_errors = validate_project_templates(root)
        require(
            any("template baseline drift before PROJECT INIT" in item for item in strict_errors),
            strict_errors,
        )

        pending, blockers = preinit_template_alignment_state(root)
        require(not blockers, blockers)
        require("planning/reviews/TEMPLATE.md" in pending, pending)
        relaxed_errors = validate_project_templates(
            root,
            allow_preinit_release_alignment=True,
        )
        require(not relaxed_errors, relaxed_errors)

        changed = align_preinit_project_templates(root)
        require("planning/reviews/TEMPLATE.md" in changed, changed)
        require(review_path.read_text(encoding="utf-8") == REVIEW_TEMPLATE, changed)
        require(not validate_project_templates(root), validate_project_templates(root))

        custom = (
            old_release_review.rstrip()
            + "\n\nПользовательская pre-init заметка: не перезаписывать.\n"
        )
        review_path.write_text(custom, encoding="utf-8")
        custom_bytes = review_path.read_bytes()
        pending, blockers = preinit_template_alignment_state(root)
        require(blockers, "custom pre-init template drift was classified as safe")
        require("planning/reviews/TEMPLATE.md" not in pending, pending)
        allowed_errors = validate_project_templates(
            root,
            allow_preinit_release_alignment=True,
        )
        require(allowed_errors, "custom drift bypassed target validator")
        try:
            align_preinit_project_templates(root)
        except ValueError as exc:
            require("alignment blocked" in str(exc), str(exc))
        else:
            raise AssertionError("custom pre-init template drift was overwritten")
        require(
            review_path.read_bytes() == custom_bytes,
            "blocked pre-init alignment changed custom template bytes",
        )

        manifest_text = manifest_path.read_text(encoding="utf-8").replace(
            "  initialized: false",
            "  initialized: true",
            1,
        )
        manifest_path.write_text(manifest_text, encoding="utf-8")
        review_path.write_bytes(old_bytes)
        pending, blockers = preinit_template_alignment_state(root)
        require(not pending and not blockers, (pending, blockers))
        require(
            align_preinit_project_templates(root) == [],
            "initialized project template was aligned by updater",
        )

        # Updater-specific deferred alignment is transactional around target
        # validator: successful postcondition keeps exact baseline, failure
        # restores the old release template byte-for-byte.
        manifest_path.write_text(
            preinit_manifest_text(source),
            encoding="utf-8",
        )
        review_path.write_text(old_release_review, encoding="utf-8")
        validator_path = root / ".harness/tools/validate.py"
        validator_path.parent.mkdir(parents=True, exist_ok=True)
        validator_path.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
            encoding="utf-8",
        )
        aligned = _align_preinit_templates_after_reload(
            root,
            WorkingTree(root),
        )
        require("planning/reviews/TEMPLATE.md" in aligned, aligned)
        require(review_path.read_text(encoding="utf-8") == REVIEW_TEMPLATE, aligned)

        review_path.write_text(old_release_review, encoding="utf-8")
        before_failed_postcondition = review_path.read_bytes()
        validator_path.write_text(
            "#!/usr/bin/env python3\n"
            "print('synthetic target postcondition failure')\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        try:
            _align_preinit_templates_after_reload(
                root,
                WorkingTree(root),
            )
        except UpdateError as exc:
            require(exc.code == "POSTCONDITION_FAILED", (exc.code, exc))
        else:
            raise AssertionError("failed target validator did not rollback alignment")
        require(
            review_path.read_bytes() == before_failed_postcondition,
            "failed deferred alignment did not restore old template bytes",
        )


def test_project_owned_migration() -> None:
    with tempfile.TemporaryDirectory(prefix="harness-schema-migration-") as tmp:
        root = Path(tmp)
        (root / ".harness").mkdir(parents=True)
        (root / ".harness/manifest.yaml").write_text(synthetic_manifest(), encoding="utf-8")
        (root / ".harness/harness-update.toml").write_text(
            '[state]\nreport_directory = "planning/harness-updates"\n',
            encoding="utf-8",
        )
        (root / "docs/PROJECT.md").parent.mkdir(parents=True)
        (root / "docs/PROJECT.md").write_text("# Project\n", encoding="utf-8")
        (root / "docs/architecture.md").write_text("# Architecture\n", encoding="utf-8")

        req = root / "docs/requirements"
        req.mkdir(parents=True)
        (req / "SPEC.md").write_text(
            "# Requirements Specification\n\n"
            "### REQ-001 — Legacy requirement\n\n"
            "#### Requirement\n\nLegacy contract.\n\n"
            "#### Rationale\n\nLegacy reason.\n\n"
            "#### Acceptance\n\n- Works.\n\n"
            "#### Traceability\n\nSTEP-001 ADR-001\n\n"
            "### REQ-002 — Already materialized requirement\n\n"
            "#### Requirement\n\nKeep existing canonical file.\n\n"
            "#### Rationale\n\nMixed migration fixture.\n\n"
            "#### Acceptance\n\n- Existing file survives.\n\n"
            "#### Traceability\n\n",
            encoding="utf-8",
        )
        (req / "REQ-002-existing.md").write_text(
            "---\n"
            "schema: 1\n"
            "id: REQ-002\n"
            "priority: medium\n"
            "source: existing\n"
            "steps: []\n"
            "adrs: []\n"
            "---\n\n"
            "# REQ-002 — Already materialized requirement\n\n"
            "## Requirement\n\nKeep existing canonical file.\n\n"
            "## Rationale\n\nMixed migration fixture.\n\n"
            "## Acceptance\n\n- Existing file survives.\n",
            encoding="utf-8",
        )
        req2_before = (req / "REQ-002-existing.md").read_text(encoding="utf-8")
        (req / "STATUS.md").write_text("# Requirements Status\n", encoding="utf-8")

        (root / "planning/tasks").mkdir(parents=True)
        (root / "planning/tasks/STEP-001.md").write_text(legacy_step(), encoding="utf-8")
        legacy_review_path = root / "planning/reviews/STEP-001/REVIEW-20260920T000000Z.md"
        legacy_review_path.parent.mkdir(parents=True)
        legacy_review_path.write_text(legacy_review(), encoding="utf-8")
        legacy_review_before = legacy_review_path.read_text(encoding="utf-8")

        # Regression #82: simulated old-but-valid project-owned REVIEW template.
        # Current protocol adds surface proof keys + one required section. RECONCILE
        # must migrate shape without overwriting project values/unknown keys/prose.
        old_review_template = REVIEW_TEMPLATE
        for line in (
            "  implementation_baseline: null\n",
            "  surface_mode: clean-tree-fallback\n",
            "  changed_paths_hash: sha256:...\n",
            "  baseline_status: missing\n",
            "  baseline_reason: implementation baseline is missing\n",
        ):
            old_review_template = old_review_template.replace(line, "")
        old_review_template = old_review_template.replace(
            "verdict: pass\n",
            "verdict: blocked\nproject_note: keep-me\n",
            1,
        )
        old_review_template = old_review_template.replace(
            "\n## Verdict rationale\n\nКратко объяснить, почему verdict следует из findings и evidence.\n",
            "",
            1,
        )
        old_review_template += "\n## Project notes\n\nПользовательский текст должен сохраниться.\n"
        review_template_path = root / "planning/reviews/TEMPLATE.md"
        review_template_path.parent.mkdir(parents=True, exist_ok=True)
        review_template_path.write_text(old_review_template, encoding="utf-8")
        (root / "docs/adr").mkdir(parents=True)
        (root / "docs/adr/ADR-001-legacy.md").write_text(legacy_adr(), encoding="utf-8")
        (root / "docs/OPEN_QUESTIONS.md").write_text(
            "# Open Questions\n\n"
            "OQ-001 — Legacy question\n"
            "Status: RESOLVED\n"
            "Affects: REQ-001\n"
            "Context: first context line\n"
            "second context line\n"
            "Decision needed: choose option\n"
            "with second decision line\n"
            "Resolution: chosen result\n"
            "with second resolution line\n",
            encoding="utf-8",
        )

        # Immutable-history checks опираются на Git facts, поэтому synthetic
        # migration fixture тоже является настоящим repository.
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.email", "harness-test@example.invalid")
        run(root, "git", "config", "user.name", "Harness Test")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "legacy fixture")

        # Regression #92: поздний hard conflict не имеет права оставлять
        # partial migration ранних REQ/STEP/ADR/OQ/templates.
        valid_review_template = review_template_path.read_text(encoding="utf-8")
        review_template_path.write_text(
            valid_review_template.replace(
                "kind: step_review",
                "kind: audit",
                1,
            ),
            encoding="utf-8",
        )
        before_template_block = snapshot_project_files(root)
        try:
            migrate_project(root)
        except ValueError as exc:
            require("project migration preflight blocked" in str(exc), str(exc))
            require("frontmatter.kind must be step_review" in str(exc), str(exc))
        else:
            raise AssertionError("template hard conflict was migrated partially")
        require(
            snapshot_project_files(root) == before_template_block,
            "failed template preflight mutated project tree",
        )
        review_template_path.write_text(valid_review_template, encoding="utf-8")

        # Invalid later-family legacy identity также обнаруживается до первого
        # write (в частности до split monolithic REQ).
        adr_path = root / "docs/adr/ADR-001-legacy.md"
        valid_adr = adr_path.read_text(encoding="utf-8")
        adr_path.write_text(
            valid_adr.replace(
                "# ADR-001 — Legacy accepted decision",
                "# ADR-999 — Legacy accepted decision",
                1,
            ),
            encoding="utf-8",
        )
        before_adr_block = snapshot_project_files(root)
        try:
            migrate_project(root)
        except ValueError as exc:
            require("project migration preflight blocked" in str(exc), str(exc))
            require("does not match filename id ADR-001" in str(exc), str(exc))
        else:
            raise AssertionError("invalid legacy ADR identity was migrated partially")
        require(
            snapshot_project_files(root) == before_adr_block,
            "failed ADR preflight mutated project tree",
        )
        adr_path.write_text(valid_adr, encoding="utf-8")

        # Duplicate monolithic IDs would otherwise create ambiguous canonical
        # artifacts; они тоже block до mutation.
        spec_path = req / "SPEC.md"
        valid_spec = spec_path.read_text(encoding="utf-8")
        spec_path.write_text(
            valid_spec
            + "\n### REQ-001 — Duplicate legacy requirement\n\n"
            + "#### Requirement\n\nDuplicate.\n",
            encoding="utf-8",
        )
        before_spec_block = snapshot_project_files(root)
        try:
            migrate_project(root)
        except ValueError as exc:
            require("duplicate monolithic REQ id REQ-001" in str(exc), str(exc))
        else:
            raise AssertionError("duplicate monolithic REQ was migrated")
        require(
            snapshot_project_files(root) == before_spec_block,
            "failed SPEC preflight mutated project tree",
        )
        spec_path.write_text(valid_spec, encoding="utf-8")

        require(legacy_schema_pending(root), "legacy schema not detected")
        require(
            not legacy_manual_bypass_allowed(root),
            "mixed/partially migrated project received manual legacy bypass",
        )
        first = migrate_project(root)
        require(first["status"] == "MIGRATED", first)
        require(not legacy_schema_pending(root), "migration left active legacy schema")

        migrated_review_template = parse_document(review_template_path)
        review_meta = migrated_review_template["frontmatter"]
        specialized = review_meta["specialized_reviews"]
        for key in (
            "implementation_baseline",
            "surface_mode",
            "changed_paths_hash",
            "baseline_status",
            "baseline_reason",
        ):
            require(key in specialized, f"review template migration missed {key}")
        require(review_meta["verdict"] == "blocked", "project-owned template value overwritten")
        require(review_meta["project_note"] == "keep-me", "unknown project key was lost")
        require(
            "Project notes" in migrated_review_template["sections"]
            and "Пользовательский текст" in migrated_review_template["sections"]["Project notes"],
            "custom project template prose was lost",
        )
        require(
            "Verdict rationale" in migrated_review_template["sections"],
            "missing structural section was not added",
        )
        require(not validate_project_templates(root), validate_project_templates(root))

        step = parse_document(root / "planning/tasks/STEP-001.md")
        require(step["frontmatter"]["schema"] == 1, "STEP schema not migrated")
        require(step["frontmatter"]["plan"]["status"] == "draft", "legacy Ready must become draft")

        req_files = list((root / "docs/requirements").glob("REQ-001-*.md"))
        require(len(req_files) == 1, f"REQ split failed: {req_files}")
        requirement = parse_document(req_files[0])
        require(requirement["frontmatter"]["id"] == "REQ-001", "REQ id lost")
        require(
            (req / "REQ-002-existing.md").read_text(encoding="utf-8") == req2_before,
            "mixed migration overwrote existing canonical REQ",
        )

        decision = parse_document(root / "docs/adr/ADR-001-legacy.md")
        require(decision["frontmatter"]["status"] == "accepted", "Accepted ADR status lost")

        oq_files = list((root / "docs/open-questions").glob("OQ-001-*.md"))
        require(len(oq_files) == 1, "OQ split failed")
        oq_document = parse_document(oq_files[0])
        require(oq_document["frontmatter"]["status"] == "resolved", "OQ status lost")
        require("second context line" in oq_document["sections"]["Context"], "multiline OQ context lost")
        require("second decision line" in oq_document["sections"]["Decision needed"], "multiline OQ decision lost")
        require("second resolution line" in oq_document["sections"]["Resolution"], "multiline OQ resolution lost")

        # Legacy immutable review остаётся byte-for-byte прежним, но migration
        # report фиксирует его hash как durable compatibility proof.
        require(
            legacy_review_path.read_text(encoding="utf-8") == legacy_review_before,
            "legacy immutable review was rewritten",
        )
        pins = legacy_review_pins(root)
        legacy_rel = legacy_review_path.relative_to(root).as_posix()
        require(legacy_rel in pins, f"legacy review was not pinned: {pins}")

        # Migration report сам является trust anchor для legacy pins и потому
        # обязан проходить строгую schema validation.
        migration_report = root / first["report"]
        migration_before = migration_report.read_text(encoding="utf-8")
        migration_report.write_text(
            migration_before.replace("result: complete", "result: draft"),
            encoding="utf-8",
        )
        try:
            legacy_review_pins(root)
        except ValueError as exc:
            require("result must be complete" in str(exc), str(exc))
        else:
            raise AssertionError("invalid migration trust report was accepted")
        migration_report.write_text(migration_before, encoding="utf-8")

        # Regex-shaped, но календарно невозможный filename не может стать
        # trust anchor для legacy pins.
        invalid_calendar_report = migration_report.with_name(
            "MIGRATION-20261340T256199Z.md"
        )
        invalid_calendar_report.write_text(migration_before, encoding="utf-8")
        try:
            legacy_review_pins(root)
        except ValueError as exc:
            require(
                "filename must be MIGRATION-<UTC timestamp>.md" in str(exc),
                str(exc),
            )
        else:
            raise AssertionError("invalid migration calendar filename was accepted")
        invalid_calendar_report.unlink()

        # Hash pin фиксирует bytes именно immutable path. Symlink вместо
        # historical review не может наследовать доверие к target content.
        legacy_backing = legacy_review_path.with_name("legacy-review-target.txt")
        legacy_review_path.rename(legacy_backing)
        legacy_review_path.symlink_to(legacy_backing.name)
        try:
            legacy_review_pins(root)
        except ValueError as exc:
            require("must not reference a symlink" in str(exc), str(exc))
        else:
            raise AssertionError("symlink legacy review was accepted as pinned history")
        legacy_review_path.unlink()
        legacy_backing.rename(legacy_review_path)

        require(not validate_all_review_reports(root), validate_all_review_reports(root))
        proof = step_completion_proof(root, "STEP-001")
        require(proof["complete"], f"legacy PASS review did not preserve completion proof: {proof}")

        # Legacy report identity is exact: STEP-001 must not trust STEP-0010.
        wrong_identity = legacy_review_before.replace("STEP-001", "STEP-0010")
        legacy_review_path.write_text(wrong_identity, encoding="utf-8")
        wrong = step_completion_proof(root, "STEP-001")
        require(not wrong["complete"], f"STEP-001 trusted STEP-0010 legacy review: {wrong}")
        legacy_review_path.write_text(legacy_review_before, encoding="utf-8")

        # RECONCILE owns template refresh, not updater.
        require((root / "planning/reviews/TEMPLATE.md").is_file(), "review template not refreshed")
        require((root / "planning/plan-reviews/TEMPLATE.md").is_file(), "planning-review template missing")

        # Project-owned template можно кастомизировать: повторный RECONCILE
        # не возвращает protocol default поверх project content.
        task_template = root / "planning/tasks/TEMPLATE.md"
        custom_template = task_template.read_text(encoding="utf-8") + "\n<!-- project customization -->\n"
        task_template.write_text(custom_template, encoding="utf-8")
        reports_before = sorted((root / "planning/audits").glob("MIGRATION-*.md"))
        second = migrate_project(root)
        require(task_template.read_text(encoding="utf-8") == custom_template, "RECONCILE overwrote project template")
        reports_after = sorted((root / "planning/audits").glob("MIGRATION-*.md"))
        require(second["status"] == "NO_CHANGES", second)
        require(reports_before == reports_after, "idempotent reconcile created an extra migration report")
        require(not validate_project_templates(root), validate_project_templates(root))

        # Additive structural drift теперь является migration pending, а не
        # тупиком validator-а. Missing key восстанавливается protocol default-ом,
        # но existing project prose остаётся нетронутым.
        stale_template = custom_template.replace("risk_flags:\n  - none\n", "")
        task_template.write_text(stale_template, encoding="utf-8")
        require(
            legacy_schema_pending(root),
            "missing template structural key was not detected as migration pending",
        )
        repaired = migrate_project(root)
        require(repaired["status"] == "MIGRATED", repaired)
        repaired_task_template = task_template.read_text(encoding="utf-8")
        require("risk_flags:\n  - none\n" in repaired_task_template, repaired_task_template)
        require(
            "<!-- project customization -->" in repaired_task_template,
            "additive template migration lost project prose",
        )
        require(not validate_project_templates(root), validate_project_templates(root))
        require(not legacy_schema_pending(root), "additive template migration did not converge")

        # Non-additive identity conflict не угадывается и не overwrite-ится.
        review_template_before_conflict = review_template_path.read_text(encoding="utf-8")
        review_template_path.write_text(
            review_template_before_conflict.replace(
                "kind: step_review",
                "kind: audit",
                1,
            ),
            encoding="utf-8",
        )
        require(
            not legacy_schema_pending(root),
            "non-additive template conflict masqueraded as migratable legacy state",
        )
        require(
            not legacy_manual_bypass_allowed(root),
            "non-additive template conflict received manual migration bypass",
        )
        conflict_errors = validate_project_templates(root)
        require(
            any("frontmatter.kind must be step_review" in item for item in conflict_errors),
            conflict_errors,
        )
        try:
            migrate_project(root)
        except ValueError as exc:
            require("project migration preflight blocked" in str(exc), str(exc))
            require("frontmatter.kind must be step_review" in str(exc), str(exc))
        else:
            raise AssertionError("non-additive project template conflict was overwritten")
        review_template_path.write_text(review_template_before_conflict, encoding="utf-8")
        require(not legacy_schema_pending(root), "restored template still marked pending")

        # После pinning historical report становится immutable contract:
        # mutation должна обнаруживаться, а RECONCILE не имеет права re-pin её.
        legacy_review_path.write_text(legacy_review_before + "\nTampered.\n", encoding="utf-8")
        review_errors = validate_all_review_reports(root)
        require(any("pinned legacy report changed" in item for item in review_errors), review_errors)
        try:
            migrate_project(root)
        except ValueError as exc:
            require("pinned legacy review changed" in str(exc), str(exc))
        else:
            raise AssertionError("tampered pinned legacy review was silently re-migrated")


def test_template_schema_bump() -> None:
    """#105: schema bump project-owned template мигрирует по объявленным шагам."""
    import template_contract as tc

    old = "---\nschema: 1\nkind: demo\nverdict: PASS\n---\n\n# Demo\n\n## Findings\n\nproject prose\n"
    target = (
        "---\nschema: 3\nkind: demo\nverdict: PASS\nseverity: low\n---\n\n"
        "# Demo\n\n## Issues\n\n- ...\n\n## Verdict rationale\n\n...\n"
    )

    def rename_findings(meta, body):
        return meta, body.replace("## Findings", "## Issues", 1)

    with tempfile.TemporaryDirectory(prefix="harness-template-schema-") as tmp:
        path = Path(tmp) / "TEMPLATE.md"
        path.write_text(old, encoding="utf-8")
        saved = dict(tc.TEMPLATE_SCHEMA_MIGRATIONS)
        try:
            # Необъявленный bump остаётся hard blocker-ом и файл не трогается.
            tc.TEMPLATE_SCHEMA_MIGRATIONS.clear()
            pending, blockers = tc._template_migration_state(path, target)
            require(any("no declared template schema migration 1 -> 2" in b for b in blockers), blockers)
            try:
                tc._migrate_template_shape(path, target)
            except ValueError:
                pass
            else:
                raise AssertionError("undeclared schema bump was migrated")
            require(path.read_text(encoding="utf-8") == old, "blocked migration changed file")

            # Цепочка 1 -> 2 (non-additive) -> 3 (additive).
            tc.TEMPLATE_SCHEMA_MIGRATIONS["demo"] = {1: rename_findings, 2: None}
            pending, blockers = tc._template_migration_state(path, target)
            require(pending and not blockers, (pending, blockers))
            require(tc._migrate_template_shape(path, target), "declared migration did nothing")
            migrated = parse_document(path)
            require(migrated["frontmatter"]["schema"] == 3, migrated["frontmatter"])
            require(migrated["frontmatter"]["severity"] == "low", migrated["frontmatter"])
            require("project prose" in migrated["body"], migrated["body"])
            require("Issues" in migrated["sections"], migrated["sections"])
            require("Verdict rationale" in migrated["sections"], migrated["sections"])
            require("Findings" not in migrated["sections"], migrated["sections"])
            # Повторный запуск — no-op.
            require(not tc._migrate_template_shape(path, target), "migration is not idempotent")

            # Downgrade никогда не мигрирует.
            _pending, blockers = tc._template_migration_state(path, old)
            require(blockers, "schema downgrade accepted")
        finally:
            tc.TEMPLATE_SCHEMA_MIGRATIONS.clear()
            tc.TEMPLATE_SCHEMA_MIGRATIONS.update(saved)


def test_release_metadata(root: Path) -> None:
    graph = load_json(update_manifest_path(root))
    lock = load_json(update_lock_path(root))
    manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
    import re
    match = re.search(r'(?m)^  release:\s*"([^"]+)"', manifest)
    require(match is not None, "manifest harness.release missing")
    release = match.group(1)
    require(graph["latest"] == f"v{release}", "graph.latest must match manifest release")
    require(lock["release"] == release, "lock release must match manifest release")
    require(lock["source"]["ref"] == f"v{release}", "lock source.ref must match manifest release")

    # В каноническом source repository release snapshot не может содержать
    # source.commit: SHA самого release commit появляется только после commit/tag.
    # В пользовательском project lock этот pin, наоборот, корректен и записывается
    # updater/adoption после разрешения реально существующего immutable tag.
    source_repository = lock["source"].get("repository")
    if os.environ.get("GITHUB_REPOSITORY") == source_repository:
        require(
            "commit" not in lock["source"],
            "canonical release snapshot lock must not contain source.commit",
        )


# Releases до v0.8.2 поставляют update engine без журнала и с defects
# #98–#103: проект на таком release выполняет следующий hop своим старым
# engine. Опубликованный v0.8.1 вышел из main без нового engine, поэтому
# транзакционный engine устанавливает минимальный bridge v0.8.2 (#119).
# Для каждого release из таблицы единственный допустимый выход — указанный
# bridge (kind=bridge, reloadRequired=true, reason).
REQUIRED_BRIDGES = {
    "v0.8.0": "v0.8.1",
    "v0.8.1": "v0.8.2",
}


def bridge_edge_errors(graph: dict) -> list[str]:
    errors: list[str] = []
    for edge in graph.get("transitions", []):
        source = edge.get("from")
        expected = REQUIRED_BRIDGES.get(source)
        if expected is None:
            continue
        target = edge.get("to")
        if target != expected:
            errors.append(f"{source} may only route to bridge {expected}, got {target}")
        if edge.get("kind") != "bridge" or edge.get("reloadRequired") is not True:
            errors.append(f"{source} -> {target} must be kind=bridge with reloadRequired=true")
        if not str(edge.get("reason") or "").strip():
            errors.append(f"{source} -> {target} bridge requires reason")
    return errors


def test_bridge_release_gate(root: Path) -> None:
    graph = load_json(update_manifest_path(root))
    errors = bridge_edge_errors(graph)
    require(not errors, "; ".join(errors))

    def edge(source: str, target: str, *, kind: str = "bridge", reload: bool = True) -> dict:
        return {"transitions": [{"from": source, "to": target, "kind": kind, "reloadRequired": reload, "reason": "journaled engine"}]}

    # Negative cases: переход мимо bridge и non-reload/standard bridge.
    require(bridge_edge_errors(edge("v0.8.1", "v0.9.0")), "gate accepted v0.8.1 edge that skips v0.8.2")
    require(bridge_edge_errors(edge("v0.8.1", "v0.8.2", kind="standard", reload=False)), "gate accepted non-bridge v0.8.1 -> v0.8.2 edge")
    require(bridge_edge_errors(edge("v0.8.0", "v0.9.0")), "gate accepted v0.8.0 edge that skips v0.8.1")
    require(not bridge_edge_errors(edge("v0.8.1", "v0.8.2")), "gate rejected valid v0.8.2 bridge edge")


def main() -> int:
    root = repo_root()
    tests = [
        ("policy-driven update paths", lambda: test_policy_driven_paths(root)),
        ("routing/reload", lambda: test_routing(root)),
        ("ownership boundary", lambda: test_ownership_contract(root)),
        ("pre-init release template alignment", test_preinit_release_template_alignment),
        ("project-owned schema migration", test_project_owned_migration),
        ("template schema bump migration", test_template_schema_bump),
        ("release metadata", lambda: test_release_metadata(root)),
        ("journaled-engine bridge release gate", lambda: test_bridge_release_gate(root)),
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print(f"HARNESS UPDATE MIGRATION SELF-TEST: PASS ({len(tests)} contracts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
