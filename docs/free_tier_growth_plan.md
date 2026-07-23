# 免費階段成長計畫 — Reader Analytics（P1）

> **文件狀態**：v1 spec（現況盤點 + 選型決策 + MVP 拆解）
> **對應 task**：`growth_p1_reader_analytics`（`docs/boss_direction_recommendations.md` §2, rid:reader-analytics）
> **對應老闆訴求**：「Reader analytics（CTR / 停留時間 / 跳出率 / 回訪 cohort） — 沒這個我盲打文章品質」
> **建立**：2026-07-19｜**owner**：主線程（本 spec 唯一 owner）
> **範圍**：本文件只做 spec；不改任何代碼、不動 storage/config/frontend。

---

## TL;DR（給趕時間的人）

1. **task 前提是錯的。** task 與 boss_direction 都寫「repo 內無任何 analytics/telemetry 實作（git ls-files 無命中）」。實際上**線上同時跑著兩套 reader analytics**：自架 Umami（站級行為）+ 自建 Supabase first-party pipeline（per-article impression / read_time / reaction + 會員閱讀史 + admin console + `pull_reader_metrics.py` 落地到 `storage/analytics/`）。`git ls-files` 看不到，是因為 `frontend-v2-fix/` 被 canonical `.gitignore:40` 排除（巢狀獨立 repo），**這正是 task 自己列為第 1 步的 code-ownership 盲點造成的誤判**，不是真的零實作。

2. **選型決策其實已在實務上做出，且方向正確：自建 first-party + 自架 Umami 分層並存。** 本 spec 的建議是**維持這個 hybrid、補完缺口，而不是改採 Plausible/SaaS**。理由：Supabase 已付費、Umami 已自架（零增量成本、cookieless）、且只有 first-party 能算「會員 cohort + 內容偏好回饋迴圈 + 未來付費漏斗」——這三項第三方 SaaS 給不了。

3. **老闆要的 4 個指標，目前覆蓋度不一，缺口具體且可定位**：
   - **停留時間**：機制已建，但 **v3 文章頁沒掛 beacon** → per-article read_time 大量漏收（`storage/analytics/latest.json` top 文章 `avg_read_time_sec: null` 的直接原因）。
   - **跳出率**：Umami 有站級 bounce；per-article bounce 要等停留時間補齊後衍生。
   - **CTR**：**完全沒收**。first-party 只記「文章被打開」，沒記「feed 卡片被曝光」，分母缺席。
   - **回訪 cohort**：**schema 層就卡死**。`session_id` = sessionStorage `vp_sid`，每個 tab session 重置，無持久 visitor id → 無法辨識回訪者。這是 4 項裡最硬的一個 gap。

4. **MVP = 補這 4 個缺口**，把「有在收一些數據」變成「老闆能讀 CTR/停留/跳出/回訪來判斷文章品質」。拆成 6 個可獨立成 task 的步驟，1–2 週。

---

## 1. 現況盤點（含證據）

### 1.1 盤點方法與 canonical repo 的誤判來源

在 canonical repo 根目錄執行：

```
git ls-files | grep -iE 'analytic|telemetry|beacon|plausible|umami|tracking|pageview|gtag|ga4'
```

命中的**只有資料產物與實驗檔**：`storage/analytics/*.json`、`storage/analytics/reader_preferences*.md`，以及若干 `experiments/.../wikimedia_pageviews_*.csv`。**沒有任何前端埋點或 ingestion 代碼命中。**

這正是 task/boss_direction 誤判「0 實作」的根源。真正原因：

```
git check-ignore frontend-v2-fix   → frontend-v2-fix   （命中，.gitignore:40）
```

`frontend-v2-fix/` 是**獨立巢狀 git repo**（remote = `github.com/yhlai0911/volpred-v2.git`），被 canonical `.gitignore` 排除。所有前端 analytics 代碼活在那個 repo 裡，**canonical 的 `git ls-files` / grep / audit 一律看不到**。

> **結論修正**：不是「repo 內無 analytics 實作」，而是「canonical repo 的檢查工具看不到前端 repo」。前端 analytics **有版控**（在 volpred-v2 repo），只是與 canonical 分家。這與 sibling task `growth_p1_article_view_display` 描述的 code-ownership 問題是同一個。詳見 §1.5。

### 1.2 線上系統 A：自架 Umami（第三方，站級行為）

`frontend-v2-fix/src/app/layout.tsx:17-18` 在**根 layout** 嵌入 Umami 追蹤腳本：

