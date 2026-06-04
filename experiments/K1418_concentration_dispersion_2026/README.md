# K1418 — S&P 500 集中度 × Dispersion Trading vol 結構不對稱

**Date**: 2026-06-05  
**Type**: trending_repost evidence package  
**Article**: "S&P 500 集中度突破 32%，指數波動率卻跌到 14%：這個缺口是怎麼來的"

## 目的

支撐 trending_repost 文章的量化 evidence package。主題：Mag 7 集中度上升如何造成「指數 RV 被低估、個股 RV 仍高」的結構性缺口，以及 dispersion trading 的期權溢價機制。

## 數據來源

- **yfinance** daily close (SPY, AAPL, MSFT, NVDA, AMZN, GOOG)
  - period: 2020-01-01 to 2026-06-03
  - auto_adjust=True
- **SPDR SPY Fact Sheet** (historical top-5 weights, approximate)

## 研究誠實說明

1. **IV 數據不可得**：期權隱含波動率需付費數據（OptionMetrics 等），本實驗全程以 21 日滾動實現波動率（RV）作為 IV 代理，文章已明確標注。
2. **集中度近似值**：歷史 top-5 權重來自公開 SPDR SPY Fact Sheet 估算，非精確歷史 bit-exact 數據（精確需付費）。
3. **本研究為結構描述，非預測模型**：vol gap 的存在不代表 dispersion trade 能穩定獲利，文章已說明。

## 主要結果

| 指標 | 數值 |
|------|------|
| Top-5 weight 2020 | 17.8% |
| Top-5 weight 2026 | 32.8% |
| 增幅 | +15.0 pp |
| SPY RV (2024-2026 avg) | 13.87% |
| Avg Top-5 RV (2024-2026 avg) | 30.21% |
| Vol gap (2024-2026 avg) | 16.35% |
| Vol gap (2020-2024 avg) | 16.64% |
| Latest vol gap (2026-06-03) | 20.25% |
| NVDA RV (2024-2026 avg) | 45.84% |
| AAPL RV | 24.78% |
| MSFT RV | 22.36% |
| AMZN RV | 29.56% |
| GOOG RV | 28.53% |

## 文件

- `K1418_script.py` — 數據抓取與計算腳本
- `K1418_results.json` — 完整結果 JSON
- `fig_concentration_over_time.png` — Top-5 權重歷史柱狀圖
- `fig_rv_gap_timeseries.png` — RV gap 時序圖

## Codex Review

**Verdict**: CONDITIONAL_PASS  
**Issues fixed**:
1. "超過三分之一" → "接近三分之一" (32.8% < 33.33%)
2. 方差分解公式改為正式 notation: `Var(R) = Σ w_i²σ_i² + 2Σ_{i<j} w_i·w_j·ρ_{ij}·σ_i·σ_j`

## anti_ai_gate

**Result**: PASS (exit 0, warn=1/3)
