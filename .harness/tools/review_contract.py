#!/usr/bin/env python3
"""Детерминированные contracts immutable review/migration history.

Review report является trust artifact только если одновременно выполнены:
- schema/kind/body contract;
- canonical timestamp identity;
- ссылка на существующий STEP;
- корректная verdict composition;
- specialized reviewer evidence;
- exact reviewed repository revision при current-review gate.

Historical reports immutable: addition разрешена, но изменение/delete/rename уже
существующего review/audit/release/update/migration report блокируется.
Legacy reviews после schema migration допускаются только по path + content hash
pins из валидного migration report.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import (
    DocumentError,
    REVIEW_VERDICTS,
    STEP_ID_RE,
    content_hash,
    parse_document,
    require_schema,
    split_frontmatter,
    string_list,
    validate_report_timestamp_identity,
)
from harness_config import (
    audit_directory,
    init_review_directory,
    planning_review_directory,
    release_directory,
    review_directory,
    skill_search_directory,
    update_report_directory,
)
from planning_contract import read_task
from review_gates import required_reviewers


SEVERITIES = {"critical", "high", "medium", "low"}
CATEGORIES = {"implementation", "evidence", "contract"}
SPECIALIZED_STATUSES = {"pass", "fail", "blocked", "not_required"}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:].lower())
    )


def validate_migration_report(root: Path, path: Path) -> list[str]:
    """Проверить migration trust report до использования legacy hash-pins.

    Invalid report не может частично предоставить allowlist: если schema/history
    повреждены, legacy reviews не считаются доказанными.
    """
    errors: list[str] = []
    if path.is_symlink():
        return ["durable migration report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]

    meta = document["frontmatter"]
    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "migration":
        errors.append("kind must be migration")
    if meta.get("result") != "complete":
        errors.append("result must be complete")

    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="MIGRATION-",
            created_at=meta.get("created_at"),
        )
    )

    changed_count = meta.get("changed_count")
    if (
        isinstance(changed_count, bool)
        or not isinstance(changed_count, int)
        or changed_count < 0
    ):
        errors.append("changed_count must be a non-negative integer")

    if document.get("h1") != "# Project Schema Migration":
        errors.append("H1 must be '# Project Schema Migration'")
    for section in ("Changed artifacts", "Legacy immutable reviews", "Notes"):
        value = document["sections"].get(section)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing or empty section '## {section}'")

    values = meta.get("legacy_review_reports", [])
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        errors.append("legacy_review_reports must be a string list")
        return errors
    review_root_rel = _configured_rel(root, review_directory(root))
    for token in values:
        digest, sep, rel = token.partition(" ")
        if not sep or not _valid_sha256(digest) or not rel:
            errors.append(f"invalid legacy review pin {token!r}")
            continue
        candidate = root / rel
        if _under_git_path(rel, review_root_rel) is None:
            errors.append(f"legacy review pin escapes configured review directory: {rel}")
            continue
        if candidate.is_symlink():
            errors.append(f"legacy review pin must not reference a symlink: {rel}")
    return errors


def legacy_review_pins(root: Path) -> dict[str, str]:
    """Прочитать hash-pinned legacy review allowlist из migration reports."""
    pins: dict[str, str] = {}
    directory = audit_directory(root)
    if not directory.is_dir():
        return pins
    for report in sorted(directory.glob("MIGRATION-*.md")):
        issues = validate_migration_report(root, report)
        if issues:
            raise ValueError(
                f"{report.relative_to(root)}: " + "; ".join(issues)
            )
        document = parse_document(report)
        meta = document["frontmatter"]
        values = meta.get("legacy_review_reports", [])
        for token in values:
            digest, sep, rel = token.partition(" ")
            if not sep or not _valid_sha256(digest) or not rel:
                raise ValueError(f"{report.relative_to(root)}: invalid legacy review pin {token!r}")
            candidate = root / rel
            review_root_rel = _configured_rel(root, review_directory(root))
            if _under_git_path(rel, review_root_rel) is None:
                raise ValueError(
                    f"{report.relative_to(root)}: legacy review pin escapes configured review directory: {rel}"
                )
            if candidate.is_symlink():
                raise ValueError(
                    f"{report.relative_to(root)}: legacy review pin must not reference a symlink: {rel}"
                )
            previous = pins.get(rel)
            if previous is not None and previous != digest:
                raise ValueError(f"conflicting legacy review pins for {rel}")
            pins[rel] = digest
    return pins


def current_legacy_review_snapshots(root: Path) -> dict[str, str]:
    """Вернуть no-frontmatter legacy reports с content hashes."""
    snapshots: dict[str, str] = {}
    directory = review_directory(root)
    if not directory.is_dir():
        return snapshots
    for path in sorted(directory.glob("STEP-*/REVIEW-*.md")):
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _ = split_frontmatter(text)
        except (OSError, UnicodeDecodeError, DocumentError):
            continue
        if frontmatter is None:
            snapshots[path.relative_to(root).as_posix()] = content_hash(text)
    return snapshots


def _legacy_review_verdict(path: Path, step_id: str) -> str | None:
    """Минимально прочитать verdict старого immutable report без его переписывания."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    identity = re.search(r"\b(STEP-\d{3,})\b", first)
    if identity is None or identity.group(1) != step_id:
        return None
    match = re.search(r"(?mi)^\*\*Verdict:\*\*\s*(PASS|FAIL|BLOCKED)\s*$", text)
    return match.group(1).upper() if match else None


