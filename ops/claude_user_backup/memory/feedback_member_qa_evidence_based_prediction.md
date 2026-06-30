---
name: feedback_member_qa_evidence_based_prediction
description: member_qa 預測/估值/選股類提問要做不要 decline；誠實的線是「方法」不是「題目」
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

用戶 2026-06-19 連續三次糾正：會員（含付費）的預測/估值/選股/點位類提問（例 yaoxk1431「假設台股3月內到6萬點，哪些股低估、哪些產業值得、要做哪些準備，幫我模擬」），**要做、要發佈、結尾加免責聲明**，不可直接 decline。

**Why**：直接 decline 付費會員傷會員關係＋傷轉換（違反 monetization mission）。而且我之前的紅線畫錯了——把「題目是不是選股/點位」當禁區是錯的。

**核心原則修正（用戶原話「只要擬作的預測不是憑空、有憑有據，為什麼要怕」）**：
研究誠實要擋的是「**無方法支撐的斷言/捏造**」，**不是「預測/模擬」這個行為本身**。
- ✅ 該做：建立在真數據＋站得住的方法（GARCH/MC 模擬、相對估值分位、歷史條件分析等）＋寫清假設＋報告不確定性區間＋標 model-conditional＋可複現＋附 value-trap 警示與免責聲明。evidence-based 模擬/推估/估值正是量化金融本身。
- ❌ 不做：沒有方法或數據支撐的斷言、捏造數字、把模型輸出講成「一定會發生」、喊單/給目標價。資料源不可得時誠實改用標示清楚的 proxy，絕不憑空生數字。

**How to apply**：
- member_qa（及任何 reader-facing 預測題）→ 不 decline，改用 VolPred 量化方法 evidence-based 回答 + 假設/不確定性/免責。
- 流程：分析（真數據+seed+artifact 可複現）→ 撰稿（anti-AI-style，見 [[feedback_use_anti_ai_style]]）→ 對抗式審查（誠實/claim-evidence + 方法論 + 文風 + 免責）→ 主線程 canonical 發佈 + question-answer --article-id link。
- 範例落地：experiments/k_taiex_60k_scenario_20260619/（GARCH 路徑模擬 + 相對估值篩選 + 產業輪動），workflow member-qa-taiex-60k。
- 對比舊（已作廢）立場：先前「踩個股估值/產業配置/點位 3 紅線就 decline」是過保守，本則取代之。盈利×誠實衝突仍是誠實優先，但「誠實」= 有方法有據，不是「不准預測」。

關聯：[[project_platform_profitability_goal]] [[feedback_no_user_policy_block]] [[feedback_reader_facing_3canon]]
