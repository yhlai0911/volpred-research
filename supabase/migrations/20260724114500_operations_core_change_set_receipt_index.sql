-- Cover the immutable delivery-receipt FK from the ChangeSet side.
-- Settlement links this column after the external Git write, and the
-- Supabase advisor requires a left-prefix index on the referencing column.
DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE INDEX IF NOT EXISTS change_sets_delivery_authority_request_idx
  ON volpred_ops.change_sets (delivery_authority_request_sha256)
  WHERE delivery_authority_request_sha256 IS NOT NULL;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
