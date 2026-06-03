# FB Pipeline 根因與永久解

**Status**：2026-06-03 立稿 · 等待 5 分鐘 user action 解鎖 80% 自動化
**Trigger incident**：email-11939（用戶嚴厲質問「FB 到底要錯幾次」），4 天 100% 失敗（5/29-6/01）
**前置 context**：email-11845 已寫過根因（5/31 hourly-10 commit `09297360`），但當時用了問選擇題 A/B/C 模式，違反 CLAUDE.md「不問選擇題」原則 → 用戶顯然把 email 當卡關等他 → 沒回 → 同問題再發。本次改成主動執行 + user 只需 5 分鐘 click。

---

## 一、根因（physical-level，不是 bug）

| 路徑 | 結果 | 原因 |
|---|---|---|
| Meta Graph API（個人帳號） | ❌ | Meta 不對個人帳號開放 programmatic post 權限 |
| Selenium / Playwright headless | ❌ | FB 風控偵測自動化 → 鎖帳風險，且違反 ToS |
| Claude in Chrome MCP | ⚠️ | 需 interactive session + browser ext + 用戶 click consent，hourly cron 環境無 browser tool |

**結論**：個人 FB 帳號（Ivan Lai）在 24/7 cron 環境**物理上無 headless 發文路徑**。每次 `awaiting_interactive_session` 都是等不到。連續 4 天累積 = 系統設計上的死結，不是執行錯誤。

## 二、流程上的次因（已修）

### Fix A：`awaiting_interactive_session` 不應算 terminal（commit 本次 fire）

`scripts/audit_fb_pipeline.py` 原把 `awaiting_interactive_session` 歸到 `TERMINAL_OR_HANDOFF_STATUSES` → audit 永遠 0 alert → dashboard 看不到 4 天累積。

**改**：
- 移出 terminal set
- 加 `AUTO_EXPIRE_HOURS=72` — awaiting 超過 72h 自動降為 `expired_skip`（補發無 ROI）
- 仍 awaiting >24h 計入 `stale_pending` + 觸發 alert email

### Fix B：新增 `expired_skip` status（commit 本次 fire）

`scripts/mark_fb_post_status.py` VALID_STATUSES 加 `expired_skip`。時效已過的 trending/event 不再無限期占用 awaiting queue。

### Fix C：標記 4 篇歷史 awaiting → expired_skip（commit 本次 fire）

- `mile_4c141c2f`（5/29 AI 基建燒錢）
- `mile_783e6f49`（5/30 NVDA 選擇權）
- `mile_1b0477a8`（5/30 VIX vs 個股波動）
- `mile_622a2b73`（5/31 AI 資本支出）

時效已過 5-6 天，補發無 ROI。dashboard `verification_fb_pipeline` warn 清乾淨。

---

## 三、永久解（VolPred FB Page + Graph API）

唯一根因解。原因：
- **物理可行**：FB Page 帳號有 Graph API access token，**完全 headless** post
- **商業路徑一致**：Mission 5（曝光×變現）的長期載體本來就是 Page，個人帳號只是過渡
- **架構乾淨**：cron / autonomous loop 不再依賴互動 session

### 三角分工

| 角色 | 用途 |
|---|---|
| Ivan Lai 個人帳號 | 維持品牌 + 重要文 + 朋友互動（人工發） |
| **VolPred FB Page**（新建） | 跑自動化發文 + 累積 SEO 友善的公開頁 |
| 連結 | Page 文章可 tag 個人 → 個人 timeline 有曝光，且 Page admin = 個人 → 完全在你控制下 |

### User Action（5 分鐘 click，唯一需要你做的事）

**Step 1**（2 min）：建 Page
1. 開 https://www.facebook.com/pages/create
2. Page name: `VolPred 波動率研究` （或你想要的名）
3. Category: `Finance` / `Education`
4. 完成 → Page 已建好

**Step 2**（3 min）：拿 Long-Lived Page Access Token
1. 開 https://developers.facebook.com/tools/explorer/
2. App: 用「Graph API Explorer」預設 app（不用自己建 app）
3. User Token → 加權限 `pages_show_list` + `pages_manage_posts` + `pages_read_engagement`
4. Generate Access Token → 拿到 short-lived user token（1 小時）
5. 用 token 換 long-lived page token（60 天）：
   ```bash
   curl -s "https://graph.facebook.com/v18.0/me/accounts?access_token=<SHORT_USER_TOKEN>" | jq
   # 找你的 Page ID + page access_token（這是 long-lived，幾乎不過期）
   ```
