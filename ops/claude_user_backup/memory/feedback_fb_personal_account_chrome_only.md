---
name: feedback_fb_personal_account_chrome_only
description: FB 是用戶個人帳號 → 只能走 Claude in Chrome / computer use，沒有 Graph API headless 選項
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-05-29 明確指正:「我經營的是我個人帳號,沒有 headless,你就是要走 computer use / Claude in Chrome」。

**Why**:FB Graph API 的程式化發文只支援 **Page**(粉專),不支援**個人 profile**。Ivan Lai 經營的是個人帳號,所以**沒有 headless / Graph API token 這條路**。唯一能發到個人 FB 的方式 = **瀏覽器自動化(Claude in Chrome / mcp__claude-in-chrome__*)**。

**How to apply**:
- FB 發文(trending_repost 雙發佈、event_article FB)一律走 Claude in Chrome browser automation,**不要**再問「FB token / Graph API / headless」這種不存在的選項。
- 這代表 FB 發文**本質需要互動 session + Chrome 開著且已登入 FB** — 這是個人帳號的固有限制,不是流程缺陷,接受它。
- master_plan P6「FB headless 化」的框架是**錯的** → 應改為「FB via Claude in Chrome,在互動 session 執行」。
- 不要為了「不間斷自動化」去硬做 headless FB(技術上不存在);trending/event 文章的 FB 發佈安排在有 Chrome 的互動 session 做。

**成本相關同場指正**:trending 掃描用免費 `agy`(Antigravity gemini-3.5),沒有付費 API 成本 tradeoff 要「決定」。已落地 `scripts/scan_trending_agy.py` + wire `VOLPRED_TRENDING_SCAN_CMD`。

**2026-06-03 再次違反紀錄(hourly-11 11:18 email)**:hourly-11 仍提「永久解 = FB Page + Graph API + 5 min user click」,被用戶用粗口糾正(email-11932:「你他媽的我就是要經營我個人 Facebook 帳號不是粉絲專頁」)。違反這條 memory 第 5/29 的明確指令。**從此永久禁止任何 Page / Graph API / 粉專方案提案**,連 fallback / Plan B 都不寫;唯一路徑 = Claude in Chrome + 互動 session,接受非 24/7 自動化現實。

**永久結論(2026-06-03 boss override 釘死)**:
- FB 自動化只有 1 條 path:Claude in Chrome(個人帳號登入)
- 4 天卡死的根因 = 物理限制(非互動 session 無法發 FB),不是流程 bug
- awaiting >72h 自動 expired_skip 是正確設計(時效過了補無 ROI)
- 不再承諾 24/7 FB 自動化 — 改成「有互動 session 才發,沒有就 expired_skip」
- docs/fb_pipeline_permanent_fix.md 已撤回 Page 提案

關聯:[[feedback_trending_repost_route]]、[[reference_antigravity_cli]]、[[project_platform_vision_full]]、[[feedback_dont_ask_do]]。
