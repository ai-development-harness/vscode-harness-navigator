---
name: benchmark-methodology
description: Design and validate optional performance evidence so weak or noisy measurements cannot become PASS claims.
---
# benchmark-methodology

Internal optional capability for STEP work with a measurable performance Acceptance criterion or a material performance review finding. It is **not** a public Harness command and must not run on ordinary work.

The semantic part chooses the benchmark design and interprets what the metric means. The deterministic tool decides whether the collected evidence is strong enough to support the stated claim.

## Activation

Use this capability only when at least one of these is true:

- STEP Acceptance contains an explicit measurable performance claim;
- PLAN introduces a performance claim that must become Verification evidence;
- REVIEW has a confirmed performance finding;
- the user explicitly asks for a benchmark/performance comparison.

Do not add benchmark overhead to unrelated STEP.

## 1. State the claim before measuring

Write one narrow claim before running the benchmark:

- metric and unit;
- `higher-is-better` or `lower-is-better`;
- scope: `microbenchmark` or `end-to-end`;
- optional minimum material effect in percent;
- what correctness must remain true.

Do not inspect a result first and then choose the claim that makes it look good.

## 2. Design comparable runs

Baseline and candidate evidence must record:

- exact revision identifiers;
- exact argv command;
- explicit environment facts relevant to the measurement;
- raw numeric samples;
- correctness pass/fail counts;
- a concrete output/trace/profile/artifact/counter proving the measured work actually ran.

Use production-relevant settings. Compare the same workload with the same command and environment. If the comparison cannot use the same command/environment, the result is `INCONCLUSIVE`, not an apples-to-oranges PASS.

Repeated runs are required for a claim. One run is only a ballpark observation.

Prefer interleaved baseline/candidate runs when drift, thermal effects, shared infrastructure or time-varying load can matter. If runs are not interleaved, record the reason explicitly; the validator exposes this as a warning.

## 3. Keep correctness adjacent to speed

A faster result with correctness failures is not a performance PASS.

Record correctness/error counts for both arms. Do not hide failed requests, parse errors, retries, dropped work, incomplete output or reduced workload behind a better timing number.

The `workProof` path must point to an existing regular repository/local evidence file. The validator records SHA-256 and byte size of that proof.

## 4. Identify limiter and sanity bound

Before interpreting a result, state:

- the bottleneck/limiter being measured;
- why the observed value is physically/algorithmically plausible;
- whether the microbenchmark maps to an end-to-end product effect.

A microbenchmark may still PASS as a **microbenchmark-only** claim when end-to-end relevance was checked and found absent. It must not be promoted to an end-to-end speedup claim.

## 5. Validate evidence

Store transient payloads under `.harness/local/benchmark/**` or pass them from another local path. Then run:

```bash
python3 .harness/tools/benchmark-methodology.py \
  --evidence-file .harness/local/benchmark/STEP-NNN/evidence.json \
  --json
```

The tool computes:

- run count;
- median;
- min/max/range;
- observed variation percentage;
- direction-normalized effect percentage;
- command/environment equality;
- correctness state;
- work-proof file digest;
- claim/effect sufficiency.

### PASS

`PASS` means the evidence is structurally sufficient and the measured effect is larger than the observed run variation and any declared minimum material effect.

PASS does **not** replace semantic reasoning about benchmark relevance, nor any other Harness Verification/Review gate.

### INCONCLUSIVE

Treat `INCONCLUSIVE` literally. Typical reasons:

- only one or two runs;
- effect is within observed variation;
- minimum claimed effect was not met;
- command/environment mismatch;
- correctness failure;
- bottleneck not identified;
- sanity bound not checked;
- end-to-end claim lacks end-to-end relevance.

Do not rewrite `INCONCLUSIVE` as “probably faster/slower”. If STEP Acceptance depends on the claim, Verification/Review does not PASS until sufficient evidence exists or the contract changes through the normal workflow.

### BLOCKED

`BLOCKED` means malformed/unverifiable benchmark evidence: unsupported schema, missing proof file, invalid path, non-finite samples, unsupported fields, and similar contract violations.

## Evidence schema

Use the closed JSON schema documented in `.harness/docs/BENCHMARK_METHODOLOGY.md`. Do not add ad-hoc fields and ask the model to interpret them.

## Review integration

For a performance finding, first satisfy the normal Evidence Gate: prove the scenario is real. Then use benchmark methodology to validate the quantitative claim.

A performance finding may say:

- “the candidate regresses latency” only when the benchmark gate supports that quantitative claim;
- “evidence is insufficient” when the gate is `INCONCLUSIVE`;
- not “regression” merely because one noisy run was slower.

## Authority boundary

This capability does not:

- modify product code;
- change Acceptance criteria;
- replace Verification, Completion Gate or Review Contract;
- create a new public command;
- invent benchmark samples;
- treat model narrative as measurement evidence.

Raw measurements and deterministic output are facts. Relevance, bottleneck interpretation and design tradeoffs remain semantic judgement.
