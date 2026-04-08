# K952: Threshold ARMA for Volatility — Chen et al. (2011)

## 動機
K947 用 threshold 切換 GARCH 參數（失敗，smooth MF 更好）。TARMA（Threshold ARMA）是不同的方法：直接對 |r_t|（absolute return 作為 vol proxy）建 ARMA 模型，並允許參數在不同 regime 間切換。可能捕捉到 GARCH 遺漏的 MA 成分和非線性 regime 效應。

## 方法
- **資料**：SPY 2004-2026（yfinance），OOS 2016-01-01 ~ 2025-12-31
- **Window**：2000 天，每 21 天 refit
- **Target**：|r_t|（absolute return）
- **模型比較**：
  1. AR(5) — baseline
  2. ARMA(2,1) — 加 MA 成分
  3. TARMA(2,1) threshold = |r_{t-1}|, c = rolling median
  4. TARMA(2,1) threshold = VIX_{t-1}, c = 20
  5. GJR(1,1,1) — arch 套件，σ² → |r| via √σ² × √(2/π)
  6. MF-GJR(VIX) — 兩成分模型 σ² = τ(VIX) × g_t

## 核心結果

| Model | MSE | MAE | Spearman ρ | QLIKE(r²) |
|-------|-----|-----|-----------|-----------|
| AR(5) | 5.699e-5 | 0.004993 | 0.339 | 1.783 |
| ARMA(2,1) | 5.572e-5 | 0.004939 | 0.354 | 1.766 |
| TARMA(\|r\|) | 5.544e-5 | 0.004931 | 0.358 | 1.756 |
| TARMA(VIX) | 5.814e-5 | 0.004932 | 0.384 | 1.715 |
| **GJR(1,1,1)** | **5.224e-5** | **0.004851** | 0.415 | 1.665 |
| **MF-GJR(VIX)** | 7.490e-5 | 0.005067 | **0.455** | **1.590** |

### DM Tests (Harvey |t| > 3.0)
- 無任何 pair 達到 Harvey 顯著門檻
- GJR 在 MSE/MAE 上 numerically 最佳
- MF-GJR(VIX) 在 ranking 能力上最佳（Spearman 0.455, QLIKE 1.590）
- TARMA 介於 AR/ARMA 和 GARCH 之間

### Regime 分析
- TARMA(VIX) 在 VIX≤20 regime 表現良好（MSE 2.329e-5）
- 但高波動 regime（VIX>20）誤差大增（MSE 1.338e-4）

## 結論
**Null result**: TARMA 不顯著優於 GARCH 家族模型。
- TARMA 的 MA 成分和 regime 切換提供溫和改善（vs AR baseline）
- 但 GJR 的 GARCH 結構（variance recursion）在預測精度上更強
- MF-GJR 的 VIX 長期成分提供最佳 ranking 能力（Spearman 0.455）
- **主要貢獻**：確認直接建模 |r_t| 的 ARMA 方法不優於間接的 GARCH → |r| 轉換

## 參考文獻
- Chen, Liu, Gerlach (2011): Bayesian Subset Selection for TARMA, Computational Statistics, 26, 1-30
- Patton (2011): Volatility forecast comparison using imperfect volatility proxies

## 檔案
- `k952.py` — 實驗腳本
- `k952_results.json` — 完整結果
- `k952_comparison.png` — 模型比較圖
