-- Read-only, service-role-only evidence for failures at the destructive
-- compare-delete boundary.  The mutation RPC remains the final transactional
-- gate; this function only identifies which durable prerequisite is absent.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  public.volpred_diagnose_publisher_article_compare_delete(
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT jsonb_build_object(
    'schema_version', 'publisher-article-compare-delete-diagnostic.v1',
    'owner_match', EXISTS (
      SELECT 1
      FROM volpred_ops.notification_owners AS ownership
      WHERE ownership.effect_family = 'publisher.article.supabase.delete'
        AND ownership.owner = 'operations_core'
        AND ownership.generation = p_owner_generation
    ),
    'request_match', EXISTS (
      SELECT 1
      FROM volpred_ops.owned_notification_requests AS owned_request
      WHERE owned_request.effect_id = btrim(p_effect_id)
        AND owned_request.effect_family =
          'publisher.article.supabase.delete'
        AND owned_request.owner_generation = p_owner_generation
    ),
    'attempt_match', EXISTS (
      SELECT 1
      FROM volpred_ops.owned_notification_attempts AS owned_attempt
      WHERE owned_attempt.effect_id = btrim(p_effect_id)
        AND owned_attempt.attempt_count = p_attempt_count
        AND owned_attempt.owner_generation = p_owner_generation
        AND owned_attempt.status = 'started'
        AND owned_attempt.worker_id = btrim(p_worker_id)
        AND owned_attempt.lease_expires_at > clock_timestamp()
    ),
    'effect_match', EXISTS (
      SELECT 1
      FROM volpred_ops.effect_requests AS effect
      WHERE effect.id = btrim(p_effect_id)
        AND effect.effect_kind = 'publisher.article.supabase.delete'
        AND effect.risk = 'destructive'
        AND effect.acknowledgement_kind =
          'publisher.article.supabase.delete.readback'
    ),
    'payload_match', EXISTS (
      SELECT 1
      FROM volpred_ops.effect_requests AS effect
      JOIN volpred_ops.effect_payloads AS payload
        ON payload.payload_ref = effect.payload_ref
       AND payload.payload_sha256 = effect.payload_sha256
      WHERE effect.id = btrim(p_effect_id)
    ),
    'approval_match', EXISTS (
      SELECT 1
      FROM volpred_ops.publisher_article_delete_approvals AS approval
      WHERE approval.approval_ref =
          p_authorization ->> 'approval_ref'
        AND approval.active
        AND approval.approver_ref IS NOT DISTINCT FROM
          p_authorization ->> 'approver_ref'
        AND approval.approved_at IS NOT DISTINCT FROM
          p_authorization ->> 'approved_at'
        AND approval.scope_sha256 IS NOT DISTINCT FROM
          p_authorization ->> 'scope_sha256'
        AND approval.authorization_sha256 = encode(
          sha256(convert_to(p_authorization::text, 'UTF8')),
          'hex'
        )
    ),
    'primary_lease_match', EXISTS (
      SELECT 1
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
    ),
    'dependency_contract_match',
      public.volpred_read_article_delete_dependency_contract()
      = jsonb_build_array(
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
      ),
    'candidate_exact',
      volpred_ops.read_publisher_article_delete_candidate(
        p_expected_candidate -> 'article' ->> 'id'
      ) IS NOT DISTINCT FROM p_expected_candidate
  );
$$;

ALTER FUNCTION
  public.volpred_diagnose_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_diagnose_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_diagnose_publisher_article_compare_delete(
    bigint, text, integer, text, text, text, bigint, text, jsonb, jsonb
  )
TO service_role;

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
