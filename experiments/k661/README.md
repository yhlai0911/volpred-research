# k661

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗**
>
> 本實驗（NFP volatility analysis）用 `get_first_friday()` 把 NFP 發布日推算成「每月第一個週五」。此 proxy 已知不可靠：對 13 個近期官方 BLS 日期驗證錯 7 個（含 2025-10 停擺幻影日）。凡依賴 NFP 日期的分類數字（event-day mean/ratio、t、p、regime 細分）都須用 canonical `volpred.data.event_dates.nfp_release_dates`（fail-closed，官方 BLS/ALFRED 日曆）重跑後才可信。另有 feed 文章引用其數字，須一併回溯。
> 根因/修正：`docs/error_log.md` 2026-07-12 CPI 條目、knowledge `390d9784`、K528 修正案。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k661`
- Status: planning
- Created At: 2026-04-16T09:40:20.793411+00:00

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
