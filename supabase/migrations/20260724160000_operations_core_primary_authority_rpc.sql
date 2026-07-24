-- Service-role-only PostgREST seam for Primary Authority.
--
-- The public wrappers delegate every lifecycle transition to the existing
-- private, database-clock transactions. Raw fencing tokens are accepted for
-- revalidation but are never returned by a wrapper.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_acquire_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  lease_payload jsonb;
BEGIN
  SELECT to_jsonb(lease_row)
  INTO STRICT lease_payload
  FROM volpred_ops.acquire_primary_authority(
    p_authority_key,
    p_holder_ref,
    p_lease_seconds,
    p_fencing_token
  ) AS lease_row;
  RETURN lease_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_renew_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  lease_payload jsonb;
BEGIN
  SELECT to_jsonb(lease_row)
  INTO STRICT lease_payload
  FROM volpred_ops.renew_primary_authority(
    p_authority_key,
    p_holder_ref,
    p_epoch,
    p_lease_seconds,
    p_fencing_token
  ) AS lease_row;
  RETURN lease_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_authorize_primary_write(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text,
  p_request_sha256 text,
  p_resource_ref text
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
  FROM volpred_ops.authorize_primary_write(
    p_authority_key,
    p_holder_ref,
    p_epoch,
    p_fencing_token,
    p_request_sha256,
    p_resource_ref
  ) AS grant_row;
  RETURN grant_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_release_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text
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
  FROM volpred_ops.release_primary_authority(
    p_authority_key,
    p_holder_ref,
    p_epoch,
    p_fencing_token
  ) AS receipt_row;
  RETURN receipt_payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
