# K957 / mile_08407091 Codex 24h Publication Review

- Article: `mile_08407091` — "40 次測試後，我們刪掉了五種最容易浪費時間的研究方向"
- Task: `paper_review_mile_08407091`
- Source experiment: `experiments/k957/`
- Reviewer: Codex
- Review date: 2026-06-19
- Verdict: **CONDITIONAL_PASS_AFTER_PATCH**

## Bottom Line

The article's headline "40 tests" is supported after audit:

- `experiments/k957/k957_results.json` now reports `n_experiments_classified = 40`.
- The actual local experiment directories in `K526` through `K566` contain 40 experiments; only `K555` is absent from that sequence.
- The article body already used the correct 40-count wording.

I patched the source artifacts because K957 still contained stale 37-count provenance in `README.md`, `k957.py`, `k957_results.json`, and the timeline figure title. I also removed the out-of-scope `K569` missing marker, since K957's documented scope is `K526-K566`.

## Claim-Evidence Match

| Article claim | Source check | Status |
|---|---:|---|
| "40 次測試" | `len(CLASSIFICATION)=40`; local directories `K526-K566` excluding `K555` = 40 | PASS after patch |
| 5 lesson framing | `meta_lessons` contains E019-E023 | PASS |
| VIX-derivative extensions mostly add little | class D count = 11; VIX-sufficiency source list includes K535/K537/K538/K539/K540/K541/K542/K543/K554/K556/K564 | PASS as synthesis |
| Daily/weekly wins may degrade at monthly frequency | daily artifact cases K560/K563/K566 retained in results | PASS |
| Prediction improvement is not automatically trading lift | K533 classified as predictive-only; E023 caveat retained | PASS |
| Asset relationships can change | E022 maps K534/K565 | PASS as limited synthesis |

## Lookahead / Timing Audit

No lookahead issue was found. K957 is a meta-synthesis with no new signal/backtest estimator and no same-day signal/return alignment.

## Reproducibility / Provenance Caveat

K957 is a manually curated synthesis table, not a script that dynamically re-parses every source JSON on each run. The previous README and script docstring implied automatic JSON/experience reading. I patched that wording to state the actual implementation: an audited `CLASSIFICATION` table derived from source experiment JSON and E019-E023 entries.

Remaining caveat: the classification table still depends on manual curation. Future synthesis experiments should either:

1. persist a machine-readable source manifest with exact JSON fields used per K-id, or
2. implement validation checks that read each referenced result file and assert the cited numbers.

## Actions Taken

- Updated `experiments/k957/README.md` from 37-count wording to the verified 40-experiment scope.
- Updated `experiments/k957/k957.py` title, chart title, missing-id list, and implementation description.
- Regenerated `experiments/k957/k957_results.json` and `experiments/k957/k957_timeline.png`.
- Updated `mile_08407091` through `scripts/publish_draft.py --update`.
- Cleared the stale `content_audit_flagged` flag through `--clear-content-audit-flag`.
- Verified Supabase PNG objects for `k957_timeline.png` and `k957_sankey.png` match local SHA-256 hashes.

## Verification

- `uv run python experiments/k957/k957.py` completed.
- `uv run python -m py_compile experiments/k957/k957.py` passed.
- `git diff --check` passed before task completion.
- Remote image readback:
  - `k957_timeline.png`: SHA matched local.
  - `k957_sankey.png`: SHA matched local.

## Verdict

`CONDITIONAL_PASS_AFTER_PATCH`.

The public article does not require retraction. The count/provenance inconsistency has been corrected in source docs, results metadata, chart output, and article audit trail. The only residual limitation is that K957 remains a curated meta-synthesis rather than a fully source-parsing aggregation script.
