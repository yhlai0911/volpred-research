# 網站重構方案 v4（整合 Codex + Gemini 審查意見）

## 架構原則

```
本地研究系統 (storage/*.json = source of truth)
    ↓ idempotent upsert via service-role RPC
Supabase DB (展示層 + 用戶數據 + analytics)
    ↓ RLS-enforced queries
Next.js API routes (server-side validation)
    ↓
前端 (anon key, read-only direct queries for public data)
```

**核心規則：**
- 所有運算在本地端，結果產生後 POST 到 DB
- DB 是展示層 + 用戶數據存儲（用戶提問、會員資料、analytics）
- 前端**不直連 Supabase 做寫入**——所有寫入經 Next.js API（防濫用）
- 讀取：公開資料可直連 Supabase（anon key + RLS），敏感資料走 API
- 用戶提問反向拉取：DB → 本地（定時 cron）

---

## 技術選型

| 項目 | 選擇 | 原因 |
|------|------|------|
| DB | Supabase PostgreSQL（預留遷移 Zeabur PG 彈性）| 免費 500MB、Auth 內建、Realtime。設計上用標準 SQL + 環境變數切換連線，未來可遷移 |
| Auth | Google OAuth + Magic Link | 零密碼、一鍵登入 |
| Search | Postgres tsvector FTS | 原生、免費、無額外服務 |
| Analytics 寫入 | 經 Next.js API（rate limit）| 防 spam |
| 大檔案 | Supabase Storage (S3-like) | 實驗 logs、PDF 等 |
| Frontend | Next.js (保持) | 不變 |
| 部署 | 新 Zeabur 專案 (volpred-v2) | 不影響現有站 |

---

## Database Schema（正規化版）

