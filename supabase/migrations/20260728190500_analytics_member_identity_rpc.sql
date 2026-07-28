-- Service-role identity merge/delete bridge for authenticated continuity.
--
-- The first-party analytics schema remains private.  This migration exposes
-- two narrow, receipt-backed SECURITY DEFINER operations so the member
-- continuity API can merge an anonymous browser identity after login and
-- delete every linked raw event without receiving table access.

GRANT volpred_analytics_worker TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO volpred_analytics_worker;
GRANT CREATE ON SCHEMA public TO volpred_analytics_worker;

DO $reacquire_identity_functions$
BEGIN
  IF pg_catalog.to_regprocedure(
    'public.merge_volpred_analytics_identity('
    'text,text,text,timestamp with time zone,bytea,bytea)'
  ) IS NOT NULL THEN
    EXECUTE pg_catalog.format(
      'ALTER FUNCTION public.merge_volpred_analytics_identity('
      'text,text,text,timestamptz,bytea,bytea) OWNER TO %I',
      CURRENT_USER
    );
  END IF;
  IF pg_catalog.to_regprocedure(
    'public.delete_volpred_analytics_identity('
    'text,text,timestamp with time zone,bytea)'
  ) IS NOT NULL THEN
    EXECUTE pg_catalog.format(
      'ALTER FUNCTION public.delete_volpred_analytics_identity('
      'text,text,timestamptz,bytea) OWNER TO %I',
      CURRENT_USER
    );
  END IF;
END;
$reacquire_identity_functions$;

ALTER TABLE volpred_analytics.identity_links
  ADD COLUMN IF NOT EXISTS anonymous_subject_digest bytea,
  ADD COLUMN IF NOT EXISTS user_subject_digest bytea;

ALTER TABLE volpred_analytics.identity_merge_receipts
  ADD COLUMN IF NOT EXISTS anonymous_subject_digest bytea,
  ADD COLUMN IF NOT EXISTS user_subject_digest bytea;

DO $digest_constraints$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_constraint
    WHERE conname = 'analytics_identity_links_anonymous_digest_length'
      AND conrelid = 'volpred_analytics.identity_links'::regclass
  ) THEN
    ALTER TABLE volpred_analytics.identity_links
      ADD CONSTRAINT analytics_identity_links_anonymous_digest_length
      CHECK (
        anonymous_subject_digest IS NULL
        OR pg_catalog.octet_length(anonymous_subject_digest) = 32
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_constraint
    WHERE conname = 'analytics_identity_links_user_digest_length'
      AND conrelid = 'volpred_analytics.identity_links'::regclass
  ) THEN
    ALTER TABLE volpred_analytics.identity_links
      ADD CONSTRAINT analytics_identity_links_user_digest_length
      CHECK (
        user_subject_digest IS NULL
        OR pg_catalog.octet_length(user_subject_digest) = 32
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_constraint
    WHERE conname = 'analytics_identity_receipts_anonymous_digest_length'
      AND conrelid =
        'volpred_analytics.identity_merge_receipts'::regclass
  ) THEN
    ALTER TABLE volpred_analytics.identity_merge_receipts
      ADD CONSTRAINT analytics_identity_receipts_anonymous_digest_length
      CHECK (
        anonymous_subject_digest IS NULL
        OR pg_catalog.octet_length(anonymous_subject_digest) = 32
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_constraint
    WHERE conname = 'analytics_identity_receipts_user_digest_length'
      AND conrelid =
        'volpred_analytics.identity_merge_receipts'::regclass
  ) THEN
    ALTER TABLE volpred_analytics.identity_merge_receipts
      ADD CONSTRAINT analytics_identity_receipts_user_digest_length
      CHECK (
        user_subject_digest IS NULL
        OR pg_catalog.octet_length(user_subject_digest) = 32
      );
  END IF;
END;
$digest_constraints$;

