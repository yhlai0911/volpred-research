---
name: feedback_email_on_major_decisions
description: 主線程做重要決策後應主動 send_alert email 通知用戶
type: feedback
originSessionId: 01d23520-901e-44a9-9f09-f9e497e18020
---
做了**重要決策**後應主動寫 email 通知用戶（透過 `send_alert` infrastructure）。

**Why**: 2026-04-19 用戶明確指示「當你做了重要決策後你可以寫 email 通知我」。CLAUDE.md 已授權 AI 完全運營 + 不問選擇題，但用戶仍需知情權去 review / override / 記錄重大變更。Email 是 async 溝通通道 — 使用者不必即時 in-session 看到也能追蹤主線程做了什麼。

**What counts as 重要決策**：
- Paper state 轉變：amber → green、新 submission-ready、reproduce gate pass、重大 errata
- 排程/ops 變更：release cadence 改、cron 新增/移除、session_crons canonical schedule 編輯
- Quota / blocker：Codex quota 耗盡、host cron fail、Supabase 大量同步失敗
- Research 重大發現：K-experiment PASS/FAIL verdict、paradigm shift、cross-market universality
- 平台運營：策略上下架、重大文章發佈、GA / SEO 重大變更

**Not 重要**（不需 email）：
- 單純 reproduce.py edit / single file tweak
- work_log append / README sync
- Task dispatch（會在下次 status 看到）
- 例行 gate rerun 沒變

**How to apply**:
- 用 `uv run volpred ops send-alert --level info|warn|critical --title "..." --body "..."`（遵 `.claude/rules/alert.md` 三段結構：觸發條件 / 影響 / 建議行動）
- 手動重要決策可加 `--force` bypass 24h dedup
- Level：常態 info；異常 warn；blocker critical
- 不要每個 edit 都寄（會 spam）— 一 session 一到兩個 summary email 較佳
- session 結束 or 換段落時發 digest 也可（合併當輪多個重要決策）
