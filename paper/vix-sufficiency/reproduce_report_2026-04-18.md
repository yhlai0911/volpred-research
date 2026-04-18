# Paper 4 Reproducibility Audit — 2026-04-18

## Scope

- Target: `paper/vix-sufficiency/main_v2.tex` only.
- `main_v2.tex` currently contains **9 tables** and **0 `figure` environments**.
- Canonical evidence used in this audit:
  - `paper/vix-sufficiency/reproduce_report.json`
  - `paper/vix-sufficiency/reproducibility_audit/main_tex_numbers.csv`
  - direct reads of `paper/vix-sufficiency/experiments/*.json`
  - direct read of `experiments/k507/k507_dynamic_allocation_results.json`
- Rule used here: when a stored experiment JSON already contains the published statistic, that JSON is treated as canonical. Manual recomputation is not treated as authoritative over stored output.

## Recommendation Codes

- `(a)` Supervisor can update `main_v2.tex` directly to the cited canonical JSON value.
- `(b)` Current paper mixes sample periods or specifications; choose one canonical source first, then rewrite.
- `(c)` No unambiguous canonical output exists; expose or store the intermediate output before rewriting.

## Summary

| Bucket | Count |
|--------|-------|
| matched | 69 |
| approx (`<0.5%`) | 0 |
| divergent | 9 |
| missing | 1 |

**Counting note**: the table above comes from the existing **79-item structured corpus** in `paper/vix-sufficiency/reproducibility_audit/main_tex_numbers.csv`, re-checked against canonical JSON outputs. In addition, a fresh row-level rescan found extra unmapped Table 2 fields and a Table 10 source-label gap that were not itemized in that legacy CSV; those qualitative findings are listed below even though they are outside the `79-item` count table.

## Matched

- Tables 1, 4, 5, 7, 8, and 9 are numerically reproducible from the current stored JSON outputs after normal paper rounding.
- Earlier 2026-04-17 audit flags on `CV = 0.33` were false positives for reproducibility purposes. `paper/vix-sufficiency/experiments/k752_vix_sufficiency_eras_results.json` stores `synthesis.r2_cv = 0.3309`, so `0.33` in `main_v2.tex` is consistent with canonical output.
- Earlier 2026-04-17 audit flags on VaR/ES `Risk Score = 1.94 / 1.63` were also false positives. `paper/vix-sufficiency/experiments/k780_tail_first_es_results.json` stores:
  - `part_d_economic_ranking.amem.total_score = 1.9407`
  - `part_d_economic_ranking.gjr.total_score = 1.6257`
  so the paper values are reproducible from canonical output.
- `Table 2` Bitcoin partial correlation `0.178` is traceable to `paper/vix-sufficiency/experiments/k746b_bitcoin_vix_fixed_results.json -> summary.full_sample_VIX_BTC_RV_corr = 0.177832...`.
- `Table 2` calendar in-sample `t = -2.39` is traceable to `paper/vix-sufficiency/experiments/k736_calendar_anomaly_vt_results.json -> part_a.t_stat = -2.392`.

## Approx

- None. After applying paper rounding conventions, no checked item fell into the `0 < error < 0.5%` bucket.

## Divergent

### 1. Inline `41.8% QLIKE improvement` is direction-reversed

- Locations:
  - `paper/vix-sufficiency/main_v2.tex:98`
  - `paper/vix-sufficiency/main_v2.tex:703`
  - `paper/vix-sufficiency/main_v2.tex:813`
- Paper claim: `41.8% QLIKE improvement` from 5-minute HAR-RV over daily models.
- Canonical source: `paper/vix-sufficiency/experiments/k745_pilot_har_rv_results.json`
  - `key_comparison.best_5min_QLIKE = 0.109341`
  - `key_comparison.best_daily_QLIKE = 0.077108`
  - `key_comparison.improvement_pct = -41.8`
  - `n_oos = 37`
- Conclusion: under K745, **daily HAR-ABS beats 5-minute HAR-RV by 41.8%**, not the other way around.
- Recommendation: `(a)`

### 2. Table 6 materially understates era-specific exceptions

- Location: `paper/vix-sufficiency/main_v2.tex:583-590`
- Canonical source: `paper/vix-sufficiency/experiments/k752_vix_sufficiency_eras_results.json -> part_d_competing_signals_by_era`
- Divergent cells:
  - Overnight VIX, Era 3: paper `0.0004`, source `0.0039`
  - Overnight VIX, Era 5: paper `0.0003`, source `0.0032`
  - VRP proxy, Era 3: paper `0.0008`, source `0.0160`
  - Vol momentum 20/60, Era 3: paper `0.0006`, source `0.0216`
  - Vol momentum 20/60, Era 5: paper `0.0002`, source `0.0372`
- The header `Harvey Pass? 0/5` is also wrong. K752 shows **4 Harvey passes**:
  - Era 3: Overnight VIX (`signal_t = -3.15`), VRP (`-6.51`), Vol momentum (`+7.60`)
  - Era 5: Vol momentum (`+9.30`)
