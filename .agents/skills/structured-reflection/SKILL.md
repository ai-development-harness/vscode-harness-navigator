---
name: structured-reflection
description: Turn significant structured Harness evidence into deduplicated durable learning proposals without treating transcripts as source of truth.
---
# structured-reflection

Internal post-work learning capability. It is optional and **not** a new user command.

Use it after significant/high-cost work, repeated FIX/review findings, progress stops, verification failures or explicit human request. Do not run it mechanically after every STEP.

## Evidence boundary

Prepare a local envelope from existing structured/durable Harness facts only:

- Review Contract finding + immutable review report;
- repair/progress stop;
- Completion outcome;
- audit/reconcile finding;
- Verification failure;
- Git evidence;
- explicit durable project decision;
- validator failure.

Transcript/chat/session memory is not an allowed source kind.

Every event must point to an existing **durable repository file** and include a stable fingerprint/class/occurrence identity. `.harness/local/**` cannot be an evidence pointer.

Scan:

```bash
python3 .harness/tools/structured-reflection.py scan \
  --evidence-file .harness/local/reflection/evidence.json --pretty
```

Tool counts distinct occurrence IDs per class. Same underlying occurrence corroborated by several sources does not become recurrence by repetition.

## Trigger

`triggerRecommended=true` only means a reflection pass is worth the cost. Typical triggers:

- a class occurred 2+ distinct times;
- repair/progress stopped;
- meaningful Verification failure.

One-off ordinary success should not trigger reflection by default.

## Lesson routing

Each lesson gets **exactly one** primary target:

```text
core-tool-gate-validator
core-reasoning-principle
project-principle
project-skill
core-skill
adr-req-oq-gap
no-action
```

Use `scope=core|project|none` consistently with the target.

Do not create duplicate rules. Check existing validator/skill/CRP/PRN/ADR/REQ/OQ before proposing a target. Tool additionally rejects a duplicate lesson fingerprint already present in reflection history.

One occurrence cannot become Core/project rule or skill unless the human explicitly requested structuralization. `adr-req-oq-gap` may legitimately describe a single concrete contract gap; `no-action` is the normal route for one-off lessons.

## Write report

Semantic payload:

```json
{
  "schemaVersion": 1,
  "lessons": [
    {
      "classKey": "review:implementation:owner-bypass",
      "summary": "Owner bypass recurs.",
      "scope": "core",
      "primaryTarget": "core-tool-gate-validator",
      "evidenceIds": ["ev-1", "ev-2"],
      "rationale": "Two independent occurrences.",
      "proposedAction": "Add deterministic ownership guard."
    }
  ],
  "rationale": "Significant repeated correction."
}
```

Validate and persist immutable report:

```bash
python3 .harness/tools/structured-reflection.py write \
  --evidence-file .harness/local/reflection/evidence.json \
  --payload-file .harness/local/reflection/lessons.json --pretty
```

Reports live under configured audit directory + `/reflections/`.

## Authority

Reflection report is only a proposal:

```text
automaticMutationAllowed = false
```

It never creates/changes validator, CRP, PRN, skill, ADR, REQ, OQ or product code itself. Route accepted work through ordinary Harness artifacts/workflows.
