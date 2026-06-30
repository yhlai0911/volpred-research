---
name: feedback-boss-report-no-fb-handback
description: Boss report 禁止把 FB awaiting / FB 互動 session 任務寫成「還需要你做」section — 違反 AI 全自動運營承諾
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d6cd9124-7ae4-4a50-a998-4ae2a3d5df54
---

# Boss report 禁止句型：FB awaiting 不可丟回老闆

任何 hourly cron / autonomous fire 寄的 boss report，**禁止**在「還需要你做」「請你 / 老闆動手」等 section 列：

- `mile_xxxx` FB 貼文走 Claude in Chrome
- FB Ivan Lai 發文待你接手
- 任何把 FB awaiting_interactive 包裝成 user-actionable 的句型

**Why**：6/3 boss 已粗口釘死「FB 個人帳號 only、Claude in Chrome 互動 session 唯一路徑、Hourly cron 物理上發不出去」（見 `docs/fb_pipeline_permanent_fix.md` §三 / 五 / 六）。但 6/8 hourly-10 仍在 boss report 寫「還需要你做：mile_22d52561 FB 走 Claude in Chrome」 — 這把 AI 該自動處理的 ops gap 丟回老闆，違反 mission（AI 全自動運營），第二次觸發 boss 不滿（email-11728 10:21 「那是你的問題，你要解決」）。

**How to apply**：
1. cron 寫 FB awaiting 後**只**記 work_log + 留 status；不在 boss report 段列出
2. 流程已有保護：72h auto-expire / dashboard awaiting 不警報 / `mark_fb_post_status expired_skip` enum — 系統自動處理，不該變老闆 inbox
3. 互動 session 自然接管時做（trending dual-publish + 補留言貼連結）；沒接管 → 72h auto-expire 算成本可接受
4. 若 boss report 真要 mention FB（罕見），用「FB 狀態」純資訊段，**不**用 imperative 「你 / 請」字眼
5. Boss report drafter（cron `cron_review.py` / `boss_report_*` 等）若改 prompt 加 FB section，先 check 此 memory + `docs/fb_pipeline_permanent_fix.md` §四撤回項

相關：[[feedback_fb_personal_account_chrome_only]] / [[feedback_use_anti_ai_style]]