```tsx
const UMAMI_SCRIPT_URL   = process.env.NEXT_PUBLIC_UMAMI_SCRIPT_URL  ?? 'https://ivan-umami.zeabur.app/stats.js';
const UMAMI_WEBSITE_ID   = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID  ?? 'cd3b8df8-84cf-4a72-b8a2-f240b8b40d8c';
// layout.tsx:97-98
{UMAMI_SCRIPT_URL && UMAMI_WEBSITE_ID ? (
  <script defer src={UMAMI_SCRIPT_URL} data-website-id={UMAMI_WEBSITE_ID} />
) : null}
```

- **已自架在 Zeabur**（`ivan-umami.zeabur.app`），有 website-id，非僅一個標籤。
- 掛在根 layout → **v3 與原版兩版都涵蓋**（Next.js App Router 巢狀 layout 不重繪 `<html>`，v3 的 `V3Layout` 只包 `{children}`，Umami 仍由根 layout 注入）。
- 提供：站級 pageview、dwell、bounce、referrer、device、cookieless 訪客近似回訪。**這已回答老闆「跳出率」的站級版本，並提供 CTR/回訪的部分近似。**
- **待驗證**：Umami dashboard 目前是否有實際流量寫入、資料是否被人真的在讀（我無法從 repo 判定線上 Umami 實例健康度，見 §8）。

### 1.3 線上系統 B：自建 Supabase first-party pipeline（per-article + 會員）

一條完整、已上線的自建鏈路：

| 層 | 檔案 | 職責 |
|---|---|---|
| 前端 beacon | `src/components/ReportImpression.tsx` | 文章頁掛載即送 impression；用 `visibilitychange`/`pagehide` 累送 `read_time_sec`；`keepalive` fetch；每 session/日去重 |
| ingestion API | `src/app/api/analytics/impression/route.ts` | 寫入 `article_impressions`（含 read_time 取 max 更新、user_id 補綁、IP rate-limit 30/min） |
| reaction API | `src/app/api/analytics/reaction/route.ts` | like/bookmark/share 寫 `article_reactions`（**須登入**，否則 401） |
| 顯示數字唯一源 | `src/lib/article-views.ts` | 文章顯示瀏覽數（seed + 成長公式），與 raw count 解耦（boss telegram-976 修過的「頂部 22／下方 3」不一致） |
| 會員視圖 | `src/app/api/me/summary/route.ts` + `MyMemberHomeConsole.tsx` | 會員閱讀史 / 收藏 / read_time |
| admin console | `src/app/api/admin/analytics/*` + `AdminAnalyticsConsole.tsx` + `src/lib/admin-analytics.ts` | 會員 vs 匿名 impression、reaction mix、weighted_views 排序 |
| 後端聚合 | `scripts/pull_reader_metrics.py` | 每日從 Supabase 拉 `article_impressions`+`article_reactions`，聚合 score / read_time / 完讀率 proxy → `storage/analytics/reader_metrics_YYYY-MM-DD.json` + `latest.json` |
| 偏好迴圈 | `scripts/analyze_reader_preferences.py` → `reader_preferences.json` | 讀者偏好回饋到選題（memory `project_reader_preference_feedback_loop`） |

### 1.4 資料庫 schema（`docs/migration/001_schema.sql:151-185`）

```sql
CREATE TABLE article_impressions (
  id BIGSERIAL PRIMARY KEY,
  article_id UUID REFERENCES articles(id),
  user_id UUID REFERENCES profiles(id),   -- NULL = 匿名
  session_id TEXT,                          -- 前端 vp_sid（sessionStorage，每 session 重置）
  read_time_sec INT,
  impression_date DATE,                     -- trigger 依 Asia/Taipei 自動設值
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_impressions_dedup ON article_impressions (article_id, session_id, impression_date);

CREATE TABLE article_reactions (
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  reaction TEXT NOT NULL,                   -- like / bookmark / share
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (article_id, user_id, reaction)
);
```

**關鍵限制**：`article_impressions` 沒有持久 `visitor_id` 欄位；辨識粒度只有 `session_id`（會重置）與 `user_id`（僅登入者）。→ 回訪 cohort 在此 schema 下算不出來（§3.4）。

### 1.5 實測資料現況（`storage/analytics/latest.json`, 2026-07-18 pull）

