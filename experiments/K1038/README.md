# K1038: GAS-t Score-Driven Volatility Model vs GARCH (Multi-Asset)

## 動機
Score-Driven (GAS) 模型是 Creal, Koopman & Lucas (2013, JASA) 提出的替代 GARCH 框架。核心差異在於 GARCH 用 squared innovations 更新波動率（異常值影響巨大），而 GAS 用 predictive density 的 score function 更新（Student-t 下自動 downweight 異常值）。K437 曾測試 SPY 單一資產，結論為 GAS-t underperforms。K1038 擴展到 4 資產、7 年 OOS、加入 leverage 變體和完整 VaR/ES 評估。

## 方法

### 模型
| 模型 | 更新機制 | 分配 | 參數數 |
|------|---------|------|--------|
| GARCH(1,1) | epsilon^2 | Normal | 3 |
| GJR-GARCH(1,1) | epsilon^2 + leverage | Normal | 4 |
| GAS-t(1,1) | Score of t-density | Student-t | 4 |
| GAS-t(1,1)+Leverage | Score + asymmetry | Student-t | 5 |

### 技術規格
- 資產：SPY, QQQ, GLD, 0050.TW
- 數據來源：yfinance
- 期間：2005-01-01 ~ 2026-04-10
- OOS：2019-01-01 起（~7 年，1759-1828 觀測值）
- Window: 2000, refit_every: 63
- 評估 target: r^2 (squared returns)
- 評估指標：QLIKE (Patton 2011), MSE, Spearman rho, VaR/ES Trinity backtest
- DM threshold: Harvey (2016) |t| > 3.0

## 結果

### QLIKE 排名（越低越好）
| Asset | GARCH | GJR | GAS-t | GAS-t-Lev | Best |
|-------|-------|-----|-------|-----------|------|
| SPY | 1.5139 | **1.4960** | 1.5309 | 1.5301 | GJR |
| QQQ | 1.5008 | 1.4915 | 1.5015 | **1.4884** | GAS-t-Lev |
| GLD | **1.5014** | 1.5076 | 1.5101 | 1.5111 | GARCH |
| 0050.TW | 1.4719 | 1.4822 | 1.4796 | **1.4695** | GAS-t-Lev |

### DM 檢定
**沒有任何一組 DM test 達到 Harvey (2016) |t| > 3.0 門檻。** 所有模型間的 QLIKE 差異在統計上不顯著。

| Asset | GAS-t vs GJR | GAS-t-Lev vs GJR | GAS-t-Lev vs GAS-t |
|-------|-------------|-------------------|---------------------|
| SPY | t=-0.99 | t=-1.73 | t=0.04 |
| QQQ | t=-0.30 | t=0.12 | t=1.29 |
| GLD | t=-0.26 | t=-0.37 | t=-1.60 |
| 0050.TW | t=0.07 | t=0.59 | t=0.43 |

### VaR Trinity (Kupiec + CC + Basel) 通過率
| 模型 | 1% Trinity PASS | 2.5% Trinity PASS |
|------|----------------|-------------------|
| GARCH | 0/4 | 0/4 |
| GJR | 0/4 | 1/4 |
| **GAS-t** | **2/4** (GLD, 0050.TW) | **2/4** (SPY, 0050.TW) |
| **GAS-t-Lev** | **2/4** (GLD, 0050.TW) | 1/4 (0050.TW) |

### ES Backtest (Acerbi-Szekely)
**所有模型在所有資產的 ES backtest 均 PASS（p > 0.05）。**

## 結論

1. **QLIKE：GAS-t 不顯著優於 GJR-GARCH。** GAS-t-Lev 在 QQQ 和 0050.TW 有最低 QLIKE，但 DM test 均 |t| < 3.0。GJR 在 SPY 最佳，GARCH 在 GLD 最佳。結論：**無統計顯著差異**，各模型在不同資產間互有勝負。

2. **GAS-t + leverage vs plain GAS-t：無顯著差異。** 最大 |t| = 1.60 (GLD)，遠低於 3.0。leverage effect 在 GAS 框架中的邊際貢獻不明確。

3. **VaR：GAS-t 的 Student-t 分配明顯改善。** GAS-t/GAS-t-Lev 的 1% VaR Trinity PASS 率為 2/4，而 GARCH/GJR 為 0/4。GAS-t 的違約率更接近理論值（如 GLD: GAS-t 1.04% vs GARCH/GJR 1.75%）。這是 GAS-t 的主要優勢——**不是預測力更好，而是分配假設更準確**。

4. **跨資產：沒有系統性 pattern。** 高峰態資產（SPY kurt=15.4, 0050.TW kurt=18.9）不見得從 GAS-t 獲益更多。QLIKE 排名因資產而異。

## 局限性
- 0050.TW 數據從 2009 起，IS 較短
- GAS-t 的 MLE 估計使用 scipy.optimize（非 arch 套件），可能有局部最優問題
- 只用 r^2 proxy（squared returns），未用 5-min RV
- OOS refit 每 63 天——更頻繁可能改變結果
- Student-t df 在 VaR 計算中使用最後一次 fit 的值

## 檔案
- `k1038.py` — 實驗腳本
- `k1038_results.json` — 完整結果
- `k1038_qlike_comparison.png` — QLIKE bar chart
- `k1038_spy_volatility_path.png` — SPY volatility path overlay

## 參考文獻
- Creal, D., Koopman, S.J., & Lucas, A. (2013). Generalized autoregressive score models with applications. JASA, 108(501), 1-18.
- Harvey, A.C. (2013). Dynamic Models for Volatility and Heavy Tails. Cambridge University Press.
- Blasques, F., Koopman, S.J., & Lucas, A. (2015). Information-theoretic optimality of observation-driven time series models. Biometrika, 102(2), 325-343.
- Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies. Journal of Econometrics, 160(1), 246-256.
- Harvey, D.I., Leybourne, S.J., & Newbold, P. (2016). Tests for forecast encompassing. Journal of Business & Economic Statistics.
