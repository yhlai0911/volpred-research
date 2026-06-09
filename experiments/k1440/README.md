# K1440: Yield-Curve Slope Regimes and Forward SPY Realized Volatility

- **K id**: K1440
- **Status**: completed, awaiting follow-up if promoted to article
- **Created**: 2026-06-10
- **Task source**: `research_regime_tnx_fvx_10y_5y_tnx_irx_regime_spy_realize`

## Question

用 `yfinance` 可直接取得的美債殖利率 proxy，
`^TNX - ^FVX`（10Y-5Y）與 `^TNX - ^IRX`（10Y-3M proxy），
檢驗殖利率曲線 **倒掛 / 平坦 / 陡峭** regime 下，
SPY **未來 21 日 realized vol** 是否有系統性差異。

## Why This Exists

K871 已做過較完整的 predictive-regression 版本，結論是：

- 殖利率曲線對 forward RV 的訊號在控制 VIX 後極弱
- OOS R² 沒有改善
- 倒掛不等於短期 vol spike

K1440 不重做 regression，而是改成：

1. **只用 yfinance**，避免 FRED 依賴
2. **做 regime-conditioned distribution**
3. **主檢定改用 HAC/Newey-West**

這樣可以直接回答：「倒掛 / 陡峭曲線，是否真的對應較高的未來 SPY 波動率分布？」

## Literature Preamble

本題的文獻定位不是「殖利率曲線是否預測 recession」本身，
而是「這個 macro term-spread 指標，能否轉化成可見的 equity vol regime」。

實驗前對齊的 3 個文獻方向：

1. **Estrella and Mishkin (1998)**：殖利率曲線是 recession leading indicator。
   這提供 macro 先驗，但不等於短天期 equity vol predictor。
2. **Estrella and Trubin / New York Fed recession-probability line**：
   真正有效的訊號通常是月到季的 business-cycle horizon，不是 1 個月內的股市波動。
3. **K871 / 專案既有 null 線**：
   本專案已看到「curve 對 vol 的訊號若存在，也很容易被 VIX 吸收」。

所以 K1440 的可反駁假說是：
即使 regression NULL，**曲線 regime** 可能仍對未來 SPY RV 的條件分佈有可見差異。

## Data

- Source: `yfinance`
- Tickers: `^TNX`, `^FVX`, `^IRX`, `SPY`
- Period: 2010-01-04 to 2026-06-09
- Joint daily observations: 4,131

## Method

### Outcome

- SPY future 21-day realized vol
- 定義：`log_ret.shift(-1).rolling(21).std() * sqrt(252)` 再對齊到 day `t`
- 也就是 day `t` 的 outcome 使用 `t+1 .. t+21` 的報酬

### Regime variables

- `slope_10y5y = ^TNX - ^FVX`
- `slope_10y3m = ^TNX - ^IRX`

### Lookahead protection

- 所有 regime signal 一律 `shift(1)`
- 所以 day `t` 的 bucket 只用到 `t-1` 已知的 slope
- outcome 則是 `t+1..t+21` 的 forward RV

### Regime buckets

對每個 slope proxy 都建三個 regime：

- `inverted`: lagged slope < 0
- `flat`: 0 到正 slope 的 75th percentile
- `steep`: 正 slope 的 top quartile

這是 **descriptive full-sample bucket**，不是即時交易 cut-off。

### Statistical tests

主檢定：

- `OLS(rv ~ regime_dummies)` with **HAC / Newey-West**
- `maxlags = 21`
- baseline = `flat`

輔助檢定：

- Welch t-test（只做描述，不當最終結論）

Multiple testing:

- 2 proxies × 2 contrasts = 4 HAC contrasts
- Bonferroni `alpha = 0.05 / 4 = 0.0125`

## Main Results

### 10Y-5Y proxy: `^TNX - ^FVX`

- `q75(positive slope) = 1.016`
- Regime counts: inverted 437, flat 2,749, steep 923
- Mean forward RV:
  - inverted: 0.1656
  - flat: 0.1424
  - steep: 0.1510
- **Naive Welch**:
  - inverted vs flat `t=6.19`, `p=9.7e-10`
  - steep vs flat `t=2.73`, `p=0.0065`
- **HAC**:
  - inverted vs flat `coef=+0.0233`, `p=0.125`
  - steep vs flat `coef=+0.0086`, `p=0.521`

### 10Y-3M proxy: `^TNX - ^IRX`

- `q75(positive slope) = 2.173`
- Regime counts: inverted 614, flat 2,616, steep 879
- Mean forward RV:
  - inverted: 0.1394
  - flat: 0.1503
  - steep: 0.1415
- **Naive Welch**:
  - inverted vs flat `t=-2.51`, `p=0.0122`
  - steep vs flat `t=-2.81`, `p=0.0050`
- **HAC**:
  - inverted vs flat `coef=-0.0110`, `p=0.301`
  - steep vs flat `coef=-0.0089`, `p=0.477`

### Autocorrelation reality check

Forward 21d RV is extremely autocorrelated:

- `acf(1) ≈ 0.992`
- `acf(21) ≈ 0.497`

這正是 K1439 剛驗到的同類風險：
若只看一般 Welch / iid SE，顯著性很容易被重疊視窗誇大。

## Verdict

**NULL**

0/4 HAC regime contrasts survive Bonferroni `alpha=0.0125`.

最值得記錄的發現不是「curve regime 有效」，
而是：

- `10Y-5Y` 的倒掛看起來在 naive Welch 下很顯著
- 但一旦承認 21d forward RV 的 overlap autocorrelation，用 HAC 後就不顯著

也就是說，這題再次支持：

1. **yield curve 對短期 equity vol 不是穩健 regime signal**
2. **overlapping RV + naive t-test 很容易做出假陽性**

## Files

- `k1440.py`
- `k1440_results.json`
- `figures/tnx_minus_fvx_forward_rv_boxplot.png`
- `figures/tnx_minus_irx_forward_rv_boxplot.png`

## Reproduce

```bash
uv run python experiments/k1440/k1440.py
```

## Honest Limits

- `^TNX/^FVX/^IRX` 是 Yahoo proxy，不是官方 FRED constant-maturity series
- `steep` bucket 是 full-sample descriptive q75，不是 real-time tradable threshold
- 這個實驗回答的是 **regime-conditioned distribution**，不是 forecast model race
- 若要做更強 inference，下一步應是：
  - rolling / expanding ex-ante thresholds
  - 與 VIX 聯合條件化
  - 或直接在 K871 framework 下做 VIX-controlled HAC regression
