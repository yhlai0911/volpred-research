---
name: feedback_fb_personal_account_chrome_only
description: FB 個人帳號無 Graph API/粉專(釘死)；發文走真 GUI Chrome，2026-07-07 起 fb_realchrome_post CDP-attach(port 9222)可從 headless hourly 發，不再限互動 session
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

**2026-07-07 機制更正(實證推翻「非互動 session 無法發 FB」)**:
本日 headless hourly-14 dispatch fire **成功發 FB**（mile_d12825bb MOVE 文），用 `scripts/fb_realchrome_post.py` **CDP-attach 到專用持久 profile 的真 GUI Chrome**（`~/.volpred/fb_chrome_profile`，port 9222）。
- **不變(釘死)**:個人帳號無 Graph API / 無粉專 / 無 headless 假瀏覽器 — 上面 6/3 boss override 全部仍成立,禁止任何 Page/Graph API 提案。
- **更正**:「必須互動 session + Claude in Chrome MCP」的假設**過時**。CDP-attach 是 scriptable,**任何 session(含 headless hourly cron)都能發**,前提 = 老闆那台 dedicated Chrome(port 9222)開著且已一次性登入 FB(密碼只能老闆輸)。所以 FB 發文**不再是「非 24/7」的物理限制** — 只要 dedicated Chrome 常駐登入,hourly 即可自主發。
- **awaiting_interactive_session 的正確處理**:先跑 `fb_realchrome_post.py --check`;PASS(port 9222 登入)→ 直接發,不要標 awaiting 堆積。draft 缺 `## 圖片` 時先 `upload_chart(png, bucket='article-images')` 上傳 lazypack 再補圖(worker 只吃 URL、0 圖 ABORT)。
- SOP 正典 = skill `fb-publishing`(唯一機制 fb_realchrome_post + 硬規則:發前查重/主文必附圖/連結進留言/中文剪貼簿)。
- 老闆 msg229「你立刻發 明明就有開著的Chrome」= 正是這條認知落差的 incident。

關聯:[[feedback_trending_repost_route]]、[[reference_antigravity_cli]]、[[project_platform_vision_full]]、[[feedback_dont_ask_do]]、[[feedback_fb_post_idempotency_guard]]。
