# Codex Self-Review — research_rp_f1168bab52

Date: 2026-06-17

Verdict: `PASS_WITH_CAVEATS`

## Scope

Source-code-level review of `research_rp_f1168bab52.py` and generated `research_rp_f1168bab52_results.json`.

## Checks

1. Lookahead leakage: PASS
   - VIX and VIX3M signals are explicitly lagged: `vix_lag1`, `vix3m_lag1`.
   - trailing 20-day return is `rolling(20).sum().shift(1)`.
   - macro controls use `shift(1)` or 21-day changes shifted by one day.
   - future RV labels start at `t+1`.

2. Forward-label OOS leakage: PASS
   - expanding OOS training set uses only rows whose `label_end_* < forecast_origin`.
   - This avoids the K1337 failure mode where forward labels overlap the prediction date.

3. Statistical claim alignment: PASS
   - README numbers are copied from `research_rp_f1168bab52_results.json`.
   - QLIKE is treated as the primary volatility forecast loss.
   - Verdict is not upgraded despite positive MSE R2 because QLIKE rejects the augmented model in the wrong direction and the trading rule underperforms.

4. Trading rule timing: PASS
   - Monthly weights are formed from lagged VIX/VIX3M and lagged past-return regime.
   - Weights are applied to the next 21 trading days' SPY return.

5. Methodology caveats: REQUIRED
   - VIX/VIX3M are index proxies, not option-chain model-free variance swap rates.
   - Two-maturity monthly panel is small; the FMB-style term slope is a reduced-form diagnostic.
   - Daily close-to-close RV is not high-frequency realized variance.

## Bottom Line

The experiment is reproducible and lookahead-clean for the stated free-data design. The evidence should be recorded as `MIXED_DIAGNOSTIC_NOT_TRADABLE`: some raw term-structure asymmetry appears, but it does not survive controls, OOS QLIKE, or the trading-rule gate.
