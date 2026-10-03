#!/usr/bin/env python3
"""Детерминированная проекция состояния Harness-проекта для UI/Navigator.

Модуль собирает canonical артефакты и связи в стабильный JSON graph. Он не
вызывает LLM, не мутирует repository и не выбирает визуальный layout: эти
обязанности намеренно остаются на стороне клиента.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from document_contract import DocumentError, parse_document
from execution_groups import implementation_plan_step_count, normalize_execution_groups
from impact_analysis import plan_staleness
from harness_config import (
    adr_directory,
    load_manifest,
    open_questions_directory,
    requirements_directory,
    review_directory,
    task_directory,
)
from planning_contract import step_completion_proof
from review_contract import review_reports, validate_review_report
from traceability_coverage import build_coverage


CORE_TYPES = {"REQ", "ADR", "STEP", "OQ"}


class ProjectStateError(RuntimeError):
    """Canonical project state нельзя безопасно превратить в graph snapshot."""


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _title(document: dict[str, Any]) -> str:
    h1 = str(document.get("h1") or "").strip()
    if " — " in h1:
        return h1.split(" — ", 1)[1].strip()
    return h1.lstrip("# ").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _canonical_docs(
    root: Path,
    directory: Path,
    pattern: str,
    *,
    id_prefix: str,
    exact_stem: bool = False,
) -> list[dict[str, Any]]:
    """Прочитать canonical Markdown fail-closed, без собственного parser-а."""
    result: list[dict[str, Any]] = []
    if not directory.is_dir():
        return result

    for path in sorted(directory.glob(pattern)):
        if path.name == "TEMPLATE.md" or path.is_symlink():
            continue
        try:
            document = parse_document(path)
        except DocumentError as exc:
            raise ProjectStateError(
                f"cannot parse canonical artifact {_rel(root, path)}: {exc}"
            ) from exc

        artifact_id = document["frontmatter"].get("id")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id.startswith(id_prefix + "-")
        ):
            raise ProjectStateError(
                f"invalid {id_prefix} identity in {_rel(root, path)}"
            )

        if exact_stem:
            identity_ok = path.stem == artifact_id
        else:
            identity_ok = (
                path.stem == artifact_id
                or path.name.startswith(artifact_id + "-")
            )
        if not identity_ok:
            raise ProjectStateError(
                f"artifact id {artifact_id} does not match path {_rel(root, path)}"
            )

        result.append({"path": path, "document": document})
    return result


def _requirement_status(
    root: Path,
    meta: dict[str, Any],
    steps_by_id: dict[str, dict[str, Any]],
) -> str:
    """Повторить lifecycle semantics projection_contract без нового source of truth."""
    step_ids = _string_list(meta.get("steps"))
    if not step_ids:
        return "planned"

    completed = 0
    deferred = 0
    cancelled = 0
    existing = 0

    for step_id in step_ids:
        item = steps_by_id.get(step_id)
        if item is None:
            continue
        existing += 1
        status = item["document"]["frontmatter"].get("status")
        if status == "deferred":
            deferred += 1
        elif status == "cancelled":
            cancelled += 1
        try:
            proof = step_completion_proof(root, step_id)
        except Exception:
            proof = {"complete": False}
        if proof.get("complete"):
            completed += 1

    if existing == 0:
        return "planned"
    if completed == existing:
        return "completed"
    if completed:
        return "partial"
    if deferred == existing:
        return "deferred"
    if cancelled == existing:
        return "cancelled"
    return "planned"


def _skill_nodes(root: Path) -> list[dict[str, Any]]:
    """Вернуть discoverable skills как вспомогательные graph nodes."""
    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        return []

    nodes: list[dict[str, Any]] = []
    for directory in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            continue
        slug = directory.name
        nodes.append(
            {
                "id": f"SKILL:{slug}",
                "artifactId": slug,
                "type": "SKILL",
                "title": slug,
                "status": "available",
                "path": _rel(root, skill_file),
                "metadata": {},
            }
        )
    return nodes


def _dependency_analysis(
    steps_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Вычислить cycles, longest chain и downstream impact только из STEP graph."""
    dependents: dict[str, set[str]] = defaultdict(set)
    dependencies: dict[str, list[str]] = {}

    for step_id, item in steps_by_id.items():
        values = [
            value
            for value in _string_list(
                item["document"]["frontmatter"].get("depends_on")
            )
            if value in steps_by_id
        ]
        dependencies[step_id] = values
        for dependency in values:
            dependents[dependency].add(step_id)

    cycles: list[list[str]] = []
    color = {step_id: 0 for step_id in steps_by_id}
    stack: list[str] = []

    def visit(node: str) -> None:
        color[node] = 1
        stack.append(node)
        for dependency in dependencies.get(node, []):
            if color[dependency] == 0:
                visit(dependency)
            elif color[dependency] == 1:
                try:
                    start = stack.index(dependency)
                except ValueError:
                    continue
                cycle = stack[start:] + [dependency]
                if cycle not in cycles:
                    cycles.append(cycle)
        stack.pop()
        color[node] = 2

    for step_id in sorted(steps_by_id):
        if color[step_id] == 0:
            visit(step_id)

    longest: list[str] = []
    if not cycles:
        memo: dict[str, list[str]] = {}

        def downstream_chain(node: str) -> list[str]:
            if node in memo:
                return memo[node]
            best: list[str] = []
            for child in sorted(dependents.get(node, set())):
                candidate = downstream_chain(child)
                if len(candidate) > len(best):
                    best = candidate
            memo[node] = [node, *best]
            return memo[node]

        for step_id in sorted(steps_by_id):
            candidate = downstream_chain(step_id)
            if len(candidate) > len(longest):
                longest = candidate

    impact: dict[str, list[str]] = {}
    for step_id in sorted(steps_by_id):
        seen: set[str] = set()
        pending = list(dependents.get(step_id, set()))
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(dependents.get(current, set()))
        impact[step_id] = sorted(seen)

    return {
        "longestChain": longest,
        "cycles": cycles,
        "downstreamImpact": impact,
    }


