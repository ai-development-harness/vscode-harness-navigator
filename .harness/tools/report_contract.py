#!/usr/bin/env python3
"""Строгие validators durable operational reports.

Поддерживаемые kinds:
- harness_update;
- audit;
- release_check;
- skill_search.

Reports являются долговременными repository facts, поэтому validator проверяет
не только frontmatter, но и canonical filename, timestamp identity, H1 и
обязательные sections. Symlink запрещён как trust anchor.

SKILL SEARCH особенно чувствителен: последующий SKILL INSTALL: #N должен
разрешать выбор из сохранённого report, а не из chat/session memory.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
from typing import Any

from document_contract import DocumentError, parse_document, validate_report_timestamp_identity
from harness_config import (
    audit_directory,
    release_directory,
    skill_search_directory,
    skill_search_max_results,
    update_report_directory,
)


# Общий structural helper для report body. Пустая обязательная section считается
# contract failure даже если frontmatter полностью валиден.
def _require_sections(document: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for name in names:
        value = document["sections"].get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing or empty section '## {name}'")
    return errors


# ---------------------------------------------------------------------------
# HARNESS UPDATE report: доказывает фактический route и конечный update result.
# ---------------------------------------------------------------------------
def validate_harness_update_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable Harness update report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "harness_update":
        errors.append("kind must be harness_update")
    for key in ("initial_release", "final_target"):
        value = meta.get(key)
        if not isinstance(value, str) or re.fullmatch(r"v\d+\.\d+\.\d+", value) is None:
            errors.append(f"{key} must be vMAJOR.MINOR.PATCH")
    route = meta.get("route")
    if not isinstance(route, list) or not route or not all(
        isinstance(item, str) and re.fullmatch(r"v\d+\.\d+\.\d+", item)
        for item in route
    ):
        errors.append("route must be a non-empty release-tag list")
    else:
        if meta.get("initial_release") != route[0]:
            errors.append("route must start with initial_release")
        if meta.get("final_target") not in route and meta.get("result") == "success":
            errors.append("successful route must reach final_target")
    if meta.get("result") not in {"success", "reload_required"}:
        errors.append("result must be success|reload_required")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="UPDATE-",
            created_at=meta.get("created_at"),
        )
    )
    if not document.get("h1", "").startswith("# Harness Update — "):
        errors.append("H1 must start with '# Harness Update — '")
    errors.extend(
        _require_sections(
            document,
            ("Route", "Managed path changes", "Verification", "Follow-up"),
        )
    )
    return errors


# ---------------------------------------------------------------------------
# AUDIT report: durable snapshot источников, observed state и corrective action.
# ---------------------------------------------------------------------------
def validate_audit_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable audit report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "audit":
        errors.append("kind must be audit")
    if not isinstance(meta.get("scope"), str) or not meta.get("scope", "").strip():
        errors.append("scope must be non-empty string")
    if meta.get("mode") != "audit":
        errors.append("mode must be audit")
    if meta.get("result") != "complete":
        errors.append("result must be complete")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="AUDIT-",
            created_at=meta.get("created_at"),
        )
    )
    if not document.get("h1", "").startswith("# Audit — "):
        errors.append("H1 must start with '# Audit — '")
    errors.extend(
        _require_sections(
            document,
            ("Sources checked", "Actual state", "Drift / findings", "Evidence", "Corrective actions"),
        )
    )
    return errors


# ---------------------------------------------------------------------------
# RELEASE CHECK report: ready/blocked verdict + concrete verification evidence.
# ---------------------------------------------------------------------------
def validate_release_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable release report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "release_check":
        errors.append("kind must be release_check")
    if not isinstance(meta.get("target"), str) or not meta.get("target", "").strip():
        errors.append("target must be non-empty string")
    if meta.get("verdict") not in {"ready", "blocked"}:
        errors.append("verdict must be ready|blocked")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="RELEASE-",
            created_at=meta.get("created_at"),
        )
    )
    if not document.get("h1", "").startswith("# Release Check — "):
        errors.append("H1 must start with '# Release Check — '")
    errors.extend(
        _require_sections(
            document,
            (
                "Requirements / scope",
                "Verification gates",
                "Security / migrations / compatibility",
                "Unresolved blockers",
                "Evidence",
            ),
        )
    )
    return errors


_CANDIDATE_HEADING_RE = re.compile(r"(?m)^### #(\d+) — (.+?)\s*$")
_CANDIDATE_FIELD_RE = re.compile(
    r"(?m)^- (Repository|Path|URL|Ref/commit inspected|License|Why it fits|Limitations|Safety notes|Recommendation):\s*(.+?)\s*$"
)
_REQUIRED_CANDIDATE_FIELDS = {
    "Repository",
    "Path",
    "URL",
    "Ref/commit inspected",
    "License",
    "Why it fits",
    "Limitations",
    "Safety notes",
    "Recommendation",
}


# Candidate numbering/fields — machine contract для дальнейшего SKILL INSTALL
# по номеру. Пропуск #2 или отсутствующий provenance field делает выбор
# неоднозначным и потому invalid.
def _validate_skill_candidates(section: str, count: int) -> list[str]:
    errors: list[str] = []
    headings = list(_CANDIDATE_HEADING_RE.finditer(section))
    numbers = [int(match.group(1)) for match in headings]
    expected = list(range(1, count + 1))
    if numbers != expected:
        errors.append(
            "Candidates headings must be contiguous #1..#candidate_count "
            f"(expected {expected}, got {numbers})"
        )

    for index, heading in enumerate(headings):
        number = int(heading.group(1))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        block = section[heading.end():end]
        fields = {match.group(1) for match in _CANDIDATE_FIELD_RE.finditer(block)}
        missing = sorted(_REQUIRED_CANDIDATE_FIELDS - fields)
        if missing:
            errors.append(
                f"candidate #{number} missing fields: " + ", ".join(missing)
            )
    return errors


# ---------------------------------------------------------------------------
# SKILL SEARCH report: query/result provenance и индексируемые candidates.
# ---------------------------------------------------------------------------
def validate_skill_search_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable skill search report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "skill_search":
        errors.append("kind must be skill_search")
    if not isinstance(meta.get("query"), str) or not meta.get("query", "").strip():
        errors.append("query must be non-empty string")
    if meta.get("status") != "complete":
        errors.append("status must be complete")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="SKILL-SEARCH-",
            created_at=meta.get("created_at"),
        )
    )

    count = meta.get("candidate_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        errors.append("candidate_count must be a non-negative integer")
        count_value = 0
    else:
        count_value = count
        try:
            maximum = skill_search_max_results(root)
        except Exception as exc:
            errors.append(f"cannot resolve skills.search.maxResults: {exc}")
        else:
            if count > maximum:
                errors.append(
                    f"candidate_count exceeds skills.search.maxResults ({maximum})"
                )

    if not document.get("h1", "").startswith("# SKILL SEARCH — "):
        errors.append("H1 must start with '# SKILL SEARCH — '")

    errors.extend(
        _require_sections(
            document,
            (
                "Search strategy",
                "Ranking criteria",
                "Candidates",
                "Rejected / notable alternatives",
                "Next command",
            ),
        )
    )
    candidates = document["sections"].get("Candidates", "")
    if isinstance(candidates, str):
        errors.extend(_validate_skill_candidates(candidates, count_value))
    return errors


def validate_all_operational_reports(root: Path) -> list[str]:
    """Проверить все configured durable operational report directories.

    Unexpected Markdown filename также ошибка: неизвестный durable artifact не
    должен выпадать из validation просто потому, что его prefix опечатан.
    """
    errors: list[str] = []

    update_root = update_report_directory(root)
    if update_root.is_dir():
        for path in sorted(update_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"}:
                continue
            if not path.name.startswith("UPDATE-"):
                errors.append(
                    f"update-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_harness_update_report(root, path):
                errors.append(f"update-report: {path.relative_to(root)}: {issue}")

    audit_root = audit_directory(root)
    if audit_root.is_dir():
        for path in sorted(audit_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"} or path.name.startswith("MIGRATION-"):
                continue
            if not path.name.startswith("AUDIT-"):
                errors.append(
                    f"audit-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_audit_report(root, path):
                errors.append(f"audit-report: {path.relative_to(root)}: {issue}")

    release_root = release_directory(root)
    if release_root.is_dir():
        for path in sorted(release_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"}:
                continue
            if not path.name.startswith("RELEASE-"):
                errors.append(
                    f"release-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_release_report(root, path):
                errors.append(f"release-report: {path.relative_to(root)}: {issue}")

    search_root = skill_search_directory(root)
    if search_root.is_dir():
        for path in sorted(search_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"}:
                continue
            if not path.name.startswith("SKILL-SEARCH-"):
                errors.append(
                    f"skill-search-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_skill_search_report(root, path):
                errors.append(f"skill-search-report: {path.relative_to(root)}: {issue}")

    return errors


# ---------------------------------------------------------------------------
# Public CLI:
# --all                         -> все operational reports;
# --file <path> --kind <kind>   -> один repository-relative report;
# --json                        -> machine-readable result.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--kind", choices=["audit", "release_check", "skill_search", "harness_update"])
    parser.add_argument("--all", action="store_true", dest="validate_all")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if args.validate_all:
        errors = validate_all_operational_reports(root)
    elif args.file and args.kind:
        raw_path = Path(args.file)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            errors = ["report path escapes repository"]
        else:
            path = root / raw_path
            validators = {
                "audit": validate_audit_report,
                "release_check": validate_release_report,
                "skill_search": validate_skill_search_report,
                "harness_update": validate_harness_update_report,
            }
            errors = validators[args.kind](root, path)
    else:
        parser.error("use --all or --file <path> --kind <kind>")

    result = {"valid": not errors, "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("REPORT CONTRACT: FAIL")
        for item in errors:
            print(f"  - {item}")
    else:
        print("REPORT CONTRACT: PASS")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
