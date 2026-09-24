#!/usr/bin/env python3
"""Canonical schema-v1 contract project-owned templates.

До PROJECT INIT templates являются bootstrap baseline и должны byte-for-byte
совпадать с protocol definitions. После INIT template становится project-owned:
validator требует совместимую structural shape, но не перезаписывает custom
prose/values.

Это разделение не позволяет protocol update молча уничтожить project-specific
template customizations, одновременно сохраняя обязательные schema fields.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from document_contract import (
    atomic_write_text,
    DocumentError,
    parse_document,
    parse_sections,
    render_document,
    split_frontmatter,
)
from harness_config import (
    adr_directory,
    architecture_path,
    get,
    audit_directory,
    init_review_directory,
    open_questions_directory,
    planning_review_directory,
    release_directory,
    requirements_directory,
    review_directory,
    load_manifest,
    skill_search_directory,
    task_directory,
)

STEP_TEMPLATE = """---
schema: 1
id: STEP-NNN
status: planned
type: implementation
priority: medium
phase: TBD
depends_on: []
requirements:
  - REQ-NNN
adrs: []
architecture_refs:
  - "docs/architecture.md#relevant-section"
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

# STEP-NNN — Название

## Goal

Один чёткий результат STEP.

## Context

Почему задача появилась и какое текущее состояние важно.

## Scope

- Конкретная работа внутри STEP.

## Mutation policy

### Allowed

- Явно перечислить допустимые области mutation.

### Conditional

- Указать изменения, допустимые только при доказанной необходимости.

### Forbidden

- unrelated scope.

## Out of scope

- Явно перечислить то, что легко случайно реализовать «заодно».

## Acceptance criteria

- Проверяемый критерий 1.
- Проверяемый критерий 2.

## Verification

- command: `python3 .harness/tools/validate.py --mode manual`

## Deliverables

- Expected code/docs/tests/config artifacts.

## Implementation plan

Заполняется командой `STEP PLAN STEP-NNN`. Пока semantic planning-review не дал PASS для текущих context basis + content hash, `plan.status` не может быть `ready`.

## Evidence

Generated verification block записывает deterministic runner. Дополнительные semantic observations можно хранить вне generated markers.

## Blocker / Failure reason

—
"""

REQ_TEMPLATE = """---
schema: 1
id: REQ-NNN
priority: medium
source: brief
steps:
  - STEP-NNN
adrs: []
---

# REQ-NNN — Название

## Requirement

Проверяемое описание требуемого поведения/результата без привязки к случайной реализации.

## Rationale

Почему requirement существует.

## Acceptance

- Наблюдаемый критерий 1.
- Наблюдаемый критерий 2.
"""

ADR_TEMPLATE = """---
schema: 1
id: ADR-NNN
status: proposed
date: YYYY-MM-DD
deciders: []
supersedes: []
superseded_by: []
requirements:
  - REQ-NNN
steps:
  - STEP-NNN
---

# ADR-NNN — Название решения

## Context

Почему требуется устойчивое решение.

## Problem

Какую архитектурную проблему нужно решить.

## Decision

Принятое решение.

## Alternatives considered

### Вариант A

Плюсы/минусы.

### Вариант B

Плюсы/минусы.

## Consequences

Положительные и отрицательные последствия.

## Security implications

Если не применимо — явно указать.

## Data / migration implications

Если не применимо — явно указать.

## Compatibility / operational implications

Если не применимо — явно указать.
"""

OQ_TEMPLATE = """---
schema: 1
id: OQ-NNN
status: open
affects:
  - PROJECT
created_at: YYYY-MM-DDTHH:MM:SSZ
resolved_at: null
---

# OQ-NNN — Краткий вопрос

## Context

Почему вопрос существенный и почему его нельзя безопасно решить предположением.

## Decision needed

Какое решение требуется.

## Resolution

Заполняется после решения вопроса. Для `status: open` может быть пустым.
"""

REVIEW_TEMPLATE = """---
schema: 1
kind: step_review
step_id: STEP-NNN
verdict: pass
reviewer_role: reviewer
created_at: YYYY-MM-DDTHH:MM:SSZ
reviewed_revision:
  git_head: null
  worktree_hash: null
