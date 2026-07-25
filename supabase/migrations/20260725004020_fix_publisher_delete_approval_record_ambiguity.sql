-- Qualify the approval lookup and keep PL/pgSQL locals distinct from columns.
--
-- The initial production smoke reached this function before any insert and
-- PostgreSQL correctly rejected ``approval_ref = approval_ref`` as ambiguous.
-- This forward-only replacement preserves the original ACL and ownership.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
SET ROLE volpred_ops_definer;

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
  requested_approval_ref text;
  requested_approver_ref text;
  requested_approved_at text;
  requested_scope_sha256 text;
  requested_authorization_sha256 text;
BEGIN
  requested_approval_ref := p_authorization ->> 'approval_ref';
  requested_approver_ref := p_authorization ->> 'approver_ref';
  requested_approved_at := p_authorization ->> 'approved_at';
  requested_scope_sha256 := p_authorization ->> 'scope_sha256';
  IF jsonb_typeof(p_authorization) <> 'object'
      OR (
        SELECT count(*)
        FROM pg_catalog.jsonb_object_keys(p_authorization)
      ) <> 4
      OR NOT p_authorization ?& ARRAY[
        'approval_ref', 'approver_ref', 'approved_at', 'scope_sha256'
      ]
      OR requested_approval_ref IS NULL
      OR btrim(requested_approval_ref) = ''
      OR requested_approver_ref IS NULL
      OR btrim(requested_approver_ref) = ''
      OR requested_approved_at IS NULL
      OR requested_approved_at::timestamptz IS NULL
      OR requested_scope_sha256 !~ '^[0-9a-f]{64}$'
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = '' THEN
    RAISE EXCEPTION 'publisher delete approval fields are invalid';
  END IF;
  requested_authorization_sha256 := encode(
    sha256(convert_to(p_authorization::text, 'UTF8')),
    'hex'
  );
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'publisher-delete-approval:' || btrim(requested_approval_ref),
      0
    )
  );
  SELECT approval.*
  INTO existing
  FROM volpred_ops.publisher_article_delete_approvals AS approval
  WHERE approval.approval_ref = btrim(requested_approval_ref);
  IF existing.approval_ref IS NOT NULL THEN
    IF existing.authorization_sha256
          <> requested_authorization_sha256
        OR existing.approver_ref <> btrim(requested_approver_ref)
        OR existing.approved_at <> requested_approved_at
        OR existing.scope_sha256 <> requested_scope_sha256 THEN
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
    btrim(requested_approval_ref),
    btrim(requested_approver_ref),
    requested_approved_at,
    requested_scope_sha256,
    requested_authorization_sha256,
    true,
    clock_timestamp(),
    btrim(p_actor_ref)
  );
  RETURN public.volpred_read_publisher_article_delete_approval(
    btrim(requested_approval_ref)
  );
END;
$$;

COMMENT ON FUNCTION
  public.volpred_record_publisher_article_delete_approval(jsonb, text)
IS
  'Idempotently persist one immutable scope-bound delete approval.';

RESET ROLE;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
