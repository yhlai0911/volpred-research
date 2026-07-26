-- Evidence-bound, one-shot gate for the Work Coordinator owner cutover.
--
-- A Python preflight produces canonical manifest bytes with a 15-minute
-- validity window.  The database verifies and durably stages those bytes
-- against the current owner generation.  Owner transfer and exact rollback
-- then consume the same gate row in their compare-and-set transaction.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

CREATE TABLE volpred_ops.work_cutover_gates (
  manifest_sha256 text PRIMARY KEY
    CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  canonical_payload bytea NOT NULL,
  source_owner text NOT NULL CHECK (source_owner = 'legacy'),
  source_generation bigint NOT NULL CHECK (source_generation > 0),
  status text NOT NULL
    CHECK (status IN ('ready', 'consumed', 'rolled_back')),
  prepared_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  staged_at timestamptz NOT NULL,
  staged_by text NOT NULL,
  consumed_at timestamptz,
  consumed_generation bigint CHECK (consumed_generation > 0),
  rolled_back_at timestamptz,
  CHECK (valid_until = prepared_at + interval '15 minutes'),
  CHECK (
    (status = 'ready'
      AND consumed_at IS NULL
      AND consumed_generation IS NULL
      AND rolled_back_at IS NULL)
    OR
    (status = 'consumed'
      AND consumed_at IS NOT NULL
      AND consumed_generation IS NOT NULL
      AND rolled_back_at IS NULL)
    OR
    (status = 'rolled_back'
      AND consumed_at IS NOT NULL
      AND consumed_generation IS NOT NULL
      AND rolled_back_at IS NOT NULL)
  )
);

CREATE TABLE volpred_ops.work_cutover_gate_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  manifest_sha256 text NOT NULL
    REFERENCES volpred_ops.work_cutover_gates(manifest_sha256)
    ON DELETE RESTRICT,
  event text NOT NULL CHECK (event IN ('staged', 'consumed', 'rolled_back')),
  owner_generation bigint CHECK (owner_generation > 0),
  actor_ref text NOT NULL,
  recorded_at timestamptz NOT NULL,
  UNIQUE (manifest_sha256, event)
);

CREATE VIEW volpred_ops.work_cutover_gate_reads AS
SELECT
  'work-cutover-gate.v1'::text AS schema_version,
  manifest_sha256,
  source_owner,
  source_generation,
  status,
  prepared_at,
  valid_until,
  staged_at,
  staged_by,
  consumed_at,
  consumed_generation,
  rolled_back_at
FROM volpred_ops.work_cutover_gates;

GRANT SELECT, INSERT, UPDATE ON volpred_ops.work_cutover_gates
  TO volpred_ops_definer;
GRANT SELECT, INSERT ON volpred_ops.work_cutover_gate_receipts
  TO volpred_ops_definer;
GRANT SELECT ON volpred_ops.work_cutover_gate_reads
  TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.work_cutover_gate_receipts_sequence_seq
  TO volpred_ops_definer;

ALTER TABLE volpred_ops.work_cutover_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_cutover_gates FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_cutover_gate_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_cutover_gate_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY work_cutover_gates_definer_select
  ON volpred_ops.work_cutover_gates
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_cutover_gates_definer_insert
  ON volpred_ops.work_cutover_gates
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
CREATE POLICY work_cutover_gates_definer_update
  ON volpred_ops.work_cutover_gates
  FOR UPDATE TO volpred_ops_definer
  USING (true) WITH CHECK (true);
CREATE POLICY work_cutover_gate_receipts_definer_select
  ON volpred_ops.work_cutover_gate_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_cutover_gate_receipts_definer_insert
  ON volpred_ops.work_cutover_gate_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE FUNCTION volpred_ops.read_work_cutover_gate(
  p_manifest_sha256 text
)
RETURNS SETOF volpred_ops.work_cutover_gate_reads
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
  SELECT *
  FROM volpred_ops.work_cutover_gate_reads
  WHERE manifest_sha256 = p_manifest_sha256;
$$;

