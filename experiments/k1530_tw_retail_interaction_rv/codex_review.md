# K1530 Codex Review

Reviewer: Codex CLI
Review date: 2026-06-17

## Verdict

Implementation: PASS.

Empirical finding: `MIXED_PROXY_WEAK_OOS`.

Do not market this as a confirmed retail-participation volatility predictor.
The result is an ETF-proxy pilot with mixed coefficient signs and no
Harvey-strength OOS QLIKE pass.

## Checks Performed

- Ran:
  `uv run python experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py`
- Ran:
  `uv run python -m py_compile experiments/k1530_tw_retail_interaction_rv/k1530_tw_retail_interaction_rv.py`
- Verified required artifacts:
  - `README.md`
  - `k1530_tw_retail_interaction_rv.py`
  - `k1530_tw_retail_interaction_rv_results.json`
  - `k1530_tw_retail_interaction_rv.png`
- Checked results/code for `NaN` / `Infinity`; none found.

## Lookahead Review

Pass.

- Target is day-t 0050 realized variance.
- Retail residual share and margin activity are converted to z-scores, then
  explicitly lagged with `.shift(1)`.
- Recent-return and negative-return controls are also lagged:
  `ret5_lag1` and `neg_ret5_lag1`.
- Interactions are built from lagged retail proxy × lagged negative-return
  variable.
- This satisfies `signal from t-1, return/RV at t`.

## Statistical Review

Pass with caveats.

- Four headline interaction tests are reported: 2 targets × 2 retail proxies.
- Bonferroni alpha is disclosed as 0.0125.
- Two `r2_ann` interactions pass Bonferroni:
  - residual retail: HAC t=-3.9515, p=0.000078
  - margin activity: HAC t=+2.9518, p=0.003160
- No OOS model clears Harvey:
  - best OOS DM t is -2.7765 for Parkinson + residual retail.
  - Harvey threshold requires DM t < -3 for augmented model superiority.

## Framing Caveats

- Residual-retail `r2_ann` coefficient is opposite the simple hypothesis:
  high residual-retail × recent losses is associated with lower, not higher,
  log squared-return variance in the full-sample HAC regression.
- Margin activity has the expected positive sign for `r2_ann`, but its OOS DM
  t is only -1.5288.
- Parkinson target OOS QLIKE improvements are economically nontrivial, but the
  interaction coefficients do not pass Bonferroni.
- The proxy is 0050 ETF residual participation, not official full-market retail
  share.

## Final

The code is acceptable and the null/mixed framing is honest. The only valid
research takeaway is that 0050 public retail-like proxies contain suggestive
but unstable information; stronger claims require official retail-share data,
stock-level panel tests, or intraday order-flow data.
