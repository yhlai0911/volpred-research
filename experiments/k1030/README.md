# K1030: A4f Cross-Market Validation — European Equity (EURO STOXX 50)

**[提出: 賴奕豪, 執行: Claude]**

## 問題與動機

K994/K997 證明 A4f 需要 asset-specific fear index 才能跨市場泛化。K756 測試了 12 個國際市場但只用 US VIX。本實驗測試 A4f 在歐洲市場（EURO STOXX 50）的效果，使用 VIX 和 own-RV20 作為 τ 驅動。

原計劃使用 VSTOXX（歐洲 VIX），但該指標在 yfinance 上不可用。改用 20 日實現波動率（RV20）作為本地 fear proxy，延續 K997 對 EEM/0050.TW 的做法。

## 方法

- **資產**: ^STOXX50E (EURO STOXX 50 Index) + FEZ (US-traded ETF)
- **模型**:
  - M1: GJR-t(df=8) — baseline
  - M2: A4f-VIX-t(df=8) — US VIX as τ driver
  - M3: A4f-RV20-t(df=8) — own 20d realized vol as τ driver
- **配置**: OOS 2019-01-01, window=2000, refit/63d, seed=42
- **評估**: QLIKE on r², DM test (Harvey |t|>3.0), VaR/ES backtesting, Spearman rank correlation

## 關鍵結果

### QLIKE 與 DM 檢定

| Asset | QLIKE GJR | QLIKE A4f-VIX | Improvement | DM t-stat | Significant? |
|-------|-----------|---------------|-------------|-----------|-------------|
| ^STOXX50E | 1.5646 | 1.5126 | +3.3% | -3.642 | **YES** (|t|>3.0) |
| FEZ | 1.4223 | 1.3711 | +3.6% | -3.454 | **YES** (|t|>3.0) |

A4f-RV20 is NOT significant for either asset (DM t=-1.65 / +0.29).

### VaR/ES Scorecard (^STOXX50E)

| Model | VaR 2.5% | VaR 1% | ES 2.5% | ES 1% |
|-------|----------|--------|---------|-------|
| GJR-t | FAIL | FAIL | PASS | PASS |
| A4f-VIX-t | **PASS** | FAIL | PASS | PASS |
| A4f-RV20-t | FAIL | FAIL | PASS | PASS |

For FEZ: A4f-VIX passes VaR 1% (p=0.586), while GJR and RV20 fail.

### Regime Analysis

VIX 效果在 Medium VIX (20-30) 最強：
- ^STOXX50E Medium: DM t=-3.15, QLIKE 改善 7.4%
- FEZ Medium: DM t=-2.53, QLIKE 改善 6.2%

## 結論

**A4f-VIX 在歐洲市場顯著有效**（2/2 資產通過 Harvey |t|>3.0 門檻）。

核心發現：
1. **US VIX 對歐洲股票波動率預測同樣有效**——不需要 VSTOXX。VIX-r² 相關性（0.44-0.49）與 SPY（~0.63）相當。
2. **Own 20d RV 作為 fear proxy 無效**——RV20 對兩個資產都不顯著（STOXX50E DM t=-1.65, FEZ DM t=+0.29）。
3. **VIX 顯著優於 RV20**（head-to-head DM t=3.56 / 3.27）。
4. **A4f-VIX 改善 VaR coverage**——STOXX50E VaR 2.5% 唯一 PASS 模型。

**Paper 9 意義**: 這擴展了 A4f 的跨市場有效性——從 SPY/QQQ（美國）和 GLD+GVZ（商品）到歐洲股票。VIX 不僅是美國市場的 fear gauge，對歐洲市場也同樣有效。

**令人意外的發現**: 原假設是「歐洲市場需要歐洲 fear index」，但實際上 US VIX 就夠了。這可能因為：(1) 全球化使恐慌高度同步，(2) VIX 是全球 fear 的 leading indicator，(3) STOXX50E/FEZ 與 SPY 高度相關（VIX-RV20 corr = 0.78-0.79）。

## 局限性

- VSTOXX 無法取得，無法直接比較 VSTOXX vs VIX 對歐洲市場的效果
- VaR 1% 對所有模型都偏高，可能需要更高 df 或調整
- OOS 期間包含 COVID-19，可能誇大 VIX 的效果

## 檔案

- `k1030.py` — 實驗腳本
- `k1030_results.json` — 完整結果
- `k1030_qlike_comparison.png` — QLIKE 比較圖
- `k1030_dm_summary.png` — DM 檢定摘要圖
- `k1030_var_es_scorecard.png` — VaR/ES 評分卡

## 數據來源

yfinance: ^STOXX50E, FEZ, ^VIX (2005-2026)