```
window_days=30, since=2026-06-18
articles_with_activity = 223
raw_impression_rows    = 520      ← 30 天 520 筆 / 223 篇 ≈ 2.3 impression/篇（偏薄）
raw_reaction_rows      = 0        ← 0 筆 reaction
top 文章 avg_read_time_sec = null ← 停留時間沒進來
```

- **impression 偏薄 + read_time null**：高度懷疑是 §3.2 的 v3 beacon 缺失——若主流量在 v3（美化層），而 beacon 只掛原版，per-article 表就會系統性漏收。
- **reaction = 0**：reaction 需登入才能送（route 401 gate），會員數少 → 幾乎收不到。非 bug，是「登入門檻 × 會員基數小」的結構結果。

### 1.6 code-ownership 現況（task 第 1 步的正解）

- 前端**有版控**，在獨立 repo `github.com/yhlai0911/volpred-v2.git`（即 `frontend-v2-fix/`）。
- 風險**不是**「沒版控」，而是「canonical repo 的 audit / grep / `git ls-files` 掃不到前端」→ 造成本 task 這種「以為零實作」的誤判，且前端改動不受 canonical CI / 測試 / roadmap-coverage 覆蓋。
- **本 spec 不擅自改 code-ownership 結構**（動 `.gitignore` / submodule 化屬架構決策，且與 `growth_p1_article_view_display` 重疊）。建議：把「前端 analytics 檔清單」以一份 canonical-side manifest（純文字）納入 `audit_roadmap_coverage.py` 之類的稽核視野，讓 canonical 側「看得到」前端有哪些 analytics 實作，避免重複誤判。列為 §7 步驟 0。

---

## 2. 選型決策

### 2.1 判準（老闆指定）

讀者隱私｜成本（平台已付費 Supabase）｜能否算回訪 cohort / CTR / 停留時間。

### 2.2 三個選項評比

| 判準 | 自建 first-party（Supabase + beacon） | 自架 Umami（現況已有） | 第三方 SaaS（Plausible Cloud） |
|---|---|---|---|
| 讀者隱私 | 最佳（資料自持、可 cookieless、RLS 控管） | 佳（cookieless、開源、資料自持） | 佳（EU 主機、cookieless），但資料出境第三方 |
| 成本 | **零增量**（Supabase 已付費） | **零增量**（已自架在 Zeabur） | 月費（依流量，$9+/mo 起，隨 pageview 漲） |
| 站級 pageview/bounce/referrer | 要自己算 | **現成** | 現成 |
| **per-article** 停留 / 完讀 | **可**（read_time 已在 schema） | 弱（Umami 事件可做但 join 內容 metadata 麻煩） | 弱（custom events 有限、無法 join 內容表） |
| **會員 cohort / 身分綁定** | **只有這條能做**（user_id join profiles） | 不行（匿名分析工具） | 不行 |
| **內容偏好回饋迴圈**（選題） | **已接**（`analyze_reader_preferences.py`） | 不行 | 不行 |
| **未來付費漏斗**（會員 → 轉換） | **只有這條能做** | 不行 | 不行 |
| 回訪 cohort | 需補 visitor_id（§3.4） | 站級近似（Umami 自帶 returning visitor） | 站級近似 |

### 2.3 建議（單一結論）

> **維持並補完現有 hybrid：自建 Supabase first-party（主力）＋ 自架 Umami（站級行為輔助）。不引入 Plausible 或其他 SaaS。**

理由：
1. **成本**：兩套都零增量；SaaS 是唯一會產生月費且隨流量遞增的選項，與「免費階段」定位相悖。
2. **隱私**：兩套皆資料自持、可 cookieless；SaaS 讓讀者資料出境第三方，反而較差。
3. **cohort / 迴圈 / 漏斗**：老闆的核心訴求「判斷文章品質」與平台終極目標「付費轉換」，都需要**會員身分綁定 + 內容 metadata join + 付費漏斗**——這三項**只有 first-party 能給**，SaaS 與 Umami 都是匿名站級工具，天花板明確。
4. **沉沒建置**：first-party 鏈路已上線（beacon → API → 表 → 聚合 → 偏好迴圈 → admin console），改採 SaaS 等於丟棄可用資產再重建。

**分工定位**：Umami 負責便宜的站級行為（bounce / referrer / device / 站級回訪），first-party 負責 per-article + 會員身分 + 付費漏斗。兩者不重疊、互補。

---

## 3. 缺口分析（對映老闆 4 個指標）

### 3.1 CTR（點擊率）— 完全未收，需新增

