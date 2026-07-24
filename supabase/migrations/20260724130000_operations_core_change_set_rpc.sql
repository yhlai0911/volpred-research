-- Service-role-only PostgREST seam for durable ChangeSet lifecycle state.
--
-- These public wrappers delegate to the private transaction functions and
-- return token-redacted read views. They expose neither FORCE-RLS tables nor
-- raw WorkLease / Primary Authority tokens.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_create_change_set(
  p_id text,
  p_idempotency_key text,
  p_work_item_id text,
  p_work_item_version integer,
  p_base_commit text,
  p_workspace_ref text,
  p_exact_paths jsonb,
  p_content_hashes jsonb,
  p_required_checks jsonb,
  p_author_ref text,
  p_author_evidence_ref text,
  p_proposal_sha256 text,
  p_schema_version text,
  p_created_at timestamptz
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  change_payload jsonb;
BEGIN
  SELECT to_jsonb(change_row)
  INTO STRICT change_payload
  FROM volpred_ops.create_change_set(
    p_id, p_idempotency_key, p_work_item_id, p_work_item_version,
    p_base_commit, p_workspace_ref, p_exact_paths, p_content_hashes,
    p_required_checks, p_author_ref, p_author_evidence_ref,
    p_proposal_sha256, p_schema_version, p_created_at
  ) AS change_row;
  RETURN change_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_change_set(
  p_change_set_id text
)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT to_jsonb(change_row)
  FROM volpred_ops.change_set_reads AS change_row
  WHERE change_row.id = btrim(p_change_set_id)
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_read_change_set_by_idempotency_key(
    p_idempotency_key text
  )
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT to_jsonb(change_row)
  FROM volpred_ops.change_set_reads AS change_row
  WHERE change_row.idempotency_key = btrim(p_idempotency_key)
$$;

CREATE OR REPLACE FUNCTION public.volpred_checkpoint_change_set_actuation(
  p_change_set_id text,
  p_proposal_sha256 text,
  p_land_command_sha256 text,
  p_actuation_receipt jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  change_payload jsonb;
BEGIN
  SELECT to_jsonb(change_row)
  INTO STRICT change_payload
  FROM volpred_ops.checkpoint_change_set_actuation(
    p_change_set_id, p_proposal_sha256, p_land_command_sha256,
    p_actuation_receipt
  ) AS change_row;
  RETURN change_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_mark_change_set_landed(
  p_change_set_id text,
  p_proposal_sha256 text,
  p_land_command_sha256 text,
  p_delivery_authority_request_sha256 text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  change_payload jsonb;
BEGIN
  SELECT to_jsonb(change_row)
  INTO STRICT change_payload
  FROM volpred_ops.mark_change_set_landed(
    p_change_set_id, p_proposal_sha256, p_land_command_sha256,
    p_delivery_authority_request_sha256
  ) AS change_row;
  RETURN change_payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_create_change_set(
  text, text, text, integer, text, text, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_change_set(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_change_set_by_idempotency_key(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_checkpoint_change_set_actuation(
  text, text, text, jsonb
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_mark_change_set_landed(
  text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_create_change_set(
    text, text, text, integer, text, text, jsonb, jsonb, jsonb,
    text, text, text, text, timestamptz
  ),
  public.volpred_read_change_set(text),
  public.volpred_read_change_set_by_idempotency_key(text),
  public.volpred_checkpoint_change_set_actuation(
    text, text, text, jsonb
  ),
  public.volpred_mark_change_set_landed(text, text, text, text)
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_create_change_set(
    text, text, text, integer, text, text, jsonb, jsonb, jsonb,
    text, text, text, text, timestamptz
  ),
  public.volpred_read_change_set(text),
  public.volpred_read_change_set_by_idempotency_key(text),
  public.volpred_checkpoint_change_set_actuation(
    text, text, text, jsonb
  ),
  public.volpred_mark_change_set_landed(text, text, text, text)
TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