- Recommendation: `(a)`

### 3. Table 3 / paragraph below it mixes sample periods, so the benchmark comparison is not fair

- Locations:
  - `paper/vix-sufficiency/main_v2.tex:470-471`
  - `paper/vix-sufficiency/main_v2.tex:493`
- Paper presentation:
  - Buy-and-hold 50/50 SPY/GLD Sharpe = `0.947`
  - 12/VIX Sharpe = `0.870`
  - Line 493 interprets this as a same-table ranking result.
- Canonical sources:
  - `0.947` comes from `experiments/k507/k507_dynamic_allocation_results.json -> full_sample_results.static_5050.sharpe`
    - sample: `2005-01-03 to 2026-03-26`
    - `n_days = 5339`
  - `0.870` comes from `paper/vix-sufficiency/experiments/k731_vix_term_structure_results.json -> full_sample_strategies["12/VIX"].sharpe`
- Conclusion: both numbers exist, but the comparison is **not same-window / same-experiment**, so the line-493 ranking claim is methodologically unfair.
- Recommendation: `(b)`

### 4. Table 10 is labeled `SPY/GLD`, but the stored insurance numbers are not a clean SPY/GLD output

- Location: `paper/vix-sufficiency/main_v2.tex:772-775`
- Traceable pieces:
  - `3.49%/yr` maps to `paper/vix-sufficiency/experiments/k738_vt_insurance_cost_benefit_results.json -> cross_asset_summary.avg_return_drag_12vix = 3.486`
  - `2.12%/yr` maps to `...avg_return_drag_ewma = 2.121`
  - `gamma* = 4.5 / 4.4` maps to `decision_guide.median_breakeven_gamma_*`
- But the table row label says `SPY/GLD`, and the stored K738 per-asset outputs do **not** support `-8.2 pp` for SPY or GLD:
  - `SPY -> mdd_reduction_pp = 20.275`
  - `GLD -> mdd_reduction_pp = 9.423`
- Conclusion: the table appears to combine cross-asset summary numbers with a SPY/GLD label, and at least one key cell is not reproducible from the cited experiment output.
- Recommendation: `(c)`

## MISSING / Unmapped Row-Level Fields

### A. Table 2 — Behavioral sentiment row is not backed by a canonical stored output

- Location: `paper/vix-sufficiency/main_v2.tex:420`
- Unmapped paper fields:
  - `partial r = 0.091`
  - `IS t-stat = 1.64`
  - `R^2_{OOS,CT} = 0.365`
  - `DM |t| = 0.52`
  - `Raw p = 0.603`
- What K732 does store:
  - `delta_r2 = 0.004295...`
  - `bsi_t_stat = 5.5826`
  - `dm_stat_oos = 1.6370`
  - `dm_pval_oos = 0.1016`
  - `dm_bsi_vs_bh.dm_stat = -1.1795`
- Conclusion: the row clearly uses some intermediate output that is **not present** in the current `K732` JSON.

### B. Table 2 — Calendar anomaly row only has the IS `t` stored; the OOS row is not reproducible from current K736 JSON

- Location: `paper/vix-sufficiency/main_v2.tex:428`
- Directly reproducible:
  - `IS t-stat = -2.39` from `K736 part_a.t_stat = -2.392`
- Not reproducible as canonical forecast-output fields:
  - `partial r = -0.007`
  - `IS ΔR² = 0.012`
  - `R^2_{OOS,CT} = 0.348`
  - `DM |t| = 0.15`
  - `Raw p = 0.881`
- Nearest stored values are weight-seasonality diagnostics such as:
  - `part_c.vt_weight_seasonality.weight_diff = -0.0038`
  - `part_e.r2_weights_month_dummies = 0.0123`
  but these are not the same statistic as the table labels.
- Conclusion: current `K736` JSON does not expose the exact outputs needed to reproduce the full row.

## Evidence Paths

- `paper/vix-sufficiency/main_v2.tex`
- `paper/vix-sufficiency/reproduce_report.json`
- `paper/vix-sufficiency/reproducibility_audit/main_tex_numbers.csv`
- `paper/vix-sufficiency/experiments/k745_pilot_har_rv_results.json`
- `paper/vix-sufficiency/experiments/k752_vix_sufficiency_eras_results.json`
- `paper/vix-sufficiency/experiments/k780_tail_first_es_results.json`
- `paper/vix-sufficiency/experiments/k738_vt_insurance_cost_benefit_results.json`
- `paper/vix-sufficiency/experiments/k732_pcr_behavioral_sentiment_results.json`
- `paper/vix-sufficiency/experiments/k736_calendar_anomaly_vt_results.json`
- `paper/vix-sufficiency/experiments/k746b_bitcoin_vix_fixed_results.json`
- `experiments/k507/k507_dynamic_allocation_results.json`
