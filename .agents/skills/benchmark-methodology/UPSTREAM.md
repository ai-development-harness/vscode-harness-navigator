# Provenance

Source: project-native
Repository: `ai-development-harness/ai-development-harness-template`
Path: `.agents/skills/benchmark-methodology/`
Provenance recorded: `2026-10-07`

## Design reference

- pstack benchmark checklist:
  https://github.com/michael-denyer/pstack-claude/tree/main/plugins/pstack/skills/benchmark-checklist

## Harness adaptation

Harness keeps the evidence-discipline ideas but separates them into a semantic methodology skill and a deterministic evidence gate. The Core validator computes run statistics, checks comparability/correctness/work proof, and returns PASS/INCONCLUSIVE/BLOCKED. The model remains responsible only for benchmark design and relevance reasoning.
