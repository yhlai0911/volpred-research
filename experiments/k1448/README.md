# K1448: Inflation-Expectation Regime and Forward Stock/Bond Volatility

- **K id**: K1448
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_regime_vol_tip_ief_tlt_regime_vol_yfinance`

## Question

用 `TIP/IEF` 與 `TIP/TLT` 的相對表現當作 **通膨預期 proxy**，
檢驗「通膨預期上升 vs 下降」 regime 下，
未來 21 日的：

- `SPY` forward realized vol
- `IEF` forward realized vol
- `TLT` forward realized vol
- `SPY-IEF` forward correlation
- `SPY-TLT` forward correlation

是否有穩健差異。

## Motivation

這題不是要重做 CPI / breakeven inflation 正規 macro 模型，
而是要測一個更便宜、可日更、可直接拿 `yfinance` 跑的 proxy：

- `TIP/IEF`：短中天期 nominal bond 對 TIPS 的相對表現
- `TIP/TLT`：長天期 nominal bond 對 TIPS 的相對表現

如果這兩個 proxy 真反映通膨預期變化，
那麼理論上可能看到：

1. 股票或長債的 forward vol 在 rising regime 較高
2. 股債相關在 rising regime 較不負，甚至轉正

## Literature Preamble

本題先對齊三個文獻方向，再設計實驗：

1. **Estrella and Mishkin (1998)**  
   term spread 對 recession 有預測力，但主要是月到季的 macro horizon，
   不等於短天期 equity-vol predictor。

2. **Campbell, Sunderam, and Viceira (2017)**  
   nominal bond 的風險屬性會隨 inflation / deflation state 改變；
   這提供「股債相關與債券避險能力會隨 inflation regime 漂移」的理論背景。

3. **Baele, Bekaert, and Inghelbrecht (2010)**  
   stock-bond comovement 不是常數，會被 macro / risk state 驅動；
   所以通膨 proxy regime 值得拿來檢驗 forward correlation。

本實驗因此聚焦在：
**inflation-expectation proxy 是否能當作 short-horizon vol/corr regime signal。**

## Data

- Source: `yfinance`
- Tickers: `TIP`, `IEF`, `TLT`, `SPY`
- Period: 2010-01-04 to 2026-06-09
- Joint daily observations: 4,133

## Method

### Signal

- `tip_over_ief = log(TIP / IEF).diff(63).shift(1)`
- `tip_over_tlt = log(TIP / TLT).diff(63).shift(1)`

`63d` 約等於一季。
`shift(1)` 保證 day `t` 的 regime 只用到 `t-1` 已知資訊。

### Regimes

- `rising`: lagged 63d log-ratio change > 0
- `falling`: lagged 63d log-ratio change <= 0

### Outcomes

- Forward 21d annualized RV:
  - `SPY`
  - `IEF`
  - `TLT`
- Forward 21d rolling correlation:
  - `SPY-IEF`
  - `SPY-TLT`

定義都用 `t+1 .. t+21` 的報酬，因此沒有 same-day leak。

### Statistical inference

主檢定：

- `OLS(outcome ~ rising_dummy)` with **HAC / Newey-West**
- `maxlags = 21`

原因：

- forward 21d RV 與 forward 21d rolling corr 都是重疊視窗
- 若當成 iid 做普通 t-test，顯著性很容易被誇大

Multiple testing:

- 2 proxies × 5 outcomes = 10 primary contrasts
- Bonferroni 與 BH 都報告

## Files

- `k1448.py`
- `k1448_results.json`
- `figures/forward_outcomes_by_regime.png`
- `figures/inflation_proxy_ratios.png`

## Reproduce

```bash
uv run python experiments/k1448/k1448.py
```

## Honest Limits

- `TIP/IEF`、`TIP/TLT` 只是 market-implied proxy，不是官方 breakeven inflation series
- regime 切法用 sign，屬低自由度 descriptive design，不是最優 threshold 搜尋
- 這題回答的是 short-horizon forward RV / corr，不直接等於 medium-horizon macro forecasting
- 若要更強 inference，下一步應補：
  - 與 `^VIX` 聯合條件化
  - rolling ex-ante z-score thresholds
  - FRED breakeven inflation 對照版
