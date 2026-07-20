# k904

> ⚠️→✅ **`task_s4_nfp` 用了 first-Friday proxy，已於 2026-07-19 用 canonical BLS 日曆重跑**
> （task `assign_1238781f`）
>
> - 封存原版 `k904_paper8_shock_nfp_fix.py` / `..._results.json` **不修改**。
> - 新增 `k904_task_s4_nfp_canonical.py` / `k904_task_s4_nfp_canonical_results.json`。
> - **`task_s2_shock_types` 未重跑也未更動** —— 它以 |ΔVIX|>2 分類，從不讀取 NFP 日期，
>   proxy 缺陷碰不到它。重跑只會注入快照雜訊。
> - **設計是 2×2 factorial**（日期來源 × mapping 規則），不是兩臂對照 ——
>   修日曆會同時改「日期」與「release→trading-day 對應」，混在一起報會把 lookahead 修正
>   誤歸因給日曆。第一版犯了這個錯，由 Codex review 判 FAIL 抓出。
> - headline（official + forward mapper）：overall ratio **1.1598**（p **0.0424**）、
>   Low **1.305**、High **0.935**。無符號翻轉。
> - 分解：固定 archived mapper 時純日期效應 1.1427 → 1.1449（幾乎沒動）；
>   真正推動 pooled 數字的是 mapper 修正。
> - **endpoint 修正**：2026-04-03 是 Good Friday（BLS 有發、美股休市），reaction 日是
>   2026-04-06。原本價格窗切在 2026-04-05，導致該事件在 official arm 被**靜默丟棄**
>   而 proxy arm 卻往回對應到 04-02。價格窗已延到 2026-04-06，兩臂都是 195/195 完整對應。
> - proxy arm 逐位重現封存 JSON（1.142670 vs 1.142569），證明重寫忠實。
> - 複審狀態以 `experiments/k904/review_verdict.json` 為準（gate 產生、Codex 填寫、
>   pin 住審查當下的 sha256）。本行不複述裁決，以免與裁決檔漂移。
> - 檢定變體：本實驗**一直**顯式用 Welch（`equal_var=False`）。姊妹實驗 k741 原本因省略
>   參數而落在 Student's，已於 2026-07-20 統一為 Welch，兩者不再分歧
>   （見 `experiments/k741/README.md` §「檢定變體」）。
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
