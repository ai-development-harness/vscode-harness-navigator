---
name: pr-maintenance
description: Read provider facts for an existing Pull Request, perform bounded semantic CI/review triage, and hand mutations back to the existing Git/STEP workflow.
---
# pr-maintenance

Internal semantic capability for an **already existing Pull Request**. It is not a new user command and never owns Git mutation.

Use it when the user asks to:

- diagnose/fix failing Pull Request CI;
- process review comments or review requests;
- make the Pull Request easier to review;
- boundedly watch/re-check an active Pull Request.

## Hard boundary

Provider facts come only from:

```bash
python3 .harness/tools/pr-maintenance.py snapshot --selector <branch-or-number> --pretty
```

Do not reconstruct checks/comments/reviews from chat history. Preserve `factId`/`providerId` in semantic output.

Mutations remain owned by existing workflows:

```text
code/task fix   → STEP/FIX/QUICK FIX as appropriate
commit          → GIT COMMIT
publish         → GIT PUSH
Pull Request create/reuse → GIT PR
finish merged   → GIT PR FINISH
```

This capability has **no merge authority**, no force-push/history-rewrite authority and cannot bypass Git policy.

## Snapshot freshness

Snapshot contains `snapshotBasis`. Every semantic payload must include that exact basis and be validated by re-reading live provider state:

```bash
python3 .harness/tools/pr-maintenance.py validate \
  --selector <branch-or-number> \
  --payload-file '<local-json-or->' --pretty
```

If provider facts changed between reasoning and validation, tool returns `PR_SNAPSHOT_STALE`. Re-read facts; do not apply stale advice.

## CI triage

Mode: `ci-triage`.

1. Inspect failed provider check facts and their provider diagnostics/URL.
2. Identify the **first actionable root failure**, not every downstream red check.
3. At most one item may have `disposition=fix` in one pass.
4. Classify other facts only when materially necessary: `retry | ignore | blocked`.
5. Validate semantic payload.
6. If fix is needed, route it through normal task/scope rules. Do not mutate from this skill.
7. After normal commit/push, take a fresh provider snapshot and re-check.

Do not turn a failing check into a speculative product defect without evidence. If provider output is insufficient, return blocker/clarification rather than inventing a cause.

## Review feedback ingestion

Mode: `feedback`.

For each material `comment:*` / `review:*` fact classify:

```text
fix     → feedback is valid and requires in-scope change
dismiss → evidence shows it is not applicable / already satisfied
clarify → intent or requested behavior is materially ambiguous
```

Deduplicate repeated comments by meaning, but keep every external provider ID that supports the classification. A semantic finding may not reference a provider ID absent from the current snapshot.

## Reviewability preparation

Mode: `reviewability`.

Produce concise reviewer guidance from current Pull Request facts:

- intent/what changed;
- highest-risk surfaces;
- relevant Verification evidence/checks;
- generated/mechanical paths that can be skimmed.

`generatedOrMechanicalPaths` may contain only paths actually present in the provider Pull Request diff. This output is guidance, not a review verdict.

## Bounded babysit

Mode: `babysit`.

One invocation may refresh provider state at most 3 times (`refreshCount=0..3`). Stop when:

- state becomes stable with no actionable change;
- CI/review requires a code decision;
- provider capability is unavailable;
- budget is exhausted.

Do not busy-poll. Do not auto-merge. If the Pull Request becomes merged, use normal `GIT PR FINISH` when requested/appropriate.

## Semantic payload

```json
{
  "schemaVersion": 1,
  "mode": "feedback",
  "snapshotBasis": "sha256:...",
  "refreshCount": 0,
  "items": [
    {
      "factId": "comment:123",
      "disposition": "fix",
      "summary": "Empty-input path is missing.",
      "action": "Add guarded handling and regression coverage."
    }
  ],
  "reviewerGuidance": null,
  "nextAction": "fix",
  "rationale": "The comment identifies an observable missing behavior."
}
```

Validated output always says:

```text
mutationAuthority = existing-git-pr-workflow-only
autoMergeAllowed = false
historyRewriteAllowed = false
```

Never override these fields by prose.