- **現況**：first-party 只記「文章被打開」（article-open impression），**沒記「feed 卡片被曝光」**。CTR = 打開數 / 卡片曝光數，分母缺席。
- **需要**：feed / 首頁 / 分類頁的**卡片曝光事件**（list-impression）+ 卡片點擊事件。
- **方案**：優先用 Umami custom event（`umami.track('card_impression', {article_id})` / `card_click`）低成本收 CTR；若要 join 內容 metadata 做精細分析，再考慮 first-party list-impression 輕量 beacon（IntersectionObserver 曝光才送，避免灌水）。MVP 先走 Umami event。

### 3.2 停留時間（dwell）— 機制已建但 v3 漏收，需補掛

- **現況**：`ReportImpression.tsx` 已會送 read_time_sec，但**只掛在原版 `src/app/reports/[id]/ReportDetail.tsx:178`**；v3 `src/app/v3/reports/[id]/ArticleReader.tsx` **沒有 import/mount `ReportImpression`**（grep 零命中）。
- **後果**：v3 文章頁的閱讀不進 first-party 表 → `latest.json` top 文章 read_time 全 null、impression 偏薄。
- **方案**：在 v3 `ArticleReader.tsx` 掛 `<ReportImpression articleId={...} />`（元件已存在，直接複用；符合 dual-route standing rule「兩版都要有」）。**這是投報比最高的一步**——一個元件掛載即補齊 v3 停留時間與 impression。

### 3.3 跳出率（bounce）— 站級已有，per-article 待衍生

- **現況**：Umami 提供站級 bounce。first-party 無 per-article bounce。
- **方案**：待 §3.2 補齊 v3 read_time 後，在 `pull_reader_metrics.py` 衍生 per-article bounce proxy = `read_time_sec < BOUNCE_THRESHOLD_SEC`（例如 < 10s）的 impression 佔比。門檻要在 methodology_notes 標明為 proxy（沿用現有 `read_time_is_proxy` 誠實標註慣例）。

### 3.4 回訪 cohort — schema 層卡死，需加持久 visitor_id

- **現況**：辨識粒度只有 `session_id`（sessionStorage `vp_sid`，每 session 重置）與 `user_id`（僅登入者）。**無法辨識「同一匿名訪客跨 session 回訪」。**
- **方案（二選一或並用）**：
  - **(a) first-party 持久 visitor_id**：前端改用 `localStorage` 存一個 UUID（`vp_vid`），beacon 帶上；`article_impressions` 加一欄 `visitor_id TEXT`。之後 cohort / 回訪率 / N 日留存可從 first-party 精算，且能與 user_id 串（匿名→註冊的轉換路徑，直接服務付費漏斗）。**推薦**，因為只有這條能接付費漏斗。
  - **(b) 靠 Umami 站級 returning-visitor**：零開發，但只有站級、無法 per-article、無法接會員身分。作為 (a) 上線前的過渡讀數。
- **隱私**：`localStorage` UUID 是第一方、無跨站追蹤、可在隱私頁揭露並提供清除方式（§6）。比 cookie 溫和。

### 3.5 缺口總表

| 老闆指標 | 現況覆蓋 | 缺口 | MVP 動作 |
|---|---|---|---|
| 停留時間 | 部分（原版有、v3 漏） | v3 beacon 未掛 | 步驟 1：v3 掛 `ReportImpression` |
| 跳出率 | 站級（Umami） | per-article 無 | 步驟 4：pull 腳本衍生 bounce proxy |
| CTR | 無 | 卡片曝光/點擊未收 | 步驟 2：Umami card event |
| 回訪 cohort | 站級近似（Umami） | 無持久 visitor id | 步驟 3：加 `vp_vid` + `visitor_id` 欄 |

---

## 4. MVP 資料 schema

**原則**：不重建，只增量。沿用既有兩張表，加最小欄位。

### 4.1 `article_impressions` 增量（migration，新檔）

```sql
-- supabase/migrations/0XX_article_impressions_visitor_id.sql
ALTER TABLE article_impressions ADD COLUMN visitor_id TEXT;   -- localStorage vp_vid，持久匿名訪客
CREATE INDEX idx_impressions_visitor ON article_impressions (visitor_id, created_at);
-- dedup 索引維持不變（article_id, session_id, impression_date）；visitor_id 僅供 cohort 分析，不進 dedup key
```

欄位語意：
- `session_id`（既有）：per-tab-session，維持 dedup / 防灌用途不變。
- `visitor_id`（新）：per-device 持久，跨 session，供回訪 cohort / 留存 / 匿名→會員轉換分析。
- `user_id`（既有）：登入者，最終身分。

