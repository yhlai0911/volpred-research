-- Service-role-only PostgREST seam for owner-fenced commit settlement.
--
-- The public wrapper delegates to the existing private transaction. It
-- accepts the raw lease tokens needed for database-clock revalidation but
-- returns only the durable token-redacted delivery receipt.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_settle_commit_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_authority_request_sha256 text,
  p_commit_owner_generation bigint,
  p_commit_owner_ref text,
  p_settlement_sha256 text,
  p_change_set_id text,
  p_work_lease_token text,
  p_work_lease_ref text,
  p_primary_authority_ref text,
  p_repository text,
  p_commit_sha text,
  p_parent_sha text,
  p_exact_paths jsonb,
  p_commit_worker_ref text,
  p_actuation_observed_at timestamptz,
  p_actuation_status text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  receipt_payload jsonb;
BEGIN
  SELECT to_jsonb(receipt_row)
  INTO STRICT receipt_payload
  FROM volpred_ops.settle_commit_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_authority_request_sha256,
    p_commit_owner_generation,
    p_commit_owner_ref,
    p_settlement_sha256,
    p_change_set_id,
    p_work_lease_token,
    p_work_lease_ref,
    p_primary_authority_ref,
    p_repository,
    p_commit_sha,
    p_parent_sha,
    p_exact_paths,
    p_commit_worker_ref,
    p_actuation_observed_at,
    p_actuation_status
  ) AS receipt_row;
  RETURN receipt_payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_settle_commit_write(
  text, text, bigint, text, text, bigint, text, text, text, text,
  text, text, text, text, text, jsonb, text, timestamptz, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION public.volpred_settle_commit_write(
  text, text, bigint, text, text, bigint, text, text, text, text,
  text, text, text, text, text, jsonb, text, timestamptz, text
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.volpred_settle_commit_write(
  text, text, bigint, text, text, bigint, text, text, text, text,
  text, text, text, text, text, jsonb, text, timestamptz, text
) TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
