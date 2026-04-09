# K1005: Proxy-Reliance Conformal VaR

## 動機
arXiv:2603.22569 (2026) 提出在 conformal prediction 框架下校準 VaR 時控制對 volatility proxy 的依賴。傳統 parametric VaR 依賴分配假設（Student-t），而 conformal VaR 只需要標準化殘差的交換性（exchangeability），是 distribution-free 的方法。

## 研究問題
1. Conformal VaR 是否比 parametric VaR（Student-t）校準更好？
2. A4f 的 volatility forecast 搭配 conformal score，是否比 GJR 更好？
3. Adaptive Conformal Inference（ACI, Gibbs & Candes 2021）能否進一步改善？

## 方法

### 三種 VaR 方法
1. **Parametric-t**: VaR = sigma * t_ppf(alpha, df) * sqrt((df-2)/df)
2. **Split Conformal**: VaR = sigma * quantile(z_calibration, alpha)，z = r/sigma，calibration window W=500
3. **ACI (Adaptive Conformal)**: 同 Split Conformal，但 alpha_t 動態調整：alpha_{t+1} = alpha_t + gamma*(alpha - I(violation))

### 模型
- GJR_t: 標準 GJR-GARCH with Student-t
- A4f_t_joint: MF-GJR-X with VIX² as tau component + Student-t (joint MLE)

### 數據
- SPY 2004-2026 (yfinance), OOS: 2019-2026
- Window=2000, refit/63d, seed=42

## 結果

### Aggregate Scorecards（VaR 1% + 2.5% + 5% + ES 2.5%）

| Method | Score | Pass Rate |
|--------|-------|-----------|
| GJR_t + parametric | 7/14 | 50.0% |
| GJR_t + conformal | 13/14 | 92.9% |
| GJR_t + ACI | **14/14** | **100.0%** |
| A4f_t + parametric | **14/14** | **100.0%** |
| A4f_t + conformal | **14/14** | **100.0%** |
| A4f_t + ACI | **14/14** | **100.0%** |

### Violation Rates (%) — closer to target is better

| Method | VaR 1% (target 1.00) | VaR 2.5% (target 2.50) | VaR 5% (target 5.00) |
|--------|---------------------|----------------------|---------------------|
| GJR_t + parametric | 1.81 | 3.56 | 6.46 |
| GJR_t + conformal | 1.46 | 2.76 | 5.52 |
| GJR_t + ACI | **1.01** | **2.48** | **5.07** |
| A4f_t + parametric | 1.20 | 2.74 | 5.42 |
| A4f_t + conformal | 1.30 | 2.70 | 5.52 |
| A4f_t + ACI | **1.01** | **2.42** | **4.90** |

## 核心發現

### Finding 1: Conformal VaR 大幅改善 GJR_t 的校準
GJR_t + parametric 只有 50% pass rate（VaR 1% 和 5% 都 fail），但 GJR_t + conformal 達 92.9%，ACI 達 100%。這表明 **GJR_t 的 Student-t 分配假設不夠好**，conformal 校正能有效修正。

### Finding 2: A4f_t 的 parametric VaR 已經很好，conformal 幾乎無改善
A4f_t + parametric 已經是 14/14 (100%)，conformal 和 ACI 也是 100%。這表明 **A4f_t 的 Student-t 分配假設已經足夠好**——VIX 作為外生變數改善了條件分配的擬合。

### Finding 3: ACI 的 violation rate 最接近名義水準
ACI 在所有 alpha 水準上都最接近 target：1.01% vs 1.00%、2.48% vs 2.50%、5.07% vs 5.00%。自適應機制有效校準了覆蓋率。

### Finding 4: Proxy-reliance 的實證含義
- **GJR 高度依賴分配假設**（proxy-reliant）：parametric 失敗，conformal 成功
- **A4f 對分配假設不敏感**（proxy-robust）：兩者都成功
- 這與 Patton (2011) 的 proxy-robustness 理論一致：當模型的 level component (tau) 正確時，殘差的分配形狀影響較小

## 局限
- 單一資產（SPY），未跨市場驗證
- Conformal window W=500 和 ACI gamma=0.01 未做 sensitivity analysis
- ES 評估只在 2.5%，未做 1% ES
- OOS 期間包含 COVID（2020）但未分段分析

## 參考文獻
- arXiv:2603.22569 (2026): Conformal VaR with proxy-reliance
- Gibbs & Candes (2021): Adaptive Conformal Inference
- Vovk et al. (2005): Conformal prediction
- Patton (2011): QLIKE, proxy-robust evaluation
- Kupiec (1995): VaR unconditional coverage
- Christoffersen (1998): VaR conditional coverage
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): t>3.0 threshold

## 檔案
- `k1005.py` — 實驗腳本
- `k1005_results.json` — 完整結果
- `k1005_scorecard_comparison.png` — Scorecard 比較圖
- `k1005_violation_rates.png` — Violation rate 比較圖
