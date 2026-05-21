# FB Pending Backlog Audit — 2026-05-17

**Audit type**: Governance / process gap diagnostic
**Trigger**: trending_repost agent 連續報告 fb_post_status=pending / pending_manual 未實際發佈到 Ivan Lai FB
**Scope**: 純診斷，不改 production 檔；不嘗試 auto-post（過去 6+ retry 失敗，pattern 已知）
**Author**: 主線程 (Claude)
**Data source**: `storage/reports/trending_repost_log.json` (mtime 2026-05-17 04:29)

---

## 1. 現況統計

### 1.1 Pending 條目清單

`trending_repost_log.json` 共 7 entries，其中 **6 個 fb_post_status 非 `success`**：

| date | mile_id | status | word_count | feed published? | FB draft 備好? |
|---|---|---|---|---|---|
| 2026-05-15 | mile_ed39c127 | `pending` | 1976 | draft (status field) | ✗ 無 fb_post_draft |
| 2026-05-16 | mile_27eb3e20 | `success` ✓ | 0 | published | (success) |
| 2026-05-16 | mile_50f44a46 | `pending_manual` | 1143 | published | ✓ 有 fb_post_draft + fb_comment_draft |
| 2026-05-16 | mile_dda1e670 | `pending_manual` | 1977 | published | ✓ 有 fb_post_draft + fb_comment_draft |
| 2026-05-16 | mile_609d9ff3 | `pending` | 1715 | published | ✗ 無 fb_post_draft |
| 2026-05-17 | mile_207d3750 | `pending` | 2100 | (n/a) | ✓ 有 fb_draft + fb_comment_link |
| 2026-05-17 | mile_ba1dc7f8 | `pending` | 1850 | (n/a) | ✓ 有 fb_draft + fb_comment_link |

### 1.2 Headline 指標

- **Pending count**: **6 / 7** (85.7%)
- **最早 pending**: `mile_ed39c127` (2026-05-15) — **已 pending ~2 天**
- **唯一 success**: `mile_27eb3e20` (2026-05-16) — 但 `fb_post_url: null` + `word_count: 0`，**`success` status 可信度本身存疑**（可能是 logger 樂觀標記，非真正 FB post 完成）
- **`retry_count` 欄位**: 7 條目中只有最新 2 條（2026-05-17）有此欄位，全部 = 0 — 代表**沒有任何 retry 邏輯實際被執行過**
- **總影響範圍**: 5 個雙發佈承諾的 trending_repost 任務 ≈ 50% 任務未完成（per publishing.md L7 + trending-repost SKILL § 7 「FB / Ivan Lai 同步發佈是任務定義的一部分」）

### 1.3 Schema 不一致警訊（次要 finding）

7 entries 中欄位名稱不統一：
- 2026-05-16 三筆用 `fb_post_draft` + `fb_comment_draft`
- 2026-05-17 兩筆用 `fb_draft` + `fb_comment_link`
- 2026-05-15 + `mile_609d9ff3` **完全沒寫 FB draft 欄位**

= **trending_repost workflow 對 FB draft 的 schema contract 不固定**，下游 retry / batch poster 無法依賴穩定欄位名稱讀。

---

## 2. Root Cause 分析

### 2.1 結構性（root cause 1 — primary）：沒有任何 production FB poster 真的能跑

trending-repost SKILL § 7 設計 **primary path = `claude-in-chrome` 瀏覽器自動化**：
- 假設 Ivan Lai 已登入用戶 Chrome profile
- 假設 Chrome 是開的
- 假設 claude-in-chrome MCP tools 可在 dispatch 派出的 agent context 內 invoke

實際運行條件下 **三個假設沒有任何一個被自動驗證**：
- Background agent / cron-dispatch 派出的 trending_repost agent **沒有 MCP tool access**（claude-in-chrome MCP 只在主線程互動 session 有；headless dispatch ≠ interactive session）
- 即使主線程跑，Chrome browser state 是 ephemeral（沒登入、tab 不在 FB、redirect 等）
- 沒有 healthcheck / dead-man switch 偵測 "agent 嘗試 FB post 但 MCP 不可用" → agent 只好 fallback 寫 `pending_manual` 並結束

**證據**：5/6 pending 中**沒有任何 retry attempt log**（`retry_count: 0`），代表不是「試了 N 次失敗」而是「從來沒實際 attempt 過 post」。

