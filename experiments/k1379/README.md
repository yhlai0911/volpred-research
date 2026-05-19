# K1379 — Paper 9 HAR-RV / HAR-RV-VIX Benchmarks (C4 Horse Race Fix)

## Motivation

Paper 9 review v3 identified C4 (HIGH): "a horse race without HAR-RV is incomplete."
The volatility forecasting literature requires HAR-RV as a standard baseline. Referees
at JFEC/JEF/JoF will flag selective benchmarks. K1379 adds HAR-RV (B-1) and
HAR-RV-VIX (B-2) to the existing horse race and reports:
- If A4f significantly outperforms HAR-RV (|t| > 3.0) → substantial contribution
- If not → honest limitation (HAR-RV = competitive lower-cost alternative)

## Method

- Data: `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` (pinned snapshot)
- RV proxy: RV_t = r²_t (squared log return, daily data HAR convention)
- Models:
  - B0: GJR-GARCH(1,1) benchmark (recomputed for consistent loss series)
  - A4f: τ_t = θ₀ + θ₁VIX²_{t-1}, free ω_g (recomputed)
  - B-1: HAR-RV: RV_t = β₀ + β₁RV_{t-1} + β₂RV̄^(5)_{t-1} + β₃RV̄^(22)_{t-1}
  - B-2: HAR-RV-VIX: HAR-RV + β₄VIX²_{t-1}
- Rolling window: W=2000, refit_every=63, OOS_start=2019-01-01
- Lookahead prevention: all regressors use lag 1+ (t-1 for daily, t-5 for weekly, etc.)
- QLIKE loss (Patton 2011, proxy-robust): L = σ̂²/r² - log(σ̂²/r²) - 1
- DM test (Harvey 2016 threshold |t| > 3.0) for:
  - A4f vs B0 (GJR), A4f vs B-1 (HAR-RV), A4f vs B-2 (HAR-RV-VIX)
  - B-1 vs B0 (does HAR beat GJR?)
- seed=42

## Success Criteria

- Report all DM t-stats honestly regardless of outcome
- If A4f beats HAR-RV with |t| > 3.0: strengthen paper contribution claim
- If A4f does NOT beat HAR-RV: add as limitation, note both pass for Harvey significance vs GJR
- Output suitable for Table 2 addition (new rows B-1, B-2)

## Output Files

- `k1379.py`: main compute script
- `k1379_results.json`: DM results for 4-model comparison
- `k1379_losses.npy`: all 4 loss series (for potential K_NEW_C White RC/SPA)
