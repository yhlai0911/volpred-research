-- owned_notification_requests is append-only.  A plain SELECT is sufficient
-- after the owner-generation row has been locked.  PostgreSQL applies UPDATE
-- RLS policies to SELECT FOR SHARE; the immutable request table deliberately
-- has no UPDATE policy, so the prior locking read was filtered to zero rows.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  public.volpred_compare_delete_publisher_article(
    p_owner_generation bigint,
    p_effect_id text,
    p_attempt_count integer,
    p_worker_id text,
    p_primary_authority_key text,
    p_primary_authority_holder_ref text,
    p_primary_authority_epoch bigint,
    p_primary_fencing_token text,
    p_authorization jsonb,
    p_expected_candidate jsonb
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  owned_request volpred_ops.owned_notification_requests;
  owned_attempt volpred_ops.owned_notification_attempts;
  effect volpred_ops.effect_requests;
  approval volpred_ops.publisher_article_delete_approvals;
  active_lease volpred_ops.primary_authority_leases;
  effect_payload jsonb;
  target_article_id text;
  observed jsonb;
  deleted_id text;
BEGIN
  target_article_id := p_expected_candidate -> 'article' ->> 'id';
  IF p_owner_generation IS NULL
      OR p_owner_generation <= 0
      OR p_effect_id IS NULL
      OR btrim(p_effect_id) = ''
      OR p_attempt_count IS NULL
      OR p_attempt_count <= 0
      OR p_worker_id IS NULL
      OR btrim(p_worker_id) = ''
      OR p_primary_authority_key
        <> 'publisher:article.supabase.delete'
      OR p_primary_authority_holder_ref IS NULL
      OR btrim(p_primary_authority_holder_ref) = ''
      OR p_primary_authority_epoch IS NULL
      OR p_primary_authority_epoch <= 0
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = ''
      OR jsonb_typeof(p_authorization) <> 'object'
      OR jsonb_typeof(p_expected_candidate) <> 'object'
      OR target_article_id IS NULL
      OR btrim(target_article_id) = '' THEN
    RAISE EXCEPTION 'publisher compare-delete fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION 'publisher compare-delete owner generation was replaced';
  END IF;

  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;
  SELECT * INTO STRICT owned_attempt
  FROM volpred_ops.owned_notification_attempts
  WHERE effect_id = owned_request.effect_id
    AND attempt_count = p_attempt_count
  FOR SHARE;
  IF owned_attempt.status <> 'started'
      OR owned_attempt.worker_id <> btrim(p_worker_id)
      OR owned_attempt.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'publisher compare-delete attempt is not active';
  END IF;
  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_requests
  WHERE id = owned_request.effect_id
  FOR SHARE;
  IF effect.effect_kind <> ownership.effect_family
      OR effect.risk <> 'destructive'
      OR effect.acknowledgement_kind
        <> 'publisher.article.supabase.delete.readback' THEN
    RAISE EXCEPTION 'publisher compare-delete effect contract drifted';
  END IF;
  effect_payload := convert_from(
    volpred_ops.read_effect_payload(effect.payload_ref),
    'UTF8'
  )::jsonb;
  IF effect_payload -> 'authorization'
        IS DISTINCT FROM p_authorization
      OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements(
          effect_payload -> 'scope' -> 'candidates'
        ) AS item(candidate)
        WHERE item.candidate = p_expected_candidate
      ) THEN
    RAISE EXCEPTION
      'publisher compare-delete request is outside durable scope';
  END IF;

  SELECT * INTO STRICT approval
  FROM volpred_ops.publisher_article_delete_approvals
  WHERE approval_ref = p_authorization ->> 'approval_ref'
  FOR SHARE;
  IF NOT approval.active
      OR approval.approver_ref
        IS DISTINCT FROM p_authorization ->> 'approver_ref'
      OR approval.approved_at
        IS DISTINCT FROM p_authorization ->> 'approved_at'
      OR approval.scope_sha256
        IS DISTINCT FROM p_authorization ->> 'scope_sha256'
      OR approval.authorization_sha256 <> encode(
        sha256(convert_to(p_authorization::text, 'UTF8')),
        'hex'
      ) THEN
    RAISE EXCEPTION 'publisher compare-delete approval is not active';
  END IF;

  SELECT * INTO STRICT active_lease
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_primary_authority_key)
    AND holder_ref = btrim(p_primary_authority_holder_ref)
    AND epoch = p_primary_authority_epoch
    AND fencing_token_sha256 = encode(
      sha256(convert_to(p_primary_fencing_token, 'UTF8')),
      'hex'
    )
    AND lease_expires_at > clock_timestamp()
  FOR SHARE;

  IF public.volpred_read_article_delete_dependency_contract()
      <> jsonb_build_array(
        jsonb_build_object(
          'table', 'article_impressions',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_reactions',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_relations',
          'column', 'source_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_relations',
          'column', 'target_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'article_tags',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'comments',
          'column', 'article_id',
          'on_delete', 'cascade'
        ),
        jsonb_build_object(
          'table', 'question_articles',
          'column', 'article_id',
          'on_delete', 'cascade'
        )
      ) THEN
    RAISE EXCEPTION 'publisher compare-delete cascade contract drifted';
  END IF;

  PERFORM 1
  FROM public.articles AS article_row
  WHERE article_row.id::text = target_article_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'schema_version', 'publisher-article-compare-delete.v1',
      'article_id', target_article_id,
      'deleted', true,
      'already_absent', true
    );
  END IF;
  PERFORM 1 FROM public.article_impressions AS child
    WHERE child.article_id::text = target_article_id FOR UPDATE;
  PERFORM 1 FROM public.article_reactions AS child
    WHERE child.article_id::text = target_article_id FOR UPDATE;
  PERFORM 1 FROM public.article_relations AS child
    WHERE child.source_id::text = target_article_id
       OR child.target_id::text = target_article_id
    FOR UPDATE;
  PERFORM 1 FROM public.article_tags AS child
    WHERE child.article_id::text = target_article_id FOR UPDATE;
  PERFORM 1 FROM public.comments AS child
    WHERE child.article_id::text = target_article_id FOR UPDATE;
  PERFORM 1 FROM public.question_articles AS child
    WHERE child.article_id::text = target_article_id FOR UPDATE;

  observed :=
    volpred_ops.read_publisher_article_delete_candidate(target_article_id);
  IF observed IS DISTINCT FROM p_expected_candidate THEN
    RETURN jsonb_build_object(
      'schema_version', 'publisher-article-compare-delete.v1',
      'article_id', target_article_id,
      'deleted', false,
      'already_absent', false
    );
  END IF;
  DELETE FROM public.articles AS article_row
  WHERE article_row.id::text = target_article_id
  RETURNING article_row.id::text INTO deleted_id;
  RETURN jsonb_build_object(
    'schema_version', 'publisher-article-compare-delete.v1',
    'article_id', target_article_id,
    'deleted', deleted_id = target_article_id,
    'already_absent', false
  );
END;
$$;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