specialized_reviews:
  gate_basis: sha256:...
  required: []
  implementation_baseline: null
  surface_mode: clean-tree-fallback
  changed_paths_hash: sha256:...
  baseline_status: missing
  baseline_reason: implementation baseline is missing
  security: not_required
  security_evidence: null
  security_reason: no_security_surface
  tests: not_required
  tests_evidence: null
  tests_reason: no_test_surface
---

# STEP REVIEW STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

- Task contract
- REQ/ADR/OQ/architecture refs
- Implementation plan
- Diff/current code
- Tests/verification

## Findings

При PASS material findings отсутствуют.

### F-001 — Title

**Severity:** high
**Category:** implementation
**Location:** path:line / component
**Scenario:** Given / When / Then
**Impact:** ...
**Fix direction:** ...

## Verification observations

Зафиксировать реальные проверки и ограничения доказательств.

## Verdict rationale

Кратко объяснить, почему verdict следует из findings и evidence.
"""

PLAN_REVIEW_TEMPLATE = """---
schema: 1
kind: planning_review
step_id: STEP-NNN
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: sha256:...
plan_content_hash: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# Planning Review STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

- STEP contract
- Semantic dependency contracts (completion proof проверяется перед IMPLEMENT)
- Linked REQ/Accepted ADR/Open Questions
- Architecture refs
- Proposed Implementation plan
- Verification feasibility

## Findings

При PASS material semantic contradictions отсутствуют.

## Verdict rationale

TBD
"""

INIT_REVIEW_TEMPLATE = """---
schema: 1
kind: init_review
stage: requirements
verdict: pass
reviewer_role: reviewer
finding_count: 0
basis: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# PROJECT INIT Review — requirements | roadmap — YYYY-MM-DD HH:MM

## Scope checked

TBD

## Findings

TBD

## Verdict rationale

TBD
"""

AUDIT_TEMPLATE = """---
schema: 1
kind: audit
scope: project
mode: audit
created_at: YYYY-MM-DDTHH:MM:SSZ
result: complete
---

# Audit — YYYY-MM-DD

## Sources checked

TBD

## Actual state

TBD

## Drift / findings

TBD

## Evidence

TBD

## Corrective actions

- STEP-NNN / none
"""

RELEASE_TEMPLATE = """---
schema: 1
kind: release_check
target: version-or-tag
verdict: blocked
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# Release Check — YYYY-MM-DD

## Requirements / scope

TBD

## Verification gates

TBD

## Security / migrations / compatibility

TBD

## Unresolved blockers

TBD

## Evidence

TBD
"""

SKILL_SEARCH_TEMPLATE = """---
schema: 1
kind: skill_search
query: user-description
status: complete
created_at: YYYY-MM-DDTHH:MM:SSZ
candidate_count: 0
---

# SKILL SEARCH — timestamp

## Search strategy

- queries/sources used

## Ranking criteria

- relevance;
- SKILL.md / Agent Skills compatibility;
- workflow quality;
- provenance/maintenance;
- license;
- safety.

## Candidates

### #1 — name

- Repository: owner/repo
- Path: path
- URL: url
- Ref/commit inspected: ref
- License: license/unknown
- Why it fits: ...
- Limitations: ...
- Safety notes: ...
- Recommendation: ...

## Rejected / notable alternatives

- candidate: reason

## Next command

