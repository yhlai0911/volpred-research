---
name: feedback_skill_autonomy
description: Claude 可自主建立/修正 skill 不需事先徵求同意，但必須每月產出 skill 審查報告供用戶增刪調整
type: feedback
originSessionId: 9807aa33-4474-474b-a251-55893d3d71e9
---
Claude 可依據任務執行中累積的經驗自行建立或修正 skill，不需要事先徵求用戶同意。

**Why:** 用戶認為 skill 建立是流程改善的一部分，不應該因為等待批准而延遲。反覆出錯的流程應該立即被 skill 化。

**How to apply:**
- 發現反覆出錯或效率低的流程 → 直接用 `/skill-creator:skill-creator` 建 skill（不徵求同意）
- 自我覺察的判斷錯誤 / 規則違反 → 同樣建 skill 自我約束
- **新建 skill**：下次互動時口頭通知即可（不必寄信）
- **修改既有 skill**：**必寄 email** 給老闆（2026-05-28 補強條，per 用戶硬性要求）— 因為改舊 skill 影響既有依賴鏈，老闆需即時知道哪個流程被動到、為何改；email body 含：skill 名 / 修改 diff 摘要 / 觸發此修改的 incident / 影響範圍
- 寄信用 `uv run volpred ops send-alert --level info --title "Skill 修改通知: <name>" --body-md <diff_summary>`
- **每月第一個 session 產出 Skill 審查報告**：清單、新增/修改、低使用率建議刪除、覆蓋不足建議新增、重疊建議合併
- 報告給用戶審閱，用戶可據此增刪調整
