---
name: feedback_refill_check_saturation_and_running_hourly
description: 補池/refill 前必 pgrep hourly 避免 race + 判斷 K「可寫」要查 narrative-arc 飽和度不只 results.json
metadata:
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

2026-06-08 凌晨 autonomous tick 教訓（兩個 refill/補池失誤，hourly agent 的 8th belt 推翻我的判斷）：

## 失誤 1：判斷 K「可寫成文章」只查 results.json，沒查 narrative-arc 飽和度
- 00:18 我補 6 篇「可寫」文章（commit 026c8110），理由是「有 results.json = 有真數據可寫」。
- **錯**：那 5 個 K（K159/K181/K510/K737/K495）各已有 ≥2 篇 research-audience feed 文章。有資料 ≠ 故事沒講過。寫 general 版是 **narrative-arc duplicate**（[[feedback_narrative_arc_dedup]]），publisher dedup 會在浪費 token 後 reject。全被標 failed。
- **正確判斷**：audience-gap（research→general）不是 refillable signal，若該 K 的 research 覆蓋已飽和（≥2 篇/arc 已講完）那是 fully-told story 不是 gap。
- **How to apply**：refill / 評估 K 可否寫文章前，查「該 K 已有幾篇 feed 文章 + arc 是否已講」，不只 `ls results.json`。hourly 的 refill 8th belt（commit 078fa9d8）已自動 enforce skip research-saturated K。

## 失誤 2：深層 pool 問題時沒先 pgrep hourly → 與正在跑的 hourly agent race
- 我 00:18 refill 後，01:07 hourly agent（opus）獨立診斷同一 pool 根因、正在實作 8th belt。我的 refill 變成它要 reconcile 的 incident。
- **How to apply**：補池 / 動 next_tasks.json / 大改 ops 共享狀態前，先 `pgrep -fl hourly`；若 hourly 在跑 → **stand down**，讓它完成再 review，不 race。

## 真結論（白天決策）
易寫的 uncovered K 已大致寫完 → 池低的真需求是 **contrarian 新研究**（加密/HFT 微結構/options surface/總經/行為財務/EM ex-台），不是反覆 refill 既有 K。連結稍早「故步自封」糾正。

相關：[[feedback_narrative_arc_dedup]]、[[feedback_dedup_3_layers_mainthread]]、[[feedback_continuous_work_and_read_mail]]、[[feedback_proactively_complete_red_alerts]]。