def build_project_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        manifest = load_manifest(root)
    except Exception as exc:
        raise ProjectStateError(
            f"cannot load .harness/manifest.yaml: {exc}"
        ) from exc

    requirements = _canonical_docs(
        root,
        requirements_directory(root),
        "REQ-*.md",
        id_prefix="REQ",
    )
    adrs = _canonical_docs(
        root,
        adr_directory(root),
        "ADR-*.md",
        id_prefix="ADR",
    )
    steps = _canonical_docs(
        root,
        task_directory(root),
        "STEP-*.md",
        id_prefix="STEP",
        exact_stem=True,
    )
    oqs = _canonical_docs(
        root,
        open_questions_directory(root),
        "OQ-*.md",
        id_prefix="OQ",
    )

    steps_by_id = {
        item["document"]["frontmatter"]["id"]: item
        for item in steps
    }

    project = (
        manifest.get("project")
        if isinstance(manifest.get("project"), dict)
        else {}
    )
    harness = (
        manifest.get("harness")
        if isinstance(manifest.get("harness"), dict)
        else {}
    )
    project_name = (
        project.get("name")
        if isinstance(project.get("name"), str)
        else None
    )

    nodes: dict[str, dict[str, Any]] = {
        "PROJECT": {
            "id": "PROJECT",
            "artifactId": "PROJECT",
            "type": "PROJECT",
            "title": project_name or "Project",
            "status": (
                "initialized"
                if project.get("initialized") is True
                else "not_initialized"
            ),
            "path": ".harness/manifest.yaml",
            "metadata": {"initializedAt": project.get("initializedAt")},
        }
    }

    for item in requirements:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "REQ",
            "title": _title(doc),
            "status": _requirement_status(root, meta, steps_by_id),
            "path": _rel(root, item["path"]),
            "metadata": {
                "priority": meta.get("priority"),
                "source": meta.get("source"),
            },
        }

    for item in adrs:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "ADR",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {"date": meta.get("date")},
        }

    for item in steps:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
        execution_groups = normalize_execution_groups(
            plan.get("execution_groups"),
            implementation_plan_step_count(doc["sections"].get("Implementation plan", "")),
        )
        try:
            plan_impact = plan_staleness(root, artifact_id)
        except (OSError, UnicodeError, ValueError) as exc:
            plan_impact = {
                "status": "blocked",
                "causes": [
                    {
                        "component": "PLANNING_CONTEXT",
                        "change": str(exc),
                    }
                ],
                "action": f"STEP PLAN {artifact_id}",
            }
        step_reviews = review_reports(root, artifact_id)
        latest_review_verdict = step_reviews[-1]["verdict"] if step_reviews else None
        latest_completion_result = (
            step_reviews[-1].get("completionResult") if step_reviews else None
        )
        if meta.get("status") == "completed":
            completion_state = "completed"
        elif latest_review_verdict == "PASS" and latest_completion_result == "FAIL":
            completion_state = "review_pass_completion_fix_required"
        elif latest_review_verdict == "PASS" and latest_completion_result == "BLOCKED":
            completion_state = "review_pass_completion_blocked"
        elif latest_review_verdict == "PASS":
            completion_state = "review_pass_completion_pending"
        else:
            completion_state = "not_ready_for_completion"
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "STEP",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {
                "completionState": completion_state,
                "latestReviewVerdict": latest_review_verdict,
                "latestCompletionResult": latest_completion_result,
                "stepType": meta.get("type"),
                "priority": meta.get("priority"),
                "phase": meta.get("phase"),
                "riskFlags": _string_list(meta.get("risk_flags")),
                "planStatus": plan.get("status"),
                "planRevision": plan.get("revision"),
                "executionGroups": execution_groups,
                "planFreshness": plan_impact.get("status"),
                "planStaleCauses": plan_impact.get("causes", []),
                "planRemediation": plan_impact.get("action"),
            },
        }

    for item in oqs:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "OQ",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {
                "createdAt": meta.get("created_at"),
                "resolvedAt": meta.get("resolved_at"),
            },
        }

    for node in _skill_nodes(root):
        nodes[node["id"]] = node

    diagnostics: list[dict[str, Any]] = []
    diagnostic_keys: set[tuple[str, str, str, str]] = set()
    edge_map: dict[tuple[str, str, str], dict[str, Any]] = {}

    def resolve_id(
        artifact_id: str,
        *,
        declared_source: str,
        relation: str,
    ) -> str:
        if artifact_id in nodes:
            return artifact_id

        missing_id = f"MISSING:{artifact_id}"
        if missing_id not in nodes:
            expected_type = (
                artifact_id.split("-", 1)[0]
                if "-" in artifact_id
                else "UNKNOWN"
            )
            nodes[missing_id] = {
                "id": missing_id,
                "artifactId": artifact_id,
                "type": "MISSING",
                "title": artifact_id,
                "status": "missing",
                "path": None,
                "metadata": {"expectedType": expected_type},
            }

        key = ("MISSING_REFERENCE", declared_source, artifact_id, relation)
        if key not in diagnostic_keys:
            diagnostic_keys.add(key)
            diagnostics.append(
                {
                    "code": "MISSING_REFERENCE",
                    "source": declared_source,
                    "target": artifact_id,
                    "relation": relation,
                }
            )
        return missing_id

    def add_edge(
        source: str,
        target: str,
        relation: str,
        declared_by: str,
    ) -> None:
        actual_source = resolve_id(
            source,
            declared_source=declared_by,
            relation=relation,
        )
        actual_target = resolve_id(
            target,
            declared_source=declared_by,
            relation=relation,
        )
        key = (actual_source, actual_target, relation)
        edge = edge_map.get(key)
        if edge is None:
            edge = {
                "id": f"{relation}:{actual_source}:{actual_target}",
                "source": actual_source,
                "target": actual_target,
                "relation": relation,
                "declaredBy": [],
            }
            edge_map[key] = edge
        if declared_by not in edge["declaredBy"]:
            edge["declaredBy"].append(declared_by)
            edge["declaredBy"].sort()

    for item in requirements:
        meta = item["document"]["frontmatter"]
        req_id = meta["id"]
        for step_id in _string_list(meta.get("steps")):
            add_edge(req_id, step_id, "implemented_by", req_id)
        for adr_id in _string_list(meta.get("adrs")):
            add_edge(adr_id, req_id, "addresses", req_id)

    for item in adrs:
        meta = item["document"]["frontmatter"]
        adr_id = meta["id"]
        for req_id in _string_list(meta.get("requirements")):
            add_edge(adr_id, req_id, "addresses", adr_id)
        for step_id in _string_list(meta.get("steps")):
            add_edge(adr_id, step_id, "governs", adr_id)

    for item in steps:
        meta = item["document"]["frontmatter"]
        step_id = meta["id"]
        for dependency in _string_list(meta.get("depends_on")):
            add_edge(step_id, dependency, "depends_on", step_id)
        for req_id in _string_list(meta.get("requirements")):
            add_edge(req_id, step_id, "implemented_by", step_id)
        for adr_id in _string_list(meta.get("adrs")):
            add_edge(adr_id, step_id, "governs", step_id)

    for item in oqs:
        meta = item["document"]["frontmatter"]
        oq_id = meta["id"]
        for target in _string_list(meta.get("affects")):
            add_edge(oq_id, target, "affects", oq_id)

    invalid_review_count = 0
    reviews_root = review_directory(root)
    if reviews_root.is_dir():
        for step_id in sorted(steps_by_id):
            directory = reviews_root / step_id
            if not directory.is_dir():
                continue
            valid_by_path = {
                item["path"]: item
                for item in review_reports(root, step_id)
            }
            for path in sorted(directory.glob("REVIEW-*.md")):
                if path.is_symlink():
                    continue
                errors = validate_review_report(
                    root,
                    path,
                    expected_step_id=step_id,
                )
                if errors:
                    invalid_review_count += 1
                    diagnostics.append(
                        {
                            "code": "INVALID_REVIEW",
                            "path": _rel(root, path),
                            "errors": errors,
                        }
                    )
                    continue

                report = valid_by_path.get(path)
                if report is None:
                    continue
                doc = report["document"]
                meta = doc["frontmatter"]
                review_id = f"REVIEW:{step_id}:{path.stem}"
                nodes[review_id] = {
                    "id": review_id,
                    "artifactId": path.stem,
                    "type": "REVIEW",
                    "title": f"Review {step_id}",
                    "status": str(meta.get("verdict") or "unknown"),
                    "path": _rel(root, path),
                    "metadata": {
                        "stepId": step_id,
                        "createdAt": meta.get("created_at"),
                        "verificationStatus": meta.get("verification_status"),
                    },
                }
                add_edge(review_id, step_id, "reviews", review_id)

    edges = sorted(
        edge_map.values(),
        key=lambda item: (
            item["relation"],
            item["source"],
            item["target"],
        ),
    )
    node_list = sorted(
        nodes.values(),
        key=lambda item: (item["type"], item["id"]),
    )

    degree: Counter[str] = Counter()
    for edge in edges:
        if (
            not edge["source"].startswith("MISSING:")
            and not edge["target"].startswith("MISSING:")
        ):
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1

    core_nodes = [
        node
        for node in node_list
        if node["type"] in CORE_TYPES
    ]
    connected_core = [
        node
        for node in core_nodes
        if degree[node["id"]] > 0
    ]
    relationship_coverage = (
        round(100.0 * len(connected_core) / len(core_nodes), 1)
        if core_nodes
        else 100.0
    )

    dependency = _dependency_analysis(steps_by_id)
    blocked: list[dict[str, Any]] = []
    for step_id, item in sorted(steps_by_id.items()):
        if item["document"]["frontmatter"].get("status") == "blocked":
            downstream = dependency["downstreamImpact"].get(step_id, [])
            blocked.append(
                {
                    "nodeId": step_id,
                    "kind": "blocked_step",
                    "affects": downstream,
                    "impactCount": len(downstream),
                }
            )
    for item in oqs:
        meta = item["document"]["frontmatter"]
        if meta.get("status") == "open":
            affects = _string_list(meta.get("affects"))
            blocked.append(
                {
                    "nodeId": meta["id"],
                    "kind": "open_question",
                    "affects": affects,
                    "impactCount": len(affects),
                }
            )

    uncovered_requirements = sorted(
        node["id"]
        for node in core_nodes
        if node["type"] == "REQ"
        and not any(
            edge["source"] == node["id"]
            and edge["relation"] == "implemented_by"
            and not edge["target"].startswith("MISSING:")
            for edge in edges
        )
    )
    isolated = sorted(
        node["id"]
        for node in core_nodes
        if degree[node["id"]] == 0
    )

    missing_count = sum(
        1 for node in node_list if node["type"] == "MISSING"
    )
    review_count = sum(
        1 for node in node_list if node["type"] == "REVIEW"
    )
    skill_count = sum(
        1 for node in node_list if node["type"] == "SKILL"
    )
    by_type = Counter(node["type"] for node in core_nodes)
    by_status = Counter(str(node["status"]) for node in core_nodes)

    integrity = (
        "degraded"
        if diagnostics or dependency["cycles"]
        else "ok"
    )
    coverage = build_coverage(root)

    return {
        "schemaVersion": 1,
        "status": "PASS",
        "integrity": integrity,
        "project": {
            "name": project_name,
            "initialized": project.get("initialized") is True,
            "initializedAt": project.get("initializedAt"),
            "harnessVersion": harness.get("version"),
            "harnessRelease": harness.get("release"),
        },
        "summary": {
            "artifacts": len(core_nodes),
            "reviews": review_count,
            "skills": skill_count,
            "relationships": len(edges),
            "byType": dict(sorted(by_type.items())),
            "byStatus": dict(sorted(by_status.items())),
            "blockers": len(blocked),
            "missingReferences": missing_count,
            "invalidReviews": invalid_review_count,
            "relationshipCoveragePercent": relationship_coverage,
            "traceabilityCoverage": coverage["metrics"],
        },
        "graph": {
            "rootNodeId": "PROJECT",
            "nodes": node_list,
            "edges": edges,
        },
        "insights": {
            "blockers": blocked,
            "uncoveredRequirements": uncovered_requirements,
            "traceabilityCoverage": {
                "requirements": coverage["requirements"],
                "orphanSteps": coverage["orphanSteps"],
                "invalidReferences": coverage["invalidReferences"],
                "blockingOpenQuestions": coverage["blockingOpenQuestions"],
            },
            "isolatedArtifacts": isolated,
            "dependency": {
                "longestChain": dependency["longestChain"],
                "cycles": dependency["cycles"],
            },
        },
        "diagnostics": diagnostics,
        "sources": {
            "requirements": _rel(root, requirements_directory(root)),
            "adrs": _rel(root, adr_directory(root)),
            "steps": _rel(root, task_directory(root)),
            "openQuestions": _rel(root, open_questions_directory(root)),
            "reviews": _rel(root, review_directory(root)),
            "skills": ".agents/skills",
        },
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Построить deterministic machine-readable graph состояния Harness-проекта."
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = (args.root or repo_root()).resolve()

    try:
        result = build_project_state(root)
    except (OSError, UnicodeError, ValueError, ProjectStateError) as exc:
        blocked = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "error": str(exc),
        }
        if args.as_json:
            print(
                json.dumps(
                    blocked,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        else:
            print(f"PROJECT STATE: BLOCKED: {exc}")
        return 1

    if args.as_json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    else:
        summary = result["summary"]
        print(f"PROJECT STATE: PASS ({result['integrity']})")
        print(f"artifacts: {summary['artifacts']}")
        print(f"relationships: {summary['relationships']}")
        print(f"blockers: {summary['blockers']}")
        print(
            "relationshipCoveragePercent: "
            f"{summary['relationshipCoveragePercent']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
