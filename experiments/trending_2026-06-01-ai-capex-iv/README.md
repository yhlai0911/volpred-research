# trending_2026-06-01-ai-capex-iv

**Task type**: trending_repost  
**Date**: 2026-06-01  
**Published**: mile_622a2b73  
**Title**: 資本支出暴增八成，股票卻平靜如水：AI 巨頭的波動率定價迷局

## 任務描述

分析微軟（MSFT）與 Meta（META）在 2025Q1–2026Q1 期間的季度資本支出軌跡，
對照同期 30 日已實現波動率（HV30），檢視「高 CapEx = 高波動率」的直覺假設
是否成立。

## 關鍵發現

- MSFT 2026Q1 CapEx = $30.9B，YoY +84.5%；同期 HV30 = 30.9%
- META 2026Q1 CapEx = $19.0B，YoY +46.8%；同期 HV30 = 33.8%
- **反直覺**：CapEx 增幅最劇烈的 2025Q3-Q4（MSFT），HV30 反而降至歷史低點（15.5%）
- META 波動率最高季度（2025Q2, HV30=50.2%）並非 CapEx 最高季度（2025Q4, $21.4B）
- N=10 觀測（2 公司 × 5 季），樣本偏小，所有結論為觀察性描述

## 方法

- 資料來源：yfinance quarterly_cashflow（對應 10-Q/8-K）+ 日線收盤價
- HV30：30 日滾動標準差 × √252 × 100（年化，%）
- YoY CapEx 計算：與 4 季前對比
- IV proxy：本次無法從 yfinance 免費層取得選擇權 mid-price，改用 HV30 代理，文章明確標注

## 檔案

- `fetch_data.py` — 數據抓取與分析腳本
- `raw_data.csv` — MSFT/META 日線收盤價與 HV30（2024-2026）
- `quarterly_summary.csv` — 季度彙總表（CapEx + HV30 均值）
- `capex_hv_chart.png` — CapEx 柱狀 + HV30 折線雙軸圖
- `hv30_timeseries.png` — HV30 日線時序圖（含季末 CapEx 標記）

## 數據來源聲明

- Microsoft CapEx：Microsoft Corporation Form 10-Q（各季 SEC 申報）
- Meta CapEx：Meta Platforms, Inc. Form 10-Q（各季 SEC 申報）
- 市場數據：yfinance API（Yahoo Finance）

## FB 發文狀態

fb_post_status=skipped_headless（per user memory feedback_fb_personal_account_chrome_only）
