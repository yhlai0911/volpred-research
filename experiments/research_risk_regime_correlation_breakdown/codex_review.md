# Codex Source Review — research_risk_regime_correlation_breakdown

Review date: 2026-06-15  
Reviewer: Codex interactive session  
Verdict on experiment integrity: `PASS`  
Verdict on research hypothesis: `NULL` as reported in results

## Scope

Reviewed:

- `research_risk_regime_correlation_breakdown.py`
- `research_risk_regime_correlation_breakdown_results.json`
- `README.md`
- Generated figures

## Checks

1. Lookahead bias: `PASS`
   - Forward outcomes start at `i + 1` in `future_window_stat()` and `future_worst_cum_return()` (`.py` lines 144-160).
   - Formal predictive features are explicitly lagged: `corr60_lag1`, `corr_vol21_lag1`, `corr_vol_q80_lag1`, and RV controls all use `.shift(1)` (`.py` lines 396-403).
   - The high-corr-vol threshold uses an expanding quantile and then shifts it by one day (`.py` lines 366, 399-400).

2. DCC leakage control: `PASS`
   - Full-sample DCC-GARCH is not used as a predictive feature.
   - The script labels it `descriptive_only` and records the reason that using full-sample DCC parameters for prediction would leak future information (`.py` lines 244-249, 501-504, 558-560).

3. HAC / overlapping-window inference: `PASS`
   - Forward horizon is 21 trading days (`.py` line 54).
   - HAC regressions use `maxlags=FORWARD_HORIZON`, i.e. 21 (`.py` lines 164-167).
   - Stationary bootstrap uses block length 21 and fixed seed (`.py` lines 58-59, 96-120).

4. Random seed: `PASS`
   - `SEED = 42` is fixed (`.py` line 47).
   - NumPy seed is set in `main()` (`.py` line 349).
   - Bootstrap RNG uses the same seed by default (`.py` lines 96-105).

5. Verdict integrity: `PASS`
   - The raw transition event-rate difference is positive, but bootstrap CI crosses zero and HAC control regression makes the high-signal coefficient negative and non-significant.
   - Results therefore report `NULL`, not a positive early-warning claim.
   - README explicitly says no article should claim a working detector.

6. Reproducibility: `PASS_WITH_CAVEAT`
   - Data source, tickers, start/end dates, and `auto_adjust=True` choice are specified in code and results.
   - Exact future reruns can drift if yfinance revises adjusted data, but the workflow is fully reproducible from free data.

## Conclusion

The experiment artifact is acceptable as a NULL result. It should not be promoted as an article candidate unless the article is specifically about a failed early-warning signal or methodology lesson.
