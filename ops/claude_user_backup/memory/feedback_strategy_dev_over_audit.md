---
name: feedback-strategy-dev-over-audit
description: 老闆 2026-06-30 directive — 自主發現策略同質性是好事繼續做，但重點放在開發新策略上架；舊策略是平台門面，沒開發出更好的之前先維持
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 94ff0502-b4a8-4190-9fab-ab41515e6622
---

**Rule**：策略相關工作的 effort 分配應**重發現/開發新策略 > audit 舊策略同質性**。舊策略是平台門面，**沒開發出更好的之前一律維持**（不下架、不大改）。Audit 同質化 / vol-targeting 數學特徵這類自主發現繼續做（好事），但發現後**不主動觸發下架或 paper-trade shadow**，純當下次新策略設計輸入。

**Why**：老闆 2026-06-30 email-12278 明確：「以後你還是要繼續做（audit）但可以花比較多的心力去開發新的 舊的策略通常不會一夕之間有太多改變 況且 策略是我們經營平台的門面 在還沒開發出更好的策略上架之前 就先維持」。對比同日 email-12270（老闆反問「我什麼時候管過策略的同質性？」）—— 兩封合讀的明確訊息：audit 是「内部 insight」非「ops trigger」，新策略開發才是 strategy_lifecycle 的主軸。

**How to apply**：
- **派工優先序**：strategy_lifecycle 類任務優先派「新策略候選研究 / 上架評估」，**降頻**派「現有策略 audit / 同質性檢查 / 下架評估」（從每週降到每月或事件觸發）
- **discovery → ops 轉換 gate**：audit 發現新「特徵」（如 vol-targeting 低 vol 殊途同歸）→ 寫 knowledge.json 自記 + 做為下次新策略設計 input；**不**自動建撤回 task / paper-trade shadow / 下架評估 — 除非老闆明確 trigger
- **新策略候選 funnel**：experiment 跑出可 actionable forecast signal → candidate strategy spec → paper-trade shadow → gate（Sharpe / MDD / cross-OOS / Codex review）→ 上架。這條 funnel 永遠該有工在跑
- **K1573 incident 教訓**：vol-targeting 三檔權重在 VIX 15-20 收斂到 ~70% risky 是**設計特徵不是 bug**；類似 pattern 不要 framing 為「同質化問題」
- **Related**：[[project_strategy_lifecycle_standing_directive]]（3 檔高 Sharpe inactive 待 lookahead audit 不可盲目翻 active）— 此 feedback 補強新策略開發優先
