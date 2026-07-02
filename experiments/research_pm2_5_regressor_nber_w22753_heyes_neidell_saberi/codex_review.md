# Codex Source Review

- **Experiment**: `research_pm2_5_regressor_nber_w22753_heyes_neidell_saberi`
- **Review date**: 2026-07-02
- **Reviewer**: Codex
- **Verdict**: PASS for a conservative NULL pilot; not sufficient for a production claim about monitor-level PM2.5 or intraday RV.

## Checks

- Experiment three-piece set exists: README, script, results JSON.
- Data sources are recorded in the script and results JSON.
- AQI signal uses explicit `signal.shift(1)` before market-day merge.
- Market HAR / VIX features are lagged before prediction.
- OOS loop trains only on rows before forecast date.
- QLIKE orientation is `actual / predicted - log(actual / predicted) - 1`.
- Random bootstrap diagnostics use fixed `seed=42`.
- Result does not overclaim: primary conclusion is NULL, and event diagnostics are labeled as diagnostic / underpowered where appropriate.

## Residual Risks

- County AQI is not monitor-level PM2.5 concentration.
- Daily Garman-Klass variance is a proxy, not intraday realized variance.
- No weather, traffic, seasonality, macro-news, or wildfire controls.
- AQI top-decile result is opposite-signed and may be seasonal; do not publish it as a causal finding.

## Publication Use

This experiment may support an internal knowledge entry that a lag-clean daily AQI proxy did not improve SPY daily variance prediction after HAR/VIX controls. It should not be cited as evidence that PM2.5 has no same-day return or intraday volatility effect.
