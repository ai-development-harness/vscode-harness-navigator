#!/usr/bin/env python3
"""Synthetic regressions for optional benchmark methodology (#228)."""
from __future__ import annotations

from pathlib import Path
import tempfile

from benchmark_methodology import BenchmarkMethodologyError, evaluate


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def evidence() -> dict:
    common = {
        "command": ["python3", "bench.py", "--requests", "10000"],
        "environment": {"CPU": "fixture-cpu", "MODE": "release"},
        "correctness": {"passed": 10000, "failed": 0},
    }
    return {
        "schemaVersion": 1,
        "claim": {
            "summary": "Candidate increases throughput by at least 10%.",
            "metric": "throughput",
            "unit": "req/s",
            "direction": "higher-is-better",
            "scope": "end-to-end",
            "minimumEffectPct": 10,
        },
        "baseline": {
            "revision": "base123",
            "samples": [100.0, 101.0, 99.0],
            "workProof": {
                "kind": "counter",
                "path": ".harness/local/bench/baseline.txt",
                "summary": "processed=10000 in benchmark output",
            },
            **common,
        },
        "candidate": {
            "revision": "cand456",
            "samples": [120.0, 121.0, 119.0],
            "workProof": {
                "kind": "counter",
                "path": ".harness/local/bench/candidate.txt",
                "summary": "processed=10000 in benchmark output",
            },
            **common,
        },
        "comparison": {"interleaved": True, "rationale": "Alternated baseline/candidate runs."},
        "bottleneck": {"identified": True, "summary": "CPU parser path is the measured limiter."},
        "sanityLimit": {"checked": True, "summary": "Observed values remain below fixture hardware ceiling."},
        "endToEnd": {"checked": True, "relevant": True, "summary": "Same end-to-end request path used in production."},
    }


def expect_invalid(root: Path, payload: dict) -> None:
    try:
        evaluate(payload, root)
    except BenchmarkMethodologyError:
        return
    raise AssertionError("malformed benchmark evidence must be rejected")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="benchmark-methodology-") as tmp:
        root = Path(tmp)
        write(root, ".harness/local/bench/baseline.txt", "processed=10000 throughput=100\n")
        write(root, ".harness/local/bench/candidate.txt", "processed=10000 throughput=120\n")

        good = evaluate(evidence(), root)
        assert good["status"] == "PASS", good
        assert good["comparison"]["effectPct"] > 10
        assert good["baseline"]["stats"]["runs"] == 3
        assert good["baseline"]["workProof"]["sha256"].startswith("sha256:")

        one_run = evidence()
        one_run["baseline"]["samples"] = [100.0]
        one_run["candidate"]["samples"] = [120.0]
        result = evaluate(one_run, root)
        assert result["status"] == "INCONCLUSIVE"
        assert "INSUFFICIENT_REPEATED_RUNS" in result["reasonCodes"]
        assert "BALLPARK_ONLY" in result["warnings"]

        noisy = evidence()
        noisy["baseline"]["samples"] = [80.0, 100.0, 120.0]
        noisy["candidate"]["samples"] = [90.0, 112.0, 134.0]
        result = evaluate(noisy, root)
        assert result["status"] == "INCONCLUSIVE"
        assert "EFFECT_WITHIN_OBSERVED_VARIATION" in result["reasonCodes"]

        mismatch = evidence()
        mismatch["candidate"]["environment"] = {"CPU": "other", "MODE": "release"}
        result = evaluate(mismatch, root)
        assert result["status"] == "INCONCLUSIVE"
        assert "ENVIRONMENT_MISMATCH" in result["reasonCodes"]

        bad_correctness = evidence()
        bad_correctness["candidate"]["correctness"] = {"passed": 9999, "failed": 1}
        result = evaluate(bad_correctness, root)
        assert result["status"] == "INCONCLUSIVE"
        assert "CORRECTNESS_FAILURE" in result["reasonCodes"]

        micro = evidence()
        micro["claim"]["scope"] = "microbenchmark"
        micro["endToEnd"]["relevant"] = False
        micro["endToEnd"]["summary"] = "Microbenchmark isolates parser; no end-to-end claim is made."
        result = evaluate(micro, root)
        assert result["status"] == "PASS", result
        assert result["claimRestriction"] == "microbenchmark-only"
        assert "MICROBENCHMARK_ONLY" in result["warnings"]

        non_interleaved = evidence()
        non_interleaved["comparison"] = {
            "interleaved": False,
            "rationale": "Dedicated isolated host; all baseline runs then candidate runs.",
        }
        result = evaluate(non_interleaved, root)
        assert result["status"] == "PASS", result
        assert "NON_INTERLEAVED_RUNS" in result["warnings"]

        lower = evidence()
        lower["claim"]["summary"] = "Candidate reduces latency by at least 10%."
        lower["claim"]["metric"] = "latency"
        lower["claim"]["unit"] = "ms"
        lower["claim"]["direction"] = "lower-is-better"
        lower["baseline"]["samples"] = [100.0, 101.0, 99.0]
        lower["candidate"]["samples"] = [80.0, 81.0, 79.0]
        result = evaluate(lower, root)
        assert result["status"] == "PASS", result
        assert result["comparison"]["effectPct"] > 10

        missing_proof = evidence()
        missing_proof["candidate"]["workProof"]["path"] = ".harness/local/bench/missing.txt"
        expect_invalid(root, missing_proof)

        malformed = evidence()
        malformed["claim"]["unknown"] = True
        expect_invalid(root, malformed)

    print("benchmark methodology self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
