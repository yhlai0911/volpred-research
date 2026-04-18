-- 2026-04-18 Contentlayer cutover: declarative record of the RLS
-- policies that already exist on `articles`, so they live in the repo
-- (not just in the production DB) and cannot be dropped by a future
-- migration without an intentional change.
--
-- Write access to articles is restricted to service_role only. Anon
-- and authenticated users are strictly read-only (public reads only
-- see status='published'; admins see all statuses). Application code
-- MUST go through feed.json + feed_sync (service_role) to write.
-- Frontend / admin CMS / direct PATCH against articles is physically
-- impossible without the service role key.

ALTER TABLE articles ENABLE ROW LEVEL SECURITY;

-- Drop-then-create lets this migration be replayed safely.
DROP POLICY IF EXISTS articles_public_read ON articles;
DROP POLICY IF EXISTS articles_admin_read ON articles;
DROP POLICY IF EXISTS articles_service ON articles;

CREATE POLICY articles_public_read ON articles
  FOR SELECT
  USING (status = 'published');

CREATE POLICY articles_admin_read ON articles
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM profiles
      WHERE profiles.id = auth.uid()
        AND profiles.role = 'admin'
    )
  );

CREATE POLICY articles_service ON articles
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
