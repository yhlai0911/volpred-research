# trending_2026_05_26_etf — 5月台股 ETF 配息潮 VolPred 角度

## 概述

2026-05-26 trending repost：分析 5 月台股 ETF 配息潮的波動率視角，包含 vol-adjusted yield 比較、除息前後事件研究、VIXTWN 走勢。

## 資料來源

- **ETF 價格與配息歷史**：yfinance（0056.TW / 00878.TW / 00919.TW / 00929.TW / 00940.TW / 006208.TW / 0050.TW / 00850.TW / 00922.TW）
- **VIXTWN**：`data/vixtwn/vixtwn_daily.csv`（本地存儲）
- **資料期間**：ETF 事件研究 2023-01-01 至 2026-05-26；VIXTWN 分析 2026-03-01 至 2026-05-22

## 計算方法

### Vol-Adjusted Yield
```
vol_adj_yield = annual_dividend_yield / annualized_20day_realized_vol
```
- 年化殖利率：2025-01-01 起配息總和 / 最新收盤價
- 年化波動率：最近 30 個交易日的 log return 標準差 × √252

### 除息前後事件研究
- 事件窗口：`[-5, +5]` 個交易日（相對除息日）
- 計算：log return 累積值，以全部除息事件取平均
- 樣本：2023-2026 各 ETF 除息紀錄（共 100+ 個事件）

### VIXTWN 波動率環境
- 2026-03 平均：36.09（高波動，關稅衝擊後）
- 2026-04 平均：31.74（回落中）
- 2026-05 平均：37.00（5 月配息潮期間，偏高）

## 主要發現

1. **00919 vol-adjusted yield 最高（0.711）**：每承擔 1 單位年化波動率可獲得 0.711% 配息，遠高於科技主題 00929（0.145）
2. **除息前 5 日 pre-rally**：高殖利率 ETF（yield >9%）平均 +1.23%，除息後 5 日收縮至接近零（+0.07%）
3. **VIXTWN 在 5 月配息潮處於偏高水位（均值 37.0）**：高於長期正常範圍 25-30，影響 risk-parity 配置決策
4. **Vol-adj yield vs 表面殖利率不一致**：00919（12.01%）比 00922（10.08%）殖利率高但波動率低，因此 risk-adjusted 表現更佳

## 圖表

- `figures/fig1_etf_vol_adjusted_yield.png` — ETF 殖利率 vs 波動率散點 + vol-adj yield 排行
- `figures/fig2_vixtwn_may_dividend.png` — VIXTWN 走勢 vs 5 月配息潮期間
- `figures/fig3_ex_div_event_returns.png` — 除息前後 5 日累積報酬比較

## 關聯實驗

- K557：VT 與 gold regime 配置策略
- K736：Taiwan calendar anomaly × VT 策略

## 發佈

- Task ID：`trending_repost_2026_05_26_etf_dividend_vol`
- 發佈日期：2026-05-26
- Feed slug：`trending_2026_05_26_etf_dividend`
