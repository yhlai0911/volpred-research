# Codex Source-Code Review - mile_50616ca2 / K1370c

- **Article**: 把同一個模型算慢一點，答案真的會變嗎？
- **Task**: `paper_review_mile_50616ca2`
- **Experiment**: `experiments/k1370c/`
- **Review timestamp**: 2026-06-18 15:42 Asia/Taipei
- **Verdict**: **CONDITIONAL PASS**

## Scope

This review checked the production article against:

- `storage/reports/feed.json`
- `experiments/k1370c/README.md`
- `experiments/k1370c/k1370c_nstart_sensitivity.py`
- `experiments/k1370c/k1370c_results.json`
- `experiments/k1370/k1370.py`
- `experiments/k1370/k1370_replicates.json`

## Findings

1. **Article numbers match K1370c results.**
   - `n_replicates_tested=20`, selected from K1370 v2 at indices `0,50,...,950`.
   - `max_abs_delta=0.09184185996815764`.
   - `mean_abs_delta=0.004853025072552608`.
   - Baseline median `3.839098166742658`; N_start=100 median `3.839113566772532`.
   - Runtime `490.25910210609436` seconds.

2. **No lookahead issue found in K1370c.**
   - The script reuses K1370's in-sample stationary block bootstrap machinery.
   - The comparison is a deterministic sensitivity rerun, not a forecast/backtest signal.
   - The hold-constant guard explicitly asserts `derived_boot_seed == v2_record_boot_seed` for each selected replicate.

3. **Provenance is weaker than ideal.**
   - `K1370c` was computed against the K1370 replicate file committed with `cbcb9c34`.
   - The current `experiments/k1370/k1370_replicates.json` was later changed in `f1bdea2d`.
   - Example: selected `v2_idx=550` is `3.1596040785309576` in K1370c's recorded baseline, but `3.251454459955349` in the current K1370 replicate file.
   - This does not overturn the article: comparing K1370c's N_start=100 values to the current selected K1370 replicates gives `max_abs_delta=0.011590367039895355` and `mean_abs_delta=0.0006040772456748833`, which is even smaller than the published sensitivity gap.
   - Follow-up recommendation: future sensitivity experiments should persist the baseline source commit/hash or a frozen selected-replicate snapshot in their own experiment directory.

4. **Article metadata had a false intraday horizon.**
   - `arc_dedup` classified the phrase "多等好幾個小時" as intraday because the classifier used bare `小時` as an intraday keyword.
   - This was metadata-only; the article body and numerical claims were not affected.

## Actions Taken

- Tightened `src/volpred/publisher/arc_dedup.py` so generic runtime wording with `小時` is not automatically intraday.
- Added an arc-dedup regression test for "完整重跑要多等好幾個小時".
- Added scoped `--id` support to `scripts/backfill_arc_dedup_metadata.py`.
- Backfilled only `mile_50616ca2` so its `details.arc_signature.time_horizon` is now `unspecified`.
- Rebuilt `storage/reports/INDEX.md` and `storage/reports/index.json` from the current feed source.

## Recommendation

No public article correction is required. Keep the conclusion scoped to K1370c's 20-replicate sensitivity check, and do not cite the current mutable K1370 replicate file as if it were the frozen baseline used by K1370c.
