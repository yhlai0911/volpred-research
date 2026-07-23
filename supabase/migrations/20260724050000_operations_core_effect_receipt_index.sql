-- Cover the outbox foreign key used by receipt lookups and parent-row checks.
-- Supabase's performance advisor reports unindexed foreign keys, and the
-- receipt primary key begins with effect_id rather than outbox_sequence.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE INDEX effect_attempt_receipts_outbox_sequence_idx
  ON volpred_ops.effect_attempt_receipts (outbox_sequence);

RESET ROLE;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
