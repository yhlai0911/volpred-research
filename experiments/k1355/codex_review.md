# K1355 Codex Review

Date: 2026-06-21

Verdict: CONDITIONAL_PASS as an experiment artifact; research conclusion is
MIXED_WEAK / proxy-only.

## Scope Reviewed

- `experiments/k1355/K1355.py`
- `experiments/k1355/K1355_results.json`
- `experiments/k1355/README.md`

## Findings

1. LOOKAHEAD: PASS.
   - Liquidity-proxy model features are explicitly lagged (`*_l1`) before
     predicting same-day proxy spread.
   - Volatility-channel predictors use explicit system-factor lag:
     `factor_df[f"{name}_signal"] = factor_df[name].shift(1)`.
   - OOS split is fixed at 2020-01-01; volatility models train only on pre-2020
     rows and predict 2020 onward.

2. TARGET / PROXY HONESTY: CONDITIONAL_PASS.
   - The code and README clearly state that true CPQS is unavailable from
     yfinance because bid/ask quotes are missing.
   - The experiment labels the constructed variable as `cpqs_like` and caps the
     claim at proxy-only. This is necessary and correct.

3. INFERENCE: CONDITIONAL_PASS after fix.
   - Initial pooled asset-day DM would have overstated significance by treating
     same-day cross-asset losses as independent.
   - The final code uses date-clustered cross-asset mean loss differences for
     pooled DM and keeps the stacked asset-day DM only as a diagnostic.
   - Final primary GB result: pooled QLIKE improves by 10.31%, but
     date-clustered DM t = -2.24, which does not pass the project Harvey gate
     of -3.0. Per-asset Harvey passes are 2/8.

4. METHOD / CLAIM ALIGNMENT: PASS.
   - The verdict is `MIXED_WEAK`, not PASS.
   - The result supports only an exploratory yfinance proxy channel. It does not
     validate true CPQS, true bid-ask spread estimation, or trade-level
     liquidity without bid/ask or high-frequency labels.

## Final Review Decision

No remaining correctness bug found that invalidates the saved JSON. The
artifact is acceptable as a completed proxy experiment, but it should not be
promoted as a strong liquidity-discovery claim.
