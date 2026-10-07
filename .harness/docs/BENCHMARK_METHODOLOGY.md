# Benchmark Methodology

`benchmark-methodology` is an optional internal capability for performance-sensitive STEP work.

Its rule is simple:

> A performance claim is not evidence because a model says it looks faster. The measurement must be reproducible, comparable, correct and larger than its own observed noise.

## When it applies

Use it only for:

- measurable performance Acceptance criteria;
- explicit performance optimization work;
- confirmed performance review findings;
- an explicit benchmark request.

Normal STEP do not pay this context/runtime cost.

## Boundary

```text
semantic benchmark design
        ↓
real benchmark execution
        ↓
raw evidence JSON + proof files
        ↓
benchmark-methodology.py
        ↓
PASS | INCONCLUSIVE | BLOCKED
        ↓
ordinary Verification / Review / Completion
```

The deterministic gate does not run the benchmark for the agent. It validates evidence that the benchmark run produced.

## Evidence contract

Schema version 1:

```json
{
  "schemaVersion": 1,
  "claim": {
    "summary": "Candidate increases throughput by at least 10%.",
    "metric": "throughput",
    "unit": "req/s",
    "direction": "higher-is-better",
    "scope": "end-to-end",
    "minimumEffectPct": 10
  },
  "baseline": {
    "revision": "<exact-revision>",
    "command": ["./bench", "--requests", "10000"],
    "environment": {"CPU": "...", "MODE": "release"},
    "samples": [100.0, 101.0, 99.0],
    "correctness": {"passed": 10000, "failed": 0},
    "workProof": {
      "kind": "counter",
      "path": ".harness/local/benchmark/run/base.txt",
      "summary": "processed=10000"
    }
  },
  "candidate": {
    "revision": "<exact-revision>",
    "command": ["./bench", "--requests", "10000"],
    "environment": {"CPU": "...", "MODE": "release"},
    "samples": [120.0, 121.0, 119.0],
    "correctness": {"passed": 10000, "failed": 0},
    "workProof": {
      "kind": "counter",
      "path": ".harness/local/benchmark/run/candidate.txt",
      "summary": "processed=10000"
    }
  },
  "comparison": {
    "interleaved": true,
    "rationale": "Alternated baseline/candidate runs."
  },
  "bottleneck": {
    "identified": true,
    "summary": "Parser CPU path is the measured limiter."
  },
  "sanityLimit": {
    "checked": true,
    "summary": "Result remains below the known hardware/work ceiling."
  },
  "endToEnd": {
    "checked": true,
    "relevant": true,
    "summary": "Benchmark exercises the production request path."
  }
}
```

Unknown keys fail closed.

`workProof.kind` is one of:

```text
counter
output
trace
artifact
profile
```

The path must remain inside the repository root, exist as a regular non-symlink file, and is hashed by the validator.

## Statistics

For each arm the tool computes:

- `runs`;
- `median`;
- `min`;
- `max`;
- `range`;
- `variationPct = (max - min) / abs(median) * 100`.

Direction-normalized effect:

```text
higher-is-better:
  effectPct = (candidateMedian - baselineMedian) / abs(baselineMedian) * 100

lower-is-better:
  effectPct = (baselineMedian - candidateMedian) / abs(baselineMedian) * 100
```

The conservative observed noise band is the larger `variationPct` of baseline and candidate.

## PASS

PASS requires all of the following:

- exact same command;
- exact same recorded environment;
- zero correctness failures;
- at least 3 samples for both arms;
- existing work-proof files;
- identified bottleneck;
- sanity-limit check;
- end-to-end relevance check;
- for an `end-to-end` claim, relevance must be true;
- effect must be strictly larger than observed variation;
- effect must meet `minimumEffectPct` when supplied.

A non-interleaved comparison may still PASS, but returns `NON_INTERLEAVED_RUNS`; the caller must explain why that design is acceptable.

## INCONCLUSIVE

`INCONCLUSIVE` is the correct result for valid but insufficient evidence.

Reason codes include:

```text
INSUFFICIENT_REPEATED_RUNS
EFFECT_WITHIN_OBSERVED_VARIATION
MINIMUM_EFFECT_NOT_MET
COMMAND_MISMATCH
ENVIRONMENT_MISMATCH
CORRECTNESS_FAILURE
BOTTLENECK_NOT_IDENTIFIED
SANITY_LIMIT_NOT_CHECKED
END_TO_END_RELEVANCE_NOT_CHECKED
END_TO_END_CLAIM_NOT_RELEVANT
ZERO_BASELINE_MEDIAN
```

One/two-run evidence additionally reports `BALLPARK_ONLY`.

The caller must not turn INCONCLUSIVE into a PASS performance claim by narrative reasoning.

## Microbenchmark scope

A microbenchmark is allowed to prove only a narrow microbenchmark claim.

`endToEnd.checked` is still required. When checked but not relevant, a valid narrow result can PASS with:

```text
claimRestriction = microbenchmark-only
warning = MICROBENCHMARK_ONLY
```

That result cannot be cited as end-to-end product speedup/regression evidence.

## Revisions and environment

Both arms carry exact revision identifiers because a comparison often measures different commits.

Environment is an explicit non-empty string map. Put only measurement-relevant facts there, but make them specific enough to reproduce the comparison: runtime/build mode, CPU/GPU class, concurrency, dataset or other material knobs.

## Relationship to Harness gates

Benchmark PASS is a quantitative evidence component, not final authority.

It does not replace:

- STEP contract;
- Verification;
- product verification driver;
- Completion Gate;
- Review Contract;
- security/test specialized reviewers.

If Acceptance says “latency improves by >= 10%”, a benchmark `INCONCLUSIVE` means Acceptance is not yet proven.

If REVIEW is evaluating a suspected regression, the benchmark result is evidence for or against the quantitative hypothesis; it does not bypass the ordinary Evidence Gate or finding contract.