6. 把 Page ID + Page access_token 貼到 `.env`：
   ```
   FB_PAGE_ID=...
   FB_PAGE_ACCESS_TOKEN=...
   ```
7. 告訴我「token 配好了」，我立即啟動 publisher

**完成後**：所有 trending_repost / event_article 發到 feed 同時自動推 Page，0 互動 session 需求。

### 我這邊已準備（待 token）

- `scripts/publish_to_fb_page.py`（待寫，骨架見下方 §四）— Graph API headless publisher
- `volpred.publisher.publisher._sync_fb_post()` 改為 routing：個人帳號路徑（claude-in-chrome）→ Page 路徑（Graph API）
- 第一週並行兩條路徑驗證 → 穩定後 deprecate 個人帳號路徑
- 寫到 Page 後仍可選擇人工 share 到個人 timeline（一鍵）

### Fallback（若 Page 路徑卡）

- **Plan B**：Buffer.com / Make.com 排程（~$5-15/month，連 RSS → FB Page）— 仍須 Page
- **Plan C**：純維持人工 — 但接受 awaiting 是常態，不要再期待 24/7 自動

---

## 四、`publish_to_fb_page.py` 骨架（待 token 注入即可上線）

```python
# scripts/publish_to_fb_page.py
import os, requests
from pathlib import Path

PAGE_ID = os.environ["FB_PAGE_ID"]
TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
BASE = f"https://graph.facebook.com/v18.0/{PAGE_ID}"

def post_to_page(message: str, link: str | None = None) -> dict:
    payload = {"message": message, "access_token": TOKEN}
    if link:
        payload["link"] = link
    r = requests.post(f"{BASE}/feed", data=payload, timeout=30)
    r.raise_for_status()
    return r.json()  # {"id": "..."}

def post_comment(post_id: str, message: str) -> dict:
    r = requests.post(
        f"https://graph.facebook.com/v18.0/{post_id}/comments",
        data={"message": message, "access_token": TOKEN},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def publish_full(message: str, mile_id: str) -> dict:
    """主貼文 + 第一則留言貼 VolPred 連結（同 trending-repost 規則）。"""
    post = post_to_page(message)
    comment_url = f"https://volpred.zeabur.app/v3/reports/{mile_id}"
    comment_msg = f"完整版分析 + 圖表在這裡 → {comment_url}"
    comment = post_comment(post["id"], comment_msg)
    return {
        "post_id": post["id"],
        "post_url": f"https://www.facebook.com/{post['id']}",
        "comment_id": comment["id"],
    }
```

整合進 `volpred.publisher.publisher`：
- `_sync_fb_post` 新增 routing：env 有 `FB_PAGE_ID` 走 Graph API 路徑；無則 fallback 標 `awaiting_interactive_session`
- `mark_fb_post_status` success 寫回 feed.json `details.fb_post_url` + `details.fb_comment_url`
- 失敗 → retry 3 次 → 最終標 `fb_silent_reject` + alert email

## 五、Mission impact

- **Mission 4（平台運營）**：FB pipeline 從 best-effort 改 first-class — `verification_fb_pipeline` 不再 chronic warn
- **Mission 5（曝光×流量）**：每篇 trending/event 100% 觸達 FB → 漏斗入口擴大 + SEO 友善的公開 Page 累積
- **Mission 1（文章寫好）+ ULTIMATE GOAL**：付費漏斗的 awareness 段不再漏接

## 六、為什麼這次回信不問選擇題

CLAUDE.md L93-96：「除此之外：遇任何問題自行由底層邏輯與流程去修整優化」
memory `feedback_dont_ask_do`：「判斷『建議做』之後立即執行，不問『要我直接做嗎？』型選擇題」

上次 email-11845（5/31）我問 A/B/C，用戶顯然把 email 當「卡關等他」忘了回 → 4 天無進展 → 第三 strike。

本次直接做 Option A 的 80%（audit fix、status enum、4 篇 expired_skip、永久解 doc、程式碼骨架），只留 user 必須親自的 5 分鐘 click（Page 創建 + token 拿取，FB account safety constraint），不再問。
