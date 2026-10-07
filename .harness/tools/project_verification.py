#!/usr/bin/env python3
"""Project Verification Driver / feature-map contract.

Harness itself does not know how to click a browser, drive a CLI or exercise a
desktop application. That knowledge belongs to the project-owned verification
skill. This module owns only the deterministic boundary around that skill:

- fixed project-owned skill + machine-readable feature-map locations;
- supported product-surface taxonomy without a browser assumption;
- exact acceptance/source references and source-drift fingerprints;
- one-time driver qualification tied to the exact skill bytes;
- validation of real-product observations before STEP Verification can use them.

The module never edits product code and never executes project-specific drive
commands. Semantic agents follow the project-owned skill; deterministic code
checks whether the resulting proof is admissible.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from document_contract import atomic_write_text, parse_document, stable_hash
from planning_contract import (
    canonical_requirement_path,
    task_path,
)


SCHEMA_VERSION = 1
DRIVER_SKILL_PATH = ".agents/skills/verify-product/SKILL.md"
FEATURE_MAP_PATH = "docs/verification/feature-map.json"
LOCAL_PROOF_ROOT = ".harness/local/product-verification"
SURFACES = {"web", "cli", "api", "desktop", "mobile", "library", "service", "other"}
FEATURE_ID_RE = re.compile(r"FEATURE-[A-Z0-9][A-Z0-9._-]{1,63}$")
REQ_ID_RE = re.compile(r"REQ-\d{3,}$")
STEP_ID_RE = re.compile(r"STEP-\d{3,}$")
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}$")
REQUIRED_DRIVER_SECTIONS = ("Launch", "Doctor", "Drive", "Evidence", "Cleanup")
MAX_FEATURES = 200
MAX_SOURCE_PATHS = 64
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


class ProjectVerificationError(ValueError):
    """Project verification contract is missing, stale or malformed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _single_line(value: Any, label: str, *, max_chars: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectVerificationError(f"{label} must be a non-empty string")
    result = value.strip()
    if "\n" in result or "\r" in result:
        raise ProjectVerificationError(f"{label} must be a single line")
    if len(result) > max_chars:
        raise ProjectVerificationError(f"{label} exceeds {max_chars} chars")
    return result


def _string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
    max_items: int = 64,
) -> list[str]:
    if not isinstance(value, list):
        raise ProjectVerificationError(f"{label} must be an array")
    if not allow_empty and not value:
        raise ProjectVerificationError(f"{label} must not be empty")
    if len(value) > max_items:
        raise ProjectVerificationError(f"{label} exceeds {max_items} items")
    result = [
        _single_line(item, f"{label}[{index}]")
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise ProjectVerificationError(f"{label} must not contain duplicates")
    return result


def _repo_path(root: Path, value: str, *, label: str) -> Path:
    raw = _single_line(value, label)
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ProjectVerificationError(f"{label} escapes repository: {raw}") from exc
    return candidate


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _file_proof(root: Path, value: str, *, label: str) -> dict[str, Any]:
    path = _repo_path(root, value, label=label)
    if not path.is_file() or path.is_symlink():
        raise ProjectVerificationError(f"{label} must be a regular file: {value}")
    size = path.stat().st_size
    if size > MAX_EVIDENCE_BYTES:
        raise ProjectVerificationError(
            f"{label} exceeds {MAX_EVIDENCE_BYTES} bytes: {value}"
        )
    rel = path.relative_to(root.resolve()).as_posix()
    return {
        "path": rel,
        "sha256": _sha256_bytes(path.read_bytes()),
        "bytes": size,
    }


def _local_evidence(root: Path, value: str, *, label: str) -> dict[str, Any]:
    proof = _file_proof(root, value, label=label)
    prefix = LOCAL_PROOF_ROOT + "/"
    if not proof["path"].startswith(prefix):
        raise ProjectVerificationError(
            f"{label} must stay under {LOCAL_PROOF_ROOT}/"
        )
    return proof


def _driver_sections(text: str) -> dict[str, str]:
    lines = text.replace("\r\n", "\n").splitlines()
    indexes: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line.startswith("## "):
            indexes.append((index, line[3:].strip()))
    result: dict[str, str] = {}
    for offset, (index, name) in enumerate(indexes):
        end = indexes[offset + 1][0] if offset + 1 < len(indexes) else len(lines)
        result[name] = "\n".join(lines[index + 1 : end]).strip()
    return result


def driver_skill_state(root: Path) -> dict[str, Any]:
    path = _repo_path(root, DRIVER_SKILL_PATH, label="verification driver skill")
    if not path.is_file() or path.is_symlink():
        raise ProjectVerificationError(
            f"project verification driver missing: {DRIVER_SKILL_PATH}"
        )
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*verify-product\s*$", text)
    if match is None:
        raise ProjectVerificationError(
            "verification driver frontmatter must declare name: verify-product"
        )
    sections = _driver_sections(text)
    missing = [
        name
        for name in REQUIRED_DRIVER_SECTIONS
        if not sections.get(name)
    ]
    if missing:
        raise ProjectVerificationError(
            "verification driver sections missing/empty: " + ", ".join(missing)
        )
    if any(token in text for token in ("<TBD>", "{{TBD}}", "PLACEHOLDER")):
        raise ProjectVerificationError(
            "verification driver still contains placeholder content"
        )
    encoded = text.encode("utf-8")
    return {
        "path": DRIVER_SKILL_PATH,
        "sha256": _sha256_bytes(encoded),
        "bytes": len(encoded),
        "sections": list(REQUIRED_DRIVER_SECTIONS),
    }


def _criteria(path: Path, section: str) -> list[str]:
    document = parse_document(path)
    text = document["sections"].get(section)
    if not isinstance(text, str):
        raise ProjectVerificationError(
            f"{path}: required section '## {section}' is missing"
        )
    result: list[str] = []
    for raw in text.splitlines():
        match = re.match(r"^\s*[-*]\s+(.+?)\s*$", raw)
        if match and match.group(1).strip():
            result.append(match.group(1).strip())
    return result


def _validate_acceptance_ref(root: Path, value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"artifact", "criterion"}:
        raise ProjectVerificationError(
            f"{label} must contain exactly artifact, criterion"
        )
    artifact = _single_line(value.get("artifact"), f"{label}.artifact")
    criterion = _single_line(value.get("criterion"), f"{label}.criterion", max_chars=2000)
    if REQ_ID_RE.fullmatch(artifact):
        path = canonical_requirement_path(root, artifact)
        section = "Acceptance"
    elif STEP_ID_RE.fullmatch(artifact):
        path = task_path(root, artifact)
        section = "Acceptance criteria"
    else:
        raise ProjectVerificationError(
            f"{label}.artifact must be REQ-NNN or STEP-NNN"
        )
    if criterion not in _criteria(path, section):
        raise ProjectVerificationError(
            f"{label}.criterion is not an exact bullet in {artifact} {section}"
        )
    return {"artifact": artifact, "criterion": criterion}


def source_basis(root: Path, paths: list[str]) -> str:
    if not paths:
        raise ProjectVerificationError("feature sourcePaths must not be empty")
    if len(paths) > MAX_SOURCE_PATHS:
        raise ProjectVerificationError(
            f"feature sourcePaths exceeds {MAX_SOURCE_PATHS} files"
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, value in enumerate(paths):
        path = _repo_path(root, value, label=f"sourcePaths[{index}]")
        if not path.is_file() or path.is_symlink():
            raise ProjectVerificationError(
                f"sourcePaths[{index}] must be a regular file: {value}"
            )
        rel = path.relative_to(root.resolve()).as_posix()
        if rel in seen:
            raise ProjectVerificationError("sourcePaths must not contain duplicates")
        seen.add(rel)
        normalized.append(
            {"path": rel, "sha256": _sha256_bytes(path.read_bytes())}
        )
    return stable_hash(sorted(normalized, key=lambda item: item["path"]))


def _feature(root: Path, value: Any, index: int) -> dict[str, Any]:
    label = f"features[{index}]"
    if not isinstance(value, dict):
        raise ProjectVerificationError(f"{label} must be an object")
    allowed = {
        "id",
        "title",
        "surface",
        "requirements",
        "acceptance",
        "sourcePaths",
        "sourceBasis",
        "entryPoints",
        "drive",
        "observe",
    }
    unknown = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if unknown:
        raise ProjectVerificationError(
            f"{label} unsupported keys: " + ", ".join(unknown)
        )
    if missing:
        raise ProjectVerificationError(
            f"{label} missing keys: " + ", ".join(missing)
        )
    feature_id = _single_line(value.get("id"), f"{label}.id")
    if FEATURE_ID_RE.fullmatch(feature_id) is None:
        raise ProjectVerificationError(
            f"{label}.id must match FEATURE-<stable-id>"
        )
    surface = _single_line(value.get("surface"), f"{label}.surface")
    if surface not in SURFACES:
        raise ProjectVerificationError(
            f"{label}.surface must be one of {sorted(SURFACES)}"
        )

    requirements = _string_list(
        value.get("requirements"),
        f"{label}.requirements",
        allow_empty=True,
        max_items=32,
    )
    for req_id in requirements:
        if REQ_ID_RE.fullmatch(req_id) is None:
            raise ProjectVerificationError(
                f"{label}.requirements must contain REQ-NNN ids"
            )
        if not canonical_requirement_path(root, req_id).is_file():
            raise ProjectVerificationError(
                f"{label}: linked requirement does not exist: {req_id}"
            )

    raw_acceptance = value.get("acceptance")
    if not isinstance(raw_acceptance, list):
        raise ProjectVerificationError(f"{label}.acceptance must be an array")
    acceptance = [
        _validate_acceptance_ref(root, item, f"{label}.acceptance[{offset}]")
        for offset, item in enumerate(raw_acceptance)
    ]

    source_paths = _string_list(
        value.get("sourcePaths"),
        f"{label}.sourcePaths",
        max_items=MAX_SOURCE_PATHS,
    )
    actual_basis = source_basis(root, source_paths)
    stored_basis = _single_line(value.get("sourceBasis"), f"{label}.sourceBasis")
    if SHA256_RE.fullmatch(stored_basis) is None:
        raise ProjectVerificationError(f"{label}.sourceBasis must be sha256:...")
    stale = stored_basis != actual_basis

    return {
        "id": feature_id,
        "title": _single_line(value.get("title"), f"{label}.title"),
        "surface": surface,
        "requirements": requirements,
        "acceptance": acceptance,
        "sourcePaths": source_paths,
        "sourceBasis": stored_basis,
        "actualSourceBasis": actual_basis,
        "stale": stale,
        "entryPoints": _string_list(
            value.get("entryPoints"), f"{label}.entryPoints", max_items=32
        ),
        "drive": _string_list(value.get("drive"), f"{label}.drive", max_items=64),
        "observe": _string_list(value.get("observe"), f"{label}.observe", max_items=32),
    }


def _load_map(root: Path) -> dict[str, Any]:
    path = _repo_path(root, FEATURE_MAP_PATH, label="feature map")
    if not path.is_file() or path.is_symlink():
        raise ProjectVerificationError(
            f"project verification feature map missing: {FEATURE_MAP_PATH}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectVerificationError(f"cannot parse feature map: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectVerificationError("feature map must be a JSON object")
    if set(value) != {"schemaVersion", "driver", "features"}:
        raise ProjectVerificationError(
            "feature map keys must be schemaVersion, driver, features"
        )
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ProjectVerificationError(
            f"feature map schemaVersion must be {SCHEMA_VERSION}"
        )
    return value


def validate_feature_map(root: Path, *, require_qualified: bool = True) -> dict[str, Any]:
    raw = _load_map(root)
    driver_raw = raw.get("driver")
    if not isinstance(driver_raw, dict):
        raise ProjectVerificationError("feature map driver must be an object")
    if set(driver_raw) != {
        "skillPath",
        "primarySurface",
        "additionalSurfaces",
        "qualification",
    }:
        raise ProjectVerificationError(
            "feature map driver keys must be skillPath, primarySurface, "
            "additionalSurfaces, qualification"
        )
    if driver_raw.get("skillPath") != DRIVER_SKILL_PATH:
        raise ProjectVerificationError(
            f"feature map driver.skillPath must be {DRIVER_SKILL_PATH}"
        )
    primary = _single_line(driver_raw.get("primarySurface"), "driver.primarySurface")
    if primary not in SURFACES:
        raise ProjectVerificationError(
            f"driver.primarySurface must be one of {sorted(SURFACES)}"
        )
    additional = _string_list(
        driver_raw.get("additionalSurfaces"),
        "driver.additionalSurfaces",
        allow_empty=True,
        max_items=len(SURFACES),
    )
    declared_surfaces = {primary, *additional}
    if any(item not in SURFACES for item in declared_surfaces):
        raise ProjectVerificationError(
            f"driver surfaces must be one of {sorted(SURFACES)}"
        )

    driver_state = driver_skill_state(root)
    raw_features = raw.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise ProjectVerificationError("feature map features must be a non-empty array")
    if len(raw_features) > MAX_FEATURES:
        raise ProjectVerificationError(f"feature map exceeds {MAX_FEATURES} features")
    features = [
        _feature(root, value, index)
        for index, value in enumerate(raw_features)
    ]
    ids = [item["id"] for item in features]
    if len(ids) != len(set(ids)):
        raise ProjectVerificationError("feature ids must be unique")
    for item in features:
        if item["surface"] not in declared_surfaces:
            raise ProjectVerificationError(
                f"{item['id']}: surface {item['surface']} is not declared by driver"
            )

    stale_features = [item["id"] for item in features if item["stale"]]
    qualification = driver_raw.get("qualification")
    qualification_state = "UNQUALIFIED"
    qualification_value: dict[str, Any] | None = None
    if qualification is not None:
        if not isinstance(qualification, dict):
            raise ProjectVerificationError("driver.qualification must be null or object")
        expected = {
            "status",
            "skillSha256",
            "provenFeatureId",
            "observed",
            "evidence",
            "qualifiedAt",
        }
        if set(qualification) != expected:
            raise ProjectVerificationError(
                "driver.qualification has unsupported/missing keys"
            )
        if qualification.get("status") != "qualified":
            raise ProjectVerificationError(
                "driver.qualification.status must be qualified"
            )
        skill_hash = _single_line(
            qualification.get("skillSha256"),
            "driver.qualification.skillSha256",
        )
        if SHA256_RE.fullmatch(skill_hash) is None:
            raise ProjectVerificationError(
                "driver.qualification.skillSha256 must be sha256:..."
            )
        proven = _single_line(
            qualification.get("provenFeatureId"),
            "driver.qualification.provenFeatureId",
        )
        if proven not in ids:
            raise ProjectVerificationError(
                "driver qualification references unknown provenFeatureId"
            )
        evidence = qualification.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ProjectVerificationError(
                "driver.qualification.evidence must be non-empty"
            )
        for index, item in enumerate(evidence):
            if (
                not isinstance(item, dict)
                or set(item) != {"sha256", "bytes"}
                or SHA256_RE.fullmatch(str(item.get("sha256") or "")) is None
                or isinstance(item.get("bytes"), bool)
                or not isinstance(item.get("bytes"), int)
                or item["bytes"] < 0
            ):
                raise ProjectVerificationError(
                    f"driver.qualification.evidence[{index}] is malformed"
                )
        qualification_value = {
            "status": "qualified",
            "skillSha256": skill_hash,
            "provenFeatureId": proven,
            "observed": _single_line(
                qualification.get("observed"),
                "driver.qualification.observed",
                max_chars=4000,
            ),
            "evidence": evidence,
            "qualifiedAt": _single_line(
                qualification.get("qualifiedAt"),
                "driver.qualification.qualifiedAt",
            ),
        }
        qualification_state = (
            "QUALIFIED"
            if skill_hash == driver_state["sha256"]
            else "STALE_DRIVER"
        )

    if require_qualified and qualification_state != "QUALIFIED":
        raise ProjectVerificationError(
            "verification driver is not qualified for its current bytes: "
            + qualification_state
        )
    if stale_features:
        raise ProjectVerificationError(
            "verification feature map is stale for source changes: "
            + ", ".join(stale_features)
        )

    map_basis = stable_hash(
        {
            "schemaVersion": SCHEMA_VERSION,
            "driver": {
                "skillPath": DRIVER_SKILL_PATH,
                "primarySurface": primary,
                "additionalSurfaces": additional,
                "skillSha256": driver_state["sha256"],
            },
            "features": [
                {
                    key: item[key]
                    for key in (
                        "id",
                        "title",
                        "surface",
                        "requirements",
                        "acceptance",
                        "sourcePaths",
                        "sourceBasis",
                        "entryPoints",
                        "drive",
                        "observe",
                    )
                }
                for item in features
            ],
        }
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS" if qualification_state == "QUALIFIED" and not stale_features else "BLOCKED",
        "driver": {
            **driver_state,
            "primarySurface": primary,
            "additionalSurfaces": additional,
            "qualificationState": qualification_state,
            "qualification": qualification_value,
        },
        "featureMapPath": FEATURE_MAP_PATH,
        "featureMapBasis": map_basis,
        "features": features,
        "staleFeatures": stale_features,
    }


def feature_source_basis(root: Path, feature_id: str) -> dict[str, Any]:
    value = validate_feature_map(root, require_qualified=False)
    for feature in value["features"]:
        if feature["id"] == feature_id:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "status": "PASS",
                "featureId": feature_id,
                "sourcePaths": feature["sourcePaths"],
                "sourceBasis": feature["actualSourceBasis"],
                "storedSourceBasis": feature["sourceBasis"],
                "stale": feature["stale"],
            }
    raise ProjectVerificationError(f"unknown verification feature: {feature_id}")


def qualify_driver(root: Path, payload: Any) -> dict[str, Any]:
    """Stamp current driver bytes only after a concrete live proof existed."""
    current = validate_feature_map(root, require_qualified=False)
    if current["staleFeatures"]:
        raise ProjectVerificationError(
            "cannot qualify driver while feature map is stale: "
            + ", ".join(current["staleFeatures"])
        )
    if not isinstance(payload, dict) or set(payload) != {
        "featureId",
        "observed",
        "evidencePaths",
    }:
        raise ProjectVerificationError(
            "qualification payload keys must be featureId, observed, evidencePaths"
        )
    feature_id = _single_line(payload.get("featureId"), "featureId")
    feature_ids = {item["id"] for item in current["features"]}
    if feature_id not in feature_ids:
        raise ProjectVerificationError(f"qualification feature does not exist: {feature_id}")
    observed = _single_line(payload.get("observed"), "observed", max_chars=4000)
    evidence_paths = _string_list(
        payload.get("evidencePaths"),
        "evidencePaths",
        max_items=16,
    )
    proofs = [
        _local_evidence(root, path, label=f"evidencePaths[{index}]")
        for index, path in enumerate(evidence_paths)
    ]

    raw = _load_map(root)
    raw["driver"]["qualification"] = {
        "status": "qualified",
        "skillSha256": current["driver"]["sha256"],
        "provenFeatureId": feature_id,
        "observed": observed,
        "evidence": [
            {"sha256": item["sha256"], "bytes": item["bytes"]}
            for item in proofs
        ],
        "qualifiedAt": _utc_now(),
    }
    path = root / FEATURE_MAP_PATH
    atomic_write_text(
        path,
        json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    refreshed = validate_feature_map(root, require_qualified=True)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "featureId": feature_id,
        "driverSkillSha256": refreshed["driver"]["sha256"],
        "featureMapBasis": refreshed["featureMapBasis"],
        "evidence": proofs,
    }


def validate_product_observations(
    root: Path,
    expected_feature_ids: list[str],
    supplied: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate observations for exact product entries in STEP Verification."""
    if not expected_feature_ids:
        return [], []
    if len(expected_feature_ids) != len(set(expected_feature_ids)):
        raise ProjectVerificationError(
            "STEP Verification product entries must not contain duplicates"
        )
    current = validate_feature_map(root, require_qualified=True)
    by_id = {item["id"]: item for item in current["features"]}
    missing = [item for item in expected_feature_ids if item not in by_id]
    if missing:
        raise ProjectVerificationError(
            "STEP Verification references unknown product features: "
            + ", ".join(missing)
        )
    if supplied is None:
        return [], list(expected_feature_ids)
    if not isinstance(supplied, list):
        raise ProjectVerificationError("productVerification must be an array")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(supplied):
        if not isinstance(raw, dict) or set(raw) != {
            "featureId",
            "status",
            "observed",
            "evidencePaths",
        }:
            raise ProjectVerificationError(
                f"productVerification[{index}] keys must be "
                "featureId, status, observed, evidencePaths"
            )
        feature_id = _single_line(
            raw.get("featureId"),
            f"productVerification[{index}].featureId",
        )
        if feature_id not in expected_feature_ids:
            raise ProjectVerificationError(
                f"unexpected product verification feature: {feature_id}"
            )
        if feature_id in seen:
            raise ProjectVerificationError(
                f"duplicate product verification feature: {feature_id}"
            )
        seen.add(feature_id)
        status = _single_line(
            raw.get("status"),
            f"productVerification[{index}].status",
        )
        if status not in {"PASS", "FAIL"}:
            raise ProjectVerificationError(
                f"productVerification[{index}].status must be PASS or FAIL"
            )
        observed = _single_line(
            raw.get("observed"),
            f"productVerification[{index}].observed",
            max_chars=4000,
        )
        evidence_paths = _string_list(
            raw.get("evidencePaths"),
            f"productVerification[{index}].evidencePaths",
            allow_empty=status == "FAIL",
            max_items=16,
        )
        proofs = [
            _local_evidence(
                root,
                path,
                label=f"productVerification[{index}].evidencePaths[{offset}]",
            )
            for offset, path in enumerate(evidence_paths)
        ]
        feature = by_id[feature_id]
        result.append(
            {
                "featureId": feature_id,
                "status": status,
                "observed": observed,
                "surface": feature["surface"],
                "sourceBasis": feature["sourceBasis"],
                "driverSkillSha256": current["driver"]["sha256"],
                "featureMapBasis": current["featureMapBasis"],
                "evidence": proofs,
            }
        )

    pending = [item for item in expected_feature_ids if item not in seen]
    return result, pending


def _payload(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    value = Path(path)
    return json.loads(value.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate/qualify the project-owned real-product verification driver."
    )
    sub = parser.add_subparsers(dest="operation", required=True)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true", dest="as_json")

    basis = sub.add_parser("basis")
    basis.add_argument("--feature", required=True)
    basis.add_argument("--json", action="store_true", dest="as_json")

    qualify = sub.add_parser("qualify")
    qualify.add_argument("--payload-file", required=True)
    qualify.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    try:
        if args.operation == "status":
            result = validate_feature_map(root, require_qualified=True)
        elif args.operation == "basis":
            result = feature_source_basis(root, args.feature)
        else:
            result = qualify_driver(root, _payload(args.payload_file))
    except (ProjectVerificationError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reason": str(exc),
        }

    output = (
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if getattr(args, "as_json", False)
        else json.dumps(result, ensure_ascii=False)
    )
    print(output)
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DRIVER_SKILL_PATH",
    "FEATURE_MAP_PATH",
    "LOCAL_PROOF_ROOT",
    "ProjectVerificationError",
    "driver_skill_state",
    "feature_source_basis",
    "qualify_driver",
    "source_basis",
    "validate_feature_map",
    "validate_product_observations",
]
