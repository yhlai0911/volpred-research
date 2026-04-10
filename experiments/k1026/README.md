# K1026: Proxy-Reliance Controlled Conformal VaR vs Parametric VaR

## 動機

K800/K800v2 嘗試用 conformal prediction 修正 VaR 但被 Codex 推翻為 artifact。K802 確立 GJR + Student-t 為正確解法，K1021 進一步確認 A4f + Student-t(df=8) 在 2.5% VaR 拿到 6/6 PASS。

本實驗基於 arXiv:2603.22569 的思想，重新用正確的方法論實作 conformal VaR：不假設分配，而是用標準化殘差的經驗分位數動態校準 VaR。與 K800 的關鍵差異：(1) 用足夠長的校準窗口（252 天），(2) 嚴格的統計檢定評估，(3) 與 parametric 方法的公平比較。

## 研究問題

1. Conformal prediction 能否在不假設分配的情況下產生 valid VaR？
2. 與 parametric（Student-t）VaR 比較，coverage 和 sharpness 如何？
3. Base model（GJR vs A4f）對 conformal VaR 的影響有多大？

## 方法

### 模型（5 個 VaR 方法）

| 方法 | 波動率模型 | 分配假設 | VaR 計算 |
|------|-----------|---------|---------|
| M1: GJR+Normal | GJR-GARCH | Normal | sigma * z_alpha |
| M2: GJR+t(8) | GJR-GARCH | Student-t(df=8) | sigma * t_inv * sqrt((df-2)/df) |
| M3: A4f+t(8) | A4f (VIX-driven) | Student-t(df=8) | sigma * t_inv * sqrt((df-2)/df) |
| M4: Conformal-GJR | GJR-GARCH | **無假設** | sigma * Q_alpha(e_{t-252:t-1}) |
| M5: Conformal-A4f | A4f (VIX-driven) | **無假設** | sigma * Q_alpha(e_{t-252:t-1}) |

### Conformal VaR 核心思想

標準化殘差 `e_t = r_t / sigma_t`，取過去 252 天 e_t 的 alpha-quantile 作為動態乘數：
```
VaR_t = sigma_t * Quantile_alpha(e_{t-252}, ..., e_{t-1})
ES_t  = sigma_t * Mean(e_s | e_s <= Q_alpha)
```

優點：無需假設 innovation 分配（Normal/t/skew-t），讓數據自己說話。

### 評估

- **VaR levels**: 1%, 2.5%, 5%
- **Tests**: Kupiec (UC), Christoffersen (CC), DQ, Basel traffic light
- **ES**: Acerbi-Szekely Z1/Z2 (at 2.5%)
- **Conditional calibration**: VIX high vs low regime
- **Sharpness**: average |VaR| (越小越好，在 coverage 正確前提下)

### 資料

- SPY 2005-01-03 to 2026-04-09, N=5601
- OOS: 2013-01-02 to end (~13 years)
- VIX: ^VIX (yfinance)
- Window=2000, refit/63d, conformal cal_window=252
- seed=42

## 結果

### Pass Rate 總覽

| 方法 | Pass/Total | Pass Rate |
|------|-----------|----------|
| M1: GJR+Normal | 7/12 | 58% |
| M2: GJR+t(8) | 7/12 | 58% |
| M3: A4f+t(8) | 10/12 | **83%** |
| M4: Conformal-GJR | 11/12 | **92%** |
| M5: Conformal-A4f | 11/12 | **92%** |

### 2.5% VaR（最具資訊量的水準）

| 方法 | Scorecard | Violation Rate | Avg |VaR| |
|------|----------|---------------|-----------|
| M1: GJR+Normal | 4/6 | 3.51% (target 2.5%) | 0.01776 |
| M2: GJR+t(8) | 4/6 | 3.39% | 0.01809 |
| M3: A4f+t(8) | 5/6 | 3.06% | 0.01811 |
| **M4: Conformal-GJR** | **6/6** | **2.56%** | 0.02000 |
| **M5: Conformal-A4f** | **6/6** | **2.71%** | 0.01946 |

### 條件校準（VIX regime, 2.5%）

