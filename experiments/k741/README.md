# k741

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗；且此為論文引用源**
>
> 本實驗（NFP event study）用 `first_friday` 把 NFP 發布日推算成「每月第一個週五」。此 proxy 已知不可靠：對 13 個近期官方 BLS 日期驗證錯 7 個（含 2025-10 停擺幻影日）。`part_a_historical`（n_nfp=195、ratio_vs_all=1.145、ratio_vs_friday=1.165、p_vs_all=0.081、p_vs_friday=0.061 及所有 VIX-regime 細分）皆建立在污染的日期集合上。
> **重要**：`paper/volatility-absorption/main_v3.tex` 的 Table~\ref{tab:nfp} 明確以本檔 `k741_nfp_event_study_results.json .part_a_historical` 為 source，論文摘要/結果段所有 NFP 數字都來自此處 → 論文 NFP 事件證據直接受此 proxy 影響。
> 修正方向：改用 canonical `volpred.data.event_dates.nfp_release_dates` 重跑；根因見 `docs/error_log.md` 2026-07-12、knowledge `390d9784`、K528 修正案。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k741`
- Status: planning
- Created At: 2026-04-16T09:40:48.867526+00:00

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
