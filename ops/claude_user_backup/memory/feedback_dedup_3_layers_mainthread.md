---
name: feedback_dedup_3_layers_mainthread
description: 派寫作 agent 前主線程必做 3-layer 主題查重 (candidates / grep / cross-article matrix)，不僅靠 agent LanceDB
type: feedback
originSessionId: 01d23520-901e-44a9-9f09-f9e497e18020
---
派 daily_article / event_article 寫作 agent 前，**主線程必做 3 層主題查重**（per `.claude/rules/publish-checklist.md` L38-53）：

- **層 1**: `jq '.top_10_uncovered, .missing_*_top5' storage/publication_candidates.json` — 只選 uncovered/missing_audience 的 K
- **層 2**: `grep -i "核心關鍵詞" storage/reports/INDEX.md | head` 或 `grep -i "K<id>" storage/reports/feed.json | grep title` — 檢既有文章標題與 tags
- **層 3**: 多篇並行時，主線程先手畫主題軸 matrix（VT / VIX / 台股 / 事件 / 方法論 / 資產類 / 策略類），每篇分配**不同軸**

**Why**：
- LanceDB dist 0.6-0.8 **不足以排除主題重疊**（K1098 vs 台美 VT dist=0.769 仍高度相關）— 不能僅信 agent 自身 LanceDB 查重
- 2026-04-19 TSMC 04/13 單事件踩過 5+ 篇坑（rule 已明訂 max 3-4 篇）
- 2026-04-20 session 自我 audit：6 次 dispatch，5/6 沒做層 3 cross-article matrix，1/6（K886）完全沒做層 1 + 層 2

**How to apply**：
- 派 agent 前 **必在主線程 bash** 跑層 1 + 層 2 指令並把結果納入 brief 或 rejection 決策
- 若 agent LanceDB dist < 0.45 → hard duplicate → **停派**
- 若 0.45 ≤ dist < 0.60 → 需換 angle（user story / audience / K 編號差異化明文寫進 brief）
- 連續派多篇時，主題軸 matrix 用 work_log 前 5 筆的主題反推（不能連兩篇 VT、連三篇 VIX 等）
- Agent 完成後如果查重失誤產生重複，要**立即 unpublish + 記 error_log**，不要讓 draft 進池污染讀者 feed
