-- ═══════════════════════════════════════════════════════════
-- VolPred v2 — Phase 1 RLS (Row Level Security)
-- 所有寫入經 Next.js API (service_role)，前端只做公開讀取
-- ═══════════════════════════════════════════════════════════

-- ───────── Profiles ─────────
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- 自己讀自己
CREATE POLICY "profiles_read_own" ON profiles FOR SELECT
  USING (auth.uid() = id);

-- 自己更新自己（但不能改 role）
CREATE POLICY "profiles_update_own" ON profiles FOR UPDATE
  USING (auth.uid() = id)
  WITH CHECK (
    auth.uid() = id
    AND role = (SELECT role FROM profiles WHERE id = auth.uid())
  );

-- service_role 完整存取（用於研究系統寫入）
CREATE POLICY "profiles_service" ON profiles FOR ALL
  USING (auth.role() = 'service_role');

-- ───────── Articles ─────────
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;

-- 公開讀 published
CREATE POLICY "articles_public_read" ON articles FOR SELECT
  USING (status = 'published');

-- admin 讀全部（含 draft/scheduled）
CREATE POLICY "articles_admin_read" ON articles FOR SELECT
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));

-- service_role 完整存取
CREATE POLICY "articles_service" ON articles FOR ALL
  USING (auth.role() = 'service_role');

-- ───────── Tags / Article_tags ─────────
ALTER TABLE tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "tags_public_read" ON tags FOR SELECT USING (true);
CREATE POLICY "tags_service" ON tags FOR ALL USING (auth.role() = 'service_role');

ALTER TABLE article_tags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "article_tags_public_read" ON article_tags FOR SELECT USING (true);
CREATE POLICY "article_tags_service" ON article_tags FOR ALL USING (auth.role() = 'service_role');

-- ───────── Article Relations ─────────
ALTER TABLE article_relations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "article_relations_public_read" ON article_relations FOR SELECT USING (true);
CREATE POLICY "article_relations_service" ON article_relations FOR ALL USING (auth.role() = 'service_role');

-- ───────── Questions ─────────
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;

-- 讀：自己的 + internal + 已回答/排名的
CREATE POLICY "questions_read" ON questions FOR SELECT
  USING (
    user_id = auth.uid()
    OR source = 'internal'
    OR status IN ('ranked', 'researching', 'answered')
  );

-- 用戶提問（source 必須是 user）
CREATE POLICY "questions_user_insert" ON questions FOR INSERT
  WITH CHECK (auth.uid() = user_id AND source = 'user');

-- service_role 完整存取
CREATE POLICY "questions_service" ON questions FOR ALL
  USING (auth.role() = 'service_role');

-- ───────── Question Articles ─────────
ALTER TABLE question_articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "question_articles_public_read" ON question_articles FOR SELECT USING (true);
CREATE POLICY "question_articles_service" ON question_articles FOR ALL USING (auth.role() = 'service_role');

-- ───────── Papers ─────────
ALTER TABLE papers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "papers_public_read" ON papers FOR SELECT USING (true);
CREATE POLICY "papers_service" ON papers FOR ALL USING (auth.role() = 'service_role');

-- ───────── Impressions（只能透過 API 寫入）─────────
ALTER TABLE article_impressions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "impressions_service_insert" ON article_impressions FOR INSERT
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY "impressions_admin_read" ON article_impressions FOR SELECT
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));

-- ───────── Reactions ─────────
ALTER TABLE article_reactions ENABLE ROW LEVEL SECURITY;

-- 自己可以新增/刪除 reaction
CREATE POLICY "reactions_own_insert" ON article_reactions FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "reactions_own_delete" ON article_reactions FOR DELETE
  USING (auth.uid() = user_id);

-- 所有人可讀（顯示 like 數）
CREATE POLICY "reactions_public_read" ON article_reactions FOR SELECT USING (true);

-- ───────── Strategy Signals ─────────
ALTER TABLE strategy_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "signals_public_read" ON strategy_signals FOR SELECT USING (true);
CREATE POLICY "signals_service" ON strategy_signals FOR ALL USING (auth.role() = 'service_role');

-- ───────── Memory Entries ─────────
ALTER TABLE memory_entries ENABLE ROW LEVEL SECURITY;

-- 公開讀（thinking/knowledge 展示用）
CREATE POLICY "memory_public_read" ON memory_entries FOR SELECT USING (true);

CREATE POLICY "memory_service" ON memory_entries FOR ALL
  USING (auth.role() = 'service_role');

-- ───────── Risk Forecasts ─────────
ALTER TABLE risk_forecasts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "forecasts_public_read" ON risk_forecasts FOR SELECT USING (true);
CREATE POLICY "forecasts_service" ON risk_forecasts FOR ALL USING (auth.role() = 'service_role');

-- ───────── Paper Trades ─────────
ALTER TABLE paper_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "trades_public_read" ON paper_trades FOR SELECT USING (true);
CREATE POLICY "trades_service" ON paper_trades FOR ALL USING (auth.role() = 'service_role');

-- ───────── Feature Flags ─────────
ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY;
CREATE POLICY "flags_public_read" ON feature_flags FOR SELECT USING (true);
CREATE POLICY "flags_admin_write" ON feature_flags FOR ALL
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));

-- ───────── Comments（暫不啟用）─────────
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "comments_disabled" ON comments FOR ALL USING (false);

-- ───────── Audit Log ─────────
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "audit_admin_read" ON audit_log FOR SELECT
  USING (EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role = 'admin'));
CREATE POLICY "audit_service" ON audit_log FOR ALL
  USING (auth.role() = 'service_role');

-- ───────── Quota Usage ─────────
ALTER TABLE quota_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY "quota_read_own" ON quota_usage FOR SELECT
  USING (user_id = auth.uid());
CREATE POLICY "quota_service" ON quota_usage FOR ALL
  USING (auth.role() = 'service_role');
