# 網站重構計畫 — Codex + Gemini 審查意見

## Codex (GPT) 審查

### 評價：方向正確，但尚未達到可執行的水準

### 嚴重問題

1. **雙源資料架構仍有風險**
   - 本地 JSON 是 source of truth，Supabase 是展示層 — 但沒有版本控制、冪等鍵、replay 工具和 drift 偵測
   - 生產環境中 DB 事實上就是 source of truth，不管你怎麼稱呼它
   - 建議：用 server-side ingestion/RPC + idempotent upsert 取代直接寫入

2. **存取模型不安全**
   - `article_views` 允許無限制匿名 INSERT → analytics 灌水和寫入放大攻擊
   - `research_questions` 設為公開可讀但標記為「內部」→ 矛盾
   - `comments` 表沒有 RLS → 不應存在於真實部署中

3. **Schema 過度使用 JSONB/TEXT[]**
   - `tags`, `related_articles`, `feed_articles`, `details` 等應正規化為 join tables
   - 這會讓搜尋、篩選、排名、去重和索引變差

4. **Feature gating 只在前端**
   - 前端的 `<FeatureGate>` 元件不是真正的授權
   - 如果前端直連 Supabase，premium/admin 邊界必須也存在於 RLS 或 RPC 中

5. **時程過於樂觀**
   - 10-15 天只夠做嚴格 MVP（auth + 持久化問題 + 基本文章遷移）
   - 完整實作（OAuth + RLS + 排程 + admin CRUD + analytics + QA + 切換）需要 **3-5 週**

### 建議的改進

- `profiles` 加入：email, avatar_url, status, billing_role, last_seen_at
- `articles` 加入：slug (分開於 PK), updated_at, excerpt, cover_image_url, search_document (FTS)
- 新增 join tables：`article_tags`, `article_relations`, `question_article_links`
- `user_questions` 加入：title, body, topic, moderation_status, duplicate_of
- 用 quota ledger 取代 `questions_remaining` 單一計數器
- 拆分 analytics：`article_impressions`, `article_reactions`, `bookmarks`
- 加入 audit tables、subscriptions/entitlements、search index 策略
- Premium $5/month 可能太低

### 建議的 Phase 順序（與原計畫不同）
1. Schema 設計 + RLS + migration scripts
2. Article read path + article import
3. Auth + profiles + user questions
4. Publish workflow + admin
5. Analytics
6. Memory/risk/paper-trading migration
7. Feature gating + premium
8. Cleanup + cutover

---

## Gemini 審查

### 評價：架構方向正確，推薦立即開始 Phase 1

### 主要建議

1. **合併 question tables**
   - `research_questions` 和 `user_questions` 合併為一張 `questions` 表
   - 加入 `source` 欄位（'internal' / 'user'）
   - 簡化 Q&A 頁面邏輯

2. **Articles 用 UUID PK + slug UNIQUE**
   - 不要用 slug 當 PK（未來改 slug 會很痛苦）
   - UUID 作為穩定 PK，slug 用於 SEO URL

3. **Analytics spam 防護**
   - `article_views` 加 unique constraint：`(article_id, session_id, created_at::date)`
   - 防止同一用戶/session 一天內重複計數

4. **JSONB 佔空間**
   - 大 experiment 資料（logs/CSV）改存 Supabase Storage（S3-like）
   - DB 只存 metadata/summary

5. **Supabase Free Tier 注意**
   - 免費專案 1 週不活躍會 pause
   - 需要 heartbeat cron 保持活躍

6. **Full-Text Search**
   - 用 Postgres `tsvector` 做高效全文搜索
   - 計畫中提到搜尋但沒定義實作

7. **文章關聯**
   - 用 `parent_id` 或 `version_group_id` 取代 `related_articles TEXT[]`
   - 更好地連結同一研究的「一般版」和「專業版」

8. **Phase 順序微調**
   - Phase 1 (Questions) 正確——最低風險驗證 Auth+DB
   - Phase 2 應合併 Article Migration + Minimal Admin View

### Admin Dashboard
   - 將 Draft Management 提前到 Phase 2（可以驗證 Article migration）
   - Phase 4 (Admin Dashboard) 通常比預期多 30-50% 時間

---

## 共識重點（兩者都提到）

| 問題 | Codex | Gemini |
|------|-------|--------|
| Analytics INSERT 無限制 | ★ 嚴重 | ★ 需 unique constraint |
| Feature gating 不能只前端 | ★ 嚴重 | ✓ 提到 |
| 缺 Full-Text Search | ★ 需 tsvector | ★ 需 tsvector |
| 時程偏樂觀 | 3-5 週 | tight but doable |
| Schema 需正規化 | ★ join tables | ✓ 合併 tables |
| Premium 定價 | $5 太低 | 未提及 |

## 下一步

根據審查意見，應優先修正：
1. Analytics rate limiting / unique constraint
2. Server-side feature gating (RLS)
3. 加入 FTS (tsvector)
4. 調整時程為 3-5 週
5. Schema 正規化（至少 article_tags join table）