```sql
-- ═══════════════════════════════════
-- 會員系統
-- ═══════════════════════════════════

CREATE TABLE profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT,
  display_name TEXT,
  avatar_url TEXT,
  role TEXT DEFAULT 'free',          -- free / premium / admin
  status TEXT DEFAULT 'active',      -- active / suspended
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 配額管理（取代單一 counter，按月重置）
CREATE TABLE quota_usage (
  id SERIAL PRIMARY KEY,
  user_id UUID REFERENCES profiles(id),
  period_start DATE NOT NULL,        -- 每月 1 號
  questions_used INT DEFAULT 0,
  questions_limit INT DEFAULT 3,     -- free=3, premium=unlimited(-1)
  UNIQUE(user_id, period_start)
);

-- ═══════════════════════════════════
-- 文章系統（正規化）
-- ═══════════════════════════════════

CREATE TABLE articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT UNIQUE NOT NULL,         -- URL-friendly: leverage-direction-matters
  title TEXT NOT NULL,
  content TEXT,
  excerpt TEXT,                      -- 自動截取前 200 字
  audience TEXT DEFAULT 'research',  -- research / general / diary / daily / qa
  phase TEXT,
  status TEXT DEFAULT 'draft',       -- draft / scheduled / published / archived
  category TEXT DEFAULT 'milestone',
  proposer TEXT,
  author_id TEXT DEFAULT 'claude',
  cover_image_url TEXT,
  details JSONB,                     -- 保留彈性欄位（少用）
  search_doc TSVECTOR,               -- Full-text search
  scheduled_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 文章標籤（正規化 join table）
CREATE TABLE tags (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE article_tags (
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  tag_id INT REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (article_id, tag_id)
);

-- 文章關聯（一般 ↔ 研究 延伸閱讀）
CREATE TABLE article_relations (
  source_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  target_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  relation_type TEXT DEFAULT 'related', -- related / general_version / research_version
  PRIMARY KEY (source_id, target_id)
);

-- FTS 自動更新 trigger
CREATE OR REPLACE FUNCTION update_search_doc() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_doc := to_tsvector('chinese', COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.content, ''));
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER articles_search_update
  BEFORE INSERT OR UPDATE ON articles
  FOR EACH ROW EXECUTE FUNCTION update_search_doc();

-- ═══════════════════════════════════
-- 問題系統（合併為一表）
-- ═══════════════════════════════════

CREATE TABLE questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,               -- internal / user
  user_id UUID REFERENCES profiles(id), -- NULL for internal
  question TEXT NOT NULL,
  status TEXT DEFAULT 'open',         -- open/partially_answered/answered/evaluating/ranked/researching
  priority TEXT DEFAULT 'medium',
  proposer TEXT,
  answer TEXT,
  score INT,
  score_breakdown JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  answered_at TIMESTAMPTZ
);

-- 問題-文章關聯
CREATE TABLE question_articles (
  question_id UUID REFERENCES questions(id) ON DELETE CASCADE,
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  PRIMARY KEY (question_id, article_id)
);

-- ═══════════════════════════════════
-- 論文系統
-- ═══════════════════════════════════

CREATE TABLE papers (
  id TEXT PRIMARY KEY,                -- leverage-direction, taiwan-vt
  title TEXT NOT NULL,
  authors TEXT NOT NULL,
  abstract TEXT,
  status TEXT DEFAULT 'working',      -- working / submitted / accepted / published
  target_journal TEXT,
  pages INT,
  pdf_url TEXT,
  score INT,                          -- review score
  tags TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════
-- Analytics（防 spam）
-- ═══════════════════════════════════

CREATE TABLE article_impressions (
  id BIGSERIAL PRIMARY KEY,
  article_id UUID REFERENCES articles(id),
  user_id UUID REFERENCES profiles(id),  -- NULL = anonymous
  session_id TEXT,
  read_time_sec INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  -- 防重複：同一 session 同一天只計一次
  UNIQUE(article_id, session_id, (created_at::date))
);

CREATE TABLE article_reactions (
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  reaction TEXT NOT NULL,              -- like / bookmark / share
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (article_id, user_id, reaction)  -- 每人每篇每類只能一次
);

-- 聚合 view（定時 refresh）
CREATE MATERIALIZED VIEW article_stats AS
SELECT
  a.id AS article_id,
  a.title,
  a.audience,
  COUNT(DISTINCT i.id) AS view_count,
  COUNT(DISTINCT i.session_id) AS unique_viewers,
  AVG(i.read_time_sec) FILTER (WHERE i.read_time_sec > 5) AS avg_read_sec,
  COUNT(DISTINCT r.user_id) FILTER (WHERE r.reaction = 'like') AS likes,
  COUNT(DISTINCT r.user_id) FILTER (WHERE r.reaction = 'bookmark') AS bookmarks,
  COUNT(DISTINCT r.user_id) FILTER (WHERE r.reaction = 'share') AS shares
FROM articles a
LEFT JOIN article_impressions i ON a.id = i.article_id
LEFT JOIN article_reactions r ON a.id = r.article_id
WHERE a.status = 'published'
GROUP BY a.id, a.title, a.audience;

-- ═══════════════════════════════════
-- 研究記憶
-- ═══════════════════════════════════

CREATE TABLE memory_entries (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,                  -- thinking / knowledge / log / experiment
  content JSONB NOT NULL,              -- metadata + summary
  created_at TIMESTAMPTZ DEFAULT NOW()
);
-- 大檔案（experiment raw data）存 Supabase Storage，DB 只存 metadata

-- ═══════════════════════════════════
-- 風險預報 + Paper Trading
-- ═══════════════════════════════════

CREATE TABLE risk_forecasts (
  id SERIAL PRIMARY KEY,
  data JSONB NOT NULL,
  generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE paper_trades (
  id SERIAL PRIMARY KEY,
  strategy TEXT NOT NULL,
  entry JSONB NOT NULL,
  trade_date DATE NOT NULL
);

-- ═══════════════════════════════════
-- 留言系統（預留，暫不啟用）
-- ═══════════════════════════════════

CREATE TABLE comments (
  id SERIAL PRIMARY KEY,
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  parent_id INT REFERENCES comments(id),
  content TEXT NOT NULL,
  status TEXT DEFAULT 'visible',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════
-- Feature Gating
-- ═══════════════════════════════════

CREATE TABLE feature_flags (
  feature TEXT PRIMARY KEY,
  required_role TEXT DEFAULT 'free',
  enabled BOOLEAN DEFAULT true,
  description TEXT
);

INSERT INTO feature_flags VALUES
  ('view_feed',          'free', true, '瀏覽 Feed'),
  ('view_risk_forecast', 'free', true, '風險預報'),
  ('vix_calculator',     'free', true, 'VIX 計算器'),
  ('view_paper',         'free', true, '論文下載'),
  ('ask_question',       'free', true, '提問（配額限制）'),
  ('view_ranking',       'free', true, '排名表'),
  ('realtime_thinking',  'free', true, '即時思考流'),
  ('priority_research',  'free', true, '優先研究'),
  ('unlimited_questions','free', true, '無限提問'),
  ('early_access',       'free', true, '提前閱讀'),
  ('export_data',        'free', true, '資料匯出');
-- 啟動付費時：UPDATE SET required_role='premium' WHERE feature IN (...)

-- ═══════════════════════════════════
-- Audit Log（管理操作追蹤）
-- ═══════════════════════════════════

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_id UUID REFERENCES profiles(id),
  actor_type TEXT DEFAULT 'admin',     -- admin / system / claude
  action TEXT NOT NULL,                -- publish / archive / score / role_change
  target_type TEXT,                    -- article / question / profile
  target_id TEXT,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Row Level Security（server-side enforced）

```sql
-- Profiles: 自己讀自己
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_own" ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "update_own" ON profiles FOR UPDATE USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id AND role = (SELECT role FROM profiles WHERE id = auth.uid()));
  -- 不能自己升級 role

