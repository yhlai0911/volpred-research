---
name: Test all affected features before deploying frontend changes
description: 修改核心前端組件前必須通盤考慮所有功能，不能只測目標功能
type: feedback
---

2026-04-04 教訓：修改 FeedBrowser.tsx 的 badge 邏輯時，破壞了 tag 篩選（台股/美股）和 tag pills 顯示。

**Why:** 只關注 badge 一致性，沒考慮 FeedBrowser 的其他功能（tag filtering, audience tabs, tag display）也依賴相同的數據結構。改了 AudienceBadge 的 props 和 audience 預設值，連鎖破壞了篩選邏輯。

**How to apply:**
- 修改前先讀懂整個組件的完整邏輯（不只改的那幾行）
- 列出所有受影響的功能：badge、tag 篩選、audience tab、tag pills、搜尋
- 最小修改原則：能只改 ReportDetail 就不動 FeedBrowser
- 本地 `npm run build` 確認無 TypeScript 錯誤
- 部署前在瀏覽器測試所有 tab 和篩選功能
- **絕對不可以「通盤修改」核心組件——一次只改一個地方**
