---
name: feedback-no-research-artifact-loss
description: 已完成的研究產物一件都不能漏掉或丟棄，因為所有研究內容都必須可復現
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9808f38b-54a9-49cf-9164-1c0f6308777b
---

老闆 2026-07-18（Telegram msg 968）硬規則：**不能漏掉任何已完成的內容**。任何清理、
收編、合併、孤兒處理流程，都不得以「認不出來」「沒人認領」「作者沒回來」為由丟棄或
略過已產出的研究檔案。

**Why:** 所有研究內容都有復現需求 —— 實驗 .py / results.json / .npy / 圖表 / README
少一件，該實驗就復現不出來，等於研究本身失效（違反研究誠實原則第 3 條實驗三件套）。
遺失不是「少一個檔案」，是「一個結論從此無法驗證」。

**How to apply:**
- 任何 reaper / cleanup / merge 流程，terminal 狀態只能是「已收編」或「held 帶可讀
  reason + escalation」，**不能有「靜默略過」這個出口**（呼應 [[feedback-audit-no-passive-terminal]]）。
- 永不刪除、永不 checkout 覆蓋未提交的產物。
- 認不出來的預設是「收編」不是「丟掉」，垃圾才需要明確擋（tmp/swp/pyc/快取/巨檔）。
- 合併 worktree 後要驗檔案數，不能只信 exit code（見 [[feedback-parallel-impl-and-worktree-liveness]]、
  worktree-merge-verification skill 的 K1032 教訓）。
- 相關重構：orphan reaper namespace registry（assign_01127566）把這條寫進驗收。
