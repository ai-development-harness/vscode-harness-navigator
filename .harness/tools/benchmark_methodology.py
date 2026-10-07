#!/usr/bin/env python3
"""Deterministic evidence sufficiency checks for performance claims.

The model may design a benchmark and interpret why a result matters, but it may
not promote a weak measurement to PASS. This module validates a closed evidence
schema, computes medians/ranges/effect size, and returns PASS only when the
claim is supported beyond the observed variation of the collected runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


SCHEMA_VERSION = 1
DIRECTIONS = {"higher-is-better", "lower-is-better"}
SCOPES = {"microbenchmark", "end-to-end"}
PROOF_KINDS = {"counter", "output", "trace", "artifact", "profile"}
MIN_REPEATED_RUNS = 3
MAX_RUNS = 200


class BenchmarkMethodologyError(ValueError):
    """Benchmark evidence is malformed or cannot be compared safely."""


def _text(value: Any, label: str, *, max_chars: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkMethodologyError(f"{label} must be a non-empty string")
    result = value.strip()
    if len(result) > max_chars:
        raise BenchmarkMethodologyError(f"{label} exceeds {max_chars} chars")
    return result


def _single(value: Any, label: str, *, max_chars: int = 1000) -> str:
    result = _text(value, label, max_chars=max_chars)
    if "\n" in result or "\r" in result:
        raise BenchmarkMethodologyError(f"{label} must be one line")
    return result


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkMethodologyError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("unsupported=" + ",".join(extra))
        raise BenchmarkMethodologyError(f"{label} keys mismatch ({'; '.join(details)})")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkMethodologyError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BenchmarkMethodologyError(f"{label} must be finite")
    return result


def _samples(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or not value or len(value) > MAX_RUNS:
        raise BenchmarkMethodologyError(
            f"{label} must contain 1..{MAX_RUNS} numeric samples"
        )
    return [_finite_number(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _command(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 128:
        raise BenchmarkMethodologyError(f"{label} must be a non-empty argv array")
    return [_single(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _environment(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not value or len(value) > 128:
        raise BenchmarkMethodologyError(f"{label} must be a non-empty object with <= 128 entries")
    result: dict[str, str] = {}
    for key, item in value.items():
        clean_key = _single(key, f"{label}.key")
        clean_value = _single(item, f"{label}.{clean_key}", max_chars=2000)
        result[clean_key] = clean_value
    return dict(sorted(result.items()))


def _correctness(value: Any, label: str) -> dict[str, int]:
    data = _exact_keys(value, {"passed", "failed"}, label)
    result: dict[str, int] = {}
    for key in ("passed", "failed"):
        item = data[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise BenchmarkMethodologyError(f"{label}.{key} must be a non-negative integer")
        result[key] = item
    if result["passed"] + result["failed"] == 0:
        raise BenchmarkMethodologyError(f"{label} must record at least one correctness observation")
    return result


def _proof_path(root: Path, value: Any, label: str) -> tuple[str, str, int]:
    raw = Path(_single(value, label, max_chars=2000))
    if raw.is_absolute() or ".." in raw.parts:
        raise BenchmarkMethodologyError(f"{label} must be repository-relative")
    base = root.resolve()
    candidate = (root / raw).resolve()
    try:
        rel = candidate.relative_to(base).as_posix()
    except ValueError as exc:
        raise BenchmarkMethodologyError(f"{label} escapes repository") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise BenchmarkMethodologyError(f"{label} must point to an existing regular file: {rel}")
    data = candidate.read_bytes()
    return rel, "sha256:" + hashlib.sha256(data).hexdigest(), len(data)


def _work_proof(root: Path, value: Any, label: str) -> dict[str, Any]:
    data = _exact_keys(value, {"kind", "path", "summary"}, label)
    kind = data["kind"]
    if kind not in PROOF_KINDS:
        raise BenchmarkMethodologyError(
            f"{label}.kind must be one of {sorted(PROOF_KINDS)}"
        )
    path, digest, size = _proof_path(root, data["path"], f"{label}.path")
    return {
        "kind": str(kind),
        "path": path,
        "sha256": digest,
        "bytes": size,
        "summary": _single(data["summary"], f"{label}.summary", max_chars=4000),
    }


def _arm(root: Path, value: Any, label: str) -> dict[str, Any]:
    data = _exact_keys(
        value,
        {"revision", "command", "environment", "samples", "correctness", "workProof"},
        label,
    )
    return {
        "revision": _single(data["revision"], f"{label}.revision", max_chars=200),
        "command": _command(data["command"], f"{label}.command"),
        "environment": _environment(data["environment"], f"{label}.environment"),
        "samples": _samples(data["samples"], f"{label}.samples"),
        "correctness": _correctness(data["correctness"], f"{label}.correctness"),
        "workProof": _work_proof(root, data["workProof"], f"{label}.workProof"),
    }


def _stats(samples: list[float]) -> dict[str, float | int]:
    median = float(statistics.median(samples))
    low = min(samples)
    high = max(samples)
    if median == 0:
        variation_pct = math.inf if high != low else 0.0
    else:
        variation_pct = abs(high - low) / abs(median) * 100.0
    return {
        "runs": len(samples),
        "median": median,
        "min": low,
        "max": high,
        "range": high - low,
        "variationPct": variation_pct,
    }


def evaluate(value: Any, root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    root_data = _exact_keys(
        value,
        {
            "schemaVersion",
            "claim",
            "baseline",
            "candidate",
            "comparison",
            "bottleneck",
            "sanityLimit",
            "endToEnd",
        },
        "evidence",
    )
    if root_data["schemaVersion"] != SCHEMA_VERSION:
        raise BenchmarkMethodologyError(f"schemaVersion must be {SCHEMA_VERSION}")

    claim_raw = _exact_keys(
        root_data["claim"],
        {"summary", "metric", "unit", "direction", "scope", "minimumEffectPct"},
        "claim",
    )
    direction = claim_raw["direction"]
    if direction not in DIRECTIONS:
        raise BenchmarkMethodologyError(f"claim.direction must be one of {sorted(DIRECTIONS)}")
    scope = claim_raw["scope"]
    if scope not in SCOPES:
        raise BenchmarkMethodologyError(f"claim.scope must be one of {sorted(SCOPES)}")
    minimum_effect = claim_raw["minimumEffectPct"]
    if minimum_effect is not None:
        minimum_effect = _finite_number(minimum_effect, "claim.minimumEffectPct")
        if minimum_effect < 0:
            raise BenchmarkMethodologyError("claim.minimumEffectPct must be >= 0")
    claim = {
        "summary": _single(claim_raw["summary"], "claim.summary", max_chars=4000),
        "metric": _single(claim_raw["metric"], "claim.metric"),
        "unit": _single(claim_raw["unit"], "claim.unit"),
        "direction": str(direction),
        "scope": str(scope),
        "minimumEffectPct": minimum_effect,
    }

    baseline = _arm(root, root_data["baseline"], "baseline")
    candidate = _arm(root, root_data["candidate"], "candidate")

    comparison_raw = _exact_keys(
        root_data["comparison"],
        {"interleaved", "rationale"},
        "comparison",
    )
    if not isinstance(comparison_raw["interleaved"], bool):
        raise BenchmarkMethodologyError("comparison.interleaved must be boolean")
    comparison = {
        "interleaved": comparison_raw["interleaved"],
        "rationale": _single(comparison_raw["rationale"], "comparison.rationale", max_chars=4000),
    }

    bottleneck_raw = _exact_keys(root_data["bottleneck"], {"identified", "summary"}, "bottleneck")
    if not isinstance(bottleneck_raw["identified"], bool):
        raise BenchmarkMethodologyError("bottleneck.identified must be boolean")
    bottleneck = {
        "identified": bottleneck_raw["identified"],
        "summary": _single(bottleneck_raw["summary"], "bottleneck.summary", max_chars=4000),
    }

    sanity_raw = _exact_keys(root_data["sanityLimit"], {"checked", "summary"}, "sanityLimit")
    if not isinstance(sanity_raw["checked"], bool):
        raise BenchmarkMethodologyError("sanityLimit.checked must be boolean")
    sanity = {
        "checked": sanity_raw["checked"],
        "summary": _single(sanity_raw["summary"], "sanityLimit.summary", max_chars=4000),
    }

    e2e_raw = _exact_keys(root_data["endToEnd"], {"checked", "relevant", "summary"}, "endToEnd")
    if not isinstance(e2e_raw["checked"], bool) or not isinstance(e2e_raw["relevant"], bool):
        raise BenchmarkMethodologyError("endToEnd.checked/relevant must be boolean")
    e2e = {
        "checked": e2e_raw["checked"],
        "relevant": e2e_raw["relevant"],
        "summary": _single(e2e_raw["summary"], "endToEnd.summary", max_chars=4000),
    }

    bstats = _stats(baseline["samples"])
    cstats = _stats(candidate["samples"])
    bmed = float(bstats["median"])
    cmed = float(cstats["median"])

    reasons: list[str] = []
    warnings: list[str] = []

    if baseline["command"] != candidate["command"]:
        reasons.append("COMMAND_MISMATCH")
    if baseline["environment"] != candidate["environment"]:
        reasons.append("ENVIRONMENT_MISMATCH")
    if baseline["correctness"]["failed"] or candidate["correctness"]["failed"]:
        reasons.append("CORRECTNESS_FAILURE")
    if int(bstats["runs"]) < MIN_REPEATED_RUNS or int(cstats["runs"]) < MIN_REPEATED_RUNS:
        reasons.append("INSUFFICIENT_REPEATED_RUNS")
        warnings.append("BALLPARK_ONLY")
    if not comparison["interleaved"]:
        warnings.append("NON_INTERLEAVED_RUNS")
    if not bottleneck["identified"]:
        reasons.append("BOTTLENECK_NOT_IDENTIFIED")
    if not sanity["checked"]:
        reasons.append("SANITY_LIMIT_NOT_CHECKED")
    if not e2e["checked"]:
        reasons.append("END_TO_END_RELEVANCE_NOT_CHECKED")
    if scope == "end-to-end" and not e2e["relevant"]:
        reasons.append("END_TO_END_CLAIM_NOT_RELEVANT")
    if scope == "microbenchmark" and not e2e["relevant"]:
        warnings.append("MICROBENCHMARK_ONLY")

    effect_pct: float | None
    if bmed == 0:
        effect_pct = None
        reasons.append("ZERO_BASELINE_MEDIAN")
    else:
        raw_delta = (cmed - bmed) / abs(bmed) * 100.0
        effect_pct = raw_delta if direction == "higher-is-better" else -raw_delta
        noise_band = max(float(bstats["variationPct"]), float(cstats["variationPct"]))
        if not math.isfinite(noise_band) or effect_pct <= noise_band:
            reasons.append("EFFECT_WITHIN_OBSERVED_VARIATION")
        if minimum_effect is not None and effect_pct < minimum_effect:
            reasons.append("MINIMUM_EFFECT_NOT_MET")

    status = "PASS" if not reasons else "INCONCLUSIVE"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "reasonCodes": sorted(set(reasons)),
        "warnings": sorted(set(warnings)),
        "claim": claim,
        "baseline": {
            "revision": baseline["revision"],
            "stats": bstats,
            "correctness": baseline["correctness"],
            "workProof": baseline["workProof"],
        },
        "candidate": {
            "revision": candidate["revision"],
            "stats": cstats,
            "correctness": candidate["correctness"],
            "workProof": candidate["workProof"],
        },
        "comparison": {
            "sameCommand": baseline["command"] == candidate["command"],
            "sameEnvironment": baseline["environment"] == candidate["environment"],
            "interleaved": comparison["interleaved"],
            "rationale": comparison["rationale"],
            "effectPct": effect_pct,
            "observedVariationPct": max(
                float(bstats["variationPct"]), float(cstats["variationPct"])
            ),
        },
        "bottleneck": bottleneck,
        "sanityLimit": sanity,
        "endToEnd": e2e,
        "claimRestriction": (
            "microbenchmark-only"
            if scope == "microbenchmark" and not e2e["relevant"]
            else None
        ),
        "deterministicGate": True,
    }


def _read_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate benchmark evidence before accepting performance claims."
    )
    parser.add_argument("--evidence-file", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        result = evaluate(_read_json(args.evidence_file), Path.cwd())
    except (OSError, UnicodeError, json.JSONDecodeError, BenchmarkMethodologyError, ValueError) as exc:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCodes": ["INVALID_BENCHMARK_EVIDENCE"],
            "message": str(exc),
            "deterministicGate": True,
        }
    print(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.as_json
        else json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    )
    return 0 if result.get("status") in {"PASS", "INCONCLUSIVE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BenchmarkMethodologyError", "evaluate"]
