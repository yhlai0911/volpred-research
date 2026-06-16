# K1516 - Fiscal-Monetary Regime and Stock-Bond Correlation

**Verdict**: `NULL`

Lagged fiscal-deficit and Fed-tightening regime variables do **not** provide
robust out-of-sample predictive power for SPY/TLT forward 60-day correlation.
The high-deficit x tightening regime lines up with more positive future
correlation in 2023-2024, but the evidence is descriptive, not a publishable
forecasting edge.

## Research Question

Can a lagged "high fiscal deficit x monetary tightening" regime predict that
stock-bond correlation will turn positive, and can that signal improve a simple
60/40 allocation?

This tests the fiscal/monetary mechanism suggested by the stock-bond correlation
literature, but uses only public daily ETF prices and low-frequency FRED macro
series.

## Data

- Prices: yfinance adjusted close for `SPY` and `TLT`
- Macro: FRED `MTSDS133FMS` monthly federal surplus/deficit, `GDP`, `FEDFUNDS`
- Usable rows after lags and target construction: **5,081**
- Train: **2006-01-05 to 2019-10-04**, 3,461 rows
- OOS: **2020-01-02 to 2026-03-18**, 1,560 rows
- Target: forward 60-trading-day SPY/TLT return correlation

## Methodology

The baseline model predicts forward 60-day SPY/TLT correlation with only the
lagged 60-day realized correlation.

The augmented model adds:

- lagged deficit/GDP
- lagged Fed funds rate
- lagged 1-year Fed funds change
- high-deficit dummy
- tightening dummy
- high-deficit x tightening dummy
- low-deficit x easing dummy

Both models are fixed-window OLS estimated on the training sample only.

Economic test: a daily 60/40 strategy moves the 40% TLT sleeve to cash on the
next trading day when the lagged high-deficit x tightening signal is active.

## Lookahead Defenses

1. FRED monthly deficit data use a 45-calendar-day release lag.
2. FRED quarterly GDP uses a 120-calendar-day release lag from quarter start.
3. FRED monthly FEDFUNDS uses a 35-calendar-day release lag.
4. All macro and regime features are shifted by one trading day before use.
5. Target at date `t` uses only returns from `t+1` through `t+60`.
6. Training rows require `target_end < 2020-01-01`.
7. Allocation signal is shifted again before applying to same-day returns.

## Results

| Metric | Baseline corr60 | Augmented fiscal-monetary |
|---|---:|---:|
| OOS R2 | -0.5452 | -2.3805 |
| OOS RMSE | 0.3276 | 0.4846 |
| Positive-corr AUC | 0.6930 | 0.6978 |

DM test on squared forecast errors:

- `t = +5.988`, `p = 2.64e-09`
- Sign convention: negative would favor augmented model
- Interpretation: augmented model is significantly **worse** than the baseline

Regime descriptive:

- High-deficit x tightening days in OOS: **181** (11.6%)
- Future positive-correlation rate in regime: **77.9%**
- Future positive-correlation rate outside regime: **48.9%**
- HAC linear probability t-stat: **1.69**, p=0.091

Allocation:

- Static 60/40 Sharpe: **0.458**
- Regime switch Sharpe: **0.550**
- Strategy DM t: **-1.42**, p=0.155

The strategy improvement is not statistically strong enough to treat as an edge.

## Interpretation

The fiscal-monetary regime label captures a visually meaningful slice of
2023-2024, when high deficits and tightening coincided with positive stock-bond
correlation. But it does not survive as a stable OOS forecasting model.

The strongest empirical statement supported here is narrow:

> In this public-data daily ETF specification, high-deficit x tightening is a
> useful descriptive label for the 2023-2024 positive-correlation episode, but
> not a robust predictor or allocation rule.

## Caveats

1. Macro data are low-frequency and revised; release lags are conservative but
   not vintage-real-time.
2. `MTSDS133FMS` is a monthly cash-flow proxy, not a structural fiscal-regime
   estimate.
3. TLT starts in 2002, so the experiment cannot test the positive-correlation
   1970s-1990s regime discussed in the literature.
4. Forward 60-day correlation is noisy and overlapping, so HAC inference is
   necessary and the effective OOS sample is smaller than 1,560.
5. The allocation test uses cash for the TLT sleeve and ignores transaction
   costs, tax effects, and risk-free cash yield.
6. Low-deficit x easing has zero OOS days under this threshold design, so it is
   not an informative contrast regime in 2020-2026.

## References

1. Li, Zha, Zhang, and Zhou. "Does Fiscal Policy Matter for Stock-Bond Return
   Correlation?" NBER Working Paper 27861. https://www.nber.org/papers/w27861
2. Campbell, Sunderam, and Viceira. "Inflation Bets or Deflation Hedges?" NBER
   Working Paper 14701 / Critical Finance Review. https://www.nber.org/papers/w14701
3. CFA Institute Research Foundation. "Macroeconomic Drivers of Stocks and
   Bonds" (2025).
   https://rpc.cfainstitute.org/research/foundation/2025/macroeconomic-drivers

## Reproducibility

```bash
uv run python experiments/k1516_fiscal_regime_stock_bond_corr/k1516.py
```

Outputs:

- `k1516_results.json`
- `k1516_plots.png`