### 4.2 CTR 事件（MVP 走 Umami，無需新表）

用 Umami custom events：
- `card_impression`：`{ article_id, surface: 'feed'|'category'|'home', position }`
- `card_click`：`{ article_id, surface, position }`

CTR = `card_click` 數 / `card_impression` 數（可依 surface / position 切）。若日後要 join 內容 metadata 精算，再評估 first-party `card_events` 表；MVP 不建。

### 4.3 聚合輸出（`pull_reader_metrics.py` 增量欄位）

在既有 `reader_metrics_YYYY-MM-DD.json` 每篇文章物件增加：
```jsonc
"bounce_rate_proxy": 0.0,          // read_time < BOUNCE_THRESHOLD_SEC 佔比（proxy，標註）
"unique_visitors": 0,              // distinct visitor_id
"returning_visitor_rate": 0.0      // visitor_id 在窗內出現 >1 天的佔比
```
methodology_notes 補：`bounce_threshold_sec`、`visitor_id_source: 'localStorage vp_vid'`、`returning_defined_as`。

---

## 5. 前端埋點清單

> Dual-route standing rule：以下每一項**原版 + v3 兩版都要處理**，改完兩版都要線上驗證。

| # | 埋點 | 位置 | 事件 / 送法 | 現況 |
|---|---|---|---|---|
| A | 文章開啟 impression | `reports/[id]`（原）✅ ／ `v3/reports/[id]` ❌ | 既有 `ReportImpression` → `/api/analytics/impression` | v3 待補掛 |
| B | 文章停留 read_time | 同 A（隨 A 元件） | `visibilitychange`/`pagehide` 累送 | v3 待補掛 |
| C | 持久 visitor_id | `ReportImpression`（或共用 util） | `localStorage vp_vid`（無則建 UUID），beacon 帶上 | 新增 |
| D | 卡片曝光 card_impression | feed / 首頁 / 分類卡片元件 | IntersectionObserver 進視窗才 `umami.track('card_impression', …)` | 新增 |
| E | 卡片點擊 card_click | 同 D 卡片連結 | `umami.track('card_click', …)` | 新增 |
| F | reaction like/bookmark/share | 文章頁 reaction bar | 既有 `/api/analytics/reaction`（須登入） | 已有；確認兩版 UI 都在 |

**埋點紀律**：
- 所有 beacon 沿用既有慣例——`keepalive: true`、失敗靜默（不可影響文章可讀性）、rate-limit（impression route 已有 30/min/IP）。
- card_impression 必用 IntersectionObserver「真的進視窗」才送，避免 CTR 分母灌水。
- visitor_id 用 `localStorage`（持久）而非 sessionStorage；session_id 維持 sessionStorage 不動。

---

## 6. 隱私聲明要點

現有 `src/app/disclaimer` 已存在，需補一段 analytics 揭露（原版 + v3）：

1. **收集什麼**：匿名閱讀行為（哪篇文章、停留秒數、是否回訪）、登入會員的閱讀與收藏紀錄。
2. **怎麼識別**：一個存在你瀏覽器 `localStorage` 的隨機 ID（`vp_vid`），**不跨站、不含個資、不賣給第三方**；清除瀏覽器資料即重置。
3. **cookieless**：Umami 站級分析不使用 cookie。
4. **用途**：只用於改善文章選題與品質、平台體驗；不做廣告 retargeting。
5. **會員資料**：登入後的閱讀史綁定帳號，可於會員中心查看；提供刪除管道。
6. **選擇退出**：說明如何清除 `vp_vid`（清除 localStorage / 瀏覽器資料）。
7. **法遵**：台灣個資法揭露為主；若有 EU 流量，Umami cookieless + localStorage-only 已屬低風險，但保留 opt-out 說明。

---

## 7. 1–2 週實作步驟拆解（每步可獨立成 task）

> 每步都有明確完成定義 + 線上驗證（curl / Chrome / SQL count），不假設。排序＝投報比。

**步驟 0（canonical 可見性，0.5 天）** — 建一份 canonical-side manifest（純文字，列前端 analytics 檔清單），納入 roadmap/coverage audit 視野，讓 canonical 側掃得到前端有哪些 analytics 實作，杜絕「以為零實作」再發生。不動 `.gitignore` 結構。
- 完成定義：`audit_roadmap_coverage.py`（或新稽核）能列出前端 analytics 檔且不再誤報 0 覆蓋。

