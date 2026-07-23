# k259

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗**
>
> 本實驗（macro surprise analysis）的 `generate_nfp_dates()` 把 NFP 發布日推算成「每月第一個週五」（註解自述 "NFP = first Friday of each month"）；CPI 另用「~13 號」proxy，同屬已知不可靠站點。對 13 個近期官方 BLS 日期驗證，first-Friday 錯 7 個（含 2025-10 停擺幻影日）。凡依賴 NFP/CPI 事件日的分類數字都須用 canonical `volpred.data.event_dates.nfp_release_dates` / `cpi_release_dates`（fail-closed，官方 BLS/ALFRED 日曆）重跑後才可信。
> 根因/修正：`docs/error_log.md` 2026-07-12 CPI 條目、knowledge `390d9784`、K528 修正案。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k259`
- Status: planning
- Created At: 2026-04-16T09:37:26.889224+00:00

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
