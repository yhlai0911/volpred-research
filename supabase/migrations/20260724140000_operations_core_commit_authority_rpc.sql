-- Service-role-only PostgREST seam for owner-fenced commit authority.
--
-- The public wrapper delegates to the existing private transaction. It
-- accepts the raw lease tokens needed for database-clock revalidation but
-- returns only the durable token-redacted authority grant.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_authorize_commit_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_request_sha256 text,
  p_proposal_sha256 text,
  p_work_item_id text,
  p_work_item_version integer,
  p_commit_owner_generation bigint,
  p_work_lease_token text,
  p_repository text,
  p_expected_head text,
  p_commit_worker_ref text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  grant_payload jsonb;
BEGIN
  SELECT to_jsonb(grant_row)
  INTO STRICT grant_payload
  FROM volpred_ops.authorize_commit_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_request_sha256,
    p_proposal_sha256,
    p_work_item_id,
    p_work_item_version,
    p_commit_owner_generation,
    p_work_lease_token,
    p_repository,
    p_expected_head,
    p_commit_worker_ref
  ) AS grant_row;
  RETURN grant_payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION public.volpred_authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.volpred_authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
