# K1508: AI Power Demand and Utility/Grid ETF Volatility

## Why This Exists

The pending queue generated this topic as `K1345`, but `K1345` is already used by `experiments/K1345_pre_fomc_iv_drift/`. To avoid K-id collision, this experiment executes the same research question as `K1508`.

Research question: did the AI/data-center electricity-demand narrative reprice utilities and grid/infrastructure ETFs from low-vol defensive assets into higher-vol growth/power-infrastructure assets?

## Data

- ETF prices: yfinance adjusted close for `XLU`, `VPU`, `GRID`, `PAVE`, with `SPY` and `QQQ` as benchmarks.
- Power activity proxy: FRED `IPG2211S`, Industrial Production: Utilities: Electric Power Generation, Transmission, and Distribution.
- EIA limitation: EIA v2 API requires an API key. The public EIA `ELEC.zip` bulk file is about 226 MB, so this hourly-run experiment does not download it. The experiment records this as a limitation and does not pretend `IPG2211S` is a direct EIA load series.
- Sample starts 2016-01-01 and runs through the latest available yfinance/FRED observations at execution time.

## Literature / Source Preamble

- DOE / Lawrence Berkeley National Laboratory (2024), 2024 Report on U.S. Data Center Energy Use.
- IEA (2025), Energy and AI.
- Grid Strategies (2025), Power Demand Forecasts Revised Up.
- EIA Today in Energy (2026), Data center server energy use grows across the commercial sector.

## Method

Primary target is forward realized volatility over `t+1..t+21`, not same-day realized volatility.

Primary regression per ETF:

```text
log(fwd_rv21 ETF) - log(fwd_rv21 SPY)
  ~ post_ai_signal_shift1 + log_vix_lag1 + power_yoy_z_lagged
```

The AI date is 2022-11-30. `post_ai_signal_shift1` is explicitly shifted one trading day. The monthly power proxy is shifted two months for conservative publication lag, daily-forward-filled, then shifted one trading day.

Primary gate: at least 3 of 4 target ETFs must have `post_ai_signal_shift1` HAC `t > 3` and Bonferroni-style `p < 0.0125`.

## Lookahead Policy

- All signals use `.shift(1)` or a stricter availability lag.
- Target windows begin at `t+1`.
- No same-day signal is multiplied by same-day return.
- Seed is fixed at `42`.

## Outputs

- `k1508.py`
- `k1508_results.json`
- `k1508_panel.csv`
- `figures/k1508_relative_forward_vol.png`
- `codex_review.md`

## Success Criteria

PASS only if the post-AI relative-vol dummy passes the primary gate. Otherwise the result is reported as NULL or MIXED_WEAK, with limitations preserved.

## Result

Verdict: **NULL**.

The primary gate passed for `0/4` ETFs. XLU and VPU had positive post-AI relative-vol point estimates, but their HAC t-statistics were only about `2.10` and `2.04`, below the Harvey-style `t > 3` threshold and below the Bonferroni gate. GRID and PAVE did not support the hypothesis.

The result should be read as a negative screen on this free-data specification, not as evidence that data-center load cannot matter. The main limitation is measurement: this run uses reproducible FRED `IPG2211S` power-activity data because EIA v2 requires an API key and the public EIA electricity bulk file is too large for an hourly task.