### 2.2 結構性（root cause 2）：無 Facebook Graph API token / 無 osascript fallback

trending-repost SKILL § 7 「MCP path (alt)」段落本身就標註：
- MCP URL `mcp.facebook.com/ads` may be **Ads-API only, not personal wall posting**
- 沒有 backup mechanism (e.g. Graph API personal token、macOS osascript 操作 Chrome.app)

= **單一 path（claude-in-chrome）失敗就完全 unblock**，無第二條路。

### 2.3 流程（root cause 3）：retry log 沒人 monitor + dispatch 不檢查 backlog

SKILL § 7 「Failure handling」寫「Next trending_repost fire checks log for pending FB retries before generating new content (max 3 retries before giving up)」— 但此 check **沒被任何 dispatch script / cron job 實作**：
- 過去 2 天連續派 5 個新 trending_repost agent，**沒有任何一個先處理 backlog 再開新 content**
- 主線程 + cron dispatch 都沒有 "pending FB queue depth ≥ 3 → 暫停新派、先清 backlog" 的 gate

### 2.4 流程（root cause 4）：governance silent — 無 error_log entry、無 user alert

- `docs/error_log.md` grep `facebook|claude-in-chrome|fb post` → **0 hits**
- 連續 2 天 5+ 篇 pending 沒觸發 user-facing alert（per `feedback_email_on_major_decisions.md`「重要決策後主動 send_alert email」原則，FB workflow break 屬於該 alert 範疇）
- 等於系統默默累積 backlog，沒人知道 workflow 已完全 broken

### 2.5 設計（root cause 5）：「FB 雙發佈是任務定義一部分」與「不阻塞 feed publish」邏輯衝突

SKILL § 7 + publishing.md L7 同時主張：
- (A) FB 同步發佈是任務定義的一部分 ← strict
- (B) FB post 失敗 **不**阻塞 VolPred publish ← lax

實作上 (B) 永遠覆蓋 (A) — feed 永遠發、FB 永遠 pending，且 pending 不被視為任務失敗。**「任務定義的一部分」沒有 enforcement**，等同 nice-to-have。

---

## 3. 短期 Mitigation（下一篇前可立即執行）

### 3.1 Stop the bleeding — 暫停新 trending_repost dispatch（即刻）

- 主線程 work_log + cron prompt 暫時設 `trending_repost daily cap = 0`，**直到 backlog 清空**
- 理由：再派只會繼續累積 pending；先處理已有 5 篇 FB draft 才符合「任務定義一部分」原則
- 預估 token 成本：**0**（純 dispatch policy 調整）

### 3.2 Manual paste batch session（主線程 + 用戶協作）

主線程已備好 `fb_post_draft` / `fb_draft` + `fb_comment_draft` / `fb_comment_link` 的 4 筆：
- `mile_50f44a46`（Moody's downgrade）
- `mile_dda1e670`（Japan carry trade）
- `mile_207d3750`（NVDA earnings）
- `mile_ba1dc7f8`（cross-asset selloff）

執行方式：
1. 主線程印出 4 個 FB body + 4 個 comment link 成 1 個 batch markdown
2. 用戶在 ~15min 手動 paste 到 Ivan Lai FB（順序、間隔可控制 spam filter）
3. 用戶把 FB post URL 回報主線程
4. 主線程批次更新 `trending_repost_log.json`：`fb_post_status: "posted"` + `fb_post_url: "<URL>"` + `posted_at`

預估 token 成本：**~3k tokens**（生成 batch markdown + 4 個 log update edit）

### 3.3 補齊缺 FB draft 的 2 筆 backlog

- `mile_ed39c127`（AI 4 giants CapEx）+ `mile_609d9ff3`（VIXTWN/VIX divergence）**沒有 FB draft**
- 主線程或 forked subagent 從 mile_ JSON content 抽 hook + 1 個關鍵數字，照 SKILL § 7 + fb-ivanlai-tone.md 改寫 200-400 字
- 然後納入 3.2 batch session

預估 token 成本：**~8k tokens**（2 篇 mile_ 文 + tone reference 讀 + 2 篇 200-400 字改寫）

### 3.4 寫 error_log entry（補 governance）

