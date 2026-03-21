-- ═══════════════════════════════════════════════════════════
-- VolPred v2 — Phase 1 Schema Migration
-- 修正項目：
--   R1: 中文 FTS 改用 PGroonga（需先啟用擴充）
--   R2: Expression UNIQUE 改用 CREATE UNIQUE INDEX
--   整合 Codex + Gemini 審查意見（v4）
-- ═══════════════════════════════════════════════════════════

-- Step 0: 啟用需要的擴充
CREATE EXTENSION IF NOT EXISTS pgroonga;   -- 中文全文搜尋
CREATE EXTENSION IF NOT EXISTS pg_cron;    -- 排程（如果 free tier 不支援會報錯，不影響其他）

-- ═══════════════════════════════════════════════════════════
-- 會員系統
-- ═══════════════════════════════════════════════════════════

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

-- 配額管理（按月重置）
CREATE TABLE quota_usage (
  id SERIAL PRIMARY KEY,
  user_id UUID REFERENCES profiles(id),
  period_start DATE NOT NULL,        -- 每月 1 號
  questions_used INT DEFAULT 0,
  questions_limit INT DEFAULT 3,     -- free=3, premium=unlimited(-1)
  UNIQUE(user_id, period_start)
);

-- ═══════════════════════════════════════════════════════════
-- 文章系統（正規化）
-- ═══════════════════════════════════════════════════════════

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
  scheduled_at TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- PGroonga 中文全文搜尋索引（取代 tsvector）
CREATE INDEX idx_articles_fts ON articles
  USING pgroonga (title, content);

-- updated_at 自動更新
CREATE OR REPLACE FUNCTION update_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER articles_updated_at
  BEFORE UPDATE ON articles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

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

-- ═══════════════════════════════════════════════════════════
-- 問題系統（合併為一表）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,               -- internal / user
  user_id UUID REFERENCES profiles(id), -- NULL for internal
  question TEXT NOT NULL,
  status TEXT DEFAULT 'open',         -- open / partially_answered / answered / evaluating / ranked / researching
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

-- ═══════════════════════════════════════════════════════════
-- 論文系統
-- ═══════════════════════════════════════════════════════════

CREATE TABLE papers (
  id TEXT PRIMARY KEY,                -- leverage-direction, taiwan-vt
  title TEXT NOT NULL,
  authors TEXT NOT NULL,
  abstract TEXT,
  status TEXT DEFAULT 'working',      -- working / submitted / accepted / published
  target_journal TEXT,
  pages INT,
  pdf_url TEXT,
  score INT,
  tags TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER papers_updated_at
  BEFORE UPDATE ON papers
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ═══════════════════════════════════════════════════════════
-- Analytics（防 spam）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE article_impressions (
  id BIGSERIAL PRIMARY KEY,
  article_id UUID REFERENCES articles(id),
  user_id UUID REFERENCES profiles(id),  -- NULL = anonymous
  session_id TEXT,
  read_time_sec INT,
  impression_date DATE,                  -- trigger 自動設值（不用 GENERATED，因為 timestamptz→date 非 immutable）
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- impression_date 自動填入 trigger
CREATE OR REPLACE FUNCTION set_impression_date() RETURNS TRIGGER AS $$
BEGIN
  NEW.impression_date := (NEW.created_at AT TIME ZONE 'Asia/Taipei')::date;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER impressions_set_date
  BEFORE INSERT ON article_impressions
  FOR EACH ROW EXECUTE FUNCTION set_impression_date();

-- 防重複：同一 session 同一天只計一次
CREATE UNIQUE INDEX idx_impressions_dedup
  ON article_impressions (article_id, session_id, impression_date);

CREATE TABLE article_reactions (
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  reaction TEXT NOT NULL,              -- like / bookmark / share
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (article_id, user_id, reaction)
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

-- ═══════════════════════════════════════════════════════════
-- 策略信號面板
-- ═══════════════════════════════════════════════════════════

CREATE TABLE strategy_signals (
  id SERIAL PRIMARY KEY,
  strategy_name TEXT NOT NULL,
  display_order INT DEFAULT 0,
  weights JSONB NOT NULL,
  vix_level NUMERIC,
  sigma_ann NUMERIC,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  is_active BOOLEAN DEFAULT true
);

-- ═══════════════════════════════════════════════════════════
-- 研究記憶
-- ═══════════════════════════════════════════════════════════

CREATE TABLE memory_entries (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,                  -- thinking / knowledge / log / experiment
  content JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════
-- 風險預報 + Paper Trading
-- ═══════════════════════════════════════════════════════════

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

-- ═══════════════════════════════════════════════════════════
-- 留言系統（預留，暫不啟用）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE comments (
  id SERIAL PRIMARY KEY,
  article_id UUID REFERENCES articles(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  parent_id INT REFERENCES comments(id),
  content TEXT NOT NULL,
  status TEXT DEFAULT 'visible',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════
-- Feature Gating
-- ═══════════════════════════════════════════════════════════

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

-- ═══════════════════════════════════════════════════════════
-- Audit Log
-- ═══════════════════════════════════════════════════════════

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