CREATE OR REPLACE FUNCTION public.merge_volpred_analytics_identity(
  p_idempotency_key text,
  p_anonymous_id text,
  p_user_id text,
  p_merged_at timestamptz,
  p_anonymous_subject_digest bytea,
  p_user_subject_digest bytea
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $merge_identity$
DECLARE
  existing_receipt record;
  existing_link record;
  merged_events bigint;
BEGIN
  IF p_idempotency_key IS NULL
     OR p_idempotency_key
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'analytics identity idempotency_key is invalid';
  END IF;
  IF p_anonymous_id IS NULL
     OR p_anonymous_id
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'analytics anonymous identity is invalid';
  END IF;
  IF p_user_id IS NULL
     OR p_user_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'analytics user identity is invalid';
  END IF;
  IF p_merged_at IS NULL
     OR p_anonymous_subject_digest IS NULL
     OR p_user_subject_digest IS NULL
     OR pg_catalog.octet_length(p_anonymous_subject_digest) <> 32
     OR pg_catalog.octet_length(p_user_subject_digest) <> 32 THEN
    RAISE EXCEPTION 'analytics identity evidence is invalid';
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-analytics:identity-request:' || p_idempotency_key,
      0
    )
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-analytics:subject:user:' || p_user_id,
      0
    )
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-analytics:subject:anonymous:' || p_anonymous_id,
      0
    )
  );

  SELECT
    receipt.anonymous_id,
    receipt.user_id,
    receipt.merged_events,
    receipt.anonymous_subject_digest,
    receipt.user_subject_digest
  INTO existing_receipt
  FROM volpred_analytics.identity_merge_receipts AS receipt
  WHERE receipt.idempotency_key = p_idempotency_key;
  IF FOUND THEN
    IF existing_receipt.anonymous_id <> p_anonymous_id
       OR existing_receipt.user_id <> p_user_id
       OR existing_receipt.anonymous_subject_digest
          IS DISTINCT FROM p_anonymous_subject_digest
       OR existing_receipt.user_subject_digest
          IS DISTINCT FROM p_user_subject_digest THEN
      RAISE EXCEPTION 'analytics identity idempotency_key was reused';
    END IF;
    RETURN pg_catalog.jsonb_build_object(
      'contract', 'analytics-identity-merge-receipt.v1',
      'idempotency_key', p_idempotency_key,
      'anonymous_id', p_anonymous_id,
      'user_id', p_user_id,
      'merged_events', existing_receipt.merged_events,
      'duplicate', true
    );
  END IF;

  IF EXISTS (
    SELECT 1
    FROM volpred_analytics.privacy_tombstones AS tombstone
    WHERE tombstone.subject_digest IN (
      p_anonymous_subject_digest,
      p_user_subject_digest
    )
  ) THEN
    RAISE EXCEPTION 'cannot merge a deleted analytics identity';
  END IF;

  SELECT
    link.user_id,
    link.anonymous_subject_digest,
    link.user_subject_digest
  INTO existing_link
  FROM volpred_analytics.identity_links AS link
  WHERE link.anonymous_id = p_anonymous_id;
  IF FOUND AND (
    existing_link.user_id <> p_user_id
    OR (
      existing_link.anonymous_subject_digest IS NOT NULL
      AND existing_link.anonymous_subject_digest
          <> p_anonymous_subject_digest
    )
    OR (
      existing_link.user_subject_digest IS NOT NULL
      AND existing_link.user_subject_digest <> p_user_subject_digest
    )
  ) THEN
    RAISE EXCEPTION 'anonymous identity belongs to another subject';
  END IF;

  UPDATE volpred_analytics.events AS event
  SET user_id = p_user_id
  WHERE event.anonymous_id = p_anonymous_id
    AND event.user_id IS DISTINCT FROM p_user_id;
  GET DIAGNOSTICS merged_events = ROW_COUNT;

  INSERT INTO volpred_analytics.identity_links (
    anonymous_id,
    user_id,
    merged_at,
    anonymous_subject_digest,
    user_subject_digest
  )
  VALUES (
    p_anonymous_id,
    p_user_id,
    p_merged_at,
    p_anonymous_subject_digest,
    p_user_subject_digest
  )
  ON CONFLICT (anonymous_id) DO UPDATE SET
    merged_at = EXCLUDED.merged_at,
    anonymous_subject_digest = EXCLUDED.anonymous_subject_digest,
    user_subject_digest = EXCLUDED.user_subject_digest
  WHERE volpred_analytics.identity_links.user_id = EXCLUDED.user_id;

  INSERT INTO volpred_analytics.identity_merge_receipts (
    idempotency_key,
    anonymous_id,
    user_id,
    merged_at,
    merged_events,
    anonymous_subject_digest,
    user_subject_digest
  )
  VALUES (
    p_idempotency_key,
    p_anonymous_id,
    p_user_id,
    p_merged_at,
    merged_events,
    p_anonymous_subject_digest,
    p_user_subject_digest
  );

  RETURN pg_catalog.jsonb_build_object(
    'contract', 'analytics-identity-merge-receipt.v1',
    'idempotency_key', p_idempotency_key,
    'anonymous_id', p_anonymous_id,
    'user_id', p_user_id,
    'merged_events', merged_events,
    'duplicate', false
  );
