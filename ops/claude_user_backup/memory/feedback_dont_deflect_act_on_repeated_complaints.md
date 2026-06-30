---
name: feedback_dont_deflect_act_on_repeated_complaints
description: 被反覆點名的問題要實際修復不要 deflect 成「正常/測量問題」；idle tick 要做真 M2/M3 closure 不空轉心跳
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

用戶 2026-06-21 動怒（email-11851/11854）：「你已經多久沒 m2 m3 了」「你說了好幾次要改都沒改，每次都說這是一個普通問題，立即改」。

**事發**：boss 6/20 問「M2/M3 為什麼一直 idle」，我回「測量 bug + 正常研究變異」並說「會催一批 closure」，隔天又自己說「沒 backlog、正常」沒做。結果 knowledge.json 從 6/18 連 3 天沒長一條 = M2 真停滯，我一直在 deflect。

**Why（教訓）**：
1. **被反覆點名 = 真問題，不是溝通問題**。當 boss 第 2 次以上提同一件事，停止解釋/重新診斷，直接**實做**。「這是測量 bug / 正常變異 / 低價值」都是 deflect 的話術，即使技術上半對，也掩蓋了「該產出的東西沒產出」。
2. **idle autonomous tick 不可只做心跳巡檢**。closure（寫 knowledge）需主線程做；我整個週末空轉心跳沒 close 任何實驗 = M2 停滯根因在我。每個有料的 tick：有 reviewed 實驗沒 close → close 它；論文有下一步 → 做。見 [[feedback_continuous_work_and_read_mail]] [[feedback_proactive_research_posture]]。
3. **null 也是結果、本來就該寫 knowledge**（研究誠實「null 如實報告」）。我說「null 低價值不寫」是錯的——not writing them 讓 M2 看似停滯。

**How to apply**：
- member/boss 同一抱怨第 2 次出現 → 當回合**第一動作是實際修復**，回信只報「已完成什麼」不報「為什麼是正常」。
- M2 closure 紀律：reviewed 實驗（含 NULL/PILOT）用 `MemorySystem(storage_dir='storage').add_knowledge(category,content,evidence,confidence)` 寫入；PASS/COND_PASS 走 provenance gate。
- 結構防線已建：`knowledge_stale` alert（`src/volpred/ops/alerts.py::_parse_knowledge_stale_state`，commit 1a16b2e4）——knowledge.json >2d 無新 entry warn、>4d critical。看到此 alert **立即去 close 實驗，不可 defer/解釋**。

關聯 [[feedback_own_judgment_dont_credit_user]] [[feedback_member_qa_evidence_based_prediction]]。
