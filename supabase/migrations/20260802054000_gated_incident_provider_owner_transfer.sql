-- Evidence-gated formal owner transfer for Incident Lifecycle and Provider
-- Execution.  This migration installs the actuator only: both production
-- owners remain legacy until their exact acceptance manifests are staged
-- after the Work Coordinator cutover gate has been consumed.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

ALTER TABLE volpred_ops.incident_owner_receipts
  ADD COLUMN IF NOT EXISTS previous_owner text,
  ADD COLUMN IF NOT EXISTS rollback_of_generation bigint;
ALTER TABLE volpred_ops.provider_owner_receipts
  ADD COLUMN IF NOT EXISTS previous_owner text,
  ADD COLUMN IF NOT EXISTS rollback_of_generation bigint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'incident_owner_receipts_transfer_shape'
      AND conrelid = 'volpred_ops.incident_owner_receipts'::regclass
  ) THEN
    ALTER TABLE volpred_ops.incident_owner_receipts
      ADD CONSTRAINT incident_owner_receipts_transfer_shape CHECK (
        (
          generation = 1
          AND owner = 'legacy'
          AND previous_owner IS NULL
          AND rollback_of_generation IS NULL
        )
        OR (
          generation > 1
          AND previous_owner IN ('legacy', 'operations_core')
          AND previous_owner <> owner
          AND (
            (owner = 'operations_core' AND rollback_of_generation IS NULL)
            OR
            (owner = 'legacy'
              AND rollback_of_generation = generation - 1)
          )
        )
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'provider_owner_receipts_transfer_shape'
      AND conrelid = 'volpred_ops.provider_owner_receipts'::regclass
  ) THEN
    ALTER TABLE volpred_ops.provider_owner_receipts
      ADD CONSTRAINT provider_owner_receipts_transfer_shape CHECK (
        (
          generation = 1
          AND owner = 'legacy'
          AND previous_owner IS NULL
          AND rollback_of_generation IS NULL
        )
        OR (
          generation > 1
          AND previous_owner IN ('legacy', 'operations_core')
          AND previous_owner <> owner
          AND (
            (owner = 'operations_core' AND rollback_of_generation IS NULL)
            OR
            (owner = 'legacy'
              AND rollback_of_generation = generation - 1)
          )
        )
      );
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.formal_owner_cutover_gates (
  manifest_sha256 text PRIMARY KEY
    CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  canonical_payload bytea NOT NULL,
  capability text NOT NULL
    CHECK (capability IN ('incident.lifecycle', 'provider.execution')),
  contract_ref text NOT NULL,
  source_owner text NOT NULL CHECK (source_owner = 'legacy'),
  source_generation bigint NOT NULL CHECK (source_generation > 0),
  target_owner text NOT NULL CHECK (target_owner = 'operations_core'),
  parent_work_owner_generation bigint NOT NULL CHECK (
    parent_work_owner_generation > 0
  ),
  status text NOT NULL
    CHECK (status IN ('ready', 'consumed', 'rolled_back')),
  prepared_at timestamptz NOT NULL,
  valid_until timestamptz NOT NULL,
  staged_at timestamptz NOT NULL,
  staged_by text NOT NULL CHECK (
    staged_by = btrim(staged_by) AND staged_by <> ''
  ),
  consumed_at timestamptz,
  consumed_generation bigint CHECK (consumed_generation > 0),
  rolled_back_at timestamptz,
  rolled_back_generation bigint CHECK (rolled_back_generation > 0),
  UNIQUE (capability, source_generation),
  CHECK (valid_until = prepared_at + interval '15 minutes'),
  CHECK (
    (capability = 'incident.lifecycle'
      AND contract_ref =
        'contract://issue-13/durable-incident-owner')
    OR
    (capability = 'provider.execution'
      AND contract_ref =
        'contract://issue-12/zero-paid-provider-registry')
  ),
  CHECK (
    (status = 'ready'
      AND consumed_at IS NULL
      AND consumed_generation IS NULL
      AND rolled_back_at IS NULL
      AND rolled_back_generation IS NULL)
    OR
    (status = 'consumed'
      AND consumed_at IS NOT NULL
      AND consumed_generation IS NOT NULL
      AND rolled_back_at IS NULL
      AND rolled_back_generation IS NULL)
    OR
    (status = 'rolled_back'
      AND consumed_at IS NOT NULL
      AND consumed_generation IS NOT NULL
      AND rolled_back_at IS NOT NULL
      AND rolled_back_generation IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS
volpred_ops.formal_owner_cutover_gate_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  manifest_sha256 text NOT NULL
    REFERENCES volpred_ops.formal_owner_cutover_gates(manifest_sha256)
    ON DELETE RESTRICT,
  event text NOT NULL CHECK (
    event IN ('staged', 'consumed', 'rolled_back')
  ),
  owner_generation bigint CHECK (owner_generation > 0),
  actor_ref text NOT NULL CHECK (
    actor_ref = btrim(actor_ref) AND actor_ref <> ''
  ),
  recorded_at timestamptz NOT NULL,
  UNIQUE (manifest_sha256, event)
);

GRANT SELECT, INSERT, UPDATE
ON volpred_ops.formal_owner_cutover_gates TO volpred_ops_definer;
GRANT SELECT, INSERT
ON volpred_ops.formal_owner_cutover_gate_receipts TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.formal_owner_cutover_gate_receipts_sequence_seq
TO volpred_ops_definer;
GRANT SELECT, UPDATE ON volpred_ops.incident_owners
TO volpred_ops_definer;
GRANT SELECT, INSERT ON volpred_ops.incident_owner_receipts
TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.incident_owner_receipts_sequence_seq
TO volpred_ops_definer;
GRANT SELECT, UPDATE ON volpred_ops.provider_owners
TO volpred_ops_definer;
GRANT SELECT, INSERT ON volpred_ops.provider_owner_receipts
TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.provider_owner_receipts_sequence_seq
TO volpred_ops_definer;

ALTER TABLE volpred_ops.formal_owner_cutover_gates
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.formal_owner_cutover_gates
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.formal_owner_cutover_gate_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.formal_owner_cutover_gate_receipts
  FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS incident_owners_definer_update
ON volpred_ops.incident_owners;
CREATE POLICY incident_owners_definer_update
ON volpred_ops.incident_owners
FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS incident_owner_receipts_definer_insert
ON volpred_ops.incident_owner_receipts;
CREATE POLICY incident_owner_receipts_definer_insert
ON volpred_ops.incident_owner_receipts
FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS provider_owners_definer_update
ON volpred_ops.provider_owners;
CREATE POLICY provider_owners_definer_update
ON volpred_ops.provider_owners
FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS provider_owner_receipts_definer_insert
ON volpred_ops.provider_owner_receipts;
CREATE POLICY provider_owner_receipts_definer_insert
ON volpred_ops.provider_owner_receipts
FOR INSERT TO volpred_ops_definer WITH CHECK (true);

DROP POLICY IF EXISTS formal_owner_cutover_gates_definer_all
ON volpred_ops.formal_owner_cutover_gates;
CREATE POLICY formal_owner_cutover_gates_definer_all
ON volpred_ops.formal_owner_cutover_gates
FOR ALL TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS formal_owner_cutover_receipts_definer_all
ON volpred_ops.formal_owner_cutover_gate_receipts;
CREATE POLICY formal_owner_cutover_receipts_definer_all
ON volpred_ops.formal_owner_cutover_gate_receipts
FOR ALL TO volpred_ops_definer USING (true) WITH CHECK (true);

CREATE OR REPLACE VIEW volpred_ops.formal_owner_cutover_gate_reads AS
SELECT
  'formal-owner-cutover-gate.v1'::text AS schema_version,
  manifest_sha256,
  capability,
  source_owner,
  source_generation,
  target_owner,
  parent_work_owner_generation,
  status,
  prepared_at,
  valid_until,
  staged_at,
  staged_by,
  consumed_at,
  consumed_generation,
  rolled_back_at,
  rolled_back_generation
FROM volpred_ops.formal_owner_cutover_gates;

GRANT SELECT ON volpred_ops.formal_owner_cutover_gate_reads
TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION volpred_ops.read_formal_owner_cutover_gate(
  p_manifest_sha256 text
)
RETURNS SETOF volpred_ops.formal_owner_cutover_gate_reads
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
  SELECT *
  FROM volpred_ops.formal_owner_cutover_gate_reads
  WHERE manifest_sha256 = p_manifest_sha256;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.stage_formal_owner_cutover(
  p_manifest_sha256 text,
  p_canonical_payload bytea,
  p_actor_ref text
)
RETURNS SETOF volpred_ops.formal_owner_cutover_gate_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  manifest jsonb;
  capability_value text;
  contract_value text;
  source_generation_value bigint;
  parent_generation_value bigint;
  prepared_value timestamptz;
  valid_until_value timestamptz;
  event_at timestamptz := clock_timestamp();
  gate volpred_ops.formal_owner_cutover_gates;
  work_owner volpred_ops.work_owners;
  formal_owner record;
  inserted_sha text;
BEGIN
  IF p_manifest_sha256 IS NULL
      OR p_manifest_sha256 !~ '^[0-9a-f]{64}$'
      OR p_canonical_payload IS NULL
      OR encode(sha256(p_canonical_payload), 'hex')
        <> p_manifest_sha256
      OR p_actor_ref IS NULL
      OR btrim(p_actor_ref) = '' THEN
    RAISE EXCEPTION 'formal owner cutover manifest fields are invalid';
  END IF;

  BEGIN
    manifest := convert_from(p_canonical_payload, 'UTF8')::jsonb;
  EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'formal owner cutover manifest payload is invalid';
  END;
  IF jsonb_typeof(manifest) <> 'object'
      OR (SELECT count(*) FROM jsonb_object_keys(manifest)) <> 12
      OR NOT manifest ?& ARRAY[
        'schema_version', 'capability', 'contract_ref',
        'source_owner', 'source_generation', 'target_owner',
        'parent_work_owner_generation',
        'acceptance_receipt_sha256', 'regression_receipt_sha256',
        'live_preflight_receipt_sha256', 'prepared_at', 'valid_until'
      ]
      OR manifest->>'schema_version'
        <> 'formal-owner-cutover-manifest.v1'
      OR manifest->>'source_owner' <> 'legacy'
      OR manifest->>'target_owner' <> 'operations_core'
      OR manifest->>'source_generation' !~ '^[1-9][0-9]*$'
      OR manifest->>'parent_work_owner_generation'
        !~ '^[1-9][0-9]*$'
      OR manifest->>'acceptance_receipt_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'regression_receipt_sha256'
        !~ '^[0-9a-f]{64}$'
      OR manifest->>'live_preflight_receipt_sha256'
        !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'formal owner cutover manifest contract is invalid';
  END IF;

  capability_value := manifest->>'capability';
  contract_value := manifest->>'contract_ref';
  IF NOT (
    (capability_value = 'incident.lifecycle'
      AND contract_value =
        'contract://issue-13/durable-incident-owner')
    OR
    (capability_value = 'provider.execution'
      AND contract_value =
        'contract://issue-12/zero-paid-provider-registry')
  ) THEN
    RAISE EXCEPTION 'formal owner cutover capability is invalid';
  END IF;
  BEGIN
    source_generation_value :=
      (manifest->>'source_generation')::bigint;
    parent_generation_value :=
      (manifest->>'parent_work_owner_generation')::bigint;
    prepared_value := (manifest->>'prepared_at')::timestamptz;
    valid_until_value := (manifest->>'valid_until')::timestamptz;
  EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'formal owner cutover manifest values are invalid';
  END;
  IF valid_until_value <> prepared_value + interval '15 minutes'
      OR prepared_value > event_at + interval '1 minute'
      OR valid_until_value <= event_at THEN
    RAISE EXCEPTION 'formal owner cutover manifest is stale or future-dated';
  END IF;

  SELECT * INTO work_owner
  FROM volpred_ops.work_owners
  WHERE capability = 'work.coordinate'
  FOR SHARE;
  IF work_owner.capability IS NULL
      OR work_owner.owner <> 'operations_core'
      OR work_owner.generation <> parent_generation_value
      OR work_owner.cutover_manifest_sha256 IS NULL
      OR NOT EXISTS (
        SELECT 1 FROM volpred_ops.work_cutover_gates AS work_gate
        WHERE work_gate.manifest_sha256 =
              work_owner.cutover_manifest_sha256
          AND work_gate.status = 'consumed'
          AND work_gate.consumed_generation = work_owner.generation
      ) THEN
    RAISE EXCEPTION
      'formal owner cutover work owner is not operations_core '
      'under a consumed gate';
  END IF;

  SELECT * INTO gate
  FROM volpred_ops.formal_owner_cutover_gates
  WHERE manifest_sha256 = p_manifest_sha256
  FOR UPDATE;
  IF gate.manifest_sha256 IS NOT NULL THEN
    IF gate.canonical_payload <> p_canonical_payload
        OR gate.capability <> capability_value
        OR gate.source_generation <> source_generation_value
        OR gate.parent_work_owner_generation <> parent_generation_value
        OR gate.staged_by <> btrim(p_actor_ref) THEN
      RAISE EXCEPTION 'formal owner cutover manifest replay conflicts';
    END IF;
    RETURN QUERY
      SELECT * FROM volpred_ops.read_formal_owner_cutover_gate(
        p_manifest_sha256
      );
    RETURN;
  END IF;

  IF capability_value = 'incident.lifecycle' THEN
    SELECT owner, generation, contract_ref INTO STRICT formal_owner
    FROM volpred_ops.incident_owners
    WHERE incident_owners.capability = 'incident.lifecycle'
    FOR SHARE;
  ELSE
    SELECT owner, generation, contract_ref INTO STRICT formal_owner
    FROM volpred_ops.provider_owners
    WHERE provider_owners.capability = 'provider.execution'
    FOR SHARE;
  END IF;
  IF formal_owner.owner <> 'legacy'
      OR formal_owner.generation <> source_generation_value
      OR formal_owner.contract_ref <> contract_value THEN
    RAISE EXCEPTION
      'formal owner cutover staging compare-and-set failed';
  END IF;

  INSERT INTO volpred_ops.formal_owner_cutover_gates (
    manifest_sha256, canonical_payload, capability, contract_ref,
    source_owner, source_generation, target_owner,
    parent_work_owner_generation, status, prepared_at, valid_until,
    staged_at, staged_by
  ) VALUES (
    p_manifest_sha256, p_canonical_payload, capability_value,
    contract_value, 'legacy', source_generation_value,
    'operations_core', parent_generation_value, 'ready', prepared_value,
    valid_until_value, event_at, btrim(p_actor_ref)
  )
  ON CONFLICT DO NOTHING
  RETURNING manifest_sha256 INTO inserted_sha;

  IF inserted_sha IS NULL THEN
    RAISE EXCEPTION 'formal owner cutover manifest raced another stage';
  END IF;
  INSERT INTO volpred_ops.formal_owner_cutover_gate_receipts (
    manifest_sha256, event, owner_generation, actor_ref, recorded_at
  ) VALUES (
    p_manifest_sha256, 'staged', source_generation_value,
    btrim(p_actor_ref), event_at
  );
  RETURN QUERY
    SELECT * FROM volpred_ops.read_formal_owner_cutover_gate(
      p_manifest_sha256
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_incident_owner()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE owner_payload jsonb;
BEGIN
  SELECT jsonb_build_object(
    'schema_version', 'incident-owner-attestation.v1',
    'capability', ownership.capability,
    'owner', ownership.owner,
    'generation', ownership.generation,
    'contract_ref', ownership.contract_ref,
    'changed_at', ownership.changed_at,
    'changed_by', ownership.changed_by,
    'change_reason', ownership.change_reason,
    'receipt_sequence', receipt.sequence,
    'receipt_capability', receipt.capability,
    'receipt_owner', receipt.owner,
    'receipt_generation', receipt.generation,
    'receipt_contract_ref', receipt.contract_ref,
    'receipt_changed_at', receipt.changed_at,
    'receipt_actor_ref', receipt.actor_ref,
    'receipt_reason', receipt.reason,
    'attested_at', statement_timestamp()
  ) INTO STRICT owner_payload
  FROM volpred_ops.incident_owners AS ownership
  JOIN volpred_ops.incident_owner_receipts AS receipt
    ON receipt.capability = ownership.capability
   AND receipt.owner = ownership.owner
   AND receipt.generation = ownership.generation
   AND receipt.contract_ref = ownership.contract_ref
   AND receipt.changed_at = ownership.changed_at
   AND receipt.actor_ref = ownership.changed_by
   AND receipt.reason = ownership.change_reason
  WHERE ownership.capability = 'incident.lifecycle'
    AND ownership.contract_ref =
      'contract://issue-13/durable-incident-owner'
    AND ownership.changed_at <= statement_timestamp()
    AND (SELECT count(*) FROM volpred_ops.incident_owner_receipts) =
        ownership.generation
    AND (SELECT min(generation)
         FROM volpred_ops.incident_owner_receipts) = 1
    AND (SELECT max(generation)
         FROM volpred_ops.incident_owner_receipts) = ownership.generation;
  RETURN owner_payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_provider_owner()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE owner_payload jsonb;
BEGIN
  SELECT jsonb_build_object(
    'schema_version', 'provider-owner-attestation.v1',
    'capability', ownership.capability,
    'owner', ownership.owner,
    'generation', ownership.generation,
    'contract_ref', ownership.contract_ref,
    'changed_at', ownership.changed_at,
    'changed_by', ownership.changed_by,
    'change_reason', ownership.change_reason,
    'receipt_sequence', receipt.sequence,
    'receipt_capability', receipt.capability,
    'receipt_owner', receipt.owner,
    'receipt_generation', receipt.generation,
    'receipt_contract_ref', receipt.contract_ref,
    'receipt_changed_at', receipt.changed_at,
    'receipt_actor_ref', receipt.actor_ref,
    'receipt_reason', receipt.reason,
    'attested_at', statement_timestamp()
  ) INTO STRICT owner_payload
  FROM volpred_ops.provider_owners AS ownership
  JOIN volpred_ops.provider_owner_receipts AS receipt
    ON receipt.capability = ownership.capability
   AND receipt.owner = ownership.owner
   AND receipt.generation = ownership.generation
   AND receipt.contract_ref = ownership.contract_ref
   AND receipt.changed_at = ownership.changed_at
   AND receipt.actor_ref = ownership.changed_by
   AND receipt.reason = ownership.change_reason
  WHERE ownership.capability = 'provider.execution'
    AND ownership.contract_ref =
      'contract://issue-12/zero-paid-provider-registry'
    AND ownership.changed_at <= statement_timestamp()
    AND (SELECT count(*) FROM volpred_ops.provider_owner_receipts) =
        ownership.generation
    AND (SELECT min(generation)
         FROM volpred_ops.provider_owner_receipts) = 1
    AND (SELECT max(generation)
         FROM volpred_ops.provider_owner_receipts) = ownership.generation;
  RETURN owner_payload;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.read_formal_owner_after_mutation(
  p_capability text
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE owner_payload jsonb;
BEGIN
  IF p_capability = 'incident.lifecycle' THEN
    SELECT jsonb_build_object(
      'schema_version', 'incident-owner-attestation.v1',
      'capability', ownership.capability,
      'owner', ownership.owner,
      'generation', ownership.generation,
      'contract_ref', ownership.contract_ref,
      'changed_at', ownership.changed_at,
      'changed_by', ownership.changed_by,
      'change_reason', ownership.change_reason,
      'receipt_sequence', receipt.sequence,
      'receipt_capability', receipt.capability,
      'receipt_owner', receipt.owner,
      'receipt_generation', receipt.generation,
      'receipt_contract_ref', receipt.contract_ref,
      'receipt_changed_at', receipt.changed_at,
      'receipt_actor_ref', receipt.actor_ref,
      'receipt_reason', receipt.reason,
      'attested_at', clock_timestamp()
    ) INTO STRICT owner_payload
    FROM volpred_ops.incident_owners AS ownership
    JOIN volpred_ops.incident_owner_receipts AS receipt
      ON receipt.capability = ownership.capability
     AND receipt.owner = ownership.owner
     AND receipt.generation = ownership.generation
     AND receipt.contract_ref = ownership.contract_ref
     AND receipt.changed_at = ownership.changed_at
     AND receipt.actor_ref = ownership.changed_by
     AND receipt.reason = ownership.change_reason
    WHERE ownership.capability = 'incident.lifecycle'
      AND ownership.changed_at <= clock_timestamp();
  ELSIF p_capability = 'provider.execution' THEN
    SELECT jsonb_build_object(
      'schema_version', 'provider-owner-attestation.v1',
      'capability', ownership.capability,
      'owner', ownership.owner,
      'generation', ownership.generation,
      'contract_ref', ownership.contract_ref,
      'changed_at', ownership.changed_at,
      'changed_by', ownership.changed_by,
      'change_reason', ownership.change_reason,
      'receipt_sequence', receipt.sequence,
      'receipt_capability', receipt.capability,
      'receipt_owner', receipt.owner,
      'receipt_generation', receipt.generation,
      'receipt_contract_ref', receipt.contract_ref,
      'receipt_changed_at', receipt.changed_at,
      'receipt_actor_ref', receipt.actor_ref,
      'receipt_reason', receipt.reason,
      'attested_at', clock_timestamp()
    ) INTO STRICT owner_payload
    FROM volpred_ops.provider_owners AS ownership
    JOIN volpred_ops.provider_owner_receipts AS receipt
      ON receipt.capability = ownership.capability
     AND receipt.owner = ownership.owner
     AND receipt.generation = ownership.generation
     AND receipt.contract_ref = ownership.contract_ref
     AND receipt.changed_at = ownership.changed_at
     AND receipt.actor_ref = ownership.changed_by
     AND receipt.reason = ownership.change_reason
    WHERE ownership.capability = 'provider.execution'
      AND ownership.changed_at <= clock_timestamp();
  ELSE
    RAISE EXCEPTION 'formal owner capability is invalid';
  END IF;
  RETURN owner_payload;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.transfer_formal_owner(
  p_capability text,
  p_expected_owner text,
  p_expected_generation bigint,
  p_target_owner text,
  p_actor_ref text,
  p_reason text,
  p_manifest_sha256 text,
  p_rollback_of_generation bigint DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  gate volpred_ops.formal_owner_cutover_gates;
  owner_row record;
  replay record;
  work_owner volpred_ops.work_owners;
  event_at timestamptz;
  new_generation bigint;
BEGIN
  IF p_capability NOT IN ('incident.lifecycle', 'provider.execution')
      OR p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL OR p_expected_generation <= 0
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL OR btrim(p_reason) = ''
      OR p_manifest_sha256 IS NULL
      OR p_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'formal owner transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation IS DISTINCT FROM
          p_expected_generation THEN
    RAISE EXCEPTION
      'formal owner rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'formal owner cutover cannot carry rollback generation';
  END IF;

  -- Keep the lock order identical to staging: parent work owner, gate,
  -- capability owner.  A retry racing the original transfer must not form
  -- a work-row/gate-row lock cycle.
  SELECT * INTO work_owner
  FROM volpred_ops.work_owners
  WHERE capability = 'work.coordinate'
  FOR SHARE;

  SELECT * INTO gate
  FROM volpred_ops.formal_owner_cutover_gates
  WHERE manifest_sha256 = p_manifest_sha256
  FOR UPDATE;
  IF gate.manifest_sha256 IS NULL
      OR gate.capability <> p_capability THEN
    RAISE EXCEPTION 'formal owner cutover gate is not staged';
  END IF;

  IF p_capability = 'incident.lifecycle' THEN
    SELECT * INTO STRICT owner_row
    FROM volpred_ops.incident_owners
    WHERE incident_owners.capability = 'incident.lifecycle'
    FOR UPDATE;
  ELSE
    SELECT * INTO STRICT owner_row
    FROM volpred_ops.provider_owners
    WHERE provider_owners.capability = 'provider.execution'
    FOR UPDATE;
  END IF;

  IF owner_row.owner <> p_expected_owner
      OR owner_row.generation <> p_expected_generation THEN
    IF p_capability = 'incident.lifecycle' THEN
      SELECT * INTO replay
      FROM volpred_ops.incident_owner_receipts
      WHERE incident_owner_receipts.capability = 'incident.lifecycle'
        AND generation = p_expected_generation + 1;
    ELSE
      SELECT * INTO replay
      FROM volpred_ops.provider_owner_receipts
      WHERE provider_owner_receipts.capability = 'provider.execution'
        AND generation = p_expected_generation + 1;
    END IF;
    IF replay.capability IS NULL
        OR owner_row.generation <> replay.generation
        OR owner_row.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'formal owner compare-and-set failed: expected %/% found %/%',
        p_expected_owner, p_expected_generation,
        owner_row.owner, owner_row.generation;
    END IF;
    IF p_capability = 'incident.lifecycle' THEN
      RETURN public.volpred_read_incident_owner();
    END IF;
    RETURN public.volpred_read_provider_owner();
  END IF;

  IF p_target_owner = 'operations_core' THEN
    IF gate.source_owner <> p_expected_owner
        OR gate.source_generation <> p_expected_generation
        OR gate.status NOT IN ('ready', 'consumed')
        OR (gate.status = 'ready'
            AND gate.valid_until <= clock_timestamp())
        OR (gate.status = 'consumed'
            AND gate.consumed_generation
              IS DISTINCT FROM p_expected_generation + 1)
        OR work_owner.owner <> 'operations_core'
        OR work_owner.generation <>
            gate.parent_work_owner_generation
        OR NOT EXISTS (
          SELECT 1 FROM volpred_ops.work_cutover_gates AS work_gate
          WHERE work_gate.manifest_sha256 =
                work_owner.cutover_manifest_sha256
            AND work_gate.status = 'consumed'
            AND work_gate.consumed_generation = work_owner.generation
        ) THEN
      RAISE EXCEPTION
        'formal owner cutover gate does not authorize transfer';
    END IF;
  ELSE
    IF gate.status NOT IN ('consumed', 'rolled_back')
        OR gate.consumed_generation
          IS DISTINCT FROM p_expected_generation
        OR p_rollback_of_generation
          IS DISTINCT FROM gate.consumed_generation THEN
      RAISE EXCEPTION
        'formal owner cutover gate does not authorize rollback';
    END IF;
  END IF;

  event_at := clock_timestamp();
  new_generation := p_expected_generation + 1;
  IF p_capability = 'incident.lifecycle' THEN
    UPDATE volpred_ops.incident_owners
    SET owner = p_target_owner,
        generation = new_generation,
        changed_at = event_at,
        changed_by = btrim(p_actor_ref),
        change_reason = btrim(p_reason)
    WHERE incident_owners.capability = 'incident.lifecycle';
    INSERT INTO volpred_ops.incident_owner_receipts (
      capability, owner, generation, contract_ref, actor_ref, reason,
      changed_at, previous_owner, rollback_of_generation
    ) VALUES (
      p_capability, p_target_owner, new_generation,
      owner_row.contract_ref, btrim(p_actor_ref), btrim(p_reason),
      event_at, p_expected_owner, p_rollback_of_generation
    );
  ELSE
    UPDATE volpred_ops.provider_owners
    SET owner = p_target_owner,
        generation = new_generation,
        changed_at = event_at,
        changed_by = btrim(p_actor_ref),
        change_reason = btrim(p_reason)
    WHERE provider_owners.capability = 'provider.execution';
    INSERT INTO volpred_ops.provider_owner_receipts (
      capability, owner, generation, contract_ref, actor_ref, reason,
      changed_at, previous_owner, rollback_of_generation
    ) VALUES (
      p_capability, p_target_owner, new_generation,
      owner_row.contract_ref, btrim(p_actor_ref), btrim(p_reason),
      event_at, p_expected_owner, p_rollback_of_generation
    );
  END IF;

  IF p_target_owner = 'operations_core' AND gate.status = 'ready' THEN
    UPDATE volpred_ops.formal_owner_cutover_gates
    SET status = 'consumed', consumed_at = event_at,
        consumed_generation = new_generation
    WHERE manifest_sha256 = p_manifest_sha256;
    INSERT INTO volpred_ops.formal_owner_cutover_gate_receipts (
      manifest_sha256, event, owner_generation, actor_ref, recorded_at
    ) VALUES (
      p_manifest_sha256, 'consumed', new_generation,
      btrim(p_actor_ref), event_at
    );
  ELSIF p_target_owner = 'legacy' AND gate.status = 'consumed' THEN
    UPDATE volpred_ops.formal_owner_cutover_gates
    SET status = 'rolled_back', rolled_back_at = event_at,
        rolled_back_generation = new_generation
    WHERE manifest_sha256 = p_manifest_sha256;
    INSERT INTO volpred_ops.formal_owner_cutover_gate_receipts (
      manifest_sha256, event, owner_generation, actor_ref, recorded_at
    ) VALUES (
      p_manifest_sha256, 'rolled_back', new_generation,
      btrim(p_actor_ref), event_at
    );
  END IF;

  IF p_capability = 'incident.lifecycle' AND NOT EXISTS (
    SELECT 1
    FROM volpred_ops.incident_owners AS ownership
    JOIN volpred_ops.incident_owner_receipts AS receipt
      ON receipt.capability = ownership.capability
     AND receipt.owner = ownership.owner
     AND receipt.generation = ownership.generation
     AND receipt.contract_ref = ownership.contract_ref
     AND receipt.changed_at = ownership.changed_at
     AND receipt.actor_ref = ownership.changed_by
     AND receipt.reason = ownership.change_reason
    WHERE ownership.capability = 'incident.lifecycle'
  ) THEN
    RAISE EXCEPTION
      'formal owner post-transfer incident attestation is unbound';
  ELSIF p_capability = 'provider.execution' AND NOT EXISTS (
    SELECT 1
    FROM volpred_ops.provider_owners AS ownership
    JOIN volpred_ops.provider_owner_receipts AS receipt
      ON receipt.capability = ownership.capability
     AND receipt.owner = ownership.owner
     AND receipt.generation = ownership.generation
     AND receipt.contract_ref = ownership.contract_ref
     AND receipt.changed_at = ownership.changed_at
     AND receipt.actor_ref = ownership.changed_by
     AND receipt.reason = ownership.change_reason
    WHERE ownership.capability = 'provider.execution'
  ) THEN
    RAISE EXCEPTION
      'formal owner post-transfer provider attestation is unbound';
  END IF;

  RETURN volpred_ops.read_formal_owner_after_mutation(p_capability);
END;
$$;

ALTER VIEW volpred_ops.formal_owner_cutover_gate_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.read_formal_owner_cutover_gate(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.stage_formal_owner_cutover(text, bytea, text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.read_formal_owner_after_mutation(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_formal_owner(
  text, text, bigint, text, text, text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_incident_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_provider_owner()
  OWNER TO volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.formal_owner_cutover_gates,
  volpred_ops.formal_owner_cutover_gate_receipts
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE
  volpred_ops.formal_owner_cutover_gate_receipts_sequence_seq
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  volpred_ops.read_formal_owner_cutover_gate(text),
  volpred_ops.stage_formal_owner_cutover(text, bytea, text),
  volpred_ops.read_formal_owner_after_mutation(text),
  volpred_ops.transfer_formal_owner(
    text, text, bigint, text, text, text, text, bigint
  )
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  public.volpred_read_incident_owner(),
  public.volpred_read_provider_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
  public.volpred_read_incident_owner(),
  public.volpred_read_provider_owner()
TO service_role;

COMMENT ON FUNCTION volpred_ops.stage_formal_owner_cutover(
  text, bytea, text
) IS
  'Privileged evidence stage; requires consumed Work Coordinator cutover.';
COMMENT ON FUNCTION volpred_ops.transfer_formal_owner(
  text, text, bigint, text, text, text, text, bigint
) IS
  'Privileged CAS transfer/rollback for incident and provider formal owners.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
