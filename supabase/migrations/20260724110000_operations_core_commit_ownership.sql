-- Durable owner generation for the Git commit capability.
--
-- This migration is intentionally non-live.  It adds a legacy/operations-core
-- compare-and-set owner row, binds that generation to every new commit grant
-- and settlement, and atomically completes the WorkItem after the immutable
-- delivery receipt exists.  Existing unowned shadow grants remain NULL and
-- can never be replayed through the owner-fenced overloads.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.commit_owners (
  capability text PRIMARY KEY CHECK (capability = 'git.commit'),
  owner text NOT NULL CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  changed_at timestamptz NOT NULL,
  changed_by text NOT NULL,
  change_reason text NOT NULL
);

CREATE TABLE IF NOT EXISTS volpred_ops.commit_owner_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capability text NOT NULL
    REFERENCES volpred_ops.commit_owners(capability) ON DELETE RESTRICT,
  generation bigint NOT NULL UNIQUE CHECK (generation > 0),
  previous_owner text
    CHECK (
      previous_owner IS NULL
      OR previous_owner IN ('legacy', 'operations_core')
    ),
  owner text NOT NULL CHECK (owner IN ('legacy', 'operations_core')),
  actor_ref text NOT NULL,
  reason text NOT NULL,
  rollback_of_generation bigint,
  changed_at timestamptz NOT NULL,
  UNIQUE (capability, generation),
  CHECK (
    rollback_of_generation IS NULL OR rollback_of_generation > 0
  )
);

CREATE INDEX IF NOT EXISTS commit_owner_receipts_capability_changed_idx
  ON volpred_ops.commit_owner_receipts (
    capability, changed_at, generation
  );

ALTER TABLE volpred_ops.commit_authority_grants
  ADD COLUMN IF NOT EXISTS commit_owner_generation bigint;
ALTER TABLE volpred_ops.commit_authority_grants
  ADD COLUMN IF NOT EXISTS commit_owner_ref text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'commit_authority_grants_owner_shape_check'
      AND conrelid =
        'volpred_ops.commit_authority_grants'::regclass
  ) THEN
    ALTER TABLE volpred_ops.commit_authority_grants
      ADD CONSTRAINT commit_authority_grants_owner_shape_check
      CHECK (
        (
          commit_owner_generation IS NULL
          AND commit_owner_ref IS NULL
        )
        OR
        (
          commit_owner_generation > 0
          AND commit_owner_ref =
            'commit-owner:git.commit:generation-'
            || commit_owner_generation::text
        )
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'commit_authority_grants_owner_generation_fkey'
      AND conrelid =
        'volpred_ops.commit_authority_grants'::regclass
  ) THEN
    ALTER TABLE volpred_ops.commit_authority_grants
      ADD CONSTRAINT commit_authority_grants_owner_generation_fkey
      FOREIGN KEY (commit_owner_generation)
      REFERENCES volpred_ops.commit_owner_receipts(generation)
      ON DELETE RESTRICT;
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS commit_authority_grants_owner_generation_idx
  ON volpred_ops.commit_authority_grants (
    commit_owner_generation, granted_at, request_sha256
  )
  WHERE commit_owner_generation IS NOT NULL;

CREATE OR REPLACE VIEW volpred_ops.commit_owner_reads AS
SELECT
  'commit-owner.v1'::text AS schema_version,
  capability, owner, generation, changed_at, changed_by, change_reason
FROM volpred_ops.commit_owners;

CREATE OR REPLACE VIEW volpred_ops.commit_owner_receipt_reads AS
SELECT
  sequence, capability, generation, previous_owner, owner, actor_ref,
  reason, rollback_of_generation, changed_at
FROM volpred_ops.commit_owner_receipts;

CREATE OR REPLACE VIEW volpred_ops.commit_authority_grant_reads AS
SELECT
  request_sha256, proposal_sha256, work_item_id, work_item_version,
  work_holder_ref, commit_worker_ref, repository, expected_head,
  work_lease_ref, primary_authority_ref, granted_at,
  commit_owner_generation, commit_owner_ref
FROM volpred_ops.commit_authority_grants;

