-- Production ownership and projection for destructive publisher deletion.
--
-- The durable owner/request/attempt tables already carry an effect_family
-- discriminator. This migration adds a separate destructive family without
-- exposing those private tables. Narrow public wrappers exist only because the
-- runtime has a Supabase service-role key and no direct Postgres DSN.
--
-- Every wrapper is SECURITY DEFINER with an empty search_path, is owned by the
-- no-login volpred_ops_definer role, and is executable only by service_role.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
SET ROLE volpred_ops_definer;
CREATE TABLE IF NOT EXISTS volpred_ops.publisher_article_delete_approvals (
  approval_ref text PRIMARY KEY,
  approver_ref text NOT NULL,
  approved_at text NOT NULL,
  scope_sha256 text NOT NULL
    CHECK (scope_sha256 ~ '^[0-9a-f]{64}$'),
  authorization_sha256 text NOT NULL
    CHECK (authorization_sha256 ~ '^[0-9a-f]{64}$'),
  active boolean NOT NULL DEFAULT true,
  recorded_at timestamptz NOT NULL,
  recorded_by text NOT NULL,
  revoked_at timestamptz,
  revoked_by text,
  revoke_reason text,
  CHECK (
    (active AND revoked_at IS NULL AND revoked_by IS NULL
      AND revoke_reason IS NULL)
    OR
    (NOT active AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL
      AND revoke_reason IS NOT NULL)
  )
);

ALTER TABLE volpred_ops.publisher_article_delete_approvals
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.publisher_article_delete_approvals
  FORCE ROW LEVEL SECURITY;
RESET ROLE;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

INSERT INTO volpred_ops.notification_owners (
  effect_family, owner, generation, changed_at, changed_by, change_reason
)
VALUES (
  'publisher.article.supabase.delete',
  'legacy',
  1,
  clock_timestamp(),
  'migration:operations_core_publisher_delete_ownership',
  'initial owner remains legacy until explicit CAS cutover'
)
ON CONFLICT (effect_family) DO NOTHING;

INSERT INTO volpred_ops.notification_owner_receipts (
  effect_family, generation, previous_owner, owner, actor_ref, reason,
  rollback_of_generation, changed_at
)
SELECT
  effect_family, generation, NULL, owner, changed_by, change_reason,
  NULL, changed_at
FROM volpred_ops.notification_owners
WHERE effect_family = 'publisher.article.supabase.delete'
ON CONFLICT (effect_family, generation) DO NOTHING;

CREATE OR REPLACE FUNCTION
  public.volpred_read_publisher_article_delete_owner()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