新增 `docs/error_log.md` entry：
- Date: 2026-05-17
- Title: `trending_repost FB dual-publish workflow silent break (5/6 pending across 2 days)`
- Root cause: 上述 § 2.1-2.5
- Lesson: 任何 "dual-publish" 任務必須有 healthcheck，否則 secondary surface 會 silent 失敗
- Fix: short-term = 3.1+3.2，long-term = § 4 選定 architecture

預估 token 成本：**~2k tokens**

**短期 mitigation 總 token 成本：~13k tokens** + 用戶 ~15min manual paste 時間

---

## 4. 長期 Architecture 改進（3 選 1）

### Option A — claude-in-chrome 穩定化（lowest effort, fragile）

**做法**：
- 寫 `scripts/fb_post_via_chrome.py` — 主線程互動 session 專用 wrapper
- Pre-flight check: Chrome 開著? Ivan Lai 已登入? FB tab 存在?
- 若 pre-check fail → email user "open Chrome + login FB, then re-run"
- 不嘗試從 headless dispatch agent 跑（永遠失敗）

**Pros**: 
- 不需新 API token / OAuth flow
- 重用既有 claude-in-chrome MCP

**Cons**:
- 依賴主線程 + 互動 session + Chrome state，**無法真正自動化**
- 仍是「半人工」workflow，pending 仍可能累積（用戶忘記開 Chrome）
- claude-in-chrome MCP 本身 brittleness 未解（DOM 變動、cookie 過期、CAPTCHA）

**適合場景**：用戶能保證每天 ≥1 次主線程互動且 Chrome 開著時。

**Token cost**: ~15k (script + pre-check + log update)
**Recurring user time**: ~5min/day（盯 alert + 確保 Chrome state）

---

### Option B — osascript fallback（medium effort, macOS only）

**做法**：
- 寫 `scripts/fb_post_via_osascript.applescript`
- 控制 Chrome.app：開新 tab → navigate facebook.com → 用 keystroke 操作 textbox → 貼上 + submit
- Trigger: `osascript scripts/fb_post_via_osascript.applescript <fb_body> <comment_link>`
- 由 cron + 主線程都可呼叫（osascript 不需 Chrome MCP）

**Pros**:
- 真正 headless-friendly（cron 可呼叫，不需互動 session）
- macOS native，無新 dependency
- 仍利用既有 Chrome profile（不需新 OAuth）

**Cons**:
- 仍依賴 GUI state（Chrome 要開、FB tab 要在前景、System Events 要有 Accessibility 權限）
- FB DOM/UI 改了就 break，keystroke 順序 brittle
- 只在 macOS 上能跑

**適合場景**：用戶日常本機就掛 Chrome + FB tab，且能授 Accessibility 權限給 cron daemon。

**Token cost**: ~25k (script + dom inspection + edge case handling)
**Recurring user time**: ~0（只在 Chrome 強制重啟或 FB UI 變時要修）

---

### Option C — Facebook Graph API token（highest effort, most robust）★ 推薦

**做法**：
1. 用戶在 Facebook for Developers 建一個 personal app（個人帳號就能建）
2. Generate **Pages API access token**（針對 Ivan Lai page，非 personal wall — 個人 wall API 已停用）
3. Token 存 `~/.config/volpred/fb_token`（gitignore），TTL 60 天可 refresh
4. 寫 `scripts/fb_post_via_graph_api.py`：
   - `POST /<page-id>/feed` with `message=<body>`
   - 取 `post_id` → `POST /<post-id>/comments` with `message=<comment_with_link>`
5. cron 每 30min 掃 `trending_repost_log.json` pending 條目並逐筆發送
6. 成功寫回 `fb_post_status: "posted"` + `fb_post_url`，失敗 increment `retry_count`，retry ≥ 3 標 `failed_permanent` + email alert

**Pros**:
- **真正 headless**，零人工介入
- Token-based，不依賴 GUI / browser state
- 可獨立 unit test（mock Graph API）
- FB 官方 supported，不會因 UI 變動 break
- 可加 healthcheck cron 監控 backlog depth → 自動 alert

**Cons**:
- 需用戶一次性 setup developer app + 取 token（~15min 一次性）
- 只能發 **Page**，不能發 personal wall（FB 已 deprecate personal wall API）— **需確認 "Ivan Lai" 是 Page 還是 personal account**
  - 若是 Page → API 可發
  - 若是 personal account → API 不可發，回到 Option A/B
- Token 60 天要 refresh（可寫成 cron auto-refresh）