CREATE OR REPLACE VIEW volpred_ops.commit_delivery_receipt_reads AS
SELECT
  'change-delivery-receipt.v1'::text AS schema_version,
  receipt.change_set_id,
  authority_grant.proposal_sha256,
  authority_grant.work_item_id,
  authority_grant.work_item_version,
  receipt.authority_request_sha256,
  authority_grant.work_lease_ref,
  authority_grant.primary_authority_ref,
  receipt.repository,
  receipt.commit_sha,
  receipt.parent_sha,
  receipt.exact_paths,
  receipt.commit_worker_ref,
  'landed'::text AS status,
  receipt.actuation_observed_at,
  receipt.settled_at,
  (
    'change-delivery:' || receipt.change_set_id || ':' || receipt.commit_sha
  )::text AS settlement_ref,
  receipt.settlement_sha256,
  authority_grant.commit_owner_generation,
  authority_grant.commit_owner_ref
FROM volpred_ops.commit_delivery_receipts AS receipt
JOIN volpred_ops.commit_authority_grants AS authority_grant
  ON authority_grant.request_sha256 = receipt.authority_request_sha256;

ALTER TABLE volpred_ops.commit_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_owners FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_owner_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_owner_receipts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS commit_owners_definer_all
  ON volpred_ops.commit_owners;
CREATE POLICY commit_owners_definer_all
  ON volpred_ops.commit_owners
  FOR ALL TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS commit_owner_receipts_definer_select
  ON volpred_ops.commit_owner_receipts;
CREATE POLICY commit_owner_receipts_definer_select
  ON volpred_ops.commit_owner_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS commit_owner_receipts_definer_insert
  ON volpred_ops.commit_owner_receipts;
CREATE POLICY commit_owner_receipts_definer_insert
  ON volpred_ops.commit_owner_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS commit_authority_grants_definer_update
  ON volpred_ops.commit_authority_grants;
CREATE POLICY commit_authority_grants_definer_update
  ON volpred_ops.commit_authority_grants
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

INSERT INTO volpred_ops.commit_owners (
  capability, owner, generation, changed_at, changed_by, change_reason
)
VALUES (
  'git.commit',
  'legacy',
  1,
  clock_timestamp(),
  'migration:operations_core_commit_ownership',
  'initial Git owner remains legacy until explicit CAS cutover'
)
ON CONFLICT (capability) DO NOTHING;

INSERT INTO volpred_ops.commit_owner_receipts (
  capability, generation, previous_owner, owner, actor_ref, reason,
  rollback_of_generation, changed_at
)
SELECT
  capability, generation, NULL, owner, changed_by, change_reason,
  NULL, changed_at
FROM volpred_ops.commit_owners
WHERE capability = 'git.commit'
ON CONFLICT (capability, generation) DO NOTHING;

CREATE OR REPLACE FUNCTION volpred_ops.read_commit_owner()
RETURNS SETOF volpred_ops.commit_owner_reads
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
  SELECT *
  FROM volpred_ops.commit_owner_reads
  WHERE capability = 'git.commit';
$$;

CREATE OR REPLACE FUNCTION volpred_ops.transfer_commit_owner(
  p_expected_owner text,
  p_expected_generation bigint,
  p_target_owner text,
  p_actor_ref text,
  p_reason text,
  p_rollback_of_generation bigint DEFAULT NULL
)
RETURNS SETOF volpred_ops.commit_owner_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.commit_owners;
  replay volpred_ops.commit_owner_receipts;
  event_at timestamptz;
  owner_ref text;
  has_unsettled_change_sets boolean := false;
