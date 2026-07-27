-- Service-role-only, read-only attestation for the durable Work Coordinator
-- owner. This exposes no transfer/staging capability and does not read the
-- legacy filesystem queue.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION public.volpred_read_work_owner()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  owner_payload jsonb;
BEGIN
  SELECT to_jsonb(owner_row) || jsonb_build_object(
    'schema_version', 'work-owner-attestation.v1',
    'attested_at', statement_timestamp()
  )
  INTO STRICT owner_payload
  FROM volpred_ops.read_work_owner() AS owner_row;
  RETURN owner_payload;
END;
$$;

REVOKE ALL ON FUNCTION public.volpred_read_work_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_work_owner()
TO service_role;

COMMENT ON FUNCTION public.volpred_read_work_owner() IS
  'Service-role-only typed live Work Coordinator owner attestation; cannot stage or transfer ownership.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
