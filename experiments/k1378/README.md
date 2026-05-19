# K1378 — Paper 9 Leave-COVID-out DM Test (SF1 Robustness Fix)

## Motivation

Paper 9 (garch-x-vix) review v3 identified SERIOUS FLAW SF1:
> "No leave-COVID-out analysis. The 7-period robustness claim is stated in prose with no table."

The paper claims robustness across sub-periods but provides no quantitative support. K1378 directly
computes the DM test for A4f vs GJR-GARCH **excluding the COVID period (2020-03-01 to 2021-06-30)**
from the OOS loss evaluation. If A4f still Harvey-passes (|t| > 3.0), SF1 is refuted; otherwise
confirmed and the paper needs major revision.

## Method

- Data: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` (pinned snapshot)
- Models: A4f (τ_t = θ₀ + θ₁VIX²_{t-1}, free ω_g) vs GJR-GARCH(1,1)
- Rolling window: W=2000, refit_every=63, OOS_start=2019-01-01
- Lookahead prevention: VIX at t−1 used for day-t forecast (signal.shift(1))
- QLIKE loss proxy: r²_t (squared log return)
- DM test computed on:
  a. Full OOS (2019-01 onwards)
  b. Non-COVID OOS (exclude 2020-03-01 to 2021-06-30, ~321 trading days)
- COVID exclusion: filter by date mask applied only to QLIKE evaluation, not fitting
- Harvey threshold: |t| > 3.0
- seed=42

## Success Criteria

- Primary: |DM_t_no_covid| > 3.0 → SF1 refuted (A4f robust outside COVID)
- Secondary: Report both full-OOS and no-COVID DM stats for paper body Table
- Either outcome reported honestly (null result is valid)

## Output Files

- `k1378.py`: main compute script
- `k1378_results.json`: DM test results for both OOS subsets + metadata
- `k1378_losses.npy`: QLIKE loss series (saved for potential White RC/SPA in K_NEW_C)