def trusted_review_reports(
    root: Path,
    step_id: str,
    *,
    extra_legacy_pins: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Schema-v1 reports + exact hash-pinned legacy history для completion proof.

    extra_legacy_pins используется только внутри одной schema-migration
    транзакции: projections могут вычислить final state до публикации migration
    report, который затем делает те же pins durable.
    """
    result = review_reports(root, step_id)
    try:
        pins = legacy_review_pins(root)
    except ValueError:
        pins = {}
    if extra_legacy_pins:
        for rel, digest in extra_legacy_pins.items():
            previous = pins.get(rel)
            if previous is not None and previous != digest:
                raise ValueError(f"conflicting legacy review pin for {rel}")
            pins[rel] = digest
    directory = review_directory(root) / step_id
    if directory.is_dir():
        for path in sorted(directory.glob("REVIEW-*.md")):
            if path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            expected = pins.get(rel)
            if expected is None:
                continue
            try:
                actual = content_hash(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if actual != expected:
                continue
            verdict = _legacy_review_verdict(path, step_id)
            if verdict is None:
                continue
            result.append({
                "path": path,
                "verdict": verdict,
                "document": None,
                "legacy": True,
                "content_hash": actual,
            })
    # Hash-pinned legacy reports существовали до schema-v1 migration.
    # Их произвольные historical filenames не должны конкурировать с sortable
    # schema-v1 naming и становиться "latest" после появления нового review.
    result.sort(
        key=lambda item: (
            0 if item.get("legacy") else 1,
            item["path"].name,
        )
    )
    return result


def latest_trusted_review(
    root: Path,
    step_id: str,
    *,
    extra_legacy_pins: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    reports = trusted_review_reports(
        root,
        step_id,
        extra_legacy_pins=extra_legacy_pins,
    )
    return reports[-1] if reports else None


def _git(root: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return 127, b""
    return proc.returncode, proc.stdout


def _configured_rel(root: Path, directory: Path) -> str:
    """Вернуть configured directory как repository-relative lexical Git path."""
    try:
        return directory.relative_to(root.resolve()).as_posix().rstrip("/")
    except ValueError as exc:
        raise ValueError(f"configured directory escapes repository: {directory}") from exc


def _normalize_git_rel(rel: str) -> str | None:
    """Нормализовать repository-relative Git path без path traversal."""
    normalized = rel.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if (
        not normalized
        or normalized.startswith("/")
        or any(part == ".." for part in normalized.split("/"))
    ):
        return None
    return normalized


def _under_git_path(rel: str, base: str) -> str | None:
    """Вернуть lexical suffix Git path, не разыменовывая symlink target."""
    normalized = _normalize_git_rel(rel)
    if normalized is None:
        return None
    if normalized == base:
        return ""
    prefix = base + "/"
    return normalized[len(prefix):] if normalized.startswith(prefix) else None


def _is_step_review_report_rel(root: Path, rel: str) -> bool:
    """Проверить Git path implementation review без symlink dereference."""
    suffix = _under_git_path(rel, _configured_rel(root, review_directory(root)))
    return suffix is not None and re.fullmatch(r"STEP-\d{3,}/REVIEW-.+\.md", suffix) is not None


def repository_revision(root: Path) -> dict[str, str | None]:
    """Fingerprint exact review target, excluding report/state written by review itself.

    STEP REVIEW сначала фиксирует product/config worktree, затем создаёт immutable
    report. Сам report и .harness/local/** не должны менять reviewed revision.
    """
    code, head = _git(root, "rev-parse", "HEAD")
    git_head = head.decode("utf-8", errors="replace").strip() if code == 0 else None

    code, status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code != 0:
        raise ValueError("cannot read git worktree state")

    def local_operational(rel: str) -> bool:
        normalized = _normalize_git_rel(rel)
        return normalized is not None and (
            normalized == ".harness/local" or normalized.startswith(".harness/local/")
        )

    def review_report_path(rel: str) -> bool:
        normalized = _normalize_git_rel(rel)
        if normalized is None:
            return False
        # Configurable reviewDirectory не является blanket trust boundary:
        # распознаём только report-shaped Git paths, не symlink targets.
        return _is_step_review_report_rel(root, normalized)

    entries = [entry for entry in status.split(b"\0") if entry]
    changed: list[tuple[bytes, str, str | None]] = []
    index = 0
    while index < len(entries):
        raw = entries[index]
        index += 1
        decoded = raw.decode("utf-8", errors="surrogateescape")
        if len(decoded) < 4:
            continue
        xy = raw[:2]
        rel = decoded[3:]
        source_rel: str | None = None
        if b"R" in xy or b"C" in xy:
            if index >= len(entries):
                raise ValueError("malformed git status rename/copy entry")
            source_rel = entries[index].decode("utf-8", errors="surrogateescape")
            index += 1

        path = root / rel

        # Operational local state не является reviewed product/config revision.
        # Для rename/copy исключаем запись только если обе стороны остаются
        # внутри .harness/local/**; перенос между local и product surface обязан
        # остаться видимым в fingerprint.
        if local_operational(rel) and (
            source_rel is None or local_operational(source_rel)
        ):
            continue

        # STEP REVIEW создаёт новый report уже после snapshot. Поэтому можно
        # исключить только новое A/?? report-состояние. Mutation/rename уже
        # существующей immutable history обязана остаться частью exact revision.
        new_review_report = review_report_path(rel) and (xy == b"??" or xy[:1] == b"A")
        if new_review_report and source_rel is None:
            continue
        changed.append((xy, rel, source_rel))

    if not changed:
        return {"git_head": git_head, "worktree_hash": None}

    digest = hashlib.sha256()
    for xy, rel, source_rel in sorted(changed, key=lambda item: (item[1], item[2] or "")):
        digest.update(xy)
        digest.update(b"\0")
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        if source_rel is not None:
            # git status -z для rename/copy выдаёт destination, затем source.
            # Source path является частью index identity: два rename из разных
            # одинаковых файлов не должны иметь одинаковый review fingerprint.
            digest.update(b"SOURCE\0")
            digest.update(source_rel.encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
        path = root / rel

        # XY содержит отдельные index/worktree состояния. Хеш только working-tree
        # bytes позволял двум разным staged revisions иметь одинаковый proof.
        index_state = xy[:1]
        if index_state not in {b" ", b"?"}:
            index_code, index_blob = _git(root, "show", f":{rel}")
            if index_code == 0:
                digest.update(b"INDEX\0")
                digest.update(index_blob)
            else:
                digest.update(b"INDEX_ABSENT\0")
            digest.update(b"\0")

        if path.is_symlink():
            digest.update(b"SYMLINK\0")
            digest.update(str(path.readlink()).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            digest.update(b"FILE\0")
            digest.update(path.read_bytes())
        elif path.exists():
            digest.update(b"OTHER\0")
        else:
            digest.update(b"DELETED\0")
        digest.update(b"\0")
    return {"git_head": git_head, "worktree_hash": "sha256:" + digest.hexdigest()}


def _parse_findings(document: dict[str, Any]) -> list[dict[str, str]]:
    section = document["sections"].get("Findings", "")
    findings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in section.splitlines():
        if line.startswith("### F-"):
            if current is not None:
                findings.append(current)
            current = {"heading": line[4:].strip()}
            continue
        if current is None:
            continue
        for field in ("Severity", "Category", "Location", "Scenario", "Impact", "Fix direction"):
            prefix = f"**{field}:**"
            if line.startswith(prefix):
                current[field] = line[len(prefix):].strip()
                break
    if current is not None:
        findings.append(current)
    return findings


# ---------------------------------------------------------------------------
# STEP REVIEW validator.
# Структурный report contract отделён от require_current_revision: historical
# report должен оставаться валидным для своей revision, а current gate дополнительно
# требует совпадения с factual worktree/review gate прямо сейчас.
# ---------------------------------------------------------------------------
def validate_review_report(
    root: Path,
    path: Path,
    *,
    require_current_revision: bool = False,
    expected_step_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if path.is_symlink():
        return ["durable review report must not be a symlink"]
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]
    errors.extend(require_schema(document, kind="step_review"))

    step_id = meta.get("step_id")
    if not isinstance(step_id, str) or STEP_ID_RE.fullmatch(step_id) is None:
        errors.append("step_id must be STEP-NNN")
        return errors

    # Direct --file validation должен быть таким же строгим, как history scan:
    # если report лежит внутри configured review root, STEP identity выводится
    # из его canonical parent directory автоматически.
    if expected_step_id is None:
        try:
            suffix = path.resolve().relative_to(review_directory(root).resolve())
        except ValueError:
            suffix = None
        if (
            suffix is not None
            and len(suffix.parts) >= 2
            and STEP_ID_RE.fullmatch(suffix.parts[0]) is not None
        ):
            expected_step_id = suffix.parts[0]

    if expected_step_id is not None and step_id != expected_step_id:
        errors.append(f"step_id must match review directory {expected_step_id}")
        return errors
    try:
        task = read_task(root, step_id)
    except Exception as exc:
        errors.append(f"cannot read referenced STEP: {exc}")
        return errors

    verdict = meta.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        errors.append("verdict must be pass|fail|blocked")
    if meta.get("reviewer_role") != "reviewer":
        errors.append("reviewer_role must be reviewer")
    errors.extend(
        validate_report_timestamp_identity(
            path,
            prefix="REVIEW-",
            created_at=meta.get("created_at"),
        )
    )

    revision = meta.get("reviewed_revision")
    if not isinstance(revision, dict):
        errors.append("reviewed_revision must be a mapping")
    else:
        git_head = revision.get("git_head")
        worktree_hash = revision.get("worktree_hash")
        if git_head is not None and (
            not isinstance(git_head, str)
            or re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", git_head) is None
        ):
            errors.append("reviewed_revision.git_head must be null or a 40/64-hex Git OID")
        if worktree_hash is not None and not _valid_sha256(worktree_hash):
            errors.append("reviewed_revision.worktree_hash must be null or sha256")
        if git_head is None and worktree_hash is None:
            errors.append("reviewed_revision must contain git_head or worktree_hash")
        if require_current_revision:
            try:
                current = repository_revision(root)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if revision != current:
                    errors.append("reviewed_revision does not match current repository state")

    findings = _parse_findings(document)
    for index, finding in enumerate(findings, 1):
        prefix = f"finding F-{index:03d}"
        if finding.get("Severity") not in SEVERITIES:
            errors.append(f"{prefix}: invalid or missing Severity")
        if finding.get("Category") not in CATEGORIES:
            errors.append(f"{prefix}: invalid or missing Category")
        for field in ("Location", "Scenario", "Impact", "Fix direction"):
            if not finding.get(field):
                errors.append(f"{prefix}: missing {field}")

    if verdict == "pass" and findings:
        errors.append("PASS review must not contain material findings")
    if verdict == "fail":
        if not findings:
            errors.append("FAIL review requires at least one finding")
        if any(item.get("Category") == "contract" for item in findings):
            errors.append("FAIL cannot contain contract findings; contract defect must be BLOCKED")
        if not any(item.get("Category") in {"implementation", "evidence"} for item in findings):
            errors.append("FAIL requires implementation/evidence finding")
    if verdict == "blocked":
        if not findings:
            errors.append("BLOCKED review requires at least one finding")
        if not any(
            item.get("Category") in {"contract", "evidence"}
            for item in findings
        ):
            errors.append(
                "BLOCKED review requires a contract or blocking evidence finding"
            )

    specialized = meta.get("specialized_reviews")
    if not isinstance(specialized, dict):
        errors.append("specialized_reviews must be a mapping")
    else:
        gate_basis = specialized.get("gate_basis")
        if not _valid_sha256(gate_basis):
            errors.append("specialized_reviews.gate_basis must be sha256")
        reported_required, required_errors = string_list(
            specialized.get("required"),
            "specialized_reviews.required",
        )
        errors.extend(required_errors)
        unknown_required = sorted(set(reported_required) - {"security", "tests"})
        if unknown_required:
            errors.append(
                "specialized_reviews.required contains unknown reviewers: "
                + ", ".join(unknown_required)
            )
        required_set = set(reported_required)
        for kind in ("security", "tests"):
            status = specialized.get(kind)
            if status not in SPECIALIZED_STATUSES:
                errors.append(f"specialized_reviews.{kind} has invalid status")
                continue
            evidence = specialized.get(f"{kind}_evidence")
            reason = specialized.get(f"{kind}_reason")
            if kind in required_set and status == "not_required":
                errors.append(f"{kind} reviewer is marked required but not_required")
            if status == "not_required" and (not isinstance(reason, str) or not reason.strip()):
                errors.append(f"{kind} not_required requires reason")
            if status != "not_required" and (
                not isinstance(evidence, str) or not evidence.strip()
            ):
                errors.append(
                    f"{kind} review status {status} requires evidence summary/reference"
                )

        required_blocked = sorted(
            kind for kind in required_set if specialized.get(kind) == "blocked"
        )
        required_failed = sorted(
            kind for kind in required_set if specialized.get(kind) == "fail"
        )
        if required_blocked and verdict != "blocked":
            errors.append(
                "required specialized reviewer BLOCKED requires overall BLOCKED: "
                + ", ".join(required_blocked)
            )
        if verdict == "pass" and required_failed:
            errors.append(
                "PASS review requires PASS for all required specialized reviewers: "
                + ", ".join(required_failed)
            )

        # Preselector задаёт только минимально обязательный набор. Если reviewer
        # дополнительно запустил необязательную specialized-проверку, её
        # фактический FAIL/BLOCKED тоже является частью verdict composition:
        # выполненную проверку нельзя игнорировать только потому, что она не
        # входила в deterministic minimum.
        optional_blocked = sorted(
            kind
            for kind in ("security", "tests")
            if kind not in required_set and specialized.get(kind) == "blocked"
        )
        optional_failed = sorted(
            kind
            for kind in ("security", "tests")
            if kind not in required_set and specialized.get(kind) == "fail"
        )
        if optional_blocked and verdict != "blocked":
            errors.append(
                "optional specialized reviewer BLOCKED requires overall BLOCKED: "
                + ", ".join(optional_blocked)
            )
        if verdict == "pass" and optional_failed:
            errors.append(
                "PASS review cannot ignore optional specialized reviewer FAIL: "
                + ", ".join(optional_failed)
            )

        # Только current-review gate можно честно пересчитать по factual worktree.
        # Historical reports проверяются по сохранённому gate proof, иначе будущий
        # unrelated diff ретроактивно ломал бы immutable history.
        if require_current_revision:
            current_gate = required_reviewers(root, step_id)
            if gate_basis != current_gate["basis"]:
                errors.append("specialized_reviews.gate_basis does not match current review gate")
            if required_set != set(current_gate["required"]):
                errors.append("specialized_reviews.required does not match current review gate")

    for required_section in ("Scope checked", "Findings", "Verification observations", "Verdict rationale"):
        if required_section not in document["sections"]:
            errors.append(f"missing section '## {required_section}'")
        elif required_section != "Findings" and not document["sections"][required_section].strip():
            errors.append(f"empty section '## {required_section}'")
    return errors


def review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    """Вернуть только schema-valid immutable reviews STEP в history order."""
    directory = review_directory(root) / step_id
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("REVIEW-*.md")):
        errors = validate_review_report(root, path, expected_step_id=step_id)
        if errors:
            continue
        doc = parse_document(path)
        result.append({
            "path": path,
            "verdict": str(doc["frontmatter"]["verdict"]).upper(),
            "document": doc,
        })
    return result


def latest_review(root: Path, step_id: str, *, require_current_revision: bool = False) -> dict[str, Any] | None:
    """Вернуть latest valid report; optional gate требует current revision proof."""
    reports = review_reports(root, step_id)
    if not reports:
        return None
    report = reports[-1]
    if require_current_revision:
        if validate_review_report(root, report["path"], require_current_revision=True):
            return None
    return report


# Lexical classifier durable history. Symlink target не используется для
# classification: Git tracks path identity, а не место, куда указывает symlink.
def _is_immutable_review_path(root: Path, rel: str) -> bool:
    """Распознать immutable report по lexical Git path, не symlink target."""
    patterns = (
        (_configured_rel(root, review_directory(root)), re.compile(r"^STEP-\d{3,}/REVIEW-.+\.md$")),
        (_configured_rel(root, planning_review_directory(root)), re.compile(r"^STEP-\d{3,}/PLAN-REVIEW-.+\.md$")),
        (_configured_rel(root, init_review_directory(root)), re.compile(r"^INIT-REVIEW-.+\.md$")),
        (_configured_rel(root, audit_directory(root)), re.compile(r"^(?:MIGRATION|AUDIT)-.+\.md$")),
        (_configured_rel(root, release_directory(root)), re.compile(r"^RELEASE-.+\.md$")),
        (_configured_rel(root, skill_search_directory(root)), re.compile(r"^SKILL-SEARCH-.+\.md$")),
        (_configured_rel(root, update_report_directory(root)), re.compile(r"^UPDATE-.+\.md$")),
    )
    for base, pattern in patterns:
        suffix = _under_git_path(rel, base)
        if suffix is not None and pattern.fullmatch(suffix) is not None:
            return True
        # Configured durable directories могут перекрываться. Попадание path
        # внутрь более широкого directory не означает, что это artifact именно
        # этого kind; продолжаем проверку остальных configured roots.
    return False


def _git_changed_review_paths(root: Path, *diff_args: str) -> tuple[list[str], str | None]:
    code, raw = _git(root, *diff_args)
    if code != 0:
        return [], "cannot inspect Git diff for immutable review reports"
    values = raw.decode("utf-8", errors="replace").splitlines()
    return [value for value in values if value and _is_immutable_review_path(root, value)], None


def validate_review_immutability(root: Path, *, ci_mode: bool = False) -> list[str]:
    """Запретить mutation/delete/rename immutable review/migration history.

    Worktree/index checks сравнивают существующие tracked reports с HEAD.
    В CI дополнительно сравнивается HEAD^1 -> HEAD, чтобы mutation history нельзя
    было скрыть уже внутри commit.


    Addition допустим. До commit проверяем staged + unstaged состояние против
    HEAD. В CI сравниваем итоговый commit с первым родителем: PR merge commit
    тем самым проверяется относительно base, обычный push — относительно parent.
    """
    errors: list[str] = []
    directories = [
        review_directory(root).relative_to(root).as_posix(),
        planning_review_directory(root).relative_to(root).as_posix(),
        init_review_directory(root).relative_to(root).as_posix(),
        audit_directory(root).relative_to(root).as_posix(),
        release_directory(root).relative_to(root).as_posix(),
        skill_search_directory(root).relative_to(root).as_posix(),
        update_report_directory(root).relative_to(root).as_posix(),
    ]

    probes: list[tuple[str, tuple[str, ...]]] = [
        (
            "worktree",
            ("diff", "--name-only", "--diff-filter=MDRT", "HEAD", "--", *directories),
        ),
        (
            "index",
            ("diff", "--cached", "--name-only", "--diff-filter=MDRT", "HEAD", "--", *directories),
        ),
    ]
    if ci_mode:
        parent_code, _ = _git(root, "rev-parse", "--verify", "HEAD^1")
        if parent_code == 0:
            probes.append(
                (
                    "commit",
                    ("diff", "--name-only", "--diff-filter=MDRT", "HEAD^1", "HEAD", "--", *directories),
                )
            )
        else:
            # Root commit не имеет baseline и потому не может переписать
            # существующий report. В shallow checkout rev-list --count HEAD
            # тоже может вернуть 1, поэтому shallow state проверяем отдельно.
            shallow_code, shallow = _git(root, "rev-parse", "--is-shallow-repository")
            is_shallow = (
                shallow_code == 0
                and shallow.decode("utf-8", errors="replace").strip() == "true"
            )
            count_code, count = _git(root, "rev-list", "--count", "HEAD")
            is_real_root = (
                shallow_code == 0
                and not is_shallow
                and count_code == 0
                and count.decode("utf-8", errors="replace").strip() == "1"
            )
            if not is_real_root:
                errors.append("review immutability: cannot resolve CI baseline HEAD^1")

    seen: set[str] = set()
    for label, args in probes:
        paths, blocker = _git_changed_review_paths(root, *args)
        if blocker is not None:
            errors.append(f"review immutability ({label}): {blocker}")
            continue
        for rel in paths:
            token = f"{label}:{rel}"
            if token in seen:
                continue
            seen.add(token)
            errors.append(f"review immutability: existing report changed ({label}): {rel}")
    return errors


# ---------------------------------------------------------------------------
# Review-history aggregator:
# 1. immutable-path gate;
# 2. validate migration pins;
# 3. verify pinned legacy bytes;
# 4. validate every schema-v1 STEP review.
# ---------------------------------------------------------------------------
def validate_all_review_reports(root: Path, *, ci_mode: bool = False) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_review_immutability(root, ci_mode=ci_mode))
    directory = review_directory(root)
    if not directory.is_dir():
        return errors
    try:
        pins = legacy_review_pins(root)
    except ValueError as exc:
        pins = {}
        errors.append(f"review: invalid legacy review pins: {exc}")

    # Hash-pinned legacy history должна оставаться физически неизменной.
    for rel, expected in sorted(pins.items()):
        path = root / rel
        if path.is_symlink():
            errors.append(f"review: pinned legacy report must not be a symlink: {rel}")
            continue
        if not path.is_file():
            errors.append(f"review: pinned legacy report missing: {rel}")
            continue
        try:
            actual = content_hash(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"review: cannot read pinned legacy report {rel}: {exc}")
            continue
        if actual != expected:
            errors.append(f"review: pinned legacy report changed: {rel}")

    for path in sorted(directory.glob("STEP-*/REVIEW-*.md")):
        rel = path.relative_to(root).as_posix()
        expected_step_id = path.parent.name
        if path.is_symlink():
            errors.append(f"review: {rel}: durable review report must not be a symlink")
            continue
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _ = split_frontmatter(text)
        except (OSError, UnicodeDecodeError, DocumentError) as exc:
            errors.append(f"review: {rel}: {exc}")
            continue
        if frontmatter is None:
            if pins.get(rel) == content_hash(text):
                continue
            errors.append(
                f"review: {rel}: legacy immutable report is not hash-pinned by schema migration"
            )
            continue
        for issue in validate_review_report(
            root,
            path,
            expected_step_id=expected_step_id,
        ):
            errors.append(f"review: {rel}: {issue}")
    return errors


# ---------------------------------------------------------------------------
# Public diagnostic CLI.
#
# Modes:
# - --file: один report; --current-revision усиливает gate factual state-ом;
# - --step: все reports одного STEP;
# - без selector: полная review history + immutability/pins.
# --json меняет только представление результата, а не validation semantics.
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--step")
    parser.add_argument("--current-revision", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.file:
        raw_path = Path(args.file)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            errors = ["review path escapes repository"]
        else:
            path = root / raw_path
            errors = validate_review_report(
                root,
                path,
                require_current_revision=args.current_revision,
            )
    elif args.step:
        errors = []
        directory = review_directory(root) / args.step
        for path in sorted(directory.glob("REVIEW-*.md")) if directory.is_dir() else []:
            errors.extend(
                f"{path.relative_to(root)}: {item}"
                for item in validate_review_report(root, path)
            )
    else:
        errors = validate_all_review_reports(root)

    result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        for item in errors:
            print(f"- {item}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
