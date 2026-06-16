# Codex Review — K1347

Verdict: PASS

Reviewed at: 2026-06-16T09:18:37Z

## Checks

- Lookahead: PASS. `build_daily_weights()` forms rebalance weights using data through the rebalance-day close, and `backtest()` applies `w.shift(1)` before multiplying by daily returns (`k1347.py:172`, `k1347.py:220`).
- CVaR contribution math: PASS. Historical tail scenarios are selected from portfolio returns, and `CRC_i = w_i * (-E[R_i | tail])`; contributions sum to CVaR by linearity (`k1347.py:111`, `k1347.py:137`).
- Optimizer fallback and diagnostics: PASS. SLSQP outputs are clipped/renormalized, equal-weight fallback exists on failure, and observed CVaR optimizer success rate is 1.0 (`k1347.py:152`, `k1347_results.json:cvar_rp_optimizer_success_rate`).
- DM / bootstrap evidence: PASS. DM uses aligned net returns after turnover costs, reports actual HAC nonzero lags, and bootstrap uses seed 42 (`k1347.py:223`, `k1347.py:288`, `k1347.py:335`).
- Stress-period accounting: PASS after correction. 2018Q4 has no common OOS observations after CVaR warmup, so the result reports 1/3 evaluable stress periods rather than 1/4 (`k1347_results.json:n_stress_periods_evaluable`).

## Residual Caveat

SLSQP/BLAS floating-point path can move the last few decimals across reruns, but the sign, significance, and verdict are stable: CVaR-RP remains worse on Sharpe and improves stress MDD in only 1/3 evaluable periods.
