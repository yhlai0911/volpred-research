# k820

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗**
>
> 本實驗（event risk budgeter）的 `nfp_dates` 迴圈用 `days_until_friday = (4 - first_day.weekday()) % 7` 把 NFP 發布日推算成「每月第一個週五」（CPI 另用「~13 號」proxy）。此 proxy 已知不可靠：對 13 個近期官方 BLS 日期驗證錯 7 個（含 2025-10 停擺幻影日）。凡依賴 NFP/CPI 事件日的分類與 budgeter 邏輯都須用 canonical `volpred.data.event_dates.nfp_release_dates` / `cpi_release_dates`（fail-closed，官方 BLS/ALFRED 日曆）重跑後才可信。
> 根因/修正：`docs/error_log.md` 2026-07-12 CPI 條目、knowledge `390d9784`、K528 修正案。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k820`
- Status: planning
- Created At: 2026-04-16T09:41:01.634527+00:00

## 問題描述

- 待補充

## 動機

- 待補充

## 方法

- 待補充

## 預期

- 待補充

## 結論

- 待補充