`SKILL INSTALL: #1` либо `SKILL CREATE: <description>`.
"""

# Единственная карта configured template path -> protocol default content.
# Bootstrap, validator и RECONCILE используют одну и ту же definition surface.
def template_targets(root: Path) -> dict[Path, str]:
    architecture_ref = architecture_path(root).relative_to(root.resolve()).as_posix()
    step_template = STEP_TEMPLATE.replace(
        "docs/architecture.md#relevant-section",
        f"{architecture_ref}#relevant-section",
    )
    return {
        task_directory(root) / "TEMPLATE.md": step_template,
        requirements_directory(root) / "TEMPLATE.md": REQ_TEMPLATE,
        adr_directory(root) / "TEMPLATE.md": ADR_TEMPLATE,
        open_questions_directory(root) / "TEMPLATE.md": OQ_TEMPLATE,
        review_directory(root) / "TEMPLATE.md": REVIEW_TEMPLATE,
        planning_review_directory(root) / "TEMPLATE.md": PLAN_REVIEW_TEMPLATE,
        init_review_directory(root) / "TEMPLATE.md": INIT_REVIEW_TEMPLATE,
        audit_directory(root) / "TEMPLATE.md": AUDIT_TEMPLATE,
        release_directory(root) / "TEMPLATE.md": RELEASE_TEMPLATE,
        skill_search_directory(root) / "TEMPLATE.md": SKILL_SEARCH_TEMPLATE,
    }


def refresh_project_templates(root: Path) -> list[str]:
    """Создать только отсутствующие templates, не переписывая project content."""
    changed: list[str] = []
    for path, expected in template_targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            continue
        atomic_write_text(path, expected)
        changed.append(path.relative_to(root).as_posix())
    return changed


def _expected_template_document(expected: str) -> dict[str, Any]:
    """Разобрать protocol template definition для validation и migration."""
    expected_frontmatter, expected_body = split_frontmatter(expected)
    if expected_frontmatter is None:
        raise ValueError("protocol template definition has no frontmatter")
    expected_sections, expected_duplicates = parse_sections(expected_body)
    if expected_duplicates:
        raise ValueError(
            "protocol template definition has duplicate sections: "
            + ", ".join(expected_duplicates)
        )
    return {
        "frontmatter": expected_frontmatter,
        "body": expected_body,
        "sections": expected_sections,
    }


def _merge_missing_mapping_keys(
    expected: Any,
    actual: Any,
    *,
    prefix: str,
) -> tuple[bool, list[str]]:
    """Добавить только missing structural keys, не заменяя project values."""
    if not isinstance(expected, dict):
        return False, []
    if not isinstance(actual, dict):
        return False, [f"{prefix} must be a mapping"]

    changed = False
    blockers: list[str] = []
    for key, expected_value in expected.items():
        child = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            actual[key] = deepcopy(expected_value)
            changed = True
            continue
        if isinstance(expected_value, dict):
            child_changed, child_blockers = _merge_missing_mapping_keys(
                expected_value,
                actual[key],
                prefix=child,
            )
            changed = changed or child_changed
            blockers.extend(child_blockers)
    return changed, blockers


# Объявленные сопровождающим шаги повышения `schema` project-owned templates (#105).
# Ключ — `kind` template, а для templates без kind — prefix id (`STEP`, `REQ`, `ADR`, `OQ`).
# Значение — {from_schema: step}: `None` означает аддитивный шаг (новые keys/sections
# добавит обычная additive migration), callable(meta, body) -> (meta, body) —
# non-additive преобразование. Необъявленный bump остаётся hard blocker-ом.
TemplateSchemaStep = Callable[[dict[str, Any], str], tuple[dict[str, Any], str]] | None
TEMPLATE_SCHEMA_MIGRATIONS: dict[str, dict[int, TemplateSchemaStep]] = {}


def _template_key(meta: dict[str, Any]) -> str | None:
    kind = meta.get("kind")
    if isinstance(kind, str) and kind:
        return kind
    artifact_id = meta.get("id")
    if isinstance(artifact_id, str) and "-" in artifact_id:
        return artifact_id.split("-", 1)[0]
    return None


def _upgrade_template_schema(
    meta: dict[str, Any],
    body: str,
    expected_meta: dict[str, Any],
) -> tuple[dict[str, Any], str, bool, list[str]]:
    """Поднять `schema` по объявленным шагам; вернуть (meta, body, changed, blockers)."""
    actual = meta.get("schema")
    target = expected_meta.get("schema")
    if actual == target:
        return meta, body, False, []
    mismatch = f"frontmatter.schema differs from current template schema {target}"
    if (
        isinstance(actual, bool) or isinstance(target, bool)
        or not isinstance(actual, int) or not isinstance(target, int)
        or actual > target
    ):
        return meta, body, False, [mismatch]
    steps = TEMPLATE_SCHEMA_MIGRATIONS.get(_template_key(expected_meta) or "", {})
    upgraded = deepcopy(meta)
    for version in range(actual, target):
        if version not in steps:
            return meta, body, False, [
                f"{mismatch}: no declared template schema migration {version} -> {version + 1}"
            ]
        step = steps[version]
        if step is not None:
            try:
                upgraded, body = step(upgraded, body)
            except Exception as exc:  # noqa: BLE001 - migration failure = blocker
                return meta, body, False, [
                    f"template schema migration {version} -> {version + 1} failed: {exc}"
                ]
        upgraded["schema"] = version + 1
    return upgraded, body, True, []


def _template_migration_state(
    path: Path,
    expected: str,
) -> tuple[bool, list[str]]:
    """Вернуть (additive_pending, blockers) без repository mutation."""
    try:
        actual_doc = parse_document(path)
    except (DocumentError, OSError, UnicodeDecodeError) as exc:
        return False, [f"cannot parse template: {exc}"]

    expected_doc = _expected_template_document(expected)
    expected_meta = expected_doc["frontmatter"]
    actual_meta = deepcopy(actual_doc["frontmatter"])

    blockers: list[str] = []
    if actual_doc["duplicate_sections"]:
        blockers.extend(
            f"duplicate structural section '## {name}'"
            for name in actual_doc["duplicate_sections"]
        )
    actual_meta, body, changed_schema, schema_blockers = _upgrade_template_schema(
        actual_meta,
        actual_doc["body"],
        expected_meta,
    )
    blockers.extend(schema_blockers)
    expected_kind = expected_meta.get("kind")
    if expected_kind is not None and actual_meta.get("kind") != expected_kind:
        blockers.append(f"frontmatter.kind must be {expected_kind}")

    changed_meta, mapping_blockers = _merge_missing_mapping_keys(
        expected_meta,
        actual_meta,
        prefix="frontmatter",
    )
    blockers.extend(mapping_blockers)
    sections = parse_sections(body)[0] if changed_schema else actual_doc["sections"]
    changed_sections = any(
        name not in sections
        for name in expected_doc["sections"]
    )
    return changed_schema or changed_meta or changed_sections, blockers


def _additive_template_candidate(
    path: Path,
    expected: str,
) -> tuple[str | None, list[str]]:
    """Построить additive candidate без repository mutation.

    None означает отсутствие structural изменений. Existing values/prose
    сохраняются; blockers описывают drift, который additive migration не может
    интерпретировать безопасно.
    """
    try:
        actual_doc = parse_document(path)
    except (DocumentError, OSError, UnicodeDecodeError) as exc:
        return None, [f"cannot parse template: {exc}"]

    expected_doc = _expected_template_document(expected)
    expected_meta = expected_doc["frontmatter"]
    actual_meta = deepcopy(actual_doc["frontmatter"])

    blockers: list[str] = []
    if actual_doc["duplicate_sections"]:
        blockers.extend(
            f"duplicate structural section '## {name}'"
            for name in actual_doc["duplicate_sections"]
        )
    actual_meta, body, changed_schema, schema_blockers = _upgrade_template_schema(
        actual_meta,
        actual_doc["body"],
        expected_meta,
    )
    blockers.extend(schema_blockers)
    expected_kind = expected_meta.get("kind")
    if expected_kind is not None and actual_meta.get("kind") != expected_kind:
        blockers.append(f"frontmatter.kind must be {expected_kind}")

    changed_meta, mapping_blockers = _merge_missing_mapping_keys(
        expected_meta,
        actual_meta,
        prefix="frontmatter",
    )
    blockers.extend(mapping_blockers)
    if blockers:
        return None, blockers

    sections, duplicates = parse_sections(body) if changed_schema else (actual_doc["sections"], [])
    if duplicates:
        return None, [f"duplicate structural section '## {name}'" for name in duplicates]
    body = body.rstrip()
    changed_sections = False
    for name, default_content in expected_doc["sections"].items():
        if name in sections:
            continue
        body += f"\n\n## {name}"
        if default_content:
            body += f"\n\n{default_content}"
        changed_sections = True

    if not (changed_schema or changed_meta or changed_sections):
        return None, []
    return render_document(actual_meta, body), []


def _migrate_template_shape(path: Path, expected: str) -> bool:
    """Idempotent additive migration одного project-owned template.

    Existing values, unknown frontmatter keys и existing Markdown sections
    сохраняются. Missing mapping keys/sections получают protocol defaults.
    Non-additive conflicts fail closed и не переписываются.
    """
    candidate, blockers = _additive_template_candidate(path, expected)
    if blockers:
        raise ValueError(
            f"{path}: non-additive project template drift: " + "; ".join(blockers)
        )
    if candidate is None:
        return False
    atomic_write_text(path, candidate)
    return True


def _preinit_subset_errors(
    actual: Any,
    expected: Any,
    *,
    prefix: str,
) -> list[str]:
    """Require actual release baseline values to be an exact subset of target."""
    if isinstance(actual, dict):
        if not isinstance(expected, dict):
            return [f"{prefix} changed type"]
        errors: list[str] = []
        for key, actual_value in actual.items():
            child = f"{prefix}.{key}" if prefix else key
            if key not in expected:
                errors.append(f"{child} is not part of target template")
                continue
            errors.extend(
                _preinit_subset_errors(
                    actual_value,
                    expected[key],
                    prefix=child,
                )
            )
        return errors
    if actual != expected:
        return [f"{prefix} differs from target template value"]
    return []


def _template_body_preamble(body: str) -> str:
    """Text before first level-2 structural section, normalized only at edges."""
    lines: list[str] = []
    for line in body.replace("\r\n", "\n").splitlines():
        if line.startswith("## "):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def preinit_template_alignment_state(root: Path) -> tuple[list[str], list[str]]:
    """Вернуть (pending, blockers) для безопасного pre-INIT release alignment.

    До INIT project templates обязаны быть exact protocol baseline. Safe upgrade
    допускает old-release template только когда его semantic content является
    точным subset current target: existing keys/values, H1/preamble и existing
    sections совпадают, отсутствовать могут только новые target keys/sections.
    Unknown/custom prose/value drift блокируется и никогда не затирается.
    """
    if bool(get(load_manifest(root), "project.initialized", False)):
        return [], []

    pending: list[str] = []
    blockers: list[str] = []
    for path, expected in template_targets(root).items():
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            pending.append(rel)
            continue

        try:
            actual_text = path.read_text(encoding="utf-8")
            actual_doc = parse_document(path)
            expected_doc = _expected_template_document(expected)
        except (DocumentError, OSError, UnicodeDecodeError, ValueError) as exc:
            blockers.append(f"{rel}: cannot parse template: {exc}")
            continue
        if actual_text == expected:
            continue

        path_errors: list[str] = []
        if actual_doc["duplicate_sections"]:
            path_errors.extend(
                f"duplicate structural section '## {name}'"
                for name in actual_doc["duplicate_sections"]
            )
        path_errors.extend(
            _preinit_subset_errors(
                actual_doc["frontmatter"],
                expected_doc["frontmatter"],
                prefix="frontmatter",
            )
        )
        if _template_body_preamble(actual_doc["body"]) != _template_body_preamble(
            expected_doc["body"]
        ):
            path_errors.append("document preamble/H1 differs from target template")

        actual_sections = actual_doc["sections"]
        expected_sections = expected_doc["sections"]
        for name, actual_content in actual_sections.items():
            if name not in expected_sections:
                path_errors.append(
                    f"section '## {name}' is not part of target template"
                )
                continue
            if actual_content != expected_sections[name]:
                path_errors.append(
                    f"section '## {name}' content differs from target template"
                )

        if path_errors:
            blockers.extend(f"{rel}: {item}" for item in path_errors)
            continue
        pending.append(rel)
    return pending, blockers


def align_preinit_project_templates(root: Path) -> list[str]:
    """Exact-align pre-INIT templates только после safe additive proof."""
    pending, blockers = preinit_template_alignment_state(root)
    if blockers:
        raise ValueError(
            "pre-init project template alignment blocked: " + "; ".join(blockers)
        )
    if not pending:
        return []

    targets = template_targets(root)
    changed: list[str] = []
    pending_set = set(pending)
    for path, expected in targets.items():
        rel = path.relative_to(root).as_posix()
        if rel not in pending_set:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, expected)
        changed.append(rel)
    return changed


def project_template_migration_pending(root: Path) -> bool:
    """Есть ли именно additive structural drift, доступный RECONCILE."""
    if not bool(get(load_manifest(root), "project.initialized", False)):
        return False
    for path, expected in template_targets(root).items():
        if not path.is_file():
            return True
        pending, blockers = _template_migration_state(path, expected)
        if pending and not blockers:
            return True
    return False


def project_template_migration_blockers(root: Path) -> list[str]:
    """Вернуть non-additive template conflicts, которые нельзя bypass/migrate."""
    blockers: list[str] = []
    if not bool(get(load_manifest(root), "project.initialized", False)):
        return blockers
    for path, expected in template_targets(root).items():
        if not path.is_file():
            continue
        _pending, path_blockers = _template_migration_state(path, expected)
        rel = path.relative_to(root).as_posix()
        blockers.extend(f"{rel}: {item}" for item in path_blockers)
    return blockers


def migrate_project_templates(root: Path) -> list[str]:
    """Мигрировать все project-owned templates additive способом."""
    changed: list[str] = []
    for path, expected in template_targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            atomic_write_text(path, expected)
            changed.append(path.relative_to(root).as_posix())
            continue
        if _migrate_template_shape(path, expected):
            changed.append(path.relative_to(root).as_posix())
    return changed


def _required_mapping_shape(expected: Any, actual: Any, *, prefix: str) -> list[str]:
    """Рекурсивно потребовать structural keys без equality project-owned values."""
    errors: list[str] = []
    if not isinstance(expected, dict):
        return errors
    if not isinstance(actual, dict):
        return [f"{prefix} must be a mapping"]
    for key, expected_value in expected.items():
        child = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            errors.append(f"missing structural key {child}")
            continue
        errors.extend(
            _required_mapping_shape(
                expected_value,
                actual[key],
                prefix=child,
            )
        )
    return errors


def _validate_template_shape(path: Path, expected: str) -> list[str]:
    """Проверить current schema shape без требования byte-for-byte content.

    Expected template разбирается in-memory тем же document parser-ом; validator
    не создаёт temporary repository artifact ради comparison.
    """
    errors: list[str] = []
    try:
        actual_doc = parse_document(path)
    except (DocumentError, OSError, UnicodeDecodeError) as exc:
        return [str(exc)]

    # Expected definitions — protocol-owned constants этого release.
    # Разбираем их in-memory тем же parser-ом, без repository mutations.
    expected_doc = _expected_template_document(expected)

    for duplicate in actual_doc["duplicate_sections"]:
        errors.append(f"duplicate structural section '## {duplicate}'")
    errors.extend(
        _required_mapping_shape(
            expected_doc["frontmatter"],
            actual_doc["frontmatter"],
            prefix="frontmatter",
        )
    )
    if actual_doc["frontmatter"].get("schema") != expected_doc["frontmatter"].get("schema"):
        errors.append(
            "frontmatter.schema differs from current template schema "
            f"{expected_doc['frontmatter'].get('schema')}"
        )
    expected_kind = expected_doc["frontmatter"].get("kind")
    if expected_kind is not None and actual_doc["frontmatter"].get("kind") != expected_kind:
        errors.append(f"frontmatter.kind must be {expected_kind}")

    for section in expected_doc["sections"]:
        if section not in actual_doc["sections"]:
            errors.append(f"missing structural section '## {section}'")
    return errors


def validate_project_templates(
    root: Path,
    *,
    allow_preinit_release_alignment: bool = False,
) -> list[str]:
    """Проверить phase-dependent ownership contract templates.

    До INIT normal validation требует exact protocol baseline. Единственное
    исключение — manual target-validator внутри reload-required update: он может
    временно принять только safe additive old-release drift, доказанный через
    preinit_template_alignment_state(). После reload updater обязан выполнить
    exact alignment и повторная validation снова становится строгой.

    После INIT template project-owned: проверяется compatible schema/sections,
    custom content разрешён.
    """
    errors: list[str] = []
    initialized = bool(get(load_manifest(root), "project.initialized", False))
    safe_pending: set[str] = set()
    if not initialized and allow_preinit_release_alignment:
        pending, blockers = preinit_template_alignment_state(root)
        safe_pending = set(pending)
        errors.extend(
            f"project template incompatible: {item}"
            for item in blockers
        )

    for path, expected in template_targets(root).items():
        rel = path.relative_to(root).as_posix()
        if not path.is_file():
            if rel in safe_pending:
                continue
            errors.append(f"project template missing: {path.relative_to(root)}")
            continue
        if not initialized:
            if path.read_text(encoding="utf-8") != expected and rel not in safe_pending:
                errors.append(f"template baseline drift before PROJECT INIT: {path.relative_to(root)}")
            continue
        for issue in _validate_template_shape(path, expected):
            errors.append(f"project template incompatible: {path.relative_to(root)}: {issue}")
    return errors
