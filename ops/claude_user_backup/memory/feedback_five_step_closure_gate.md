---
name: feedback-five-step-closure-gate
description: 老闆 2026-07-22 移植自其另一專案的結案鐵律：五步全過才能稱解決，否則只能標 contained/blocked
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 330d83e4-6ab1-4f47-83f1-12e3ae8c2ce3
  modified: 2026-07-22T02:27:12.920Z
---

老闆 2026-07-22 指令：參考其另一專案（高中職股王實驗室）的「問題處理不可妥協 Gate」，寫入本專案最高層文件。

**規則**：宣稱「解決」前必走五步 — 證據化症狀（live source/log/receipt/時間戳）→ 根因判定（定位到邏輯/流程契約/排程/狀態機/API/權限/checker/架構；不明=blocked）→ 底層修正（重跑/補檔/改文字/手動清 blocker 只算止血）→ 回歸驗證（測試 + 下游回讀）→ 制度化寫回（script/contract/skill/dashboard）。

**二態詞彙**：`contained`（止血，不可稱完成）vs `root_cause_fixed_and_verified`（唯一真結案）。

**Why**：本週實證 — 「已自動接手」「retry is wired」等宣稱都是跳過驗證與制度化步驟的假完成；修 patch 不修根因造成同根因 24 張重複單。

**How to apply**：已寫入 CLAUDE.md + AGENTS.md（永遠修流程段之後）；progress_report 與 error_log 條目採二態詞彙；機械面 = [[feedback-refactor-over-patch-no-legacy]] + incident sustained-clean resolution + 3-Strike。
