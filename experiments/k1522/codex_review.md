# Codex Review: K1522

- Task: `research_factor_zoo_bias_corrected_etf_proxy_oos`
- Date: 2026-06-17
- Verdict: `PASS_NULL_RESULT`

## Checks

- **Lookahead**: PASS. Returns are computed from adjusted close and scored through `future_returns = returns.shift(-1)`. The headline bias-corrected variant uses `signal.shift(1)`, so the signal uses information no later than `t-1` for the return from `t` to `t+1`. The naive variant is reported only for audit comparison and is explicitly not the headline.
- **Bias-correction claim**: PASS with limitation. The script does not claim to implement full Open Bond Asset Pricing / TRACE correction. It labels the method as an ETF-proxy extra-lag correction that breaks the shared price denominator.
- **Formal test**: PASS. Strategy returns are tested with `volpred.stats.model_evaluation.strategy_dm_test(..., h=5, loss_fn="negative_return")`. Harvey pass requires `DM t < -3` and positive annualized return.
- **Claim strength**: PASS. Results report `NULL_ETF_PROXY`; no corrected signal passes Harvey. The best corrected signal is `carry_252` with Sharpe `0.2512` and DM `t=-0.9778`, far below threshold.
- **Reproducibility**: PASS. The experiment has `README.md`, `k1522.py`, `k1522_results.json`, and `k1522_factor_audit.png`.

## Risks

- ETF cross-section is small and combines duration, credit quality, dividend mechanics, and ETF microstructure. It is not bond-level evidence.
- The carry proxy is inferred from adjusted-close versus close returns, not bond-level yield or option-adjusted spread.
- Long-short ETF returns ignore financing, borrow, and creation/redemption frictions.

## Conclusion

K1522 is safe as a null/insufficient-evidence ETF-proxy audit. It should not be cited as a direct replication of the corporate-bond factor-zoo literature, and it does not support a publication-grade positive factor-premium claim.
