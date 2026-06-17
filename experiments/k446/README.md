# K446: Geopolitical Risk Index and SPY Realized Volatility

- Experiment ID: `K446`
- Original status: `FAIL` after 2026-06-18 Codex source-code audit
- v2 status: `FAIL/NULL` for the production article's inferential claims
- Created At: 2026-04-16T09:39:31.545373+00:00
- v2 rerun: 2026-06-18

## Research Question

Can the Caldara-Iacoviello daily Geopolitical Risk Index (GPR) predict future
SPY realized volatility beyond VIX?

## Data

- GPR: Caldara & Iacoviello daily GPR index, pinned for v2 at
  `data/gpr_daily_recent.xls`
- Market data: yfinance SPY and `^VIX`
- Cleaned sample: 2000-02-03 to 2026-02-23
- Cleaned observations: 6,552 trading days
- OOS forecast origins: 2023-01-01 to 2024-12-31, N=502
- v2 merged snapshot: `data/k446_v2_merged_dataset.csv`

## Artifacts

- Original script: `k446_gpr_vol.py`
- Original results: `k446_gpr_vol_results.json`
- v2 rerun script: `k446_gpr_vol_v2.py`
- v2 rerun results: `k446_gpr_vol_v2_results.json`
- Source-code audit: `storage/audit_reports/k446/source_code_review_20260618.md`

## v2 Method Fixes

The v2 rerun preserves the original research question but fixes the audit
failures:

1. Fixed-OOS training rows require `target_end < 2023-01-01`, dropping 5 rows
   for RV5fwd and 21 rows for RV21fwd.
2. Expanding-OOS training rows require `target_end < test_origin_date`.
3. DM tests use Newey-West long-run variance plus Harvey-Leybourne-Newbold
   small-sample t correction.
4. RV21fwd DM tests use `h=21` rather than `h=5`.
5. Incremental regressions report HAC/Newey-West coefficient t-statistics with
   `maxlags = h + 5`.
6. Granger tests use VAR lag selection by AIC and BIC; raw lag tests are kept
   only for comparison.
7. QLIKE is computed on variance forecasts, not volatility levels.

## v2 Main Results

The production article `mile_eabd7e46` was soft-unpublished after v2 because
two inferential claims reversed or weakened materially.

| Claim | Original article | v2 result |
|---|---:|---:|
| Raw GPR partial t, RV5fwd | -6.43 | HAC t = -3.32 |
| Raw GPR partial t, RV21fwd | -7.20 | HAC t = -2.55 |
| z-score GPR partial t, RV5fwd | -3.10 | HAC t = -2.31 |
| z-score GPR partial t, RV21fwd | -1.52 | HAC t = -1.04 |
| RV21 VIX+GPR vs VIX-only DM p | 0.148 | HLN-HAC p = 0.200 |
| GPR -> VIX Granger | lag1 p = 0.0499 | AIC p = 0.589, BIC p = 0.341 |

Descriptive claims remain supported:

- Seven event-window GPR-RV correlations range from -0.178 to 0.594.
- Extreme GPR regime (`>p90`) has N=656 and GPR-RV corr=0.204.

## Conclusion

K446-v2 supports a narrower conclusion:

- GPR is not a robust standalone or incremental OOS volatility forecaster beyond
  VIX in this daily SPY setup.
- The raw-GPR in-sample relationship weakens under HAC; only RV5fwd still clears
  the internal `|t| > 3` caution bar.
- z-score GPR does not clear the same bar for either horizon.
- The original lag1 Granger result does not survive AIC/BIC-selected VAR tests.
- Event/regime patterns are descriptive and ex-post, not inferential evidence.
