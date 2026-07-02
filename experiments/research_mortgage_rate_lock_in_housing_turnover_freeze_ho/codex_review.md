# Codex Review

Review date: 2026-07-02

## Scope

Reviewed the experiment implementation and result artifacts for `research_mortgage_rate_lock_in_housing_turnover_freeze_ho`.

## Checks

- Three required artifacts exist: README, script, and results JSON.
- The script downloads public FRED CSVs and yfinance prices with `auto_adjust=False`, then explicitly uses adjusted close.
- Signal alignment is explicit: raw monthly signal columns are shifted with `raw[lagged_cols].shift(1)` before merging with same-month realized variance targets.
- Random bootstrap uses fixed seed `20260702`.
- Formal tests are present: month-clustered OLS, OOS QLIKE comparison against trailing RV baseline, and month-bootstrap high-lock-in regime contrasts.
- Result interpretation matches the evidence: no core predictor is significant, the OOS QLIKE model underperforms the baseline, and the high-lock-in regime contrast is not significant.

## Verdict

PASS for a bounded public-data pilot with a null/inconclusive conclusion.

Main caveat: the embedded mortgage-rate proxy is not borrower-level origination coupon data, so this cannot test loan-level lock-in directly.
