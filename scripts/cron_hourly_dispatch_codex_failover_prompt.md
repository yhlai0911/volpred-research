新一輪 hourly tick —— **Claude dispatch 失敗，由 Codex failover 接手**（Claude 額度/auth/API 不可用時觸發）。

步驟：
1. `cat storage/ops/handoff_latest.md`（每小時 :50 已重生）。
2. 從 Section 4 pending top 8 挑一個 **Codex-eligible** task_type（platform_ops / experiment / governance / code review / daily_article / paper_review — 詳見 AGENTS.md 對照表）。**避開** reader-facing 需 anti-ai-style 的高品質寫作、`email_reply`、FB 類、`paper_body`、`paper_decision` —— 那些留給 Claude 主線程，Claude 恢復後處理。
3. `uv run python scripts/task_pool_claim.py claim --id <id> --owner codex-failover`。already_claimed → 換下一筆；全被 claim 或無 Codex-eligible → 找 `docs/error_log.md` 近 7 天 actionable lint/refactor，或跑一個 backlog experiment。
4. `start` → **完整完成**（50min 內收尾，不留半成品）→ `complete --status succeeded --result '...'`。
5. commit 訊息開頭加 `[codex]`，**不 push**（本機 git_push_backup cron 會處理）。
6. 若上一輪有未完事項，先收尾再挑新工。

結束回報：完成項目 + commit hash。記住此輪是「Claude 不可用時的 Codex 代班」，目標是讓 hourly slot 不空轉、研究/ops/code 線不中斷。