-- Articles: published 公開讀，draft 只有 admin
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public_read_published" ON articles FOR SELECT
  USING (status = 'published');
CREATE POLICY "admin_read_all" ON articles FOR SELECT
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));
CREATE POLICY "service_write" ON articles FOR ALL
  USING (auth.role() = 'service_role');

-- Questions: 用戶讀自己的 + 公開已排名的
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own_read" ON questions FOR SELECT
  USING (user_id = auth.uid() OR source = 'internal' OR status IN ('ranked','researching','answered'));
CREATE POLICY "own_insert" ON questions FOR INSERT
  WITH CHECK (auth.uid() = user_id AND source = 'user');

-- Impressions: 經 API 寫入（不直連），admin 讀
ALTER TABLE article_impressions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "api_insert" ON article_impressions FOR INSERT
  WITH CHECK (auth.role() = 'service_role');  -- 只有 server-side API 可寫
CREATE POLICY "admin_read" ON article_impressions FOR SELECT
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));

-- Reactions: 用戶自己的
ALTER TABLE article_reactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own_react" ON article_reactions FOR INSERT
  WITH CHECK (auth.uid() = user_id);
CREATE POLICY "public_read" ON article_reactions FOR SELECT USING (true);

-- Feature flags: 公開讀
ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public_read" ON feature_flags FOR SELECT USING (true);
CREATE POLICY "admin_write" ON feature_flags FOR ALL
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));

-- Comments: 暫不啟用 RLS（UI 未開放）
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "disabled" ON comments FOR ALL USING (false);
```

---

## 發文流程

```
Claude 研究完成
    ↓ POST via service-role key (idempotent upsert)
articles 表（status: draft）
    ↓ Claude 自主排程
UPDATE status='scheduled', scheduled_at=...
    ↓ 排程引擎（Supabase Edge Function / cron）
UPDATE status='published' WHERE scheduled_at <= NOW()
    ↓
前端只顯示 status='published'
```

---

> **注意**：發文內容規則、研究日記寫法、品質標準等屬於本地端 skill 管轄（autonomous-research / feed-publisher），不在網站架構範圍內。網站只負責接收、存儲、排程、展示。

---

## 全站 UI/UX

### 導航（5 項）
```
研究(首頁) | 工具(下拉:VIX計算器+風險預報) | 論文 | 問答 | 登入
```

### 頁面改善重點
- Feed 首頁：
  - ★ **投資策略固定面板**（脫離 feed 卡片，獨立置頂區塊）
    - 支援多策略並列，每個策略一張卡片
    - 策略數量可動態增減（DB `strategy_signals` 表驅動）
    - **每張卡片包含**：
      - 策略名稱
      - 該策略涉及的資產價格（不是全部顯示 SPY！台股策略顯示 0050 價格、日股顯示 N225）
      - 當前配置權重（圓餅圖或色塊比例）
      - **價值圖縮圖**（sparkline/小型折線圖，顯示近 30 天 portfolio value 走勢）
      - VIX 水準、最後更新時間
      - **「操作說明」按鈕** → 展開操作步驟（例：「1. 查 SPY 5 日均報酬 2. >0 則持有 0050 3. <0 則轉現金」）
      - **「查看績效」連結** → 連到 `/portfolio#策略ID`（portfolio 頁面對應策略區段）
    - 可收合/展開
  - 文章卡片含 views/likes、audience 篩選、無限滾動、FTS 搜尋