| 方法 | High-VIX viol | Low-VIX viol | 差距 |
|------|-------------|-------------|------|
| M1: GJR+Normal | 6.04% | 0.96% | 5.08pp |
| M2: GJR+t(8) | 5.87% | 0.90% | 4.97pp |
| M3: A4f+t(8) | 4.61% | 1.50% | 3.11pp |
| M4: Conformal-GJR | 4.01% | 1.10% | 2.91pp |
| M5: Conformal-A4f | 4.01% | 1.40% | 2.61pp |

### QLIKE（波動率預測品質）

| 模型 | QLIKE |
|------|-------|
| GJR | -8.5367 |
| A4f | -8.6439 (better) |

## 關鍵發現

### 1. Conformal VaR 確實有效，且全面通過 backtesting

M4 和 M5 均達到 92% pass rate（11/12），在 2.5% 水準拿到完美 6/6 scorecard。這不是 K800 那種 artifact，而是在嚴格統計檢定下的真實結果。

### 2. Coverage-Sharpness Tradeoff 明確

Conformal 方法的 violation rate 更接近目標（2.56% vs 3.39%），但 VaR 也更寬：
- Conformal-GJR avg|VaR| = 0.0200 vs GJR+t(8) = 0.0181（寬 10.5%）
- Conformal-A4f avg|VaR| = 0.0195 vs A4f+t(8) = 0.0181（寬 7.4%）

這是合理的 tradeoff：conformal 用更保守的 VaR 換取更準確的 coverage。

### 3. Base Model 仍然重要

A4f-based 方法（M3, M5）consistently 優於 GJR-based（M1, M2, M4）：
- A4f+t(8) 83% pass rate vs GJR+t(8) 58%
- Conformal-A4f 比 Conformal-GJR 更 sharp（0.0195 vs 0.0200）
- A4f 的 QLIKE 更低（-8.644 vs -8.537）

結論：sigma 品質是基礎，conformal 是加分。

### 4. 條件校準改善

Conformal 方法在 VIX regime 間的 violation rate 差距最小（2.61-2.91pp vs 4.97-5.08pp），說明它能更好地適應市場狀態變化。A4f 本身也有此優勢（3.11pp），但 conformal 進一步改善。

### 5. 1% VaR 仍然最難

所有方法在 1% VaR 都有挑戰（DQ test 難 pass），但 conformal 的 UC 表現明顯更好：
- Conformal-A4f: UC_p=0.227 (PASS) vs A4f+t(8): UC_p=0.055 (borderline)
- Conformal-GJR: UC_p=0.090 (PASS) vs GJR+t(8): UC_p=0.000 (FAIL)

## 局限性

1. **單一資產**：僅測試 SPY，需跨資產驗證
2. **校準窗口固定 252 天**：未測試不同窗口長度的 sensitivity
3. **Sharpness 代價**：conformal VaR 比 parametric 寬 7-10%，對資本計提不利
4. **DQ test at 1%**：所有 conformal 方法的 DQ p-value < 0.05，暗示殘差仍有時序依賴
5. **未測試 adaptive conformal**：可用 weighted quantile（近期殘差權重更高）

## 衍生方向

1. **Adaptive Conformal VaR**: 用指數加權分位數（近期殘差權重更高）解決 DQ 問題
2. **Cross-asset validation**: 台股 0050.TW、QQQ 的 conformal VaR
3. **Conformal + Student-t hybrid**: 用 conformal 校準 Student-t 的 df 參數
4. **Capital efficiency analysis**: 在 Basel III framework 下比較不同 VaR 方法的資本要求

## 參考文獻

- arXiv:2603.22569 — Proxy-reliance controlled conformal VaR
- Kupiec (1995) — Unconditional coverage LR test
- Christoffersen (1998) — Conditional coverage test
- Engle & Manganelli (2004) — Dynamic Quantile test
- Acerbi & Szekely (2014) — ES backtesting
- Patton (2011) — QLIKE loss, proxy-robust ranking
- K800/K800v2 — Conformal heuristic artifact warning
- K802 — GJR + Student-t = correct VaR solution
- K1021 — A4f + Student-t(df=8) 6/6 PASS at 2.5%

## 檔案

- `k1026.py` — 實驗腳本
- `k1026_results.json` — 完整結果
- `k1026_var_scorecard.png` — VaR scorecard heatmap
- `k1026_var_sharpness.png` — VaR sharpness comparison
- `k1026_var_timeline.png` — VaR timeline + rolling sharpness
