# K1058: A4f Cross-Market Validation on 0050.TW with US VIX

**提出**: 賴奕豪 | **執行**: Claude | **日期**: 2026-04-12

## 研究問題

A4f（乘法 GARCH-X with VIX²）是 Paper 9 的核心模型，在 SPY 上 DM t=4.48 勝 GJR（K988），且 5/5 子期間穩健（K1056）。本實驗將 A4f 應用於台灣市場（0050.TW），使用 US VIX 作為外部回歸變數，提供跨市場驗證。

## 動機

1. Paper 9 需要跨市場 robustness evidence
2. 0050.TW 是新興市場 ETF（TSMC ~50%），結構不同於美股
3. 台灣 amplification factor 4.6x（K176）——VIX 影響可能被放大
4. 8.63/VIX 策略的理論基礎假設 VIX 對台股 vol 有預測力

## 方法

| 項目 | 規格 |
|------|------|
| 資料 | 0050.TW + ^VIX，yfinance |
| 期間 | 2009-01-05 ~ 2026-04-10 (n=4,223) |
| OOS | 2019-01-01+ (n=1,760) |
| Window | 2000 天滾動 |
| Refit | 每 63 天 (28 次) |
| Target | r² (Patton 2011 proxy-robust) |
| 模型 | GJR-GARCH(1,1) vs A4f (τ = θ₀ + θ₁×VIX²_{t-1}) |
| VIX 對齊 | Forward-fill 到台股交易日 |
| 0050.TW 清洗 | `clean_tw50_data()` 處理 2014 split |

## 核心結果

### 1. QLIKE & Spearman

| 模型 | QLIKE | Spearman ρ |
|------|-------|-----------|
| GJR | 1.4614 | 0.220 |
| **A4f** | **1.4363** | **0.263** |

A4f QLIKE 改善 0.98%（方向正確，但幅度遠小於 SPY 的 ~1.01%）

### 2. DM Test

| 比較 | DM t | p | |t|>3.0? |
|------|------|---|---------|
| A4f vs GJR | **-1.26** | 0.208 | **否** |

**DM t=-1.26，未通過 Harvey |t|>3.0 門檻**。這是本實驗的關鍵 null result。

對比 SPY: DM t=-4.48（K988），差異巨大。

### 3. VaR/ES Trinity Test

| 模型 | VaR 1% Trinity | VaR 5% Trinity |
|------|---------------|---------------|
| GJR | FAIL (Kupiec fail, Basel Yellow) | FAIL (Kupiec fail) |
| **A4f** | **PASS** | FAIL (Kupiec fail) |

A4f 在 1% VaR 通過 Trinity test，GJR 全 FAIL。A4f 在尾部風險管理上有經濟價值。

### 4. VIX Regime 條件分析

| VIX Regime | QLIKE 改善 | DM t |
|------------|----------|------|
| <15 (低) | -1.30% (退步) | +0.59 |
| 15-25 (正常) | **+3.10%** | -1.59 |
| 25-35 (偏高) | -0.54% (退步) | +0.42 |
| >35 (高) | **+6.99%** | -0.78 |

A4f 的優勢集中在正常和高 VIX regime（VIX 15-25 改善 3.1%，>35 改善 7.0%），但在低/偏高 VIX 環境反而略差。

### 5. θ₁ 比較

| 市場 | θ₁ 均值 | θ₁ 中位數 |
|------|---------|----------|
| SPY (K988) | ~1e-5 量級 | — |
| 0050.TW | 1.32e-5 | 2.4e-7 |

θ₁ 在 0050.TW 上高度不穩定（std = 4.98e-5，有極端值 2.46e-4）。中位數遠低於均值，顯示多數時期 θ₁ 接近零，少數 refit 產出極端估計。

## 結論

1. **A4f 在 0050.TW 的 QLIKE 改善方向正確（+0.98%），但統計不顯著（DM t=-1.26）**
2. **未通過 Harvey |t|>3.0**——不能宣稱 A4f 顯著優於 GJR
3. A4f 在 VaR 1% Trinity test 通過（GJR 失敗），有經濟顯著性
4. θ₁ 估計高度不穩定，可能反映 VIX-to-TW transmission 的不穩定性
5. VIX regime 條件分析顯示改善集中在正常和極端 regime

## 對 Paper 9 的意義

- **正面**：A4f 方向正確，VaR 改善，regime-conditional 改善
- **限制**：DM test 未通過，跨市場 evidence 不如 SPY 強
- **解釋**：0050.TW 受多重因素驅動（TSMC 個股風險、台幣匯率、亞太情緒），US VIX 單一變數可能不足以捕捉台股 long-run component
- **建議**：Paper 9 可在 robustness section 報告此結果，承認 A4f 跨市場效果遞減，但仍保持方向一致性

## 局限性

1. 0050.TW 數據從 2009 開始（yfinance 可用範圍），比 SPY 短
2. VIX forward-fill 引入噪音（台灣假日的 VIX 估計）
3. 0050.TW 集中度高（TSMC ~50%），不完全代表台股整體
4. n_oos=1,760 vs SPY n_oos=1,825，比較基礎略有不同

## 檔案

| 檔案 | 說明 |
|------|------|
| `k1058.py` | 完整腳本 |
| `k1058_results.json` | 完整結果 JSON |
| `k1058_dm_comparison.png` | QLIKE + DM test 圖 |
| `k1058_var_trinity.png` | VaR Trinity heatmap |
| `k1058_theta1_comparison.png` | θ₁ 演化圖 |
| `k1058_forecast_timeseries.png` | 預測時序圖 |

## 參考文獻

- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold.
- K988: A4f DM t=4.48 vs GJR on SPY
- K1056: A4f 5/5 sub-period robust on SPY
- K997: VIXTWN not superior to US VIX
