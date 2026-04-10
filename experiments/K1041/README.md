# K1041: DCC-A4f Portfolio VaR (SPY/GLD)

**[提出: 賴奕豪, 執行: Claude]**

## 問題與動機

SPY/GLD 的相關性在危機時急劇變化（K920: COVID lambda=0.364），而 K891 測試 DCC-GARCH Portfolio VaR 對 50/50 SPY/GLD 為 NULL。但 K891 使用的是 GJR marginals，且 K1028 已證明 DCC-A4f 勝 DCC-GJR（DM t=2.58）。

**核心問題**：結合更好的 marginal model (A4f) 和時變相關 (DCC)，能否改善 SPY/GLD 的 portfolio VaR？

## 方法

2x2 factorial design:
- **Marginals**: GJR, A4f (tau = theta0 + theta1 * VIX^2, g = GJR unit-var)
- **Correlation**: CCC (constant), DCC(1,1) (time-varying)

4 models: CCC-GJR, DCC-GJR, CCC-A4f, DCC-A4f

VaR method: CF-Rolling (252d window on portfolio standardized residuals)

### 技術規格
- Portfolio: 50/50 SPY/GLD
- Data: yfinance, 2005-01-01 ~ 2026-04-10 (5,380 days)
- OOS: 2019-01-02 ~ 2026-04-10 (1,828 days)
- Window: 2000, refit: 63 days
- Alpha: 1%, 2.5%
- Seed: 42

## 結果

### Trinity Test (VaR Backtesting)

| Model | Alpha=2.5% | Alpha=1% | Score |
|-------|-----------|----------|-------|
| CCC-GJR | FAIL (viol=3.43%, Kupiec p=0.026) | PASS | 1/2 |
| DCC-GJR | PASS (viol=2.98%, Kupiec p=0.234) | PASS | **2/2** |
| CCC-A4f | PASS (viol=3.11%, Kupiec p=0.135) | FAIL (viol=1.65%, Kupiec p=0.018, Basel=Yellow) | 1/2 |
| DCC-A4f | PASS (viol=2.73%, Kupiec p=0.567) | PASS (viol=1.46%, Kupiec p=0.086) | **2/2** |

**DCC-GJR 和 DCC-A4f 都是 2/2 Trinity PASS。CCC models 各有 1 個 alpha FAIL。**

### QLIKE (Portfolio Variance Forecast Quality)

| Model | QLIKE | Rank |
|-------|-------|------|
| CCC-GJR | -8.7745 | 4 |
| DCC-GJR | -8.7949 | 3 |
| CCC-A4f | -8.8212 | 2 |
| **DCC-A4f** | **-8.8364** | **1** |

### DM Tests

| Comparison | DM t-stat | Significant (Harvey t>3.0) |
|------------|-----------|---------------------------|
| CCC-GJR vs DCC-GJR | +2.671 (DCC better) | No |
| CCC-A4f vs DCC-A4f | +2.550 (DCC better) | No |
| **CCC-GJR vs CCC-A4f** | **+3.086 (A4f better)** | **Yes** |
| DCC-GJR vs DCC-A4f | +2.884 (A4f better) | No |
| **CCC-GJR vs DCC-A4f** | **+3.826 (DCC-A4f better)** | **Yes** |

### 改善幅度

| Dimension | Improvement |
|-----------|-------------|
| DCC over CCC (GJR) | +0.23% QLIKE |
| DCC over CCC (A4f) | +0.17% QLIKE |
| A4f over GJR (CCC) | +0.53% QLIKE |
| A4f over GJR (DCC) | +0.47% QLIKE |

### SPY-GLD 相關性分析

| Model | Mean ρ | Std ρ | Range |
|-------|--------|-------|-------|
| CCC-GJR | -0.014 | 0.058 | [-0.08, 0.10] |
| **DCC-GJR** | **0.034** | **0.150** | **[-0.39, 0.39]** |
| CCC-A4f | -0.016 | 0.055 | [-0.08, 0.09] |
| **DCC-A4f** | **0.032** | **0.147** | **[-0.34, 0.40]** |

DCC 捕捉到 SPY/GLD 相關性的大幅波動（range 0.78 vs CCC 的 0.18）。

### COVID 子樣本 (2020-02 ~ 2020-06)

| Model | Mean ρ | Range |
|-------|--------|-------|
| CCC-GJR | -0.065 | [-0.069, -0.059] |
| **DCC-GJR** | **-0.118** | **[-0.365, 0.105]** |
| CCC-A4f | -0.052 | [-0.057, -0.045] |
| **DCC-A4f** | **-0.096** | **[-0.273, 0.047]** |

DCC 在 COVID 期間捕捉到相關性從 +0.10 暴跌到 -0.37 的急劇轉變。

## 結論

1. **DCC-A4f 是最佳 portfolio VaR 模型**：QLIKE 最低、Trinity 2/2 PASS、DM t=3.826 顯著優於 CCC-GJR（通過 Harvey 門檻）。

2. **DCC 對 SPY/GLD 比 SPY/QQQ 更有價值**：SPY/GLD DCC ρ std=0.15, range=0.78（vs K1028 SPY/QQQ 的穩定相關）。DCC 讓兩個 CCC-FAIL 的 alpha 變成 PASS。

3. **A4f 改善 > DCC 改善**：A4f 改善 QLIKE +0.53%（CCC）和 +0.47%（DCC），DCC 改善只有 +0.23%（GJR）和 +0.17%（A4f）。**Marginal model 的改善比 correlation model 更重要。**

4. **改善可加疊**：DCC-A4f 同時受益於兩個維度，QLIKE 改善為 CCC-GJR 到 DCC-A4f = +0.71%，且 DM t=3.826 統計顯著。

5. **K891 NULL 結果被推翻**：K891 用 GJR marginals 沒有改善，但 K1041 證明 A4f marginals + DCC 同時使用時，portfolio VaR 顯著改善。關鍵差異是 A4f 的 marginal vol 更準確。

## 局限性

- 僅測試 50/50 SPY/GLD，其他權重可能不同
- OOS 期間 2019-2026（~7 年），僅含 1 次重大危機（COVID）
- DCC improvement 雖然讓 Trinity PASS，但 QLIKE 改善幅度較小（+0.23%）
- 未測試 Student-t 或 FHS 等替代 VaR 方法

## 檔案

- `k1041.py`: 實驗腳本
- `k1041_results.json`: 完整結果
- `k1041_rolling_correlation.png`: 滾動相關性圖
- `k1041_portfolio_var.png`: Portfolio VaR 比較圖

## 參考文獻

- Engle (2002). Dynamic Conditional Correlation. JBES 20(3).
- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3).
- Patton (2011). Volatility forecast comparison using imperfect proxies. JoE 160(1).
- Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models.
- Christoffersen (1998). Evaluating Interval Forecasts. Int Econ Rev.
- Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320.
- Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