CREATE FUNCTION volpred_ops.stage_work_cutover_manifest(
  p_manifest_sha256 text,
  p_canonical_payload bytea,
  p_expected_owner text,
  p_expected_generation bigint,
  p_actor_ref text
)
RETURNS SETOF volpred_ops.work_cutover_gate_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  manifest jsonb;
  ownership volpred_ops.work_owners;
  gate volpred_ops.work_cutover_gates;
  prepared timestamptz;
  expires timestamptz;
  event_at timestamptz := clock_timestamp();
  inserted_sha text;
BEGIN
  IF p_manifest_sha256 IS NULL
      OR p_manifest_sha256 !~ '^[0-9a-f]{64}$'
      OR p_canonical_payload IS NULL
      OR encode(sha256(p_canonical_payload), 'hex')
        <> p_manifest_sha256
      OR p_expected_owner <> 'legacy'
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = '' THEN
    RAISE EXCEPTION
      'work ownership cutover manifest fields are invalid';
  END IF;

  BEGIN
    manifest := convert_from(p_canonical_payload, 'UTF8')::jsonb;
  EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION
      'work ownership cutover manifest payload is invalid';
  END;

  IF jsonb_typeof(manifest) <> 'object'
      OR (
        SELECT count(*) FROM jsonb_object_keys(manifest)
      ) <> 11
      OR NOT manifest ?& ARRAY[
        'schema_version',
        'legacy_row_count',
        'coordinator_row_count',
        'queue_owner_state_sha256',
        'legacy_snapshot_sha256',
        'assessment_sha256',
        'import_report_sha256',
        'projection_schema_version',
        'projection_sha256',
        'prepared_at',
        'valid_until'
      ]
      OR jsonb_typeof(manifest->'schema_version') <> 'string'
      OR jsonb_typeof(manifest->'legacy_row_count') <> 'number'
      OR jsonb_typeof(manifest->'coordinator_row_count') <> 'number'
      OR jsonb_typeof(manifest->'queue_owner_state_sha256') <> 'string'
      OR jsonb_typeof(manifest->'legacy_snapshot_sha256') <> 'string'
      OR jsonb_typeof(manifest->'assessment_sha256') <> 'string'
      OR jsonb_typeof(manifest->'import_report_sha256') <> 'string'
      OR jsonb_typeof(manifest->'projection_schema_version') <> 'string'
      OR jsonb_typeof(manifest->'projection_sha256') <> 'string'
      OR jsonb_typeof(manifest->'prepared_at') <> 'string'
      OR jsonb_typeof(manifest->'valid_until') <> 'string'
      OR manifest->>'prepared_at'
        !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR manifest->>'valid_until'
        !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR manifest->>'schema_version'
        <> 'work-owner-cutover-manifest.v3'
      OR manifest->>'projection_schema_version'
        <> 'next-tasks-read-projection.v1'
      OR manifest->>'legacy_row_count' !~ '^(0|[1-9][0-9]*)$'
      OR manifest->>'coordinator_row_count' !~ '^(0|[1-9][0-9]*)$'
      OR manifest->>'legacy_row_count'
        <> manifest->>'coordinator_row_count'
      OR manifest->>'queue_owner_state_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'legacy_snapshot_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'assessment_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'import_report_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'projection_sha256'
        !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'work ownership cutover manifest contract is invalid';
  END IF;

  BEGIN
    prepared := (manifest->>'prepared_at')::timestamptz;
    expires := (manifest->>'valid_until')::timestamptz;
  EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION
      'work ownership cutover manifest freshness is invalid';
  END;
  IF expires <> prepared + interval '15 minutes'
      OR prepared > event_at + interval '1 minute' THEN
    RAISE EXCEPTION
      'work ownership cutover manifest is stale or future-dated';
  END IF;

  SELECT * INTO gate
  FROM volpred_ops.work_cutover_gates
  WHERE manifest_sha256 = p_manifest_sha256
  FOR UPDATE;
  IF gate.manifest_sha256 IS NOT NULL THEN
    IF gate.canonical_payload <> p_canonical_payload
        OR gate.source_owner <> p_expected_owner
        OR gate.source_generation <> p_expected_generation
        OR gate.staged_by <> btrim(p_actor_ref) THEN
      RAISE EXCEPTION
        'work ownership cutover manifest replay conflicts';
    END IF;
    RETURN QUERY
      SELECT * FROM volpred_ops.read_work_cutover_gate(
        p_manifest_sha256
      );
    RETURN;
  END IF;

  IF expires <= event_at THEN
    RAISE EXCEPTION
      'work ownership cutover manifest is stale or future-dated';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.work_owners
  WHERE capability = 'work.coordinate'
  FOR SHARE;
  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    RAISE EXCEPTION
      'work ownership cutover staging compare-and-set failed: '
      'expected %/% found %/%',
      p_expected_owner,
      p_expected_generation,
      ownership.owner,
      ownership.generation;
  END IF;
  event_at := clock_timestamp();
  IF expires <= event_at THEN
    RAISE EXCEPTION
      'work ownership cutover manifest is stale or future-dated';
  END IF;

  INSERT INTO volpred_ops.work_cutover_gates (
    manifest_sha256,
    canonical_payload,
    source_owner,
    source_generation,
    status,
    prepared_at,
    valid_until,
    staged_at,
    staged_by
  )
  VALUES (
    p_manifest_sha256,
    p_canonical_payload,
    p_expected_owner,
    p_expected_generation,
    'ready',
    prepared,
    expires,
    event_at,
    btrim(p_actor_ref)
  )
  ON CONFLICT (manifest_sha256) DO NOTHING
  RETURNING manifest_sha256 INTO inserted_sha;

  IF inserted_sha IS NULL THEN
    SELECT * INTO STRICT gate
    FROM volpred_ops.work_cutover_gates
    WHERE manifest_sha256 = p_manifest_sha256
    FOR UPDATE;
    IF gate.canonical_payload <> p_canonical_payload
        OR gate.source_owner <> p_expected_owner
        OR gate.source_generation <> p_expected_generation
        OR gate.staged_by <> btrim(p_actor_ref) THEN
      RAISE EXCEPTION
        'work ownership cutover manifest replay conflicts';
    END IF;
  ELSE
    INSERT INTO volpred_ops.work_cutover_gate_receipts (
      manifest_sha256,
      event,
      owner_generation,
      actor_ref,
      recorded_at
    )
    VALUES (
      p_manifest_sha256,
      'staged',
      p_expected_generation,
      btrim(p_actor_ref),
      event_at
    );
  END IF;

  RETURN QUERY
    SELECT * FROM volpred_ops.read_work_cutover_gate(
      p_manifest_sha256
    );
