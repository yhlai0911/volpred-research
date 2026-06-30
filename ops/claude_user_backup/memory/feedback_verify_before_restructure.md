---
name: feedback_verify_before_restructure
description: Skill/doc restructuring must verify all related files and authority sources BEFORE moving content, not after user complaints
type: feedback
originSessionId: c4bbc51a-d64b-4415-95ae-1ffcd559ec8e
---
重構 skill 或文件時，不能當成「搬文字」——必須先通盤查證再動手。

**Why:** 2026-04-11 restructure autonomous-research → research-planning 時，直接從舊版複製 cron 配置（scheduling.md 才是權威），製造了過期副本。反空轉規則也重複了 5 個地方。用戶糾正後又只改數字（違反「修流程不修資料」），被連續抓了 4 輪錯誤。

**How to apply:**
1. 搬遷任何內容前，先 grep 該內容的關鍵字，找出所有相關文件
2. 確認每段內容的**單一權威來源**在哪裡
3. 如果權威來源已存在 → 引用不複製
4. 如果要建立新的權威來源 → 確認舊的副本都改為引用
5. 刪除任何段落前，確認理解它的用途（不理解就問，不要直接刪）
6. 應用 CLAUDE.md 的「修流程不修資料」原則：發現數字錯誤時，追溯到底層流程（為什麼會有副本？），不是只改數字