```sql
-- 策略信號面板（daily_update 寫入，前端讀取）
CREATE TABLE strategy_signals (
  id SERIAL PRIMARY KEY,
  strategy_id TEXT UNIQUE NOT NULL,       -- slow_vt, recommended_5050, taiwan_spy_momentum...
  strategy_name TEXT NOT NULL,
  description TEXT,                        -- 一句話描述
  display_order INT DEFAULT 0,
  weights JSONB NOT NULL,                  -- {"SPY": 0.51, "GLD": 0.26}
  asset_prices JSONB,                      -- {"SPY": 669.03, "0050.TW": 75.6} — 只放該策略相關的資產
  vix_level NUMERIC,
  sigma_ann NUMERIC,
  operation_steps TEXT[],                  -- 操作步驟（陣列）
  portfolio_link TEXT,                     -- /portfolio#策略ID
  sparkline_data JSONB,                    -- 近 30 天 portfolio value [{date, value}, ...]
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  is_active BOOLEAN DEFAULT true
);
```

- Portfolio 頁面（大改）：
  - 每個策略一個區段（錨點 `#策略ID`）
  - 每個區段包含：
    - **累計報酬圖**（完整版，含 benchmark 比較線）
    - **操作手冊**：完整的操作步驟（以 $100 萬為例的金額計算）
    - **績效指標**：Sharpe、MDD、年化報酬、勝率
    - **回測 vs 實盤**：區分歷史回測和 paper trading 實際績效
    - **交易記錄表**：每次調整的日期、動作、權重變化
  - 策略間可以切換（tabs 或 sidebar）
- Risk Forecast：儀表板風格、VIX/GARCH gauge
- VIX Calculator：情境分析、手機滑桿
- Q&A：兩欄（研究問答 + 會員排名表）、提問需登入
- Paper：論文列表（卡片+進度條）
- 全站：Dark/Light、手機底部導航、Skeleton loading、SEO、PWA

### 文章交叉連結
- 一般文章底部 → 📊 延伸閱讀研究原文
- 研究文章底部 → 📖 看不懂？讀白話版

---

## 部署策略

```
現有 volpred.zeabur.app → 不動，持續運行
新建 volpred-v2 repo → volpred-v2.zeabur.app（開發期）
穩定後 → 用戶切換 domain
```

---

## 既有資料遷移方案

### Feed 文章（~338 篇）
```python
# 一次性匯入腳本
import json
from supabase import create_client

feed = json.loads(open('storage/reports/feed.json').read())
for item in feed:
    # 個別報告有完整 content
    report_path = f'storage/reports/{item["id"]}.json'
    report = json.loads(open(report_path).read()) if exists(report_path) else item

    supabase.table('articles').upsert({
        'slug': item['id'],           # mile_xxx → slug
        'title': item['title'],
        'content': report.get('content', item.get('description', '')),
        'audience': classify_audience(item),  # 根據 tags/phase 自動分類
        'phase': item.get('phase'),
        'status': 'published',
        'published_at': item.get('published_at'),
        'proposer': item.get('proposer'),
        'details': item.get('details'),
    }).execute()

    # Tags → article_tags join table
    for tag in item.get('tags', []):
        tag_id = get_or_create_tag(tag)
        supabase.table('article_tags').upsert({...}).execute()
```

### Thinking Journal（~90 entries）
```python
thinking = json.loads(open('storage/memory/thinking_journal.json').read())
for entry in thinking:
    supabase.table('memory_entries').upsert({
        'id': entry.get('id', generate_id()),
        'type': 'thinking',
        'content': entry,   # 整個 entry 存為 JSONB
    }).execute()
```

