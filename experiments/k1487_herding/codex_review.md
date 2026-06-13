# Codex Review — K1487

Verdict: **CONDITIONAL_PASS**

## Scope

Reviewed `k1487_herding.py`, `k1487_herding_results.json`, figures, and README for:

- data-source transparency
- lookahead / timing errors
- TWSE API parsing
- rolling OOS protocol
- Granger direction labeling
- result-summary consistency

## Findings

No implementation issue found that would overturn the reported NULL / reverse-direction conclusion.

Checks:

- Forecast target is date `t` close-to-close squared log return.
- Forecast features use explicit `.shift(1)` for HAR and day-trading predictors.
- Granger tests use current `dt_z` and `log_rv`, letting `statsmodels` apply the tested lags; this avoids the earlier double-lag issue.
- TWSE old endpoint returns ROC-year dates; `parse_twse_date()` correctly maps `113/02/29` to 2024-02-29.
- OOS training uses only rows before prediction date `i`.
- Results JSON key findings match the stored test statistics.
- Figures call `apply_cjk_style()` and visually render Chinese labels correctly.

## Residual Risks

- Daily `r_t^2` is noisy; intraday RV could change effect-size estimates.
- Granger F-tests are predictive-direction tests, not structural causality.
- Price files are local yfinance snapshots ending 2026-03-17; the TWSE cache extends later but the merged panel stops at the price endpoint.
- Market-level day-trading share does not identify retail investor type directly.

## Conclusion

The evidence supports a conservative conclusion: TWSE day-trading share is a useful market-state / attention proxy, but it does **not** pass the next-day volatility forecast gate in this specification. The stronger result is reverse direction: realized volatility predicts future day-trading intensity.
