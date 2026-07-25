-- Promote the already durable, scope-bound publisher delete approval into the
-- generic WorkItem state machine before creating a destructive EffectRequest.
--
-- The original wrapper submitted a destructive WorkItem as auto/pending. The
-- coordinator correctly rejects that state: destructive work must start as
-- required/awaiting_approval and move to approved/pending through approve_work.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    p_owner_generation bigint,
    p_idempotency_key text,
    p_payload_text text,
    p_actor_ref text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  existing volpred_ops.owned_notification_requests;
  terminal_attempt volpred_ops.owned_notification_attempts;
  terminal_receipt jsonb;
  work volpred_ops.work_item_reads;
  effect volpred_ops.effect_request_reads;
  payload_view volpred_ops.effect_payload_reads;
  p_payload jsonb;
  scope jsonb;
  candidates jsonb;
  authorization_payload jsonb;
  approval_readback jsonb;
  scope_sha256 text;
  article_count integer;
  payload_bytes bytea;
  payload_sha256 text;
  payload_ref text;
  work_id text;
  effect_id text;
  target_ref text;
  request_identity jsonb;
  request_sha256 text;
  event_at timestamptz;
BEGIN
  IF p_payload_text IS NULL OR btrim(p_payload_text) = '' THEN
    RAISE EXCEPTION
      'owned publisher delete scope payload text is required';
  END IF;
  p_payload := p_payload_text::jsonb;
  scope := p_payload -> 'scope';
  candidates := scope -> 'candidates';
  authorization_payload := p_payload -> 'authorization';
  scope_sha256 := p_payload ->> 'scope_sha256';
  IF p_owner_generation IS NULL
      OR p_owner_generation <= 0
      OR p_idempotency_key IS NULL
      OR btrim(p_idempotency_key) = ''
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = ''
      OR jsonb_typeof(p_payload) <> 'object'
      OR (
        SELECT count(*)
        FROM pg_catalog.jsonb_object_keys(p_payload)
      ) <> 4
      OR NOT p_payload ?& ARRAY[
        'schema_version', 'scope_sha256', 'scope', 'authorization'
      ]
      OR p_payload ->> 'schema_version'
        <> 'publisher-article-delete.v1'
      OR scope_sha256 !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(scope) <> 'object'
      OR (
        SELECT count(*)
        FROM pg_catalog.jsonb_object_keys(scope)
      ) <> 6
      OR NOT scope ?& ARRAY[
        'schema_version', 'canonical_feed_sha256',
        'canonical_article_count', 'guards', 'candidates', 'recovery'
      ]
      OR scope ->> 'schema_version'
        <> 'publisher-article-delete-scope.v1'
      OR scope ->> 'canonical_feed_sha256'
        !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(scope -> 'canonical_article_count') <> 'number'
      OR (scope ->> 'canonical_article_count')::integer <= 0
      OR jsonb_typeof(scope -> 'guards') <> 'object'
      OR jsonb_typeof(scope -> 'recovery') <> 'object'
      OR scope -> 'recovery' ->> 'sha256' !~ '^[0-9a-f]{64}$'
      OR jsonb_typeof(candidates) <> 'array'
      OR pg_catalog.jsonb_array_length(candidates) = 0
      OR EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements(candidates) AS item(candidate)
        WHERE jsonb_typeof(item.candidate) <> 'object'
          OR item.candidate -> 'article' ->> 'id' IS NULL
          OR item.candidate -> 'article' ->> 'id'
            !~ '^[A-Za-z0-9][A-Za-z0-9_-]*$'
          OR item.candidate -> 'article' ->> 'slug' IS NULL
          OR jsonb_typeof(item.candidate -> 'dependents') <> 'object'
      )
      OR (
        SELECT count(*) <> count(
          DISTINCT item.candidate -> 'article' ->> 'id'
        )
        FROM pg_catalog.jsonb_array_elements(candidates) AS item(candidate)
      )
      OR jsonb_typeof(authorization_payload) <> 'object'
      OR (
        SELECT count(*)
        FROM pg_catalog.jsonb_object_keys(authorization_payload)
      ) <> 4
      OR NOT authorization_payload ?& ARRAY[
        'approval_ref', 'approver_ref', 'approved_at', 'scope_sha256'
      ]
      OR authorization_payload ->> 'approval_ref' IS NULL
      OR btrim(authorization_payload ->> 'approval_ref') = ''
      OR authorization_payload ->> 'approver_ref' IS NULL
      OR btrim(authorization_payload ->> 'approver_ref') = ''
      OR authorization_payload ->> 'approved_at' IS NULL
      OR authorization_payload ->> 'scope_sha256'
        IS DISTINCT FROM scope_sha256
      OR p_payload_text <> convert_from(
        convert_to(p_payload_text, 'UTF8'),
        'UTF8'
      ) THEN
    RAISE EXCEPTION
      'owned publisher delete scope request fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'operations core does not own publisher delete scope generation %',
      p_owner_generation;
  END IF;
  request_identity := jsonb_build_object(
    'schema_version', 'owned-publisher-delete-request.v1',
    'effect_family', ownership.effect_family,
    'owner_generation', ownership.generation,
    'idempotency_key', btrim(p_idempotency_key),
    'payload', p_payload,
    'actor_ref', btrim(p_actor_ref)
  );
  request_sha256 := encode(
    sha256(convert_to(request_identity::text, 'UTF8')),
    'hex'
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'owned-publisher-delete:' || btrim(p_idempotency_key),
      0
    )
  );
  SELECT * INTO existing
  FROM volpred_ops.owned_notification_requests
  WHERE idempotency_key = btrim(p_idempotency_key);
  IF existing.idempotency_key IS NOT NULL THEN
    IF existing.request_sha256 <> request_sha256
        OR existing.effect_family <> ownership.effect_family
        OR existing.owner_generation <> ownership.generation THEN
      RAISE EXCEPTION
        'owned publisher delete scope idempotency key conflicts '
        'with original request';
    END IF;
    SELECT * INTO terminal_attempt
    FROM volpred_ops.owned_notification_attempts AS attempt
    WHERE attempt.effect_id = existing.effect_id
      AND attempt.status IN ('delivered', 'dead_lettered')
    ORDER BY attempt.attempt_count DESC
    LIMIT 1;
    terminal_receipt := NULL;
    IF terminal_attempt.effect_id IS NOT NULL THEN
      terminal_receipt := jsonb_build_object(
        'schema_version', 'owned-publisher-delete-receipt.v1',
        'owner_generation', terminal_attempt.owner_generation,
        'work_id', terminal_attempt.work_id,
        'work_status', terminal_attempt.work_status,
        'effect_id', terminal_attempt.effect_id,
        'effect_status', terminal_attempt.effect_status,
        'attempt_count', terminal_attempt.attempt_count,
        'disposition', terminal_attempt.disposition,
        'evidence_ref', terminal_attempt.evidence_ref,
        'evidence_sha256', terminal_attempt.evidence_sha256,
        'primary_authority_ref', terminal_attempt.primary_authority_ref,
        'recorded_at', terminal_attempt.finished_at
      );
    END IF;
    RETURN jsonb_build_object(
      'schema_version', 'owned-publisher-delete-request.v1',
      'owner_generation', existing.owner_generation,
      'work_id', existing.work_id,
      'effect_id', existing.effect_id,
      'request_sha256', existing.request_sha256,
      'receipt', terminal_receipt
    );
  END IF;

  approval_readback :=
    public.volpred_read_publisher_article_delete_approval(
      authorization_payload ->> 'approval_ref'
    );
  IF approval_readback -> 'active' IS DISTINCT FROM 'true'::jsonb
      OR approval_readback -> 'authorization'
        IS DISTINCT FROM authorization_payload
      OR approval_readback ->> 'evidence_ref' IS NULL
      OR btrim(approval_readback ->> 'evidence_ref') = '' THEN
    RAISE EXCEPTION
      'publisher delete work approval is not active for the exact scope';
  END IF;

  article_count := pg_catalog.jsonb_array_length(candidates);
  work_id :=
    'work_owned_delete_' || substr(request_sha256, 1, 32);
  effect_id :=
    'effect_owned_delete_' || substr(request_sha256, 1, 32);
  payload_ref := 'effect-payload:' || effect_id || ':batch';
  target_ref := 'supabase:articles';
  payload_bytes := convert_to(p_payload_text, 'UTF8');
  payload_sha256 := encode(sha256(payload_bytes), 'hex');
  event_at := clock_timestamp();

  SELECT * INTO STRICT payload_view
  FROM volpred_ops.put_effect_payload(
    payload_ref,
    payload_bytes,
    payload_sha256,
    btrim(p_actor_ref)
  );
  SELECT * INTO STRICT work
  FROM volpred_ops.submit_work(
    work_id,
    'owned-publisher-delete-work:' || btrim(p_idempotency_key),
    'publisher.delete_scope',
    'publisher.article.delete',
    'Delete ' || article_count::text || ' publisher articles',
    2,
    ARRAY['supabase-article-delete-effect'],
    ARRAY['supabase-article-delete-readback'],
    'destructive',
    'required',
    payload_ref,
    NULL,
    NULL,
    btrim(p_actor_ref),
    'awaiting_approval',
    1,
    event_at,
    event_at
  );
  SELECT * INTO STRICT work
  FROM volpred_ops.approve_work(
    work.id,
    work.version,
    authorization_payload ->> 'approver_ref',
    approval_readback ->> 'evidence_ref'
  );
  SELECT * INTO STRICT effect
  FROM volpred_ops.request_effect(
    effect_id,
    'owned-publisher-delete-effect:' || btrim(p_idempotency_key),
    work.id,
    work.version,
    ownership.effect_family,
    target_ref,
    payload_ref,
    payload_sha256,
    'destructive',
    'publisher.article.supabase.delete.readback',
    target_ref,
    btrim(p_actor_ref),
    request_sha256
  );
  INSERT INTO volpred_ops.owned_notification_requests (
    idempotency_key,
    effect_family,
    owner_generation,
    work_id,
    effect_id,
    request_sha256,
    actor_ref,
    created_at
  )
  VALUES (
    btrim(p_idempotency_key),
    ownership.effect_family,
    ownership.generation,
    work.id,
    effect.id,
    request_sha256,
    btrim(p_actor_ref),
    event_at
  );
  RETURN jsonb_build_object(
    'schema_version', 'owned-publisher-delete-request.v1',
    'owner_generation', ownership.generation,
    'work_id', work.id,
    'effect_id', effect.id,
    'request_sha256', request_sha256,
    'receipt', NULL
  );
END;
$$;

ALTER FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  )
OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  )
TO service_role;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
