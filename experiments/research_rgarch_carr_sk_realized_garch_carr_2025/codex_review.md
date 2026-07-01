# Codex Review - research_rgarch_carr_sk_realized_garch_carr_2025

**Verdict**: PASS as a daily proxy gate.  
**Claim strength**: limited to yfinance daily OHLC. Do not present this as a
replication or rejection of the high-frequency RGARCH-CARR-SK paper.

## Checks Performed

- `uv run python -m py_compile experiments/research_rgarch_carr_sk_realized_garch_carr_2025/research_rgarch_carr_sk_realized_garch_carr_2025.py`
- `uv run python experiments/research_rgarch_carr_sk_realized_garch_carr_2025/research_rgarch_carr_sk_realized_garch_carr_2025.py`
- `jq` inspection of verdict, primary baseline, panel QLIKE means, per-asset
  QLIKE, selected Ridge alphas, bootstrap intervals, and feature correlations.
- PNG non-empty and dimensions checked with `file`.

## Review Notes

1. **Lookahead protection is explicit**: all feature groups use `shift(1)` or
   `rolling(...).shift(1)`. Training and scalar calibration use rows before
   2019-01-02 only.
2. **Target scope is honest**: the target is daily `r_t^2`; the script does not
   call it five-minute realized volatility.
3. **Primary baseline is conservative**: the gate baseline is the best
   calibrated traditional model among naive HAR22, HAR RV, HAR asymmetry, HAR
   range, and HAR SK. The selected primary baseline is `har_range`.
4. **Regularization is train-only**: each Ridge model chooses alpha from a fixed
   grid using the last 20% of the training window as chronological validation.
5. **Null result is not overclaimed**: the result says daily SK proxies do not
   add value over range-only; it does not reject true high-frequency realized
   higher moments.
6. **Statistical result is one-sided against the full proxy**: the full proxy has
   mean QLIKE diff +0.041787 vs `har_range`, wins 0/8 assets, and the bootstrap
   95% CI is entirely positive.

## Residual Risk

- The CARR component is a range-feature proxy, not a CARR likelihood.
- The SK channel uses rolling daily-return moments, not realized skewness or
  realized kurtosis from intraday data.
- No VaR/ES backtest is included, although the 2025 paper also emphasizes risk
  measurement.
- The result can justify deferring implementation, not closing the high-frequency
  research question.
