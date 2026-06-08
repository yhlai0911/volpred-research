# FB Pipeline 根因與永久解（2026-06-03 boss override 改寫）

**Status**：2026-06-03 改寫 · Page / Graph API 路徑**永久撤回**（boss 用粗口糾正，第二次違反 memory `feedback_fb_personal_account_chrome_only`）
**Trigger incident**：email-11932（用戶回信「你他媽的我就是要經營我個人 Facebook 帳號不是粉絲專頁」），覆蓋 hourly-11 11:18 提出的 Page + Graph API 方案
**前置 context**：5/29 已寫入 memory「FB 個人帳號 only → Claude in Chrome」；hourly-11 6/3 仍提 Page 是第二次違反。本 doc 撤回 §三/四 Page 方案，永久釘死「個人帳號 + claude-in-chrome + 非 24/7」現實。

---

## 一、根因（physical-level，不是 bug）

| 路徑 | 結果 | 原因 |
|---|---|---|
| Meta Graph API（個人帳號） | ❌ 物理不存在 | Meta 不對個人 profile 開放 programmatic post |
| Selenium / Playwright headless | ❌ 風控鎖帳 | FB 自動化偵測，違 ToS |
| Claude in Chrome MCP | ✅ **唯一可行** | 需 interactive session + Chrome ext + 已登入 FB |
| FB Page + Graph API | ❌ boss 否決 | boss 經營**個人帳號**不要粉專；不換軌道 |

**結論**：FB 自動化只有 1 條 path = Claude in Chrome（互動 session）。Cron 環境物理上發不出去 — 這是個人帳號的固有 trade-off，**不再嘗試繞過**。

## 二、流程修整（已做，保留）

### Fix A：`awaiting_interactive_session` 不算 terminal

`scripts/audit_fb_pipeline.py` 原把 awaiting 歸 terminal → audit 永遠 0 alert → 4 天累積看不見。

**改**（已 commit）：
- 移出 terminal set
- `AUTO_EXPIRE_HOURS=72` — awaiting >72h 自動降 `expired_skip`（補無 ROI）
- awaiting >24h 計 stale_pending + alert

### Fix B：`expired_skip` enum

`scripts/mark_fb_post_status.py` 新增此 status。時效過的文不再無限期占 queue。

### Fix C：4 篇歷史 awaiting 清空

`mile_4c141c2f / 783e6f49 / 1b0477a8 / 622a2b73`（5/29-6/01）→ `expired_skip`。

時效已過 5-6 天，補發無 ROI。dashboard `verification_fb_pipeline` warn 清乾淨。

---

## 三、永久解（個人帳號 + 互動 session only）

**boss 2026-06-03 釘死**：不建 Page、不要 Graph API、不要粉專、連 Plan B Buffer/Make.com 都不要（因為它們仍需 Page）。

### 唯一路徑

**Claude in Chrome（手動 / 半自動）發到 Ivan Lai 個人 FB**。前提：
1. 有互動 session 開著
2. Chrome ext `mcp__claude-in-chrome__*` available
3. Chrome 已登入 facebook.com/yihao.lai

### 接受的現實 trade-off

| 項目 | 狀態 |
|---|---|
| 24/7 自動發 FB | ❌ 物理不可能，**不再承諾** |
| Cron-driven trending 雙發 | ❌ FB 段必 awaiting → 72h 後 expired_skip |
| 互動 session 內 trending 雙發 | ✅ 寫 feed + Claude in Chrome 同步發 FB |
| 排程貼文（已發後補留言貼 VolPred 連結） | ✅ 只在互動 session 內做（handoff KEEP 區記 follow-up） |

### Cron 環境的 FB step 設計

當 hourly cron 寫 trending feed published 但發不到 FB：
1. 留 `awaiting_interactive_session` 狀態 + 寫 work_log entry `fb_post_awaiting`（**不阻塞** feed publish）
2. 72h 內若有互動 session 接手 → 走 claude-in-chrome 發；否則 audit auto-expire
3. dashboard 不再對 awaiting 警報 — 這是預期狀態，不是 bug

### 互動 session 的 FB 發文 SOP

完整 SOP 在 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md`。要點：
- 改寫版（不貼 VolPred 原文，重組 200-400 字）
- 主貼文不放連結；連結放第一則留言
- Ivan Lai 口吻（先個人觀察 → 短句短段 → 留白）
- claude-in-chrome 整段貼上，貼後 screenshot 檢查再送出

---

## 四、撤回項

下列方案 boss 已否決（2026-06-03），**永久不再提案**：
- ❌ 建 VolPred FB Page
- ❌ Page + Graph API headless publisher（`scripts/publish_to_fb_page.py` 骨架作廢）
- ❌ `_sync_fb_post` Graph API routing fork
- ❌ Buffer / Make.com 第三方排程（仍需 Page）
- ❌ 任何形式的「混合架構」— Page 連動個人帳號 / Page tag 個人 timeline 等

理由：boss 明確要求「個人帳號」是品牌核心，不接受任何把 reach 分離到 Page 的方案。商業判斷 = 個人聲量 > 自動化效率。

## 五、master_plan / memory 同步

- master_plan §6.6（FB headless 化）**作廢** — P6 改成「FB via Claude in Chrome 在互動 session 執行 + audit awaiting 自動化」
- memory `feedback_fb_personal_account_chrome_only` 加 2026-06-03 釘死段（已 commit）
- CLAUDE.md `(c2) event_article 特別` 段保留「FB 失敗不阻塞 feed publish 但必留 retry log」— 仍適用

## 六、為什麼這次釘死

- 這是**第二次**違反 memory（第一次 5/29，第二次 6/3 hourly-11）— 三振前線
- boss 用粗口表達 = trust violation；hourly chain 再提 Page 會變第三振
- 從此把「FB 自動化路徑」當 **closed question**，連 followup task 都不開

## 七、Boss-report 句型禁忌（2026-06-08 email-11728 新增）

Hourly cron / autonomous fire 寄的 boss report **禁止**：

- ❌ 「還需要你做：mile_xxxx FB 走 Claude in Chrome」
- ❌ 「FB Ivan Lai 發文待你接手」
- ❌ 任何把 awaiting_interactive_session 包裝成 user-actionable 的 imperative 段

**Why**: 6/8 10:14 hourly-10 boss report 仍寫此句型 → 10:21 boss 回信「你是說你沒辦法幫我用FB發文嗎？那是你的問題，你要解決」（email-11728） — AI 該自動處理的 ops gap 不該丟回老闆，違反 mission #1 全自動運營承諾。

**How**:
1. cron 寫 FB awaiting 後**只**記 work_log + 留 status；boss report 不列
2. 流程保護已就位：72h auto-expire + dashboard awaiting 不警報 + `expired_skip` enum
3. 互動 session 自然接管做（trending dual-publish）；沒接管 → 72h 後 auto-expire 成本可接受
4. Boss report 真要 mention FB（罕見）→ 用「FB 狀態」純資訊段、無 imperative「你 / 請」字眼
5. memory `feedback_boss_report_no_fb_handback` 紀錄此規則
