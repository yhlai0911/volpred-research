---
name: feedback_refactor_over_patch_no_legacy
description: 重構優先於修補；不可用文案/分支打補丁交差，不留遺留狀況
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 3ea0407d-5717-4a7d-b179-a947c061c88c
---

老闆糾正（Telegram msg 942, 2026-07-18）：「我不是叫你不要重構，我是叫你一定要重構，不可以只用修補的方式，以後不可以再出現這種遺留的狀況。」

觸發情境：我為了消除 dreaming email 反射式建議重構，只在 `scripts/dreaming_review.py` 的 `send_dreaming_email` 加了一個 severity 分支改文案，還自稱「已治本」。老闆點明：那個改法本身就是修補（band-aid），正是他要我停的動作。

**Why:** 反覆用 if/else + 硬編碼文案打補丁會累積技術債與遺留死碼；老闆要的是把問題邏輯真正抽成資料驅動/策略結構，讓未來擴充不必再貼補。修補只是把根因往後推。

**How to apply:**
- 遇到「找到問題」時，預設走**真重構**（抽映射表/policy 物件、消除硬編碼堆疊），不是改一次模板文案就宣稱治本。
- 重構後**移除舊死碼分支**，不保留被繞過的舊路徑 = 不留遺留狀況。
- 同類掃描：修一處時 grep 同 class 的補丁遺留一起清或明確標記，別只修觸發點。
- 別把修補說成治本；責任在實作端徹底改，不是改文案交差。

相關：[[feedback_gates_fix_immediately_two_strikes_switch_model]]（關卡壞了徹底修）、[[feedback_fix_silent_fallback_immediately]]、[[feedback_declare_complete_requires_class_sweep]]（bug class 全量掃描）。
