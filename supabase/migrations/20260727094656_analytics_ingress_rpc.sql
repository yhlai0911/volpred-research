-- Server-only ingress for the private first-party analytics boundary.
--
-- The browser calls the Next.js API route. That route authenticates any
-- supplied bearer token, computes keyed privacy digests, and invokes this RPC
-- with the service-role credential. Browser/Data API roles never receive
-- schema, table, sequence, or function access.

CREATE OR REPLACE FUNCTION public.record_volpred_analytics_event(
  p_idempotency_key text,
  p_kind text,
  p_occurred_at timestamptz,
  p_anonymous_id text,
  p_submitted_user_id text,
  p_properties jsonb,
  p_payload_digest bytea,
  p_idempotency_digest bytea,
  p_digest_key_id text,
  p_digest_key_verifier bytea,
  p_anonymous_subject_digest bytea DEFAULT NULL,
  p_user_subject_digest bytea DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_analytics
AS $ingress$
DECLARE
  existing_event record;
  suppressed_event record;
  linked_user_id text;
  canonical_user_id text;
  inserted_id bigint;
  inserted_expiry timestamptz;
BEGIN
  IF p_idempotency_key IS NULL
     OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'analytics idempotency_key is invalid';
  END IF;
  IF p_anonymous_id IS NULL AND p_submitted_user_id IS NULL THEN
    RAISE EXCEPTION 'analytics event requires an identity';
  END IF;
  IF p_anonymous_id IS NOT NULL
     AND p_anonymous_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'analytics anonymous identity is invalid';
  END IF;
  IF p_submitted_user_id IS NOT NULL
     AND p_submitted_user_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'analytics user identity is invalid';
  END IF;
  IF octet_length(p_payload_digest) <> 32
     OR octet_length(p_idempotency_digest) <> 32
     OR p_digest_key_id IS NULL
     OR length(p_digest_key_id) > 128
     OR octet_length(p_digest_key_verifier) <> 32
     OR (
       p_anonymous_id IS NOT NULL
       AND octet_length(p_anonymous_subject_digest) <> 32
     )
     OR (
       p_submitted_user_id IS NOT NULL
       AND octet_length(p_user_subject_digest) <> 32
     ) THEN
    RAISE EXCEPTION 'analytics keyed digest is invalid';
  END IF;
  IF p_properties IS NULL OR jsonb_typeof(p_properties) <> 'object' THEN
    RAISE EXCEPTION 'analytics properties must be an object';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('volpred-analytics:event:' || p_idempotency_key, 0)
  );
  INSERT INTO volpred_analytics.digest_key_identity (
    singleton,
    key_id,
    verifier
  ) VALUES (
    true,
    p_digest_key_id,
    p_digest_key_verifier
  )
  ON CONFLICT (singleton) DO NOTHING;
  IF NOT EXISTS (
    SELECT 1
    FROM volpred_analytics.digest_key_identity
    WHERE singleton
      AND key_id = p_digest_key_id
      AND verifier = p_digest_key_verifier
  ) THEN
    RAISE EXCEPTION 'analytics digest key identity mismatch';
  END IF;

  SELECT id, payload_digest, raw_expires_at
  INTO existing_event
  FROM volpred_analytics.events
  WHERE idempotency_key = p_idempotency_key;
  IF FOUND THEN
    IF existing_event.payload_digest <> p_payload_digest THEN
      RAISE EXCEPTION 'analytics event idempotency_key was reused';
    END IF;
    RETURN jsonb_build_object(
      'accepted', true,
      'duplicate', true,
      'idempotency_key', p_idempotency_key,
      'raw_expires_at', existing_event.raw_expires_at
    );
  END IF;

  SELECT event_payload_digest, suppression_reason
  INTO suppressed_event
  FROM volpred_analytics.event_dedupe_tombstones
  WHERE idempotency_digest = p_idempotency_digest;
  IF FOUND THEN
    IF suppressed_event.event_payload_digest <> p_payload_digest THEN
      RAISE EXCEPTION 'analytics event idempotency_key was reused';
    END IF;
    RETURN jsonb_build_object(
      'accepted', false,
      'duplicate', false,
      'idempotency_key', p_idempotency_key,
      'raw_expires_at', NULL,
      'reason', suppressed_event.suppression_reason
    );
  END IF;

  IF (
    p_anonymous_subject_digest IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM volpred_analytics.privacy_tombstones
      WHERE subject_digest = p_anonymous_subject_digest
    )
  ) OR (
    p_user_subject_digest IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM volpred_analytics.privacy_tombstones
      WHERE subject_digest = p_user_subject_digest
    )
  ) THEN
    RETURN jsonb_build_object(
      'accepted', false,
      'duplicate', false,
      'idempotency_key', p_idempotency_key,
      'raw_expires_at', NULL,
      'reason', 'deleted'
    );
  END IF;

  IF p_anonymous_id IS NOT NULL THEN
    SELECT user_id
    INTO linked_user_id
    FROM volpred_analytics.identity_links
    WHERE anonymous_id = p_anonymous_id;
  END IF;
  IF linked_user_id IS NOT NULL
     AND p_submitted_user_id IS NOT NULL
     AND linked_user_id <> p_submitted_user_id THEN
    RAISE EXCEPTION 'conflicting analytics identities';
  END IF;
  canonical_user_id := COALESCE(p_submitted_user_id, linked_user_id);

  IF EXISTS (
    SELECT 1
    FROM volpred_analytics.privacy_preferences
    WHERE opted_out
      AND (
        (subject_kind = 'anonymous' AND subject_id = p_anonymous_id)
        OR (subject_kind = 'user' AND subject_id = canonical_user_id)
      )
  ) THEN
    RETURN jsonb_build_object(
      'accepted', false,
      'duplicate', false,
      'idempotency_key', p_idempotency_key,
      'raw_expires_at', NULL,
      'reason', 'opted_out'
    );
  END IF;

  -- Durable, privacy-preserving abuse bound. The identity advisory lock makes
  -- the count and insert serial for concurrent requests from the same subject.
  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      'volpred-analytics:rate:'
      || COALESCE(canonical_user_id, p_anonymous_id),
      0
    )
  );
  IF (
    SELECT count(*)
    FROM volpred_analytics.events
    WHERE ingested_at >= clock_timestamp() - interval '1 minute'
      AND (
        (canonical_user_id IS NOT NULL AND user_id = canonical_user_id)
        OR (
          canonical_user_id IS NULL
          AND anonymous_id = p_anonymous_id
        )
      )
  ) >= 120 THEN
    RAISE EXCEPTION 'analytics rate limit exceeded';
  END IF;

  INSERT INTO volpred_analytics.events (
    idempotency_key,
    kind,
    occurred_at,
    anonymous_id,
    submitted_user_id,
    user_id,
    properties,
    payload_digest,
    raw_expires_at
  ) VALUES (
    p_idempotency_key,
    p_kind,
    p_occurred_at,
    p_anonymous_id,
    p_submitted_user_id,
    canonical_user_id,
    p_properties,
    p_payload_digest,
    p_occurred_at + interval '30 days'
  )
  RETURNING id, raw_expires_at
  INTO inserted_id, inserted_expiry;

  RETURN jsonb_build_object(
    'accepted', true,
    'duplicate', false,
    'idempotency_key', p_idempotency_key,
    'raw_expires_at', inserted_expiry
  );
END;
$ingress$;

REVOKE ALL ON FUNCTION public.record_volpred_analytics_event(
  text, text, timestamptz, text, text, jsonb, bytea, bytea,
  text, bytea, bytea, bytea
) FROM PUBLIC;

DO $grant_service_role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    RAISE EXCEPTION 'service_role is required for analytics ingress';
  END IF;
  REVOKE ALL ON FUNCTION public.record_volpred_analytics_event(
    text, text, timestamptz, text, text, jsonb, bytea, bytea,
    text, bytea, bytea, bytea
  ) FROM anon, authenticated;
  GRANT EXECUTE ON FUNCTION public.record_volpred_analytics_event(
    text, text, timestamptz, text, text, jsonb, bytea, bytea,
    text, bytea, bytea, bytea
  ) TO service_role;
END;
$grant_service_role$;
