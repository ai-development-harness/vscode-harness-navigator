# Traceability Coverage

`traceability-coverage.py` строит read-only deterministic graph:

```text
REQ → STEP → current completion/evidence proof
```

Explicit IDs являются source of truth. LLM не требуется для построения graph,
coverage state или freshness; semantic reviewer может добавлять diagnostics
поверх этого graph, но не переписывает explicit links.

## Запуск

```bash
python3 .harness/tools/traceability-coverage.py --json
```

JSON schema v1 содержит aggregate `metrics`, состояние каждого REQ,
`orphanSteps`, `invalidReferences` и open blocking OQ.

## Coverage semantics

- `uncovered` — нет executable STEP, который claims этот REQ;
- `covered` — coverage есть, но ещё не все executable STEP имеют current proof;
- `verified` — **все** executable STEP, claims данного REQ, имеют current completion proof;
- `stale_evidence` — STEP имеет `status: completed`, но existing revision/basis
  semantics больше не подтверждают current completion proof;
- `blocked` — OPEN OQ влияет на PROJECT, REQ, executable STEP или ADR,
  используемый executable STEP.

REQ-side ссылка на STEP не считается положительным coverage, если сам STEP не
claims REQ: это `REVERSE_TRACEABILITY_MISMATCH`.

Для split requirement completed одного STEP недостаточно: REQ становится
`verified` только после current proof всех его executable STEP.

## Orphan STEP

Generic `implementation` STEP без REQ/ADR считается orphan. Типы
`bugfix`, `refactor`, `research`, `adr`, `audit`, `review`,
`hardening`, `documentation`, `release` являются explicit typed
non-product rationale и не требуют fake product REQ только ради coverage.

## Evidence freshness

Coverage не вводит собственное понятие evidence. Он вызывает существующий
`step_completion_proof`; поэтому exact revision/basis/review freshness остаётся
единой с lifecycle Harness.

## Integrations

- PROJECT STATUS показывает `summary.traceabilityCoverage` и findings.
- PROJECT RECONCILE классифицирует coverage gaps отдельно и не создаёт STEP автоматически.
- RELEASE CHECK получает `releaseRelevant` coverage как deterministic input и
  соотносит его с фактическим release scope/policy.
- JSON пригоден UI client без повторной semantic reconstruction.

`releaseRelevant=true` сейчас является deterministic signal для
`critical/high` REQ, но окончательный release scope всё равно определяется
реальной release model/policy, а не одним percentage или priority flag.
