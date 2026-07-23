-- Cover the ownership-receipt FK from the request side.  The transfer path
-- checks generations repeatedly and the Supabase advisor requires a
-- left-prefix index on the referencing columns.
DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE INDEX IF NOT EXISTS owned_notification_requests_owner_generation_idx
  ON volpred_ops.owned_notification_requests (
    effect_family, owner_generation
  );

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