**步驟 1（v3 停留時間補掛，0.5–1 天）★最高投報比** — v3 `ArticleReader.tsx` 掛 `<ReportImpression articleId={…} />`。
- 完成定義：Chrome 開 `/v3/reports/<id>`，Network 見 `POST /api/analytics/impression`；隔日 `pull_reader_metrics.py` 該文章 `avg_read_time_sec` 非 null；SQL `select count(*) from article_impressions where ...` 較前一日增長。

**步驟 2（CTR 事件，1–2 天）** — feed/首頁/分類卡片加 `card_impression`（IntersectionObserver）+ `card_click` Umami event（兩版）。
- 完成定義：Umami dashboard 看得到兩個 event 有流量；能算出至少一個 surface 的 CTR。

**步驟 3（回訪 cohort 基建，2–3 天）** — (a) migration 加 `article_impressions.visitor_id`；(b) 前端 beacon 帶 `localStorage vp_vid`（兩版，隨步驟 1 元件）；(c) impression route 寫入 visitor_id。
- 完成定義：新 impression 的 `visitor_id` 非空；同瀏覽器隔日再訪，SQL 查得同一 visitor_id 跨兩個 impression_date。

**步驟 4（聚合衍生指標，1 天）** — `pull_reader_metrics.py` 加 `bounce_rate_proxy` / `unique_visitors` / `returning_visitor_rate`，methodology_notes 標 proxy 定義。
- 完成定義：`latest.json` 出現三個新欄位且數值合理（回訪率 ∈ [0,1]）。

**步驟 5（admin 呈現，1–2 天）** — `AdminAnalyticsConsole.tsx`（兩版 admin）加 CTR / 回訪率 / per-article bounce 卡片與排序欄，資料接步驟 2/4 輸出。
- 完成定義：admin analytics 頁線上看得到 4 個指標；數字與 canonical 聚合一致（v3=呈現層，不得脫鉤）。

**步驟 6（隱私揭露，0.5 天）** — disclaimer 補 analytics 段（兩版）。
- 完成定義：兩版 disclaimer 線上可見 analytics 揭露與 opt-out 說明。

**依賴**：步驟 1 → 3 → 4（read_time/visitor_id 是 bounce/cohort 的前提）；步驟 2 獨立；步驟 5 依賴 2/4；步驟 6 獨立。可並行：{1,2,6} 先行，{3}接1，{4}接3，{5}最後。

---

## 8. 現況讀不到 / 待驗證項（誠實揭露）

以下是本次盤點**無法從 repo 靜態判定**、需線上實測或老闆確認的項目：

1. **線上 Umami 實例健康度**：`ivan-umami.zeabur.app` 是否仍在跑、是否有實際流量寫入、dashboard 有沒有人在讀——我只能確認腳本已嵌入 layout，無法確認資料真的在累積。**需線上實測**（開站看 Network 是否有 Umami 請求 200）。
2. **v3 vs 原版實際流量佔比**：若主流量在 v3，步驟 1 的影響會非常大；若主流量在原版，影響較小。目前無流量分佈數據可判定（正是本 task 要建的東西）。
3. **reaction UI 是否兩版都掛**：確認了 reaction API 與 admin 消費端存在、`MyMemberHomeConsole` 消費 reaction，但未逐版確認文章頁上的 like/bookmark/share 按鈕在原版與 v3 都渲染。步驟 5 前需補查。
4. **會員基數**：reaction=0 的另一半原因是會員數小；實際 profiles 筆數未查（不在本 spec 範圍，屬 `growth_p1_auth_onboarding`）。
5. **Umami custom event 權限 / API**：MVP 步驟 2 假設自架 Umami 支援 `umami.track()` custom events（Umami v2 支援）；上線前需確認該實例版本。

---

## 附錄：與 sibling task 的關係

- `growth_p1_article_view_display`（顯示瀏覽次數，已 succeeded）：與本 task 共用 `article_impressions` 表與 `article-views.ts` 顯示公式；其 code-ownership 障礙（frontend gitignored）與本 spec §1.5 同源。
- `growth_p1_auth_onboarding`：會員基數 / 登入 flow 屬該 task；本 spec 的 reaction=0 與 cohort→會員轉換分析會受其進展影響。
- 本 spec 產出後，`growth_p1_reader_analytics` 應在 `audit_roadmap_coverage.py` 顯示 live（task 完成定義之一）。