BEGIN
  IF p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'commit ownership transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation IS DISTINCT FROM p_expected_generation THEN
    RAISE EXCEPTION
      'commit ownership rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'commit ownership cutover cannot carry rollback generation';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.commit_owners
  WHERE capability = 'git.commit'
  FOR UPDATE;

  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    SELECT * INTO replay
    FROM volpred_ops.commit_owner_receipts
    WHERE capability = ownership.capability
      AND generation = p_expected_generation + 1;
    IF replay.capability IS NULL
        OR ownership.generation <> replay.generation
        OR ownership.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'commit ownership compare-and-set failed: expected %/% found %/%',
        p_expected_owner, p_expected_generation,
        ownership.owner, ownership.generation;
    END IF;
    RETURN QUERY SELECT * FROM volpred_ops.read_commit_owner();
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.commit_authority_grants AS authority_grant
    LEFT JOIN volpred_ops.commit_delivery_receipts AS receipt
      ON receipt.authority_request_sha256 =
        authority_grant.request_sha256
    WHERE authority_grant.commit_owner_generation = ownership.generation
      AND receipt.authority_request_sha256 IS NULL
  ) THEN
    RAISE EXCEPTION
      'commit ownership transfer requires zero unsettled grants';
  END IF;

  owner_ref :=
    'commit-owner:git.commit:generation-' || ownership.generation::text;
  IF to_regclass('volpred_ops.change_sets') IS NOT NULL THEN
    EXECUTE
      'SELECT EXISTS ('
      'SELECT 1 FROM volpred_ops.change_sets '
      'WHERE status = ''commit_unsettled'' '
      'AND actuation_receipt->>''commit_owner_ref'' = $1'
      ')'
    INTO has_unsettled_change_sets
    USING owner_ref;
  END IF;
  IF has_unsettled_change_sets THEN
    RAISE EXCEPTION
      'commit ownership transfer requires zero unsettled ChangeSets';
  END IF;

  event_at := clock_timestamp();
  UPDATE volpred_ops.commit_owners
  SET owner = p_target_owner,
      generation = generation + 1,
      changed_at = event_at,
      changed_by = btrim(p_actor_ref),
      change_reason = btrim(p_reason)
  WHERE capability = ownership.capability
  RETURNING * INTO ownership;

  INSERT INTO volpred_ops.commit_owner_receipts (
    capability, generation, previous_owner, owner, actor_ref, reason,
    rollback_of_generation, changed_at
  )
  VALUES (
    ownership.capability, ownership.generation, p_expected_owner,
    ownership.owner, ownership.changed_by, ownership.change_reason,
    p_rollback_of_generation, ownership.changed_at
  );
  RETURN QUERY SELECT * FROM volpred_ops.read_commit_owner();
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.authorize_commit_write(
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
RETURNS SETOF volpred_ops.commit_authority_grant_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.commit_owners;
  existing volpred_ops.commit_authority_grants;
  owner_ref text;
BEGIN
  IF p_commit_owner_generation IS NULL
      OR p_commit_owner_generation <= 0 THEN
    RAISE EXCEPTION 'commit ownership generation must be positive';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('commit-authority:' || p_request_sha256, 0)
  );
  SELECT * INTO STRICT ownership
  FROM volpred_ops.commit_owners
  WHERE capability = 'git.commit'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_commit_owner_generation THEN
    RAISE EXCEPTION
      'commit ownership lost: expected operations_core/% found %/%',
      p_commit_owner_generation, ownership.owner, ownership.generation;
  END IF;
  owner_ref :=
    'commit-owner:git.commit:generation-' || ownership.generation::text;

  SELECT * INTO existing
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF existing.request_sha256 IS NOT NULL
      AND (
        existing.commit_owner_generation IS NULL
        OR existing.commit_owner_generation <> ownership.generation
        OR existing.commit_owner_ref <> owner_ref
      ) THEN
    RAISE EXCEPTION
      'commit ownership grant conflicts with its original generation';
  END IF;

  PERFORM *
  FROM volpred_ops.authorize_commit_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_request_sha256,
    p_proposal_sha256,
    p_work_item_id,
    p_work_item_version,
    p_work_lease_token,
    p_repository,
    p_expected_head,
    p_commit_worker_ref
  );

  UPDATE volpred_ops.commit_authority_grants
  SET commit_owner_generation = ownership.generation,
      commit_owner_ref = owner_ref
  WHERE request_sha256 = p_request_sha256
    AND commit_owner_generation IS NULL
    AND commit_owner_ref IS NULL;

  SELECT * INTO STRICT existing
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF existing.commit_owner_generation <> ownership.generation
      OR existing.commit_owner_ref <> owner_ref THEN
    RAISE EXCEPTION
      'commit ownership grant conflicts with its original generation';
  END IF;

  RETURN QUERY
  SELECT *
  FROM volpred_ops.commit_authority_grant_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.settle_commit_write(
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
RETURNS SETOF volpred_ops.commit_delivery_receipt_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.commit_owners;
  authority_grant volpred_ops.commit_authority_grants;
  existing volpred_ops.commit_delivery_receipts;
  delivery volpred_ops.commit_delivery_receipt_reads;
  completed volpred_ops.work_item_reads;
BEGIN
  IF p_commit_owner_generation IS NULL
      OR p_commit_owner_generation <= 0
      OR p_commit_owner_ref IS NULL
      OR btrim(p_commit_owner_ref) <> (
        'commit-owner:git.commit:generation-'
        || p_commit_owner_generation::text
      ) THEN
    RAISE EXCEPTION 'commit ownership settlement identity is invalid';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      'commit-settlement:' || p_authority_request_sha256,
      0
    )
  );
  SELECT * INTO authority_grant
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_authority_request_sha256;
  IF authority_grant.request_sha256 IS NULL
      OR authority_grant.commit_owner_generation
        <> p_commit_owner_generation
      OR authority_grant.commit_owner_ref <> btrim(p_commit_owner_ref) THEN
    RAISE EXCEPTION
      'commit ownership settlement does not match its grant';
  END IF;

  SELECT * INTO existing
  FROM volpred_ops.commit_delivery_receipts
  WHERE authority_request_sha256 = p_authority_request_sha256;
  IF existing.authority_request_sha256 IS NULL THEN
    SELECT * INTO STRICT ownership
    FROM volpred_ops.commit_owners
    WHERE capability = 'git.commit'
    FOR SHARE;
    IF ownership.owner <> 'operations_core'
        OR ownership.generation <> p_commit_owner_generation THEN
      RAISE EXCEPTION
        'commit ownership lost: expected operations_core/% found %/%',
        p_commit_owner_generation, ownership.owner, ownership.generation;
    END IF;
  END IF;

  SELECT * INTO STRICT delivery
  FROM volpred_ops.settle_commit_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_authority_request_sha256,
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
  );

  SELECT * INTO STRICT completed
  FROM volpred_ops.complete_work(
    'change-delivery-completion:' || btrim(p_change_set_id),
    delivery.work_item_id,
    p_work_lease_token,
    delivery.work_item_version,
    delivery.settlement_ref,
    'ChangeSet landed with verified commit read-back'
  );
  IF completed.status <> 'succeeded'
      OR completed.result_ref <> delivery.settlement_ref THEN
    RAISE EXCEPTION
      'commit settlement WorkItem completion read-back drifted';
  END IF;

  RETURN QUERY
  SELECT *
  FROM volpred_ops.commit_delivery_receipt_reads
  WHERE authority_request_sha256 = p_authority_request_sha256;
