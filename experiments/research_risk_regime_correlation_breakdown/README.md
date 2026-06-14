# Risk-regime Correlation Breakdown Early Detection

## Motivation

2026 年的 60/40 討論再次把股債相關性推到前台：如果股票與長債同跌，傳統配置的防禦假設會失效。`research_program.md` 的 backlog 題目要求檢查：

> SPY/TLT 60 日 rolling correlation 與 correlation instability，是否能提早偵測股債相關 regime breakdown？

本實驗把題目收斂成早期預警檢定，而不是交易策略。核心問題是：在尚未進入正相關 breakdown 時，前一日可見的「相關性波動」是否預示未來 21 日進入正相關狀態。

## Difference vs Prior Work

- `K534`：SPY/GLD 相關動態與 VIX regime，結論傾向「相關動態難預測」。
- `K1387`：SPY/TLT/GLD Gaussian vs Student-t DCC ERC，配置改善為 NULL。
- `K1460`：簡單 stock-bond correlation-regime 60/40 adaptation 未能打敗 best static benchmark。
- 本實驗：不直接測配置績效，改測 **correlation-volatility 是否是 regime transition 的 lagged early-warning state variable**。

## Literature Consulted

1. CFA Institute, *Why Static Portfolios Fail When Risk Regimes Change* (2026)  
   Motivates stock-bond co-movement as a portfolio resilience problem.
2. AQR / Journal of Portfolio Management, *A Changing Stock-Bond Correlation: Drivers and Implications* (2023)  
   Frames stock-bond correlation as a key portfolio-risk parameter driven by growth vs inflation uncertainty.
3. Andersson, Krylova, Vahamaa, *Flight-to-quality or Contagion? An Empirical Analysis of Stock-bond Correlations* (2006)  
   Defines negative stock-bond correlation as flight-to-quality and positive co-movement as contagion-like behavior.
4. CFA Institute Research Foundation, *The Performance of the 60/40 Portfolio: A Historical Perspective* (2024)  
   Documents 2022 as a major stress case because bonds did not protect when stocks fell.

## Data

- Source: `yfinance`
- Tickers: `SPY`, `TLT`
- Price field: adjusted daily close
- `auto_adjust=True` is intentional because the target is ETF total-return behavior.
- Effective sample after rolling / expanding warmup and forward-window drop: `2005-04-29` to `2026-05-13`
- Analysis sample: `n=5,293`
- At-risk transition sample: `n=4,810`

## Method

### State variables

- `corr60_spy_tlt`: 60 trading day rolling correlation of daily log returns.
- `corr_vol21`: 21 trading day standard deviation of daily changes in `corr60_spy_tlt`.
- High correlation-volatility signal:
  - `corr_vol21_lag1 = corr_vol21.shift(1)`
  - `corr_vol_q80_lag1 = expanding_q80(corr_vol21).shift(1)`
  - `high_corr_vol_signal = 1[corr_vol21_lag1 >= corr_vol_q80_lag1]`

### Regime definition

- Hedging / negative correlation: `corr60 <= -0.20`
- Decoupled / near zero: `-0.20 < corr60 < +0.20`
- Positive-correlation breakdown: `corr60 >= +0.20`

### Primary outcome

Among days not already in positive breakdown:

- `transition_to_positive_corr_21 = 1` if the future `t+1..t+21` max of `corr60` reaches `+0.20`.

### Inference

- Group mean difference by `high_corr_vol_signal`.
- Stationary bootstrap, `B=1000`, mean block `21`.
- HAC(21) linear probability model:
  - `transition_to_positive_corr_21 ~ high_corr_vol_signal + corr60_lag1 + rv21_spy_lag1 + rv21_tlt_lag1`

### DCC-GARCH

The script also estimates a full-sample bivariate DCC-GARCH sanity check. This is **descriptive only**. It is not used as a predictive feature because full-sample GARCH/DCC parameter estimation would leak future information into past signals.

## Anti-Bug Rules

- All formal predictive features are explicit `.shift(1)`.
- Forward outcomes use only `t+1..t+21`.
- Expanding quantile threshold is shifted by one day.
- DCC-GARCH output is not used in the prediction test.
- `seed=42` is fixed for bootstrap and NumPy.
- Overlapping forward windows are evaluated with HAC(21) and stationary bootstrap, not iid inference.

## Results

### Descriptive

- Mean 60d SPY/TLT correlation: `-0.263`
- Median 60d SPY/TLT correlation: `-0.299`
- Min / max 60d correlation: `-0.851` / `+0.435`
- Positive breakdown share: `9.14%`
- Lagged high corr-vol share: `25.69%`
- Base transition rate among at-risk days: `6.92%`

### H1: corr-vol predicts positive-correlation transition

Raw event rates:

- High corr-vol: `9.60%`
- Not high: `6.08%`
- Difference: `+3.53 pp`

But this does **not** survive the formal gate:

- Stationary bootstrap 95% CI: `[-1.36 pp, +8.90 pp]`
- Bootstrap two-sided `p=0.188`
- HAC(21) high-signal coefficient after controls: `-2.11 pp`, `p=0.459`

Interpretation: high corr-vol days visually and descriptively cluster near transitions, but the effect is not robust after serial dependence and current correlation level are accounted for.

### H2: corr-vol predicts worse 60/40 short-horizon drawdown

- High corr-vol forward 21d worst 60/40 cumulative return: `-1.49%`
- Not high: `-1.58%`
- Difference: `+0.084 pp`
- Bootstrap CI: `[-0.426 pp, +0.558 pp]`
- HAC(21) high-signal coefficient: `+0.415 pp`, `p=0.103`

No evidence that the signal predicts worse next-21d 60/40 drawdown.

### DCC-GARCH descriptive check

- DCC `a=0.0595`, `b=0.9224`, persistence `0.9819`
- DCC rho vs 60d rolling correlation correlation: `0.843`
- DCC positive-breakdown share: `6.99%`

This supports that the rolling-correlation proxy is tracking a similar dynamic-correlation state, but it is not evidence of predictive power.

## Verdict

`NULL`

The experiment finds a descriptive raw difference, but not a robust early-warning signal. The honest conclusion is:

1. SPY/TLT correlation breakdown regimes are real and visible in both rolling correlation and DCC-GARCH.
2. Lagged correlation-volatility alone does not robustly forecast transition into positive stock-bond correlation.
3. The current level of correlation is much more informative than the extra corr-vol dummy.
4. No article should claim a working early-warning detector from this experiment.

## Files

- `research_risk_regime_correlation_breakdown.py`
- `research_risk_regime_correlation_breakdown_results.json`
- `fig_correlation_breakdown_signal.png`
- `fig_event_rate_and_drawdown.png`
- `fig_dcc_vs_rolling_correlation.png`
- `codex_review.md`