END;
$merge_identity$;

CREATE OR REPLACE FUNCTION public.delete_volpred_analytics_identity(
  p_user_id text,
  p_idempotency_key text,
  p_acted_at timestamptz,
  p_user_subject_digest bytea
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $delete_identity$
DECLARE
  existing_receipt record;
  anonymous_ids text[];
  anonymous_digests bytea[];
  observed_user_digests bytea[];
  removed_events bigint;
  removed_links bigint;
BEGIN
  IF p_user_id IS NULL
     OR p_user_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'analytics user identity is invalid';
  END IF;
  IF p_idempotency_key IS NULL
     OR p_idempotency_key
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'analytics privacy idempotency_key is invalid';
  END IF;
  IF p_acted_at IS NULL
     OR p_user_subject_digest IS NULL
     OR pg_catalog.octet_length(p_user_subject_digest) <> 32 THEN
    RAISE EXCEPTION 'analytics privacy evidence is invalid';
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-analytics:privacy-request:' || p_idempotency_key,
      0
    )
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-analytics:subject:user:' || p_user_id,
      0
    )
  );

  SELECT
    receipt.action,
    receipt.subject_digest,
    receipt.removed_raw_events,
    receipt.removed_identity_links
  INTO existing_receipt
  FROM volpred_analytics.privacy_action_receipts AS receipt
  WHERE receipt.idempotency_key = p_idempotency_key;
  IF FOUND THEN
    IF existing_receipt.action <> 'delete'
       OR existing_receipt.subject_digest <> p_user_subject_digest THEN
      RAISE EXCEPTION 'analytics privacy idempotency_key was reused';
    END IF;
    RETURN pg_catalog.jsonb_build_object(
      'contract', 'analytics-privacy-delete-receipt.v1',
      'idempotency_key', p_idempotency_key,
      'status', 'deleted',
      'duplicate', true,
      'removed_raw_events', existing_receipt.removed_raw_events,
      'removed_identity_links', existing_receipt.removed_identity_links
    );
  END IF;

  SELECT
    COALESCE(
      pg_catalog.array_agg(link.anonymous_id),
      ARRAY[]::text[]
    ),
    COALESCE(
      pg_catalog.array_agg(link.anonymous_subject_digest)
        FILTER (WHERE link.anonymous_subject_digest IS NOT NULL),
      ARRAY[]::bytea[]
    ),
    COALESCE(
      pg_catalog.array_agg(DISTINCT link.user_subject_digest)
        FILTER (WHERE link.user_subject_digest IS NOT NULL),
      ARRAY[]::bytea[]
    )
  INTO anonymous_ids, anonymous_digests, observed_user_digests
  FROM volpred_analytics.identity_links AS link
  WHERE link.user_id = p_user_id;

  IF EXISTS (
    SELECT 1
    FROM pg_catalog.unnest(observed_user_digests) AS digest(value)
    WHERE digest.value <> p_user_subject_digest
  ) THEN
    RAISE EXCEPTION 'analytics user digest does not match identity links';
  END IF;

  INSERT INTO volpred_analytics.privacy_tombstones (
    subject_digest,
    deleted_at
  )
  SELECT digest.value, p_acted_at
  FROM pg_catalog.unnest(
    pg_catalog.array_append(
      anonymous_digests,
      p_user_subject_digest
    )
  ) AS digest(value)
  ON CONFLICT (subject_digest) DO UPDATE SET
    deleted_at = CASE
      WHEN volpred_analytics.privacy_tombstones.deleted_at
           >= EXCLUDED.deleted_at
        THEN volpred_analytics.privacy_tombstones.deleted_at
      ELSE EXCLUDED.deleted_at
    END;

  DELETE FROM volpred_analytics.events AS event
  WHERE event.user_id = p_user_id
     OR event.anonymous_id = ANY(anonymous_ids);
  GET DIAGNOSTICS removed_events = ROW_COUNT;

  DELETE FROM volpred_analytics.privacy_preferences AS preference
  WHERE (
    preference.subject_kind = 'user'
    AND preference.subject_id = p_user_id
  ) OR (
    preference.subject_kind = 'anonymous'
    AND preference.subject_id = ANY(anonymous_ids)
  );

  DELETE FROM volpred_analytics.identity_links AS link
  WHERE link.user_id = p_user_id
     OR link.anonymous_id = ANY(anonymous_ids);
  GET DIAGNOSTICS removed_links = ROW_COUNT;

  DELETE FROM volpred_analytics.identity_merge_receipts AS receipt
  WHERE receipt.user_id = p_user_id
     OR receipt.anonymous_id = ANY(anonymous_ids);

  DELETE FROM volpred_analytics.privacy_action_receipts AS receipt
  WHERE receipt.subject_digest = p_user_subject_digest
     OR receipt.subject_digest = ANY(anonymous_digests);

  INSERT INTO volpred_analytics.privacy_action_receipts (
    idempotency_key,
    action,
    subject_digest,
    acted_at,
    removed_raw_events,
    removed_identity_links
  )
  VALUES (
    p_idempotency_key,
    'delete',
    p_user_subject_digest,
    p_acted_at,
    removed_events,
    removed_links
  );

  RETURN pg_catalog.jsonb_build_object(
    'contract', 'analytics-privacy-delete-receipt.v1',
    'idempotency_key', p_idempotency_key,
    'status', 'deleted',
    'duplicate', false,
    'removed_raw_events', removed_events,
    'removed_identity_links', removed_links
  );
