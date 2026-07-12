---
name: feedback_alert_is_a_task_not_a_chore
description: 警報必須自動變成任務並被強制派出；「建議老闆行動」的 alert body 是設計失敗（2026-07-13 老闆連兩封信）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1fee114d-8786-48aa-beac-39fe0f250a47
---

在 AI 全自動運營的平台上，**一個只有老闆能處理的 alert 是設計失敗，不是通知**。alert 本來就等於 task。

2026-07-13 老闆一分鐘內回兩封信：「你要立即處理 不是只建議我」/「是你要立刻處理 不是叫我」。
`member_qa_stale` 連續 25 小時每小時寄同一份 to-do list。全量掃描發現 **27 個 alert 有 24 個**
的 body 帶 `## 建議行動`，收件人是人類。

**Why**：光改措辭沒用，framing 才是 bug。而且光發任務也沒用 —— 那筆 member question 其實**早就有
P1 task**，它在 pending **躺了 17 小時跨 ~17 班 fire**。dispatcher 每小時都正確列它為最高優先候選，
但候選清單只是**建議**，挑哪個是該班 LLM 的裁量，diversity rule 還主動推開被跳過的工作。
**優先序欄位救不了餓死 —— 一個任務輸掉一次輪替，就會每小時用同樣方式再輸一次。**

**How to apply**：
- 新增任何 alert 時，預設它會自動建任務（`src/volpred/ops/alert_remediation.py` bridge，
  預設 = 建 task；只有 `SELF_REMEDIATING` / `OWNER_DECISION` 兩個 registry 是例外，且必須寫理由）。
  **不要**在 alert body 寫「建議老闆…」；要寫「已自動處理 + 任務 id」。
- 想讓某個 alert 免除，必須把它放進兩個 exemption set 之一並附理由 —— 沒有「未分類」後門。
- **發任務 ≠ 任務會被做**。派工端有 starvation lockout（`scripts/continue_task_dispatch.py`：
  P1 6h / P2 24h / P3 72h 後候選菜單塌縮成只剩餓死任務）。改 dispatch 選工邏輯時不可繞過它。
- 通則：**「已經有 alert 在盯」只證明偵測有效，不證明處置存在。** 每建一個偵測器就要問「誰會修它，
  怎麼保證那個人真的會被叫到」。
- 老闆連兩封信罵同一件事 → 當 class 級問題處理，先做 full-population sweep（見
  [[feedback_declare_complete_requires_class_sweep]]）。

相關：[[feedback_alerts_auto_act_not_suggest]]（同方向的前一次糾正，本次是它的 class 級落地）、
[[feedback_dont_deflect_act_on_repeated_complaints]]、[[feedback_one_dispatch_per_hour]]。
