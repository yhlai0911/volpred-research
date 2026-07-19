# k904

> ⚠️→✅ **`task_s4_nfp` 用了 first-Friday proxy，已於 2026-07-19 用 canonical BLS 日曆重跑**
> （task `assign_1238781f`）
>
> - 封存原版 `k904_paper8_shock_nfp_fix.py` / `..._results.json` **不修改**。
> - 新增 `k904_task_s4_nfp_canonical.py` / `k904_task_s4_nfp_canonical_results.json`。
> - **`task_s2_shock_types` 未重跑也未更動** —— 它以 |ΔVIX|>2 分類，從不讀取 NFP 日期，
>   proxy 缺陷碰不到它。重跑只會注入快照雜訊。
> - 重跑結果：overall ratio 1.1426 → **1.1624**（p 0.0742 → **0.0401**），
>   Low 1.230 → **1.305**、High 0.984 → **0.935**。無符號翻轉，顯著性淨改善。
> - proxy arm 逐位重現封存 JSON（1.142565 vs 1.142569），證明重寫忠實。
> - 完整對照與根因：`experiments/k741/nfp_canonical_vs_proxy_comparison.md`。
> - ⚠️ `paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py` 是本檔的**過時副本**，
>   本次未動（論文目錄不在 worktree agent 權限內）。建議主線程同步或刪除。

- Experiment ID: `k904`
- Status: planning
- Created At: 2026-04-16T09:41:26.984428+00:00

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