**適合場景**：Ivan Lai 是 FB Page（business / creator page），且追求真正自動化。

**Token cost**: ~40k (script + retry logic + healthcheck + token refresh + tests)
**Recurring user time**: ~5min / 60 天（refresh token；可自動化降到 0）

---

## 5. 推薦下一步 + 預估成本

### 5.1 推薦執行順序

**Phase 1 — 立即（今天，~13k tokens + 用戶 15min）**：
1. 暫停新 trending_repost dispatch（§ 3.1）
2. 補 2 篇缺 FB draft 的 backlog（§ 3.3）
3. 生成 batch paste markdown 給用戶（§ 3.2）
4. 寫 error_log entry（§ 3.4）
5. 用戶 manual paste 5 篇 → 主線程 batch update log

**Phase 2 — 本週（驗證 Ivan Lai surface 性質）**：
6. 確認 "Ivan Lai" FB surface 是 **Page** 還是 **personal account**
   - 若 Page → 進 Phase 3 走 Option C（推薦）
   - 若 personal → 進 Phase 3 走 Option A（claude-in-chrome 強化版）

**Phase 3 — 下週（永久解決，~25-40k tokens）**：
7. 實作選定的 architecture
8. 加 healthcheck cron 監控 pending depth ≥ 3 → email alert
9. 把 trending_repost daily cap 恢復 ≤ 2
10. 寫 regression test cover 整個 dual-publish workflow

### 5.2 為什麼這個順序

- **Phase 1 先清 backlog** = 守住 "FB 同步發佈是任務定義一部分" 的承諾（不留 5+ 篇 pending 給讀者看不到的 FB 訊號）
- **Phase 2 surface 性質確認** = 避免做完 Option C 才發現「Ivan Lai 是 personal account，API 根本不能發」的浪費
- **Phase 3 永久 fix** = 之前 Three-Strike Rule 已被觸發（5 次連續 silent fail）— 不能再 patch 一輪「再試一次 claude-in-chrome」，必須結構性重構（per CLAUDE.md L84-104 Three-Strike Rule）

### 5.3 總預估成本

| Phase | Token (Claude) | 用戶時間 | 復發風險 |
|---|---|---|---|
| Phase 1 (immediate) | ~13k | ~15min one-shot | High（不 fix 結構，下週同 pattern 再來） |
| Phase 2 (surface check) | ~1k | ~2min | n/a |
| Phase 3 Option A | ~15k | ~5min/day recurring | Medium-High |
| Phase 3 Option B | ~25k | ~0 recurring | Medium |
| Phase 3 Option C | ~40k | ~15min once + 5min/60d | Low ★ |

**強烈推薦終局走 Option C**（若 Ivan Lai 是 Page）。若必須走 personal account → Option A + 規定每日 09:00 主線程啟動 morning routine 自動掃 backlog + 用戶人工 paste。

### 5.4 不做的代價

若不修：
- trending_repost workflow 持續 silent 半破（feed 端 OK、FB 端永遠 0）
- Mission Goal 1（文章寫好）+ Goal 5（曝光流量）皆受損 — FB 是 Ivan Lai personal brand 漏斗入口
- 每篇 trending_repost 改寫成本（agent token + 主線程 review token）有 50% 沒換到 FB 曝光 → ROI 砍半
- 治理上違反「任務定義一部分」原則 → CLAUDE.md 信任度降低
- Three-Strike Rule 已觸發但不執行 → 規則本身被掏空

---

## Appendix: Schema 修復建議（順手）

統一 `trending_repost_log.json` schema 為固定 contract：

```json
{
  "date": "YYYY-MM-DD",
  "timestamp": "ISO8601 + tz",
  "mile_id": "mile_XXXX",
  "trending_topic": "...",
  "source_surface": "...",
  "primary_sources_used": [...],
  "volpred_angle": "...",
  "word_count": 1234,
  "gemini_verdict": "...",
  "codex_verdict": "...",
  "feed_status": "draft|published",
  "fb": {
    "body_draft": "200-400 字改寫",
    "comment_draft": "...連結...",
    "image_path": "path or null",
    "post_status": "pending|posting|posted|failed_permanent",
    "post_url": "URL or null",
    "posted_at": "ISO8601 or null",
    "retry_count": 0,
    "last_error": "string or null"
  }
}
```

統一後 retry / healthcheck / poster script 才有穩定 contract 可依賴。