END;
$delete_identity$;

GRANT UPDATE (
  merged_at,
  anonymous_subject_digest,
  user_subject_digest
) ON volpred_analytics.identity_links
  TO volpred_analytics_worker;
DROP POLICY IF EXISTS analytics_worker_update
  ON volpred_analytics.identity_links;
CREATE POLICY analytics_worker_update
  ON volpred_analytics.identity_links
  FOR UPDATE TO volpred_analytics_worker
  USING (true) WITH CHECK (true);

REVOKE ALL ON FUNCTION public.merge_volpred_analytics_identity(
  text, text, text, timestamptz, bytea, bytea
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.delete_volpred_analytics_identity(
  text, text, timestamptz, bytea
) FROM PUBLIC;

DO $grant_service_role$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role'
  ) THEN
    RAISE EXCEPTION 'service_role is required for analytics identity RPC';
  END IF;
  REVOKE ALL ON FUNCTION public.merge_volpred_analytics_identity(
    text, text, text, timestamptz, bytea, bytea
  ) FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.delete_volpred_analytics_identity(
    text, text, timestamptz, bytea
  ) FROM anon, authenticated;
  GRANT EXECUTE ON FUNCTION public.merge_volpred_analytics_identity(
    text, text, text, timestamptz, bytea, bytea
  ) TO service_role;
  GRANT EXECUTE ON FUNCTION public.delete_volpred_analytics_identity(
    text, text, timestamptz, bytea
  ) TO service_role;
END;
$grant_service_role$;

ALTER FUNCTION public.merge_volpred_analytics_identity(
  text, text, text, timestamptz, bytea, bytea
) OWNER TO volpred_analytics_worker;
ALTER FUNCTION public.delete_volpred_analytics_identity(
  text, text, timestamptz, bytea
) OWNER TO volpred_analytics_worker;

REVOKE CREATE ON SCHEMA public FROM volpred_analytics_worker;
REVOKE volpred_analytics_worker FROM CURRENT_USER;