### Open Questions（~11 entries）
```python
questions = json.loads(open('storage/memory/open_questions.json').read())
for q in questions:
    supabase.table('questions').upsert({
        'id': q.get('id', generate_id()),
        'source': 'internal',
        'question': q['question'],
        'status': q.get('status', 'open'),
        'priority': q.get('priority', 'medium'),
        'proposer': q.get('proposer'),
        'answer': q.get('answer'),
        'score': q.get('score'),
    }).execute()

    # feed_articles → question_articles join table
    for aid in q.get('feed_articles', []):
        supabase.table('question_articles').upsert({...}).execute()
```

### Knowledge（~670 entries）
```python
knowledge = json.loads(open('storage/memory/knowledge.json').read())
for k in knowledge:
    supabase.table('memory_entries').upsert({
        'id': k.get('item_id', generate_id()),
        'type': 'knowledge',
        'content': k,
    }).execute()
```

### 其他
- `experiments.json` (~104 entries) → `memory_entries` type='experiment'
- `research_log.json` (~130 entries) → `memory_entries` type='log'
- `risk_forecast.json` → `risk_forecasts` 單筆 upsert
- `paper_trading.json` → `paper_trades` 按策略+日期 insert
- `mock_user_questions.json` → `questions` source='user'（或刪除 mock data）

### 遷移驗證
```python
# 匯入後驗證
assert supabase.table('articles').select('id', count='exact').execute().count == len(feed)
assert supabase.table('questions').select('id', count='exact').execute().count == len(questions)
assert supabase.table('memory_entries').select('id', count='exact').execute().count == total_memory
```

### 遷移順序
1. 先匯入 articles（最重要，前端立即可見）
2. 再匯入 questions（Q&A 頁面需要）
3. 再匯入 memory_entries（後台需要）
4. 最後 risk_forecast + paper_trading（次要）

## 遷移計畫（5 階段，4-5 週）

| Phase | 內容 | 週數 | 風險 |
|-------|------|------|------|
| 1 | Schema + RLS + Auth + 用戶提問持久化 | 1 | 低 |
| 2 | Article import + FTS + 發布流程 + 最小 admin | 1 | 中 |
| 3 | Analytics + reactions + article_stats | 0.5 | 中 |
| 4 | Memory 遷移 + risk forecast + paper trading | 1 | 中高 |
| 5 | Admin Dashboard + feature gating + 清理 + 測試 | 1-1.5 | 中 |
| **Total** | | **4-5 週** | |

---

## 成本

| 項目 | 免費 tier | 備註 |
|------|----------|------|
| Supabase DB | 500MB | 資料 < 50MB |
| Supabase Auth | 50K MAU | 綽餘 |
| Supabase Storage | 1GB | PDF + 實驗檔 |
| Zeabur v2 | 同現有方案 | |
| **月費** | **$0** | 免費 tier 足夠 |

注意：Supabase free tier 1 週無活動會 pause → 需 heartbeat cron。
Analytics 寫入量大時可能超出免費限制 → 設 90 天 retention + 聚合後刪原始記錄。

---

## 待驗證風險（Phase 1 執行時確認）

| # | 風險 | 驗證方式 | 備案 |
|---|------|----------|------|
| R1 | `to_tsvector('chinese', ...)` — Supabase 可能沒有 chinese config | 跑 schema 時立刻知道 | 改用 `simple` + pgroonga 擴充，或 `english`（中文靠 LIKE/trigram） |
| R2 | `UNIQUE(article_id, session_id, (created_at::date))` — expression UNIQUE 不一定支援 | 跑 schema 時立刻知道 | 加 computed column `impression_date DATE GENERATED ALWAYS AS (created_at::date) STORED` 再建 UNIQUE |
| R3 | Supabase free tier 的 `pg_cron` 可用性 | Dashboard 確認 | 改用外部 cron（session cron / GitHub Actions）觸發排程發文 |
| R4 | Edge Function free tier 500K/month 限制 | 確認用量 | 排程發文改為 daily_update.py 直接 UPDATE（不用 Edge Function） |
| R5 | `classify_audience()` 分類邏輯未定義 | Phase 2 遷移前定義 | 先全部標 'research'，後續手動/批次修正 |
| R6 | Supabase pause（1 週無活動）| daily_update 每天寫入即可 | 加 heartbeat cron 到 session cron |
| R7 | API rate limiting 具體實作 | Phase 3 analytics 時定義 | Next.js middleware + IP-based（10 req/min/IP） |
