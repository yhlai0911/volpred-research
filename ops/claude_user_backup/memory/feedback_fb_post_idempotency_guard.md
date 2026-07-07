---
name: feedback_fb_post_idempotency_guard
description: FB 發文（及任何多入口 outward-facing 動作）必須有 idempotency guard，執行端讀 canonical fb_post_status 當 pre-action gate
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1bb7c310-9b07-4b91-8e3b-9226ef11bb67
---

2026-07-07：老闆授權「發」第一篇 FB 後，同一 mile（mile_08fefa59）被**兩個 session 各發一次**（早前 email close 流程 + hourly email_reply dispatch），老闆個人頁出現 2 篇相同貼文（相隔 11 分鐘）= 機器人訊號。已 CDP 刪重複保留 1 篇。

**根因**：canonical 單源 `fb_post_status`（feed.json / trending_repost_log，`mark_fb_post_status.py` 維護）存在，但 `scripts/fb_realchrome_post.py --post` **從不讀也不寫它** → 執行端不看狀態就盲發。

**Why**：凡「多入口都能觸發的 outward-facing 動作」（發文/寄信/下單/發佈）都要 idempotency key + 跨 process 原子 claim。有 canonical 狀態源卻不在執行端讀 = 形同沒有。FB 個人頁是老闆對外門面，重複發文的鎖帳/reputation 成本遠高於加 guard。

**How to apply**：
- `fb_realchrome_post.py` 已加 guard（2026-07-07）：`--post` 前 `_claim_fb_post(mile_id)` 檢查 `fb_post_status==success`→SKIP、ledger `storage/ops/fb_post_claims.json` 有 <5min in-flight→SKIP、否則寫 in-flight claim 放行（held `shared_state_lock("fb_post_claim")`）；發成功 `_finalize_fb_post` 標 `success`。`--force` 繞過、`--dry-run` 不 claim。
- mile_id 抽取：draft「# mile_id: mile_XXX」註解 → 退回檔名 `fb_mile_XXX.md`。
- 新增任何 outward-facing 自動化，先問：多條路徑會不會同時觸發？有沒有讀 canonical 狀態當 gate？
- 相關：[[feedback_fb_dual_publish_precheck]]、[[feedback_audit_no_passive_terminal]]、[[reference_fb_chrome_browser_autoselect]]。incident 詳見 docs/error_log.md 2026-07-07。
