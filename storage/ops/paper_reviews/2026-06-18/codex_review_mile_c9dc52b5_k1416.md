# Codex Source-Code Review - mile_c9dc52b5 / K1416

- **Article**: K1416：HLN(1997) 小樣本修正的正式套用 — Paper 3 TW0050-N225 主張的穩健性確認
- **Task**: `paper_review_mile_c9dc52b5`
- **Experiment**: `experiments/k1416/`
- **Review timestamp**: 2026-06-18 19:12 Asia/Taipei
- **Verdict**: **CONDITIONAL PASS AFTER CORRECTION**

## Scope

This review checked the production article against:

- `storage/reports/feed.json`
- `storage/reports/mile_c9dc52b5.json`
- `storage/drafts/k1416_research_draft.md`
- `experiments/k1416/README.md`
- `experiments/k1416/k1416.py`
- `experiments/k1416/k1416_results.json`
- `experiments/k1412/README.md`
- `experiments/k1412/k1412.py`
- `experiments/k1412/k1412_results.json`
- `experiments/paper3_E2_cross_market_copula/paper3_E2.py`
- `experiments/paper3_E2_cross_market_copula/paper3_E2_results.json`
- `research_program.md`

## Findings

1. **The K1416 table values match the source results.**
   - HLN-adjusted t-statistics across OOS starts are `3.2402`, `3.8915`, `3.6607`, `3.0442`, `3.0929`.
   - The 5% critical values are about `1.9610` to `1.9615`.
   - Margins above the 5% cutoff are `1.2793`, `1.9304`, `1.6995`, `1.0829`, `1.1314`.
   - `k1416_results.json` marks all five starts significant at both 5% and 1%.

2. **HLN implementation is correct for the stated h=1 design.**
   - `experiments/k1416/k1416.py` implements `sqrt((n + 1 - 2h + h(h-1)/n) / n)`.
   - For h=1 this simplifies to `sqrt((n-1)/n)`.
   - Critical values use `scipy.stats.t.ppf(0.975, df=n-1)`.
   - Paper3_E2 baseline cross-check matches stored `hln_factor=0.9997580742676584`.

3. **No lookahead issue found in the referenced Paper3_E2 one-step forecast loop.**
   - `oos_forecast_pair()` trains on `ret[s:t]` / `x[s:t]`.
   - The forecast recursion uses lagged `ret[t-1]` and `x[t-1]`.
   - Realized portfolio returns are aligned through `port_ret[oos_idx:]`.

4. **Article caveats are appropriate and should remain.**
   - Four non-baseline `n_oos` values are inferred, not exact.
   - The five OOS starts are an overlapping sensitivity grid, not independent replications.
   - The 80% pass gate is an internal submission rule, not an econometric theorem.

5. **Material wording issue corrected.**
   - The original article said `TW0050-N225` was the only current Paper 3 Harvey-significant cross-market pair.
   - Current `paper3_E2_results.json` has two Student-t vs DCC Harvey-significant pairs: `TW0050-N225` (`t=3.92296`, `p=0.0000903`) and `TW0050-HSI` (`t=2.07855`, `p=0.03778`).
   - The corrected article now frames `TW0050-N225` as the strongest / most visible pair requiring OOS-start robustness verification, not as the unique significant pair.

6. **Metadata issue corrected.**
   - Existing `arc_signature` incorrectly classified the article as `null_no_info` / `factor_causality`.
   - Root cause: arc-dedup treated bare English `factor` and Chinese `因子` as factor-causality, so the phrase "HLN correction factor / 修正因子" polluted mechanism classification.
   - The corrected row is `positive_signal` / `cross_asset_spillover`.

## Actions Taken

- Updated the research article through `scripts/publish_draft.py --update`, including content, description, single-article JSON, and errata audit trail.
- Updated `experiments/k1416/README.md`, `experiments/k1416/k1416.py`, and `research_program.md` so downstream agents stop citing the stale unique-pair framing.
- Added `storage/drafts/k1416_research_draft.md` as the formal update input.
- Tightened `src/volpred/publisher/arc_dedup.py` so bare `factor` / `因子` no longer triggers factor-causality unless the context is explicitly factor investing/modeling.
- Added an arc-dedup regression test for HLN correction-factor wording.
- Extended `scripts/backfill_arc_dedup_metadata.py` to keep existing `storage/reports/<id>.json` files in sync when scoped metadata backfill patches feed rows.
- Rebuilt `storage/reports/INDEX.md` and `storage/reports/index.json`.
- Synced `mile_c9dc52b5` to Supabase and read back the row; remote status is `published`, corrected arc metadata is present, and the article no longer contains the bad unique-pair phrase.

## Recommendation

The corrected article is acceptable. Keep Paper 3 wording scoped to "`TW0050-N225` is the strongest current HLN significant cross-market pair and is robust across five alternative OOS starts"; do not describe it as the only significant pair unless explicitly referring to the superseded pre-HLN/raw-DM snapshot.