END;
$$;

CREATE FUNCTION volpred_ops.assert_work_cutover_gate_owner_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  gate volpred_ops.work_cutover_gates;
BEGIN
  IF OLD.owner = 'legacy' AND NEW.owner = 'operations_core' THEN
    SELECT * INTO gate
    FROM volpred_ops.work_cutover_gates
    WHERE manifest_sha256 = NEW.cutover_manifest_sha256;
    IF gate.manifest_sha256 IS NULL
        OR gate.status <> 'ready'
        OR gate.source_owner <> OLD.owner
        OR gate.source_generation <> OLD.generation
        OR NEW.generation <> OLD.generation + 1
        OR gate.valid_until <= clock_timestamp() THEN
      RAISE EXCEPTION
        'work ownership cutover gate does not authorize transfer';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER work_owner_cutover_gate_before_update
BEFORE UPDATE OF owner, generation, cutover_manifest_sha256
ON volpred_ops.work_owners
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.assert_work_cutover_gate_owner_update();

ALTER FUNCTION volpred_ops.transfer_work_owner(
  text, bigint, text, text, text, text, bigint
) RENAME TO transfer_work_owner_ungated;

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
  gate volpred_ops.work_cutover_gates;
  transferred volpred_ops.work_owner_reads;
  event_at timestamptz;
