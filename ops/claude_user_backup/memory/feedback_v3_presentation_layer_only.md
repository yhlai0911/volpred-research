---
name: feedback-v3-presentation-layer-only
description: 老闆 2026-07-15 — 原版網頁是核心，v3 只是美化呈現層；內容與數據必須同源不能脫鉤
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2c02c0a5-d84a-4ddd-a4c1-5f243d01e172
---

老闆（2026-07-15，v3 報頭連環假資訊 incident 後）：「原版網頁是核心 v3 是美化 所以要以原版網頁為主要內容、數據作為呈現 不能脫鉤」。

**Why**：v3 從 mock 設計稿長出來，殘留硬編碼（星期日/假天氣/假期號）與獨立資料路徑（portfolio enrich hack、diversify total cap），造成兩版數字不一致 — 老闆連續兩天抓到 v3 顯示錯誤資訊而原版正確。

**How to apply**：
- v3 任何顯示的數字/日期/統計/行情 → 與原版同 API、同 canonical 源；禁止 v3-only mock、硬編碼裝飾數字、獨立資料 hack
- 驗收法：同一資訊兩版並看，值必須一致（用瀏覽器實看，不只 curl）
- 改 v3 呈現（版式/字體/排版）自由；改內容/數據來源必先確認原版怎麼取
- 規則已落 `.claude/rules/frontend-and-deploy.md` 主從關係段（enforcement 描述以 rule 檔為準）

相關：[[feedback-test-before-deploy]]、[[feedback-fix-verify-then-report]]
