-- Service-role-only operator seam for the durable Git commit owner.
--
-- The private functions remain the single implementation of the ownership
-- transaction.  These public wrappers only make their narrow JSON result
-- available to the production PostgREST adapter; they do not expose the
-- underlying FORCE-RLS tables or any commit-authority token.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_commit_owner()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  owner_payload jsonb;
BEGIN
  SELECT to_jsonb(owner_row)
  INTO STRICT owner_payload
  FROM volpred_ops.read_commit_owner() AS owner_row;
  RETURN owner_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_transfer_commit_owner(
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
  owner_payload jsonb;
BEGIN
  SELECT to_jsonb(owner_row)
  INTO STRICT owner_payload
  FROM volpred_ops.transfer_commit_owner(
    p_expected_owner,
    p_expected_generation,
    p_target_owner,
    p_actor_ref,
    p_reason,
    p_rollback_of_generation
  ) AS owner_row;
  RETURN owner_payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER FUNCTION public.volpred_read_commit_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_transfer_commit_owner(
  text, bigint, text, text, text, bigint
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_read_commit_owner(),
  public.volpred_transfer_commit_owner(
    text, bigint, text, text, text, bigint
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_read_commit_owner(),
  public.volpred_transfer_commit_owner(
    text, bigint, text, text, text, bigint
  )
TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
