# K1056: A4f Sub-Period Stability Analysis (Paper 9 Robustness)

**[提出: 賴奕豪, 執行: Claude]**

## 動機

Paper 9 的核心發現是 A4f（乘法 GARCH-X with VIX²）以 DM t=4.48（K988 full OOS 2019-2026）顯著優於 GJR。審稿人必然會問：「這個優勢是否穩定？還是被某個特殊時期（如 COVID）驅動？」

本實驗回答這個問題，透過將 OOS 期間拆分為 5 個非重疊子期間並分別檢驗。

## 先前相關成果

| 實驗 | 內容 | 結論 |
|------|------|------|
| K988 | A4f vs GJR full OOS | DM t=4.48 |
| K988b | 17 個規格比較 | A4f 最佳 |
| K1024/K1033 | Refit frequency | CV=0.1%（不敏感） |
| K994 | Cross-asset | QQQ/GLD PASS |
| K1054 | HAR-RV proxy | A4f wins both |
| K1055 | Conformal PI | A4f 7-11% narrower |

## 方法

- **數據**：SPY daily returns + VIX，2005-01-04 ~ 2026-04-10，yfinance，n=5,350
- **模型**：A4f-VIX² (σ²_t = τ_t × g_t, τ = θ₀ + θ₁·VIX²_{t-1}) vs GJR-GARCH(1,1)
- **OOS 起始**：2015-01-01（延伸以涵蓋所有 5 個子期間）
- **Rolling window**：w=2000，refit every 63 days
- **評估**：QLIKE on r² (Patton 2011)，DM test（Harvey |t|>3.0），Spearman rank
- **Random seed**：42

### 子期間設計

| 期間 | 日期範圍 | 特徵 | 觀察數 | 平均 VIX |
|------|---------|------|--------|----------|
| P1: Pre-COVID | 2015-01 ~ 2019-12 | 低波動 + 2018 sell-off | 1,254 | 15.1 |
| P2: COVID | 2020-01 ~ 2021-06 | 極端波動 + 快速恢復 | 377 | 26.4 |
| P3: Post-COVID | 2021-07 ~ 2022-12 | 升息初期 + 熊市 | 378 | 23.3 |
| P4: Rate Hike | 2023-01 ~ 2024-06 | 高利率穩定期 | 373 | 15.9 |
| P5: Recent | 2024-07 ~ 2026-04 | 降息預期 + 關稅 | 446 | 18.7 |

## 核心結果

### Full OOS (2015-2026, n=2,828)

| 指標 | GJR | A4f | 差異 |
|------|-----|-----|------|
| QLIKE | 1.557 | 1.459 | A4f -6.27% |
| DM t-stat | — | -6.594*** | Harvey significant |
| Spearman ρ | 0.388 | 0.444 | A4f +0.056 |

### Sub-Period Results

| 子期間 | QLIKE 改善 | DM t-stat | Harvey sig? | 勝者 |
|--------|-----------|-----------|-------------|------|
| P1: Pre-COVID | +6.47% | -5.276*** | YES | A4f |
| P2: COVID | +8.43% | -1.650 | no | A4f |
| P3: Post-COVID | +5.74% | -2.661** | no | A4f |
| P4: Rate Hike | +3.40% | -3.185*** | YES | A4f |
| P5: Recent | +6.48% | -3.664*** | YES | A4f |

- **A4f wins 5/5 sub-periods** — 優勢是全面性的，不是被任何單一時期驅動
- **Binomial test**: p=0.031（5/5 勝出不太可能是隨機結果）
- **3/5 sub-periods individually Harvey-significant** (|t|>3.0)
- P2 (COVID) 和 P3 (Post-COVID) 的 DM t 未達 Harvey 門檻，但方向一致（power 不足，n~377）

### VIX Regime Analysis

| VIX Regime | n | QLIKE 改善 | DM t-stat |
|------------|---|-----------|-----------|
| VIX < 15 | 1,033 | +8.97% | -7.906*** |
| 15 ≤ VIX < 25 | 1,404 | +0.97% | -0.778 |
| 25 ≤ VIX < 35 | 328 | +13.65% | -2.889** |
| VIX ≥ 35 | 63 | +25.93% | -1.828 |

**關鍵發現**：A4f 在低 VIX (< 15) 和高 VIX (> 25) 時最有優勢。低 VIX 期間 GJR 傾向高估波動率，A4f 的 VIX² 項有效校正。高 VIX/危機期間 VIX² 提供額外資訊。中等 VIX (15-25) 時兩模型差異最小。

### θ₁ Parameter Stability

- **45 次 refit 估計的 θ₁**
- Mean: 4.83e-6, Std: 2.30e-5
- **CV = 4.75**（較高，但所有估計值均為正，方向一致）
- Range: [1.5e-7, 1.5e-4]
- **全部 45 次 θ₁ > 0**（VIX² 永遠提供正向的長期波動率貢獻）

### Rolling DM Analysis (252-day window)

- **100.0% 的 rolling windows 中 A4f 優於 GJR**
- 25.8% 達到 Harvey |t|>3.0 顯著水準
- DM-t range: [-4.812, -0.117]
- **沒有任何 252 天的 window 中 GJR 勝出**

## 結論

1. **A4f 的優勢是穩健的（robust across all sub-periods）**：5/5 子期間全勝，binomial p=0.031
2. **不是 COVID 驅動**：即使排除 COVID 期間（P2），其他 4 個期間 A4f 仍然全勝
3. **3/5 子期間 individually significant**（Harvey |t|>3.0），剩餘 2 個方向一致但 power 不足
4. **Rolling DM analysis 更強**：100% 的 252-day windows 中 A4f 均勝出
5. **θ₁ 方向永遠一致（全部正值）**，但大小有變動（CV=4.75）——VIX² 的貢獻是穩定的方向性信號
6. **VIX regime 分析**：最大改善在低 VIX (<15, +9.0%) 和危機 (>35, +25.9%)

### 局限性

- 5 個子期間中只有 P1 有足夠大的樣本（n=1,254）達到個別 Harvey 顯著
- θ₁ 的 CV 較高（4.75），反映不同波動環境下 VIX² 的邊際貢獻有變化
- 僅限 SPY（cross-asset 見 K994）

## 檔案

| 檔案 | 說明 |
|------|------|
| `k1056.py` | 完整實驗腳本 |
| `k1056_results.json` | 結果 JSON |
| `k1056_subperiod_dm.png` | 子期間 DM t-stat 條形圖 |
| `k1056_theta1_evolution.png` | θ₁ 時序演化圖 |
| `k1056_qlike_improvement.png` | QLIKE 改善分析（子期間 + VIX regime） |
| `k1056_rolling_dm.png` | Rolling DM t-stat 時序圖 |

## 參考文獻

- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Patton (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies. J Econometrics 160:246-256.
- Harvey et al. (2016). Tests for Forecast Encompassing. |t|>3.0 threshold.
- Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.