BEGIN
  SELECT * INTO gate
  FROM volpred_ops.work_cutover_gates
  WHERE manifest_sha256 = p_cutover_manifest_sha256
  FOR UPDATE;
  IF gate.manifest_sha256 IS NULL THEN
    RAISE EXCEPTION
      'work ownership cutover gate is not staged';
  END IF;

  IF p_target_owner = 'operations_core' THEN
    IF gate.source_owner <> p_expected_owner
        OR gate.source_generation <> p_expected_generation
        OR gate.status NOT IN ('ready', 'consumed')
        OR (
          gate.status = 'ready'
          AND gate.valid_until <= clock_timestamp()
        )
        OR (
          gate.status = 'consumed'
          AND gate.consumed_generation
            IS DISTINCT FROM p_expected_generation + 1
        ) THEN
      RAISE EXCEPTION
        'work ownership cutover gate does not authorize transfer';
    END IF;
  ELSIF p_target_owner = 'legacy' THEN
    IF gate.status NOT IN ('consumed', 'rolled_back')
        OR gate.consumed_generation
          IS DISTINCT FROM p_expected_generation
        OR p_rollback_of_generation
          IS DISTINCT FROM gate.consumed_generation THEN
      RAISE EXCEPTION
        'work ownership cutover gate does not authorize rollback';
    END IF;
  ELSE
    RAISE EXCEPTION
      'work ownership cutover gate target is invalid';
  END IF;

  SELECT * INTO STRICT transferred
  FROM volpred_ops.transfer_work_owner_ungated(
    p_expected_owner,
    p_expected_generation,
    p_target_owner,
    p_actor_ref,
    p_reason,
    p_cutover_manifest_sha256,
    p_rollback_of_generation
  );

  event_at := clock_timestamp();
  IF p_target_owner = 'operations_core'
      AND gate.status = 'ready'
      AND gate.valid_until <= event_at THEN
    RAISE EXCEPTION
      'work ownership cutover gate does not authorize transfer';
  END IF;
  IF p_target_owner = 'operations_core' AND gate.status = 'ready' THEN
    UPDATE volpred_ops.work_cutover_gates
    SET status = 'consumed',
        consumed_at = event_at,
        consumed_generation = transferred.generation
    WHERE manifest_sha256 = gate.manifest_sha256;
    INSERT INTO volpred_ops.work_cutover_gate_receipts (
      manifest_sha256,
      event,
      owner_generation,
      actor_ref,
      recorded_at
    )
    VALUES (
      gate.manifest_sha256,
      'consumed',
      transferred.generation,
      btrim(p_actor_ref),
      event_at
    );
  ELSIF p_target_owner = 'legacy' AND gate.status = 'consumed' THEN
    UPDATE volpred_ops.work_cutover_gates
    SET status = 'rolled_back',
        rolled_back_at = event_at
    WHERE manifest_sha256 = gate.manifest_sha256;
    INSERT INTO volpred_ops.work_cutover_gate_receipts (
      manifest_sha256,
      event,
      owner_generation,
      actor_ref,
      recorded_at
    )
    VALUES (
      gate.manifest_sha256,
      'rolled_back',
      transferred.generation,
      btrim(p_actor_ref),
      event_at
    );
  END IF;

  RETURN QUERY SELECT transferred.*;
END;
$$;

ALTER FUNCTION volpred_ops.read_work_cutover_gate(text)
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.work_cutover_gate_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.stage_work_cutover_manifest(
  text, bytea, text, bigint, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.assert_work_cutover_gate_owner_update()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_work_owner_ungated(
  text, bigint, text, text, text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_work_owner(
  text, bigint, text, text, text, text, bigint
) OWNER TO volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.work_cutover_gates,
  volpred_ops.work_cutover_gate_receipts,
  volpred_ops.work_cutover_gate_reads
FROM PUBLIC, volpred_ops_worker, volpred_ops_approver;

REVOKE ALL ON FUNCTION
  volpred_ops.read_work_cutover_gate(text),
  volpred_ops.stage_work_cutover_manifest(
    text, bytea, text, bigint, text
  ),
  volpred_ops.assert_work_cutover_gate_owner_update(),
  volpred_ops.transfer_work_owner_ungated(
    text, bigint, text, text, text, text, bigint
  ),
  volpred_ops.transfer_work_owner(
    text, bigint, text, text, text, text, bigint
  )
FROM PUBLIC, volpred_ops_worker, volpred_ops_approver;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
