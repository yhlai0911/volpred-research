---
name: feedback_fb_dual_publish_precheck
description: FB 雙發佈恢復（2026-06-19）；發 FB 前必先檢查老闆是否已手動發過同主題
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 9b03f82f-4b5a-4fd1-8247-88240cdbc856
---

用戶 2026-06-19 指示：**FB 雙發佈恢復**（trending_repost / event_article 回到 dual-publish 到 Ivan Lai FB），先前 session 級的「FB 先停」解除。

**但新增硬性 guardrail**：發 FB 前**必先檢查該主題是否已經在 FB 上發過**——因為老闆可能臨時心血來潮自己先發了。

**Why**：自動再發會造成重複貼文、傷 Ivan Lai 個人帳號觀感（個人聲量是長期商業 anchor）。寧可漏發不要重發。

**How to apply**（每次 trending_repost / event_article 要 dual-publish 到 FB 前的第一步，先於寫文案）：
1. Claude in Chrome 開 Ivan Lai 個人 FB（自選 MAC STUDIO Chrome，見 [[reference_fb_chrome_browser_autoselect]]，不問用戶）。
2. 掃最近 7–14 天貼文比對主題（主論點/關鍵數字/主圖/是否帶 volpred 連結）。
3. 已發過 → **跳過 FB 主貼文**只做 feed，`mark_fb_post_status.py --status skipped_already_posted` + 記既有 URL；不重發。不確定 → 偏保守跳過標 `skipped_uncertain_dup` 回報老闆。feed 端不受影響、FB 跳過不算失敗。

FB 個人帳號只能走 Chrome（無 headless API，見 [[feedback_fb_personal_account_chrome_only]]）→ FB 部分只能在 interactive session 執行；hourly headless cron 只能做 feed 端。

落地：`.claude/skills/trending-repost/references/fb-ivanlai-tone.md` §0 + `.claude/rules/publishing.md` FB pre-check 段。關聯 [[feedback_trending_repost_route]] [[feedback_boss_report_no_fb_handback]]。
