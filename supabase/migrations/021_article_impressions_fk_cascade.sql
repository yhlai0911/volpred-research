-- BUG-001 root cause fix: article_impressions.article_id FK was NO ACTION.
-- Migration 001 set this FK without ON DELETE behavior, causing any
-- DELETE on articles to fail with 409 when impressions existed.
-- Python-level pre-delete in scripts/supabase_sync.py was a patch;
-- this migration fixes the schema so DB-level cascade works for ALL callers
-- (including feed_sync.py, admin CMS, direct SQL).
--
-- Applied via Supabase MCP on 2026-04-18 during Contentlayer pattern
-- rollout (Phase 1: feed.json -> Supabase one-way sync).

ALTER TABLE article_impressions
  DROP CONSTRAINT article_impressions_article_id_fkey;

ALTER TABLE article_impressions
  ADD CONSTRAINT article_impressions_article_id_fkey
  FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE;
