# K1351: Oil Volatility Spillover to Equity Volatility

## Research Question

`CL=F` / `USO` 的原油波動率 shock，是否在隔日對 `SPY`、`XLE`、`XOP`
的 realized variance 有可驗證的 OOS 預測增量？

本實驗刻意不問「油價漲跌是否影響股市」，而是問 **oil vol-of-vol / RV state**
是否能在已控制目標 ETF 自身 HAR-RV 狀態後，改善 equity / energy-equity variance
forecast。

## Prior Work Check

- `K628b`：跨資產 Diebold-Yilmaz / Granger network 已含 `USO`，但重點是網路傳染與
  平滑 spillover，不是 OOS HAR-X 預測。
- `trending_2026_06_12_oil_vix_spillover`：事件型 oil / VIX / equity 同步診斷，
  下一日 lead-lag correlation 偏弱。
- `K1481`：crude inventory surprise 對 `CL=F` 自身 RV 的 pilot，非 equity spillover。

## Literature

1. Arouri, Jouini, and Nguyen (2011), *Journal of International Money and Finance*:
   oil-stock sector volatility transmission can be significant and sector-dependent.
   https://ideas.repec.org/a/eee/jimfin/v30y2011i7p1387-1405.html
2. Diebold and Yilmaz (2012), *International Journal of Forecasting*:
   directional volatility-spillover framework across asset classes.
   https://econpapers.repec.org/article/eeeintfor/v_3a28_3ay_3a2012_3ai_3a1_3ap_3a57-66.htm
3. Degiannakis, Filis, and Arora (2017), EIA working paper:
   survey evidence is heterogeneous, with sector-level differences and oil-volatility transmission.
   https://www.eia.gov/workingpapers/pdf/oil_prices_stockmarkets.pdf
4. Malik and Hammoudeh (2007), *International Review of Economics & Finance*:
   early shock / volatility transmission evidence between oil and equity markets.

## Data

- Source: Yahoo Finance via `yfinance`.
- Requested window: `2010-01-01` to `2026-06-19` exclusive.
- Actual common panel: `2010-01-04` to `2026-06-17`, `4139` common trading days.
- OOS evaluation: `2018-01-02` to `2026-06-17`, `2126` observations per spec.
- Oil proxies: `CL=F`, `USO`.
- Targets: `SPY`, `XLE`, `XOP`.
- RV proxy: annualized close-to-close squared **simple** return.

Simple returns are used because front-month WTI (`CL=F`) briefly traded negative in April 2020;
log returns would silently create invalid oil-volatility observations around the most important
stress episode.

## Design

Baseline HAR:

`log(RV_target,t) ~ 1 + log(RV_target,t-1) + log(RV_target,5,t-1) + log(RV_target,22,t-1)`

Augmented HAR-X:

`baseline + log(RV_oil,t-1) + log(RV_oil,5,t-1) + log(RV_oil,22,t-1) + log(oil_vov_22,t-1)`

Forecasts are expanding-window OOS log-OLS forecasts with `MIN_TRAIN_OBS=756` and monthly
refits (`21` trading days). Loss is non-negative QLIKE ratio loss:

`y / h - log(y / h) - 1`

The pointwise test series is:

`baseline_QLIKE - augmented_QLIKE`

so positive HAC t means the oil-volatility augmented model is better.

## Lookahead Policy

- All target HAR features are shifted one trading day before target-date alignment.
- All oil features are built as `oil_raw.shift(1)` before being aligned with target variance.
- For target date `t`, expanding OLS training rows are `df.iloc[:pos]`, strictly earlier than `t`.
- Random procedures use `seed=42`.

## Success Criteria

A spec passes only if all three hold:

- OOS QLIKE improvement `>= 1%`.
- Newey-West / Harvey t-stat on loss improvement `> 3.0`.
- Stationary-bootstrap 95% CI lower bound for mean loss improvement is positive.

## Results

Verdict: **NULL_NO_HARVEY_PASS**

No `CL=F` / `USO` to `SPY` / `XLE` / `XOP` spec passed the pre-registered QLIKE +
Harvey + bootstrap gate.

| Oil proxy | Target | QLIKE improvement | HAC t | Bootstrap 95% CI | Gate |
|---|---:|---:|---:|---:|---|
| `CL=F` | `SPY` | `+1.51%` | `+2.18` | `[+0.0118, +0.1217]` | fail Harvey |
| `CL=F` | `XLE` | `-0.17%` | `-0.28` | `[-0.0481, +0.0353]` | fail |
| `CL=F` | `XOP` | `-0.94%` | `-0.53` | `[-0.1666, +0.0485]` | fail |
| `USO` | `SPY` | `+0.94%` | `+1.09` | `[-0.0255, +0.1188]` | fail |
| `USO` | `XLE` | `-2.34%` | `-1.55` | `[-0.2131, -0.0021]` | fail |
| `USO` | `XOP` | `-2.19%` | `-1.05` | `[-0.2430, +0.0240]` | fail |

The best candidate is `CL=F -> SPY`: it clears the 1% QLIKE threshold and has a positive
bootstrap CI, but its HAC t-stat is only `2.18`, below the project Harvey threshold of `3.0`.
This is weak evidence, not a research-program finding.

High oil-vol regimes are descriptively associated with higher target variance:

- `CL=F` high-vol days: `SPY` variance ratio `3.08x`, HAC t `2.19`.
- `USO` high-vol days: `SPY` variance ratio `5.12x`, HAC t `1.96`.
- Energy-equity targets also show high-vol ratios around `3.0x` to `4.4x`, but the predictive
  HAR-X increment is negative or insignificant.

Interpretation: oil volatility co-moves with equity stress, especially for SPY in stress windows,
but lagged oil RV / vol-of-vol did not provide robust next-day OOS forecast improvement after
the target ETF's own HAR state is controlled.

## Files

- `k1351.py`
- `k1351_results.json`
- `fig_k1351_oos_qlike.png`
- `fig_k1351_oil_vol_context.png`
- `codex_review.md`

## Reproduce

```bash
uv run python experiments/k1351/k1351.py
```