END;
$$;

GRANT SELECT, INSERT, UPDATE ON volpred_ops.commit_owners
  TO volpred_ops_definer;
GRANT SELECT, INSERT ON volpred_ops.commit_owner_receipts
  TO volpred_ops_definer;
GRANT UPDATE ON volpred_ops.commit_authority_grants
  TO volpred_ops_definer;
GRANT USAGE, SELECT ON
  SEQUENCE volpred_ops.commit_owner_receipts_sequence_seq
  TO volpred_ops_definer;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER TABLE volpred_ops.commit_owners OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.commit_owner_receipts
  OWNER TO volpred_ops_definer;
ALTER SEQUENCE volpred_ops.commit_owner_receipts_sequence_seq
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_owner_reads OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_owner_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_authority_grant_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_delivery_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.read_commit_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_commit_owner(
  text, bigint, text, text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, bigint, text, text, text, text,
  text, text, text, text, text, jsonb, text, timestamptz, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.commit_owners,
  volpred_ops.commit_owner_receipts,
  volpred_ops.commit_owner_reads,
  volpred_ops.commit_owner_receipt_reads
FROM PUBLIC;
REVOKE ALL ON FUNCTION
  volpred_ops.read_commit_owner(),
  volpred_ops.transfer_commit_owner(
    text, bigint, text, text, text, bigint
  ),
  volpred_ops.authorize_commit_write(
    text, text, bigint, text, text, text, text, integer, bigint,
    text, text, text, text
  ),
  volpred_ops.settle_commit_write(
    text, text, bigint, text, text, bigint, text, text, text, text,
    text, text, text, text, text, jsonb, text, timestamptz, text
  )
FROM PUBLIC;

REVOKE EXECUTE ON FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, text, text, text, text
) FROM volpred_ops_worker;
REVOKE EXECUTE ON FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text, jsonb, text, timestamptz, text
) FROM volpred_ops_worker;

GRANT EXECUTE ON FUNCTION volpred_ops.read_commit_owner()
  TO volpred_ops_worker, volpred_ops_approver;
GRANT EXECUTE ON FUNCTION volpred_ops.transfer_commit_owner(
  text, bigint, text, text, text, bigint
) TO volpred_ops_approver;
GRANT EXECUTE ON FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) TO volpred_ops_worker;
GRANT EXECUTE ON FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, bigint, text, text, text, text,
  text, text, text, text, text, jsonb, text, timestamptz, text
) TO volpred_ops_worker;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
