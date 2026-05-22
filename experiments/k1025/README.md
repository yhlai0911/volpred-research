# K1025: Crypto Fear Channel — BTC Vol Spillover to Equity

## 動機
Paper 6 核心實證素材。K639 確認 BTC→SPY Granger causality，K746b 確認 BTC vol asymmetrically Granger-cause VIX。本實驗深化分析，提供完整的溢出效應框架。

## 方法
1. **Granger Causality**: BTC RV(20) → VIX, VIX → BTC RV, BTC RV → SPY RV（雙向測試，lag 1-10）
2. **Asymmetric Granger**: 分離 BTC 上漲 vs 下跌波動分別 Granger 測試
3. **Quantile Regression**: τ = 0.05, 0.25, 0.50, 0.75, 0.95（尾部依賴性）
4. **Rolling Diebold-Yilmaz Spillover Index**: 252 天滾動窗口
5. **EWMA Dynamic Correlation**: BTC-SPY 按 VIX regime 分組統計
6. **Forecasting Test**: AR(VIX) vs AR(VIX)+BTC_RV，DM test with Harvey correction
7. **Sub-period Granger**: 5 個子期間結構性變化分析

## 數據
- **來源**: yfinance (SPY, BTC-USD, ^VIX)
- **期間**: 2015-02-02 ~ 2026-04-08（2,812 觀測值）
- **OOS**: 2019-01-01 ~ 2026-04-08（1,826 觀測值）
- **Seed**: 42

## 核心結論

### 1. Granger Causality — 雙向但非對稱
- **BTC RV → VIX**: lag 2-10 全部顯著（p < 0.05），最佳 lag=3（F=9.23, p<0.001）
- **VIX → BTC RV**: 也顯著（lag 1: F=6.71, p=0.010）→ **雙向 feedback**
- **BTC RV → SPY RV**: lag 2+ 顯著（lag 3: F=13.29, p<0.001）
- 注意：所有序列已通過 ADF 檢定（stationary）

### 2. 非對稱性 — BTC 下跌波動溢出更強（確認 K746b）
- **BTC 負面波動 → VIX**: 所有 lag 1-5 極度顯著（lag 1: F=18.96, p<0.001）
- **BTC 正面波動 → VIX**: 所有 lag 1-5 **不顯著**（best p=0.157）
- **結論**: 只有 BTC 下跌才傳遞恐慌到股市，BTC 上漲不影響 VIX

### 3. Quantile Regression — 強烈尾部依賴
- β 從 -2.86（τ=0.05）到 22.31（τ=0.95），β(0.95)/β(0.50) = 8.54
- **解讀**: VIX 處於高位時（高分位），BTC 波動對 VIX 的影響力放大 8.5 倍
- 低分位（VIX 低迷時）β 為負——BTC 波動升高反而與低 VIX 共存（牛市特徵）

### 4. Diebold-Yilmaz Spillover — BTC 是淨接收者
- 均值總溢出 = 90.11%（三變量系統高度互聯）
- BTC 淨溢出 = -76.89% → **BTC 是溢出的淨接收者**，不是傳遞者
- 高溢出集中在 2020 COVID、2021 牛市、2025-2026

### 5. BTC-SPY 相關性隨危機上升 — BTC 非避險
| VIX Regime | EWMA Corr (mean) | Rolling 60d (mean) | % Positive |
|-----------|------------------|--------------------|------------|
| Low (<15) | 0.068 | 0.030 | 61.9% |
| Normal (15-25) | 0.265 | 0.273 | 82.7% |
| High (25-35) | 0.449 | 0.434 | 95.1% |
| Crisis (>35) | 0.409 | 0.386 | 98.4% |

- 正常時期 BTC-SPY 相關性偏低（0.07-0.27），**危機時飆升至 0.41-0.45**
- BTC 不是 crisis hedge — 最需要分散的時候反而高度正相關

### 6. 預測能力 — 邊際改善不顯著
- AR(VIX)+BTC_RV vs AR(VIX): MSE 改善 = **-0.24%**（略微惡化）
- DM stat (Harvey corrected) = -0.98, p = 0.327 → **不通過 Harvey |t|>3.0 門檻**
- BTC vol 雖然 Granger-cause VIX，但不改善 AR 預測精度

### 7. 結構性變化 — COVID 是分水嶺
- 2015-2017, 2018-2019, 2021-2022, 2023-2026: Granger **不顯著**
- 2020 (COVID): Granger **極度顯著**（F=11.05, p<0.001）
- **溢出效應並非恆常——主要在市場壓力時期啟動**

## 論文 Paper 6 可用素材
1. ✅ 非對稱 Granger（下跌 > 上漲）→ "crypto fear channel" 機制
2. ✅ 尾部依賴性（QR β 右尾放大 8.5x）→ 極端風險時溢出加劇
3. ✅ 危機時期相關性上升（BTC 非避險）→ portfolio implication
4. ✅ 結構性變化（COVID 是分水嶺）→ time-varying spillover
5. ⚠️ 預測改善不顯著 → null result，需如實報告（但 Granger 顯著不代表預測改善，這是不同概念）
6. ⚠️ BTC 是淨接收者 → 需要重新思考 spillover 方向性解讀

## 局限性
- RV(20) 是粗糙的波動率代理（未用高頻 RV）
- EWMA correlation 非正式 DCC（未做 MLE 估計）
- VAR spillover 對變量順序敏感
- BTC 市場結構 2015 vs 2026 差異巨大（ETF、機構化）
- Granger causality ≠ forecasting power（本實驗已驗證此差異）

## 參考文獻
- Diebold & Yilmaz (2012) - Better to Give than to Receive
- Engle (2002) - Dynamic Conditional Correlation
- Koenker & Bassett (1978) - Regression Quantiles
- Harvey et al. (2016) - Testing threshold

## 檔案
- `k1025.py` — 完整實驗腳本
- `k1025_results.json` — 結構化結果
- `k1025_results.png` — 六張圖表

## v2 Methodology Corrections (2026-05-22)

Independent Codex/GPT-5.4 review (reference: review_history/v5_independent/) found 3 BLOCKING issues where the paper's methodology description did not match the code. k1025_v2.py corrects all of them:

1. **BLOCKING 1 — QR predictor lag**: BTC_RV predictor changed from BTC_RV_t (same-day) to BTC_RV_{t-1} (lagged). Asymptotic SEs replaced with 1000-iteration percentile bootstrap (seed=42).
2. **BLOCKING 2 — Granger lag selection**: Changed from min-p-value selection to VAR-AIC selection (maxlags=5). Bonferroni correction (α/n_periods) applied across subperiods.
3. **BLOCKING 3 — OOS split and specification**: IS/OOS overlap fixed (strict '2018-12-31' / '2019-01-01' cut). AR order selected by AIC on IS data. Window changed from expanding to rolling (756 trading days). BTC_RV lags reduced to 1 per paper spec.
4. **MAJOR 3 — Log returns**: BTC returns changed from simple to log returns. yf.download() updated to auto_adjust=True.