BEGIN
  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete';
  RETURN jsonb_build_object(
    'schema_version', 'publisher-article-delete-owner.v1',
    'effect_family', ownership.effect_family,
    'owner', ownership.owner,
    'generation', ownership.generation,
    'changed_at', ownership.changed_at,
    'changed_by', ownership.changed_by,
    'change_reason', ownership.change_reason
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_transfer_publisher_article_delete_owner(
    p_expected_owner text,
    p_expected_generation bigint,
    p_target_owner text,
    p_actor_ref text,
    p_reason text,
    p_rollback_of_generation bigint DEFAULT NULL
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  replay volpred_ops.notification_owner_receipts;
  event_at timestamptz;
BEGIN
  IF p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL
      OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION
      'publisher delete scope ownership transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation
        IS DISTINCT FROM p_expected_generation THEN
    RAISE EXCEPTION
      'publisher delete scope rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'publisher delete scope cutover cannot carry rollback generation';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR UPDATE;

  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    SELECT * INTO replay
    FROM volpred_ops.notification_owner_receipts
    WHERE effect_family = ownership.effect_family
      AND generation = p_expected_generation + 1;
    IF replay.effect_family IS NULL
        OR ownership.generation <> replay.generation
        OR ownership.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'publisher delete scope ownership compare-and-set failed: '
        'expected %/% found %/%',
        p_expected_owner, p_expected_generation,
        ownership.owner, ownership.generation;
    END IF;
    RETURN public.volpred_read_publisher_article_delete_owner();
  END IF;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.owned_notification_attempts AS attempt
    JOIN volpred_ops.owned_notification_requests AS owned_request
      ON owned_request.effect_id = attempt.effect_id
    WHERE owned_request.effect_family = ownership.effect_family
      AND attempt.status = 'started'
      AND attempt.lease_expires_at > clock_timestamp()
  ) THEN
    RAISE EXCEPTION
      'publisher delete scope ownership transfer requires zero active attempts';
  END IF;

  event_at := clock_timestamp();
  UPDATE volpred_ops.notification_owners
  SET owner = p_target_owner,
      generation = generation + 1,
      changed_at = event_at,
      changed_by = btrim(p_actor_ref),
      change_reason = btrim(p_reason)
  WHERE effect_family = ownership.effect_family
  RETURNING * INTO ownership;

  INSERT INTO volpred_ops.notification_owner_receipts (
    effect_family, generation, previous_owner, owner, actor_ref, reason,
    rollback_of_generation, changed_at
  )
  VALUES (
    ownership.effect_family,
    ownership.generation,
    p_expected_owner,
    ownership.owner,
    ownership.changed_by,
    ownership.change_reason,
    p_rollback_of_generation,
    ownership.changed_at
  );
  RETURN public.volpred_read_publisher_article_delete_owner();
END;
$$;

CREATE OR REPLACE FUNCTION
  volpred_ops.read_publisher_article_delete_candidate(
    p_article_id text
  )
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  article_payload jsonb;
  dependents jsonb;
BEGIN
  SELECT to_jsonb(article_row)
  INTO article_payload
  FROM public.articles AS article_row
  WHERE article_row.id::text = p_article_id;
  IF article_payload IS NULL THEN
    RETURN NULL;
  END IF;

  dependents := jsonb_build_object(
    'article_impressions',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.article_impressions AS child
        WHERE child.article_id::text = p_article_id
      ),
    'article_reactions',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.article_reactions AS child
        WHERE child.article_id::text = p_article_id
      ),
    'article_relations',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.article_relations AS child
        WHERE child.source_id::text = p_article_id
           OR child.target_id::text = p_article_id
      ),
    'article_tags',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.article_tags AS child
        WHERE child.article_id::text = p_article_id
      ),
    'comments',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.comments AS child
        WHERE child.article_id::text = p_article_id
      ),
    'question_articles',
      (
        SELECT COALESCE(
          jsonb_agg(to_jsonb(child) ORDER BY to_jsonb(child)::text),
          '[]'::jsonb
        )
        FROM public.question_articles AS child
        WHERE child.article_id::text = p_article_id
      )
  );
  RETURN jsonb_build_object(
    'article', article_payload,
    'dependents', dependents
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_read_publisher_article_delete_approval(
    p_approval_ref text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  approval volpred_ops.publisher_article_delete_approvals;
  authorization_payload jsonb;
  evidence jsonb;
BEGIN
  IF p_approval_ref IS NULL OR btrim(p_approval_ref) = '' THEN
    RAISE EXCEPTION 'publisher delete approval_ref is required';
  END IF;
  SELECT * INTO STRICT approval
  FROM volpred_ops.publisher_article_delete_approvals
  WHERE approval_ref = btrim(p_approval_ref);
  authorization_payload := jsonb_build_object(
    'approval_ref', approval.approval_ref,
    'approver_ref', approval.approver_ref,
    'approved_at', approval.approved_at,
    'scope_sha256', approval.scope_sha256
  );
  evidence := jsonb_build_object(
    'schema_version', 'publisher-article-delete-approval-readback.v1',
    'authorization', authorization_payload,
    'authorization_sha256', approval.authorization_sha256,
    'active', approval.active,
    'recorded_at', approval.recorded_at,
    'revoked_at', approval.revoked_at
  );
  RETURN jsonb_build_object(
    'schema_version', 'publisher-article-delete-approval-readback.v1',
    'authorization', authorization_payload,
    'active', approval.active,
    'evidence_ref',
      'supabase:publisher-delete-approval:' || approval.approval_ref,
    'evidence_sha256', encode(
      sha256(convert_to(evidence::text, 'UTF8')),
      'hex'
    )
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_record_publisher_article_delete_approval(
    p_authorization jsonb,
    p_actor_ref text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  existing volpred_ops.publisher_article_delete_approvals;
  approval_ref text;
  approver_ref text;
  approved_at text;
  scope_sha256 text;
  authorization_sha256 text;
BEGIN
  approval_ref := p_authorization ->> 'approval_ref';
  approver_ref := p_authorization ->> 'approver_ref';
  approved_at := p_authorization ->> 'approved_at';
  scope_sha256 := p_authorization ->> 'scope_sha256';
  IF jsonb_typeof(p_authorization) <> 'object'
      OR (
        SELECT count(*)
        FROM pg_catalog.jsonb_object_keys(p_authorization)
      ) <> 4
      OR NOT p_authorization ?& ARRAY[
        'approval_ref', 'approver_ref', 'approved_at', 'scope_sha256'
      ]
      OR approval_ref IS NULL
      OR btrim(approval_ref) = ''
      OR approver_ref IS NULL
      OR btrim(approver_ref) = ''
      OR approved_at IS NULL
      OR approved_at::timestamptz IS NULL
      OR scope_sha256 !~ '^[0-9a-f]{64}$'
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = '' THEN
    RAISE EXCEPTION 'publisher delete approval fields are invalid';
  END IF;
  authorization_sha256 := encode(
    sha256(convert_to(p_authorization::text, 'UTF8')),
    'hex'
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'publisher-delete-approval:' || btrim(approval_ref),
      0
    )
  );
  SELECT * INTO existing
  FROM volpred_ops.publisher_article_delete_approvals
  WHERE approval_ref = btrim(approval_ref);
  IF existing.approval_ref IS NOT NULL THEN
    IF existing.authorization_sha256 <> authorization_sha256
        OR existing.approver_ref <> btrim(approver_ref)
        OR existing.approved_at <> approved_at
        OR existing.scope_sha256 <> scope_sha256 THEN
      RAISE EXCEPTION
        'publisher delete approval_ref conflicts with original authorization';
    END IF;
    RETURN public.volpred_read_publisher_article_delete_approval(
      existing.approval_ref
    );
  END IF;
  INSERT INTO volpred_ops.publisher_article_delete_approvals (
    approval_ref, approver_ref, approved_at, scope_sha256,
    authorization_sha256, active, recorded_at, recorded_by
  )
  VALUES (
    btrim(approval_ref), btrim(approver_ref), approved_at, scope_sha256,
    authorization_sha256, true, clock_timestamp(), btrim(p_actor_ref)
  );
  RETURN public.volpred_read_publisher_article_delete_approval(
    btrim(approval_ref)
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_revoke_publisher_article_delete_approval(
    p_approval_ref text,
    p_actor_ref text,
    p_reason text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  approval volpred_ops.publisher_article_delete_approvals;
BEGIN
  IF p_approval_ref IS NULL
      OR btrim(p_approval_ref) = ''
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL
      OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'publisher delete approval revocation fields are invalid';
  END IF;
  SELECT * INTO STRICT approval
  FROM volpred_ops.publisher_article_delete_approvals
  WHERE approval_ref = btrim(p_approval_ref)
  FOR UPDATE;
  IF NOT approval.active THEN
    IF approval.revoked_by <> btrim(p_actor_ref)
        OR approval.revoke_reason <> btrim(p_reason) THEN
      RAISE EXCEPTION
        'publisher delete approval was revoked by a different request';
    END IF;
    RETURN public.volpred_read_publisher_article_delete_approval(
      approval.approval_ref
    );
  END IF;
  UPDATE volpred_ops.publisher_article_delete_approvals
  SET active = false,
      revoked_at = clock_timestamp(),
      revoked_by = btrim(p_actor_ref),
      revoke_reason = btrim(p_reason)
  WHERE approval_ref = approval.approval_ref;
  RETURN public.volpred_read_publisher_article_delete_approval(
    approval.approval_ref
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_read_publisher_article_delete_candidate(
    p_article_id text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  candidate jsonb;
  evidence jsonb;
BEGIN
  IF p_article_id IS NULL OR btrim(p_article_id) = '' THEN
    RAISE EXCEPTION 'publisher delete article_id is required';
  END IF;
  candidate :=
    volpred_ops.read_publisher_article_delete_candidate(
      btrim(p_article_id)
    );
  evidence := jsonb_build_object(
    'schema_version', 'publisher-article-delete-candidate-readback.v1',
    'article_id', btrim(p_article_id),
    'candidate', candidate
  );
  RETURN jsonb_build_object(
    'schema_version', 'publisher-article-delete-candidate-readback.v1',
    'article_id', btrim(p_article_id),
    'candidate', candidate,
    'evidence_ref',
      'supabase:publisher-delete-candidate:' || btrim(p_article_id),
    'evidence_sha256', encode(
      sha256(convert_to(evidence::text, 'UTF8')),
      'hex'
    )
  );
END;
$$;

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
    AND owner_generation = ownership.generation
  FOR SHARE;
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
    'auto',
    payload_ref,
    NULL,
    NULL,
    btrim(p_actor_ref),
    'pending',
    1,
    event_at,
    event_at
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

CREATE OR REPLACE FUNCTION
  public.volpred_begin_owned_publisher_article_delete(
    p_owner_generation bigint,
    p_effect_id text,
    p_worker_id text,
    p_lease_seconds integer,
    p_work_lease_token text,
    p_outbox_claim_token text,
    p_primary_fencing_token text
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  owned_request volpred_ops.owned_notification_requests;
  work volpred_ops.work_items;
  effect volpred_ops.effect_requests;
  message volpred_ops.effect_outbox;
  primary_lease volpred_ops.primary_authority_lease_reads;
  authority_grant volpred_ops.effect_authority_grant_reads;
  event_at timestamptz;
  lease_expires_at timestamptz;
  authority_request_sha256 text;
  payload_bytes bytea;
BEGIN
  IF p_owner_generation IS NULL
      OR p_owner_generation <= 0
      OR p_effect_id IS NULL
      OR btrim(p_effect_id) = ''
      OR p_worker_id IS NULL
      OR btrim(p_worker_id) = ''
      OR p_lease_seconds IS NULL
      OR p_lease_seconds <= 0
      OR p_work_lease_token IS NULL
      OR btrim(p_work_lease_token) = ''
      OR p_outbox_claim_token IS NULL
      OR btrim(p_outbox_claim_token) = ''
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = '' THEN
    RAISE EXCEPTION 'owned publisher delete scope begin fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'publisher delete scope ownership lost: '
      'expected operations_core/% found %/%',
      p_owner_generation,
      ownership.owner,
      ownership.generation;
  END IF;
  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;

  event_at := clock_timestamp();
  lease_expires_at :=
    event_at + make_interval(secs => p_lease_seconds);
  SELECT * INTO STRICT work
  FROM volpred_ops.work_items
  WHERE id = owned_request.work_id
  FOR UPDATE;
  IF NOT (
    work.status = 'pending'
    OR (
      work.status IN ('claimed', 'running')
      AND work.claim_expires_at IS NOT NULL
      AND work.claim_expires_at <= event_at
    )
  ) THEN
    RAISE EXCEPTION
      'owned publisher delete scope work is not available: %',
      work.status;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'claimed',
      version = version + 1,
      claimed_by = btrim(p_worker_id),
      claim_token = p_work_lease_token,
      claim_expires_at = lease_expires_at,
      updated_at = event_at
  WHERE id = work.id
  RETURNING * INTO work;
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref
  )
  VALUES (
    work.id,
    'acquired',
    work.version,
    event_at,
    btrim(p_worker_id)
  );
  UPDATE volpred_ops.work_items
  SET status = 'running',
      version = version + 1,
      updated_at = event_at
  WHERE id = work.id
  RETURNING * INTO work;
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref
  )
  VALUES (
    work.id,
    'started',
    work.version,
    event_at,
    btrim(p_worker_id)
  );

  SELECT * INTO STRICT message
  FROM volpred_ops.effect_outbox
  WHERE effect_id = owned_request.effect_id
  FOR UPDATE;
  IF message.available_at > event_at
      OR NOT (
        message.status = 'pending'
        OR (
          message.status = 'claimed'
          AND message.claim_expires_at IS NOT NULL
          AND message.claim_expires_at <= event_at
        )
      ) THEN
    RAISE EXCEPTION
      'owned publisher delete scope effect is not available: %',
      message.status;
  END IF;
  UPDATE volpred_ops.effect_outbox
  SET status = 'claimed',
      attempt_count = attempt_count + 1,
      claimed_by = btrim(p_worker_id),
      claim_token = p_outbox_claim_token,
      claim_expires_at = lease_expires_at
  WHERE sequence = message.sequence
  RETURNING * INTO message;
  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_requests
  WHERE id = message.effect_id
  FOR KEY SHARE;
  IF effect.effect_kind <> ownership.effect_family
      OR effect.target_ref <> 'supabase:articles'
      OR effect.risk <> 'destructive'
      OR effect.acknowledgement_kind
        <> 'publisher.article.supabase.delete.readback'
      OR effect.acknowledgement_target_ref <> effect.target_ref THEN
    RAISE EXCEPTION
      'owned publisher delete scope effect contract drifted';
  END IF;

  SELECT * INTO STRICT primary_lease
  FROM volpred_ops.primary_authority_lease_reads AS active_lease
  WHERE active_lease.authority_key =
      'publisher:article.supabase.delete'
    AND active_lease.holder_ref = btrim(p_worker_id)
    AND active_lease.lease_expires_at > event_at;

  authority_request_sha256 := encode(
    sha256(
      convert_to(
        jsonb_build_object(
          'schema_version', 'owned-publisher-delete-authority.v1',
          'owner_generation', ownership.generation,
          'work_id', work.id,
          'work_version', work.version,
          'effect_id', effect.id,
          'effect_request_sha256', effect.request_sha256,
          'outbox_sequence', message.sequence,
          'attempt_count', message.attempt_count,
          'worker_id', message.claimed_by,
          'lease_expires_at', message.claim_expires_at,
          'primary_authority_key', primary_lease.authority_key,
          'primary_authority_epoch', primary_lease.epoch
        )::text,
        'UTF8'
      )
    ),
    'hex'
  );
  SELECT * INTO STRICT authority_grant
  FROM volpred_ops.authorize_effect_write(
    primary_lease.authority_key,
    primary_lease.holder_ref,
    primary_lease.epoch,
    p_primary_fencing_token,
    authority_request_sha256,
    effect.id,
    effect.request_sha256,
    effect.work_item_id,
    effect.work_item_version,
    message.sequence,
    message.attempt_count,
    p_outbox_claim_token,
    message.claim_expires_at,
    message.claimed_by,
    effect.effect_kind,
    effect.target_ref,
    effect.payload_ref,
    effect.payload_sha256,
    effect.acknowledgement_kind,
    effect.acknowledgement_target_ref
  );
  payload_bytes :=
    volpred_ops.read_effect_payload(effect.payload_ref);
  IF encode(sha256(payload_bytes), 'hex')
      <> effect.payload_sha256 THEN
    RAISE EXCEPTION
      'owned publisher delete scope durable payload hash mismatch';
  END IF;

  INSERT INTO volpred_ops.owned_notification_attempts (
    effect_id,
    attempt_count,
    work_id,
    outbox_sequence,
    owner_generation,
    worker_id,
    lease_expires_at,
    authority_request_sha256,
    outbox_claim_ref,
    primary_authority_ref,
    status,
    started_at
  )
  VALUES (
    effect.id,
    message.attempt_count,
    work.id,
    message.sequence,
    ownership.generation,
    message.claimed_by,
    lease_expires_at,
    authority_grant.request_sha256,
    authority_grant.outbox_claim_ref,
    authority_grant.primary_authority_ref,
    'started',
    event_at
  );

  RETURN jsonb_build_object(
    'schema_version', 'owned-publisher-delete-attempt.v1',
    'owner_generation', ownership.generation,
    'work_id', work.id,
    'work_version', work.version,
    'effect', jsonb_build_object(
      'schema_version', 'effect-request.v1',
      'id', effect.id,
      'idempotency_key', effect.idempotency_key,
      'work_item_id', effect.work_item_id,
      'work_item_version', effect.work_item_version,
      'effect_kind', effect.effect_kind,
      'target_ref', effect.target_ref,
      'payload_ref', effect.payload_ref,
      'payload_sha256', effect.payload_sha256,
      'risk', effect.risk,
      'acknowledgement', jsonb_build_object(
        'kind', effect.acknowledgement_kind,
        'target_ref', effect.acknowledgement_target_ref
      ),
      'requester_ref', effect.requester_ref,
      'request_sha256', effect.request_sha256,
      'status', effect.status,
      'created_at', effect.created_at
    ),
    'payload_base64',
      replace(encode(payload_bytes, 'base64'), E'\n', ''),
    'outbox_sequence', message.sequence,
    'attempt_count', message.attempt_count,
    'worker_id', message.claimed_by,
    'primary_authority_key', primary_lease.authority_key,
    'primary_authority_holder_ref', primary_lease.holder_ref,
    'primary_authority_epoch', primary_lease.epoch,
    'authority_request_sha256', authority_grant.request_sha256,
    'outbox_claim_ref', authority_grant.outbox_claim_ref,
    'primary_authority_ref', authority_grant.primary_authority_ref,
    'lease_expires_at', lease_expires_at
  );
END;
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_settle_owned_publisher_article_delete(
    p_owner_generation bigint,
    p_work_id text,
    p_work_version integer,
    p_work_lease_token text,
    p_effect_id text,
    p_outbox_sequence bigint,
    p_attempt_count integer,
    p_worker_id text,
    p_outbox_claim_token text,
    p_primary_authority_key text,
    p_primary_authority_holder_ref text,
    p_primary_authority_epoch bigint,
    p_primary_fencing_token text,
    p_authority_request_sha256 text,
    p_outbox_claim_ref text,
    p_primary_authority_ref text,
    p_outcome text,
    p_acknowledgement_kind text,
    p_acknowledgement_target_ref text,
    p_reason_code text,
    p_evidence_ref text,
    p_evidence_sha256 text
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
  work volpred_ops.work_items;
  effect volpred_ops.effect_requests;
  primary_lease volpred_ops.primary_authority_leases;
  attempt_receipt volpred_ops.effect_attempt_receipt_reads;
  event_at timestamptz;
  work_receipt_id text;
BEGIN
  IF p_owner_generation IS NULL
      OR p_owner_generation <= 0
      OR p_work_id IS NULL
      OR btrim(p_work_id) = ''
      OR p_work_version IS NULL
      OR p_work_version <= 0
      OR p_work_lease_token IS NULL
      OR btrim(p_work_lease_token) = ''
      OR p_effect_id IS NULL
      OR btrim(p_effect_id) = ''
      OR p_outbox_sequence IS NULL
      OR p_outbox_sequence <= 0
      OR p_attempt_count IS NULL
      OR p_attempt_count <= 0
      OR p_worker_id IS NULL
      OR btrim(p_worker_id) = ''
      OR p_outbox_claim_token IS NULL
      OR btrim(p_outbox_claim_token) = ''
      OR p_primary_authority_key
        <> 'publisher:article.supabase.delete'
      OR p_primary_authority_holder_ref IS NULL
      OR btrim(p_primary_authority_holder_ref) = ''
      OR p_primary_authority_epoch IS NULL
      OR p_primary_authority_epoch <= 0
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = ''
      OR p_authority_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_outbox_claim_ref IS NULL
      OR btrim(p_outbox_claim_ref) = ''
      OR p_primary_authority_ref IS NULL
      OR btrim(p_primary_authority_ref) = ''
      OR p_outcome NOT IN (
        'acknowledged',
        'retryable_failure',
        'terminal_failure'
      )
      OR p_evidence_ref IS NULL
      OR btrim(p_evidence_ref) = ''
      OR p_evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'owned publisher delete scope settlement fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'publisher delete scope ownership lost: '
      'expected operations_core/% found %/%',
      p_owner_generation,
      ownership.owner,
      ownership.generation;
  END IF;
  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;
  SELECT * INTO STRICT owned_attempt
  FROM volpred_ops.owned_notification_attempts
  WHERE effect_id = btrim(p_effect_id)
    AND attempt_count = p_attempt_count
  FOR UPDATE;
  IF owned_attempt.owner_generation <> ownership.generation
      OR owned_attempt.work_id <> owned_request.work_id
      OR owned_attempt.work_id <> btrim(p_work_id)
      OR owned_attempt.outbox_sequence <> p_outbox_sequence
      OR owned_attempt.worker_id <> btrim(p_worker_id)
      OR owned_attempt.authority_request_sha256
        <> p_authority_request_sha256
      OR owned_attempt.outbox_claim_ref
        <> btrim(p_outbox_claim_ref)
      OR owned_attempt.primary_authority_ref
        <> btrim(p_primary_authority_ref) THEN
    RAISE EXCEPTION
      'owned publisher delete scope attempt identity mismatch';
  END IF;
  IF owned_attempt.status <> 'started' THEN
    IF owned_attempt.reported_outcome <> p_outcome
        OR owned_attempt.evidence_ref <> btrim(p_evidence_ref)
        OR owned_attempt.evidence_sha256 <> p_evidence_sha256 THEN
      RAISE EXCEPTION
        'owned publisher delete scope settlement conflicts '
        'with original outcome';
    END IF;
    RETURN jsonb_build_object(
      'schema_version', 'owned-publisher-delete-receipt.v1',
      'owner_generation', owned_attempt.owner_generation,
      'work_id', owned_attempt.work_id,
      'work_status', owned_attempt.work_status,
      'effect_id', owned_attempt.effect_id,
      'effect_status', owned_attempt.effect_status,
      'attempt_count', owned_attempt.attempt_count,
      'disposition', owned_attempt.disposition,
      'evidence_ref', owned_attempt.evidence_ref,
      'evidence_sha256', owned_attempt.evidence_sha256,
      'primary_authority_ref',
        owned_attempt.primary_authority_ref,
      'recorded_at', owned_attempt.finished_at
    );
  ELSIF owned_attempt.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'owned publisher delete scope attempt lease expired';
  END IF;

  SELECT * INTO STRICT work
  FROM volpred_ops.work_items
  WHERE id = owned_attempt.work_id
  FOR UPDATE;
  IF work.version <> p_work_version
      OR work.status <> 'running'
      OR work.claimed_by <> btrim(p_worker_id)
      OR work.claim_token <> p_work_lease_token
      OR work.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'publisher delete scope work lease lost';
  END IF;

  SELECT * INTO STRICT primary_lease
  FROM volpred_ops.primary_authority_leases AS active_lease
  WHERE active_lease.authority_key =
      btrim(p_primary_authority_key)
    AND active_lease.holder_ref =
      btrim(p_primary_authority_holder_ref)
    AND active_lease.epoch = p_primary_authority_epoch
    AND active_lease.fencing_token_sha256 = encode(
      sha256(convert_to(p_primary_fencing_token, 'UTF8')),
      'hex'
    )
    AND active_lease.lease_expires_at > clock_timestamp()
  FOR SHARE;

  SELECT * INTO STRICT attempt_receipt
  FROM volpred_ops.settle_effect_outbox(
    p_outbox_sequence,
    btrim(p_effect_id),
    p_attempt_count,
    btrim(p_worker_id),
    p_outbox_claim_token,
    p_authority_request_sha256,
    btrim(p_outbox_claim_ref),
    btrim(p_primary_authority_ref),
    p_outcome,
    p_acknowledgement_kind,
    p_acknowledgement_target_ref,
    p_reason_code,
    btrim(p_evidence_ref),
    p_evidence_sha256
  );

  IF attempt_receipt.disposition = 'delivered' THEN
    work_receipt_id :=
      'owned-publisher-completion:' || p_effect_id
      || ':attempt-' || p_attempt_count::text;
    SELECT * INTO STRICT work
    FROM volpred_ops.complete_work(
      work_receipt_id,
      work.id,
      p_work_lease_token,
      work.version,
      attempt_receipt.evidence_ref,
      'owned publisher delete scope delivered with exact Supabase read-back'
    );
  ELSIF attempt_receipt.disposition = 'retry_scheduled' THEN
    SELECT * INTO STRICT work
    FROM volpred_ops.release_work(
      work.id,
      p_work_lease_token,
      work.version,
      'owned publisher provider requested durable retry'
    );
  ELSE
    event_at := clock_timestamp();
    work_receipt_id :=
      'owned-publisher-failure:' || p_effect_id
      || ':attempt-' || p_attempt_count::text;
    UPDATE volpred_ops.work_items
    SET status = 'failed',
        version = version + 1,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL,
        result_ref = attempt_receipt.evidence_ref,
        result_summary = 'owned publisher delete scope dead-lettered',
        finished_at = event_at,
        updated_at = event_at
    WHERE id = work.id
    RETURNING * INTO work;
    INSERT INTO volpred_ops.work_receipts (
      id, work_id, outcome, result_ref, summary, created_at
    )
    VALUES (
      work_receipt_id,
      work.id,
      'failed',
      attempt_receipt.evidence_ref,
      'owned publisher delete scope dead-lettered',
      event_at
    );
    INSERT INTO volpred_ops.work_events (
      work_id, kind, version, created_at, actor_ref, evidence_ref
    )
    VALUES (
      work.id,
      'failed',
      work.version,
      event_at,
      btrim(p_worker_id),
      attempt_receipt.evidence_ref
    );
  END IF;

  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_requests
  WHERE id = btrim(p_effect_id);
  event_at := attempt_receipt.recorded_at;
  UPDATE volpred_ops.owned_notification_attempts
  SET status = attempt_receipt.disposition,
      reported_outcome = attempt_receipt.reported_outcome,
      disposition = attempt_receipt.disposition,
      evidence_ref = attempt_receipt.evidence_ref,
      evidence_sha256 = attempt_receipt.evidence_sha256,
      work_status = work.status,
      effect_status = effect.status,
      finished_at = event_at
  WHERE effect_id = owned_attempt.effect_id
    AND attempt_count = owned_attempt.attempt_count
  RETURNING * INTO owned_attempt;

  RETURN jsonb_build_object(
    'schema_version', 'owned-publisher-delete-receipt.v1',
    'owner_generation', owned_attempt.owner_generation,
    'work_id', owned_attempt.work_id,
    'work_status', owned_attempt.work_status,
    'effect_id', owned_attempt.effect_id,
    'effect_status', owned_attempt.effect_status,
    'attempt_count', owned_attempt.attempt_count,
    'disposition', owned_attempt.disposition,
    'evidence_ref', owned_attempt.evidence_ref,
    'evidence_sha256', owned_attempt.evidence_sha256,
    'primary_authority_ref',
      owned_attempt.primary_authority_ref,
    'recorded_at', owned_attempt.finished_at
  );
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

GRANT SELECT, INSERT, UPDATE
  ON volpred_ops.publisher_article_delete_approvals
  TO volpred_ops_definer;
GRANT SELECT ON
  public.articles,
  public.article_impressions,
  public.article_reactions,
  public.article_relations,
  public.article_tags,
  public.comments,
  public.question_articles
TO volpred_ops_definer;
GRANT DELETE ON public.articles TO volpred_ops_definer;
GRANT EXECUTE ON FUNCTION
  public.volpred_read_article_delete_dependency_contract()
TO volpred_ops_definer;

DROP POLICY IF EXISTS publisher_delete_approvals_definer_select
  ON volpred_ops.publisher_article_delete_approvals;
CREATE POLICY publisher_delete_approvals_definer_select
  ON volpred_ops.publisher_article_delete_approvals
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_approvals_definer_insert
  ON volpred_ops.publisher_article_delete_approvals;
CREATE POLICY publisher_delete_approvals_definer_insert
  ON volpred_ops.publisher_article_delete_approvals
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS publisher_delete_approvals_definer_update
  ON volpred_ops.publisher_article_delete_approvals;
CREATE POLICY publisher_delete_approvals_definer_update
  ON volpred_ops.publisher_article_delete_approvals
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.articles;
CREATE POLICY publisher_delete_definer_select
  ON public.articles FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_delete
  ON public.articles;
CREATE POLICY publisher_delete_definer_delete
  ON public.articles FOR DELETE TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.article_impressions;
CREATE POLICY publisher_delete_definer_select
  ON public.article_impressions FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.article_reactions;
CREATE POLICY publisher_delete_definer_select
  ON public.article_reactions FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.article_relations;
CREATE POLICY publisher_delete_definer_select
  ON public.article_relations FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.article_tags;
CREATE POLICY publisher_delete_definer_select
  ON public.article_tags FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.comments;
CREATE POLICY publisher_delete_definer_select
  ON public.comments FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS publisher_delete_definer_select
  ON public.question_articles;
CREATE POLICY publisher_delete_definer_select
  ON public.question_articles FOR SELECT TO volpred_ops_definer USING (true);

ALTER FUNCTION
  volpred_ops.read_publisher_article_delete_candidate(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_read_publisher_article_delete_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_transfer_publisher_article_delete_owner(
    text, bigint, text, text, text, bigint
  )
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_read_publisher_article_delete_approval(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_record_publisher_article_delete_approval(jsonb, text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_revoke_publisher_article_delete_approval(text, text, text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_read_publisher_article_delete_candidate(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_compare_delete_publisher_article(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  )
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_begin_owned_publisher_article_delete(
    bigint, text, text, integer, text, text, text
  )
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_settle_owned_publisher_article_delete(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text,
    text, text, text
  )
  OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  volpred_ops.read_publisher_article_delete_candidate(text)
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  public.volpred_read_publisher_article_delete_owner(),
  public.volpred_transfer_publisher_article_delete_owner(
    text, bigint, text, text, text, bigint
  ),
  public.volpred_read_publisher_article_delete_approval(text),
  public.volpred_record_publisher_article_delete_approval(jsonb, text),
  public.volpred_revoke_publisher_article_delete_approval(text, text, text),
  public.volpred_read_publisher_article_delete_candidate(text),
  public.volpred_compare_delete_publisher_article(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  ),
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  ),
  public.volpred_begin_owned_publisher_article_delete(
    bigint, text, text, integer, text, text, text
  ),
  public.volpred_settle_owned_publisher_article_delete(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text,
    text, text, text
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_read_publisher_article_delete_owner(),
  public.volpred_transfer_publisher_article_delete_owner(
    text, bigint, text, text, text, bigint
  ),
  public.volpred_read_publisher_article_delete_approval(text),
  public.volpred_record_publisher_article_delete_approval(jsonb, text),
  public.volpred_revoke_publisher_article_delete_approval(text, text, text),
  public.volpred_read_publisher_article_delete_candidate(text),
  public.volpred_compare_delete_publisher_article(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  ),
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  ),
  public.volpred_begin_owned_publisher_article_delete(
    bigint, text, text, integer, text, text, text
  ),
  public.volpred_settle_owned_publisher_article_delete(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text,
    text, text, text
  )
TO service_role;

COMMENT ON FUNCTION
  public.volpred_read_publisher_article_delete_owner()
IS
  'Read the unique owner generation for publisher destructive delete.';
COMMENT ON FUNCTION
  public.volpred_transfer_publisher_article_delete_owner(
    text, bigint, text, text, text, bigint
  )
IS
  'CAS transfer publisher delete ownership with rollback identity.';
COMMENT ON FUNCTION
  public.volpred_request_owned_publisher_article_delete(
    bigint, text, text, text
  )
IS
  'Create immutable delete WorkItem, payload, EffectRequest and outbox.';
COMMENT ON FUNCTION
  public.volpred_begin_owned_publisher_article_delete(
    bigint, text, text, integer, text, text, text
  )
IS
  'Begin a publisher attempt using an active family host keepalive lease.';
COMMENT ON FUNCTION
  public.volpred_settle_owned_publisher_article_delete(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text,
    text, text, text
  )
IS
  'Settle publisher effect and WorkItem; host keepalive owns lease release.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
