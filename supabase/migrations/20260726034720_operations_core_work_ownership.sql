-- Durable, transaction-fenced owner generation for Work Coordinator writes.
--
-- The legacy signatures remain available while the durable owner is
-- `legacy`.  Operations Core uses overloads with an explicit owner
-- generation.  Every wrapper takes a shared lock on the owner row before
-- entering the original mutation, while transfer takes the same row
-- exclusively and requires zero active leases.  The two mutation paths
-- therefore cannot be valid in the same transaction horizon.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE volpred_ops.work_owners (
  capability text PRIMARY KEY
    CHECK (capability = 'work.coordinate'),
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  cutover_manifest_sha256 text
    CHECK (
      cutover_manifest_sha256 IS NULL
      OR cutover_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
  changed_at timestamptz NOT NULL,
  changed_by text NOT NULL,
  change_reason text NOT NULL
);

CREATE TABLE volpred_ops.work_owner_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capability text NOT NULL
    REFERENCES volpred_ops.work_owners(capability) ON DELETE RESTRICT,
  generation bigint NOT NULL UNIQUE CHECK (generation > 0),
  previous_owner text
    CHECK (
      previous_owner IS NULL
      OR previous_owner IN ('legacy', 'operations_core')
    ),
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  actor_ref text NOT NULL,
  reason text NOT NULL,
  cutover_manifest_sha256 text
    CHECK (
      cutover_manifest_sha256 IS NULL
      OR cutover_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
  rollback_of_generation bigint
    CHECK (
      rollback_of_generation IS NULL
      OR rollback_of_generation > 0
    ),
  changed_at timestamptz NOT NULL,
  UNIQUE (capability, generation)
);

CREATE INDEX work_owner_receipts_capability_changed_idx
  ON volpred_ops.work_owner_receipts (
    capability, changed_at, generation
  );

CREATE VIEW volpred_ops.work_owner_reads AS
SELECT
  'work-owner.v1'::text AS schema_version,
  capability,
  owner,
  generation,
  cutover_manifest_sha256,
  changed_at,
  changed_by,
  change_reason
FROM volpred_ops.work_owners;

GRANT SELECT, UPDATE ON volpred_ops.work_owners
  TO volpred_ops_definer;
GRANT SELECT, INSERT ON volpred_ops.work_owner_receipts
  TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.work_owner_receipts_sequence_seq
  TO volpred_ops_definer;

INSERT INTO volpred_ops.work_owners (
  capability,
  owner,
  generation,
  cutover_manifest_sha256,
  changed_at,
  changed_by,
  change_reason
)
VALUES (
  'work.coordinate',
  'legacy',
  1,
  NULL,
  clock_timestamp(),
  'migration:operations_core_work_ownership',
  'initial Work Coordinator owner remains legacy'
);

INSERT INTO volpred_ops.work_owner_receipts (
  capability,
  generation,
  previous_owner,
  owner,
  actor_ref,
  reason,
  cutover_manifest_sha256,
  rollback_of_generation,
  changed_at
)
SELECT
  capability,
  generation,
  NULL,
  owner,
  changed_by,
  change_reason,
  cutover_manifest_sha256,
  NULL,
  changed_at
FROM volpred_ops.work_owners
WHERE capability = 'work.coordinate';

ALTER TABLE volpred_ops.work_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_owners FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_owner_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_owner_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY work_owners_definer_select
  ON volpred_ops.work_owners
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_owners_definer_update
  ON volpred_ops.work_owners
  FOR UPDATE TO volpred_ops_definer
  USING (true) WITH CHECK (true);
CREATE POLICY work_owner_receipts_definer_select
  ON volpred_ops.work_owner_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_owner_receipts_definer_insert
  ON volpred_ops.work_owner_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE FUNCTION volpred_ops.read_work_owner()
RETURNS SETOF volpred_ops.work_owner_reads
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
  SELECT *
  FROM volpred_ops.work_owner_reads
  WHERE capability = 'work.coordinate';
$$;

CREATE FUNCTION volpred_ops.assert_work_owner(
  p_expected_owner text,
  p_expected_generation bigint DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.work_owners;
BEGIN
  SELECT * INTO STRICT ownership
  FROM volpred_ops.work_owners
  WHERE capability = 'work.coordinate'
  FOR SHARE;

  IF (
        p_expected_owner IS NOT NULL
        AND ownership.owner <> p_expected_owner
      )
      OR (
        p_expected_generation IS NOT NULL
        AND ownership.generation <> p_expected_generation
      ) THEN
    RAISE EXCEPTION
      'work ownership % mutation lost: expected generation %, found %/%',
      p_expected_owner,
      COALESCE(p_expected_generation::text, 'current'),
      ownership.owner,
      ownership.generation;
  END IF;
END;
$$;

CREATE FUNCTION volpred_ops.set_legacy_work_mutation_access(
  p_enabled boolean
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  verb text;
  preposition text;
BEGIN
  verb := CASE WHEN p_enabled THEN 'GRANT' ELSE 'REVOKE' END;
  preposition := CASE WHEN p_enabled THEN 'TO' ELSE 'FROM' END;
  EXECUTE verb || ' EXECUTE ON FUNCTION '
    || 'volpred_ops.submit_work('
    || 'text,text,text,text,text,integer,text[],text[],text,text,'
    || 'text,text,timestamptz,text,text,integer,timestamptz,timestamptz),'
    || 'volpred_ops.acquire_work(text,text[],text[],integer,text),'
    || 'volpred_ops.start_work(text,text,integer),'
    || 'volpred_ops.checkpoint_work(text,text,integer,text,text,text,text),'
    || 'volpred_ops.release_work(text,text,integer,text),'
    || 'volpred_ops.complete_work(text,text,text,integer,text,text) '
    || preposition || ' volpred_ops_worker';
  EXECUTE verb || ' EXECUTE ON FUNCTION '
    || 'volpred_ops.approve_work(text,integer,text,text) '
    || preposition || ' volpred_ops_approver';
END;
$$;

CREATE FUNCTION volpred_ops.transfer_work_owner(
  p_expected_owner text,
  p_expected_generation bigint,
  p_target_owner text,
  p_actor_ref text,
  p_reason text,
  p_cutover_manifest_sha256 text,
  p_rollback_of_generation bigint DEFAULT NULL
)
RETURNS SETOF volpred_ops.work_owner_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.work_owners;
  replay volpred_ops.work_owner_receipts;
  event_at timestamptz;
BEGIN
  IF p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL
      OR btrim(p_reason) = ''
      OR p_cutover_manifest_sha256 IS NULL
      OR p_cutover_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'work ownership transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation
        IS DISTINCT FROM p_expected_generation THEN
    RAISE EXCEPTION
      'work ownership rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'work ownership cutover cannot carry rollback generation';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.work_owners
  WHERE capability = 'work.coordinate'
  FOR UPDATE;

  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    SELECT * INTO replay
    FROM volpred_ops.work_owner_receipts
    WHERE capability = ownership.capability
      AND generation = p_expected_generation + 1;
    IF replay.capability IS NULL
        OR ownership.generation <> replay.generation
        OR ownership.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.cutover_manifest_sha256
          <> p_cutover_manifest_sha256
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'work ownership compare-and-set failed: expected %/% found %/%',
        p_expected_owner,
        p_expected_generation,
        ownership.owner,
        ownership.generation;
    END IF;
    RETURN QUERY SELECT * FROM volpred_ops.read_work_owner();
    RETURN;
  END IF;

  IF p_target_owner = 'legacy'
      AND ownership.cutover_manifest_sha256
        IS DISTINCT FROM p_cutover_manifest_sha256 THEN
    RAISE EXCEPTION
      'work ownership rollback manifest does not match current cutover';
  END IF;

  event_at := clock_timestamp();
  WITH expired AS (
    UPDATE volpred_ops.work_items
    SET status = 'pending',
        version = version + 1,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL,
        last_release_reason =
          'ownership transfer reconciled expired lease',
        updated_at = event_at
    WHERE status IN ('claimed', 'running')
      AND claim_expires_at IS NOT NULL
      AND claim_expires_at <= event_at
    RETURNING id, version
  )
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref
  )
  SELECT
    id, 'released', version, event_at, 'system:work-owner-transfer'
  FROM expired;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.work_items
    WHERE status IN ('claimed', 'running')
      AND (
        claim_expires_at IS NULL
        OR claim_expires_at > event_at
      )
  ) THEN
    RAISE EXCEPTION
      'work ownership transfer requires zero active leases';
  END IF;

  UPDATE volpred_ops.work_owners
  SET owner = p_target_owner,
      generation = generation + 1,
      cutover_manifest_sha256 = p_cutover_manifest_sha256,
      changed_at = event_at,
      changed_by = btrim(p_actor_ref),
      change_reason = btrim(p_reason)
  WHERE capability = ownership.capability
  RETURNING * INTO ownership;

  INSERT INTO volpred_ops.work_owner_receipts (
    capability,
    generation,
    previous_owner,
    owner,
    actor_ref,
    reason,
    cutover_manifest_sha256,
    rollback_of_generation,
    changed_at
  )
  VALUES (
    ownership.capability,
    ownership.generation,
    p_expected_owner,
    ownership.owner,
    ownership.changed_by,
    ownership.change_reason,
    ownership.cutover_manifest_sha256,
    p_rollback_of_generation,
    ownership.changed_at
  );

  PERFORM volpred_ops.set_legacy_work_mutation_access(
    p_target_owner = 'legacy'
  );

  RETURN QUERY SELECT * FROM volpred_ops.read_work_owner();
END;
$$;

-- Preserve the original transaction bodies as private, unfenced primitives.
ALTER FUNCTION volpred_ops.submit_work(
  text, text, text, text, text, integer, text[], text[], text, text,
  text, text, timestamptz, text, text, integer, timestamptz, timestamptz
) RENAME TO submit_work_unfenced;
ALTER FUNCTION volpred_ops.acquire_work(
  text, text[], text[], integer, text
) RENAME TO acquire_work_unfenced;
ALTER FUNCTION volpred_ops.approve_work(
  text, integer, text, text
) RENAME TO approve_work_unfenced;
ALTER FUNCTION volpred_ops.start_work(
  text, text, integer
) RENAME TO start_work_unfenced;
ALTER FUNCTION volpred_ops.checkpoint_work(
  text, text, integer, text, text, text, text
) RENAME TO checkpoint_work_unfenced;
ALTER FUNCTION volpred_ops.release_work(
  text, text, integer, text
) RENAME TO release_work_unfenced;
ALTER FUNCTION volpred_ops.complete_work(
  text, text, text, integer, text, text
) RENAME TO complete_work_unfenced;

-- Compatibility wrappers have no generation argument. Runtime roles can
-- execute them only while legacy owns the capability; Operations Core
-- stored procedures retain owner-only access so their transaction can call
-- the same private mutation body after cutover.
CREATE FUNCTION volpred_ops.submit_work(
  p_id text,
  p_idempotency_key text,
  p_source text,
  p_kind text,
  p_title text,
  p_priority integer,
  p_required_capabilities text[],
  p_required_attestations text[],
  p_risk text,
  p_approval text,
  p_payload_ref text,
  p_parent_id text,
  p_deadline timestamptz,
  p_requester_ref text,
  p_status text,
  p_version integer,
  p_created_at timestamptz,
  p_updated_at timestamptz
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.submit_work_unfenced(
    p_id, p_idempotency_key, p_source, p_kind, p_title, p_priority,
    p_required_capabilities, p_required_attestations, p_risk, p_approval,
    p_payload_ref, p_parent_id, p_deadline, p_requester_ref, p_status,
    p_version, p_created_at, p_updated_at
  );
END;
$$;

CREATE FUNCTION volpred_ops.acquire_work(
  p_worker_id text,
  p_capabilities text[],
  p_attestations text[],
  p_lease_seconds integer,
  p_token text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.acquire_work_unfenced(
    p_worker_id, p_capabilities, p_attestations, p_lease_seconds, p_token
  );
END;
$$;

CREATE FUNCTION volpred_ops.approve_work(
  p_work_id text,
  p_expected_version integer,
  p_approved_by text,
  p_evidence_ref text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.approve_work_unfenced(
    p_work_id, p_expected_version, p_approved_by, p_evidence_ref
  );
END;
$$;

CREATE FUNCTION volpred_ops.start_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.start_work_unfenced(
    p_work_id, p_lease_token, p_expected_version
  );
END;
$$;

CREATE FUNCTION volpred_ops.checkpoint_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_checkpoint_id text,
  p_artifact_ref text,
  p_artifact_sha256 text,
  p_verification_ref text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.checkpoint_work_unfenced(
    p_work_id, p_lease_token, p_expected_version, p_checkpoint_id,
    p_artifact_ref, p_artifact_sha256, p_verification_ref
  );
END;
$$;

CREATE FUNCTION volpred_ops.release_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_reason text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.release_work_unfenced(
    p_work_id, p_lease_token, p_expected_version, p_reason
  );
END;
$$;

CREATE FUNCTION volpred_ops.complete_work(
  p_report_id text,
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_result_ref text,
  p_summary text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(NULL);
  RETURN QUERY SELECT * FROM volpred_ops.complete_work_unfenced(
    p_report_id, p_work_id, p_lease_token, p_expected_version,
    p_result_ref, p_summary
  );
END;
$$;

-- Operations Core overloads bind every mutation to one explicit generation.
CREATE FUNCTION volpred_ops.submit_work(
  p_id text,
  p_idempotency_key text,
  p_source text,
  p_kind text,
  p_title text,
  p_priority integer,
  p_required_capabilities text[],
  p_required_attestations text[],
  p_risk text,
  p_approval text,
  p_payload_ref text,
  p_parent_id text,
  p_deadline timestamptz,
  p_requester_ref text,
  p_status text,
  p_version integer,
  p_created_at timestamptz,
  p_updated_at timestamptz,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.submit_work_unfenced(
    p_id, p_idempotency_key, p_source, p_kind, p_title, p_priority,
    p_required_capabilities, p_required_attestations, p_risk, p_approval,
    p_payload_ref, p_parent_id, p_deadline, p_requester_ref, p_status,
    p_version, p_created_at, p_updated_at
  );
END;
$$;

CREATE FUNCTION volpred_ops.acquire_work(
  p_worker_id text,
  p_capabilities text[],
  p_attestations text[],
  p_lease_seconds integer,
  p_token text,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.acquire_work_unfenced(
    p_worker_id, p_capabilities, p_attestations, p_lease_seconds, p_token
  );
END;
$$;

CREATE FUNCTION volpred_ops.approve_work(
  p_work_id text,
  p_expected_version integer,
  p_approved_by text,
  p_evidence_ref text,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.approve_work_unfenced(
    p_work_id, p_expected_version, p_approved_by, p_evidence_ref
  );
END;
$$;

CREATE FUNCTION volpred_ops.start_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.start_work_unfenced(
    p_work_id, p_lease_token, p_expected_version
  );
END;
$$;

CREATE FUNCTION volpred_ops.checkpoint_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_checkpoint_id text,
  p_artifact_ref text,
  p_artifact_sha256 text,
  p_verification_ref text,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.checkpoint_work_unfenced(
    p_work_id, p_lease_token, p_expected_version, p_checkpoint_id,
    p_artifact_ref, p_artifact_sha256, p_verification_ref
  );
END;
$$;

CREATE FUNCTION volpred_ops.release_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_reason text,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.release_work_unfenced(
    p_work_id, p_lease_token, p_expected_version, p_reason
  );
END;
$$;

CREATE FUNCTION volpred_ops.complete_work(
  p_report_id text,
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_result_ref text,
  p_summary text,
  p_owner_generation bigint
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  PERFORM volpred_ops.assert_work_owner(
    'operations_core', p_owner_generation
  );
  RETURN QUERY SELECT * FROM volpred_ops.complete_work_unfenced(
    p_report_id, p_work_id, p_lease_token, p_expected_version,
    p_result_ref, p_summary
  );
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER VIEW volpred_ops.work_owner_reads OWNER TO volpred_ops_definer;

ALTER FUNCTION volpred_ops.read_work_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.assert_work_owner(text, bigint)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.set_legacy_work_mutation_access(boolean)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_work_owner(
  text, bigint, text, text, text, text, bigint
) OWNER TO volpred_ops_definer;

DO $$
DECLARE
  function_name text;
  signature text;
BEGIN
  FOR function_name, signature IN
    SELECT *
    FROM (
      VALUES
        ('submit_work_unfenced',
          'text,text,text,text,text,integer,text[],text[],text,text,'
          'text,text,timestamptz,text,text,integer,timestamptz,timestamptz'),
        ('acquire_work_unfenced',
          'text,text[],text[],integer,text'),
        ('approve_work_unfenced', 'text,integer,text,text'),
        ('start_work_unfenced', 'text,text,integer'),
        ('checkpoint_work_unfenced',
          'text,text,integer,text,text,text,text'),
        ('release_work_unfenced', 'text,text,integer,text'),
        ('complete_work_unfenced', 'text,text,text,integer,text,text'),
        ('submit_work',
          'text,text,text,text,text,integer,text[],text[],text,text,'
          'text,text,timestamptz,text,text,integer,timestamptz,timestamptz'),
        ('acquire_work', 'text,text[],text[],integer,text'),
        ('approve_work', 'text,integer,text,text'),
        ('start_work', 'text,text,integer'),
        ('checkpoint_work', 'text,text,integer,text,text,text,text'),
        ('release_work', 'text,text,integer,text'),
        ('complete_work', 'text,text,text,integer,text,text'),
        ('submit_work',
          'text,text,text,text,text,integer,text[],text[],text,text,'
          'text,text,timestamptz,text,text,integer,timestamptz,timestamptz,'
          'bigint'),
        ('acquire_work', 'text,text[],text[],integer,text,bigint'),
        ('approve_work', 'text,integer,text,text,bigint'),
        ('start_work', 'text,text,integer,bigint'),
        ('checkpoint_work',
          'text,text,integer,text,text,text,text,bigint'),
        ('release_work', 'text,text,integer,text,bigint'),
        ('complete_work', 'text,text,text,integer,text,text,bigint')
    ) AS functions(function_name, signature)
  LOOP
    EXECUTE format(
      'ALTER FUNCTION volpred_ops.%I(%s) OWNER TO volpred_ops_definer',
      function_name,
      signature
    );
  END LOOP;
END;
$$;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  volpred_ops.read_work_owner(),
  volpred_ops.assert_work_owner(text, bigint),
  volpred_ops.set_legacy_work_mutation_access(boolean),
  volpred_ops.transfer_work_owner(
    text, bigint, text, text, text, text, bigint
  )
FROM PUBLIC, volpred_ops_worker, volpred_ops_approver;

REVOKE ALL ON FUNCTION
  volpred_ops.submit_work_unfenced(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz
  ),
  volpred_ops.acquire_work_unfenced(
    text, text[], text[], integer, text
  ),
  volpred_ops.approve_work_unfenced(text, integer, text, text),
  volpred_ops.start_work_unfenced(text, text, integer),
  volpred_ops.checkpoint_work_unfenced(
    text, text, integer, text, text, text, text
  ),
  volpred_ops.release_work_unfenced(text, text, integer, text),
  volpred_ops.complete_work_unfenced(
    text, text, text, integer, text, text
  )
FROM PUBLIC, volpred_ops_worker, volpred_ops_approver;

REVOKE ALL ON FUNCTION
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz
  ),
  volpred_ops.acquire_work(text, text[], text[], integer, text),
  volpred_ops.approve_work(text, integer, text, text),
  volpred_ops.start_work(text, text, integer),
  volpred_ops.checkpoint_work(
    text, text, integer, text, text, text, text
  ),
  volpred_ops.release_work(text, text, integer, text),
  volpred_ops.complete_work(text, text, text, integer, text, text),
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz,
    bigint
  ),
  volpred_ops.acquire_work(
    text, text[], text[], integer, text, bigint
  ),
  volpred_ops.approve_work(text, integer, text, text, bigint),
  volpred_ops.start_work(text, text, integer, bigint),
  volpred_ops.checkpoint_work(
    text, text, integer, text, text, text, text, bigint
  ),
  volpred_ops.release_work(text, text, integer, text, bigint),
  volpred_ops.complete_work(
    text, text, text, integer, text, text, bigint
  )
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION volpred_ops.read_work_owner()
  TO volpred_ops_worker, volpred_ops_approver;

GRANT EXECUTE ON FUNCTION
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz
  ),
  volpred_ops.acquire_work(text, text[], text[], integer, text),
  volpred_ops.start_work(text, text, integer),
  volpred_ops.checkpoint_work(
    text, text, integer, text, text, text, text
  ),
  volpred_ops.release_work(text, text, integer, text),
  volpred_ops.complete_work(text, text, text, integer, text, text),
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz,
    bigint
  ),
  volpred_ops.acquire_work(
    text, text[], text[], integer, text, bigint
  ),
  volpred_ops.start_work(text, text, integer, bigint),
  volpred_ops.checkpoint_work(
    text, text, integer, text, text, text, text, bigint
  ),
  volpred_ops.release_work(text, text, integer, text, bigint),
  volpred_ops.complete_work(
    text, text, text, integer, text, text, bigint
  )
TO volpred_ops_worker;

GRANT EXECUTE ON FUNCTION
  volpred_ops.approve_work(text, integer, text, text),
  volpred_ops.approve_work(text, integer, text, text, bigint)
TO volpred_ops_approver;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
