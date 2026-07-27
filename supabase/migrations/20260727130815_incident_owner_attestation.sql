-- Read-only formal owner attestation for Incident Lifecycle.
--
-- This migration deliberately records the current pre-cutover truth:
-- legacy generation 1. It exposes no owner-transfer or incident-mutation
-- authority. A later Issue #13 cutover must add its own gated transition.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE IF NOT EXISTS volpred_ops.incident_owners (
  capability text PRIMARY KEY
    CHECK (capability = 'incident.lifecycle'),
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  contract_ref text NOT NULL
    CHECK (
      contract_ref = 'contract://issue-13/durable-incident-owner'
    ),
  changed_at timestamptz NOT NULL,
  changed_by text NOT NULL CHECK (changed_by = btrim(changed_by)),
  change_reason text NOT NULL CHECK (change_reason = btrim(change_reason))
);

CREATE TABLE IF NOT EXISTS volpred_ops.incident_owner_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capability text NOT NULL
    REFERENCES volpred_ops.incident_owners(capability)
    ON DELETE RESTRICT,
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  contract_ref text NOT NULL
    CHECK (
      contract_ref = 'contract://issue-13/durable-incident-owner'
    ),
  actor_ref text NOT NULL CHECK (actor_ref = btrim(actor_ref)),
  reason text NOT NULL CHECK (reason = btrim(reason)),
  changed_at timestamptz NOT NULL,
  UNIQUE (capability, generation)
);

GRANT SELECT ON volpred_ops.incident_owners
TO volpred_ops_definer;
GRANT SELECT ON volpred_ops.incident_owner_receipts
TO volpred_ops_definer;

DO $$
DECLARE
  event_at timestamptz;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM volpred_ops.incident_owners
    WHERE capability = 'incident.lifecycle'
  ) THEN
    event_at := clock_timestamp();
    INSERT INTO volpred_ops.incident_owners (
      capability,
      owner,
      generation,
      contract_ref,
      changed_at,
      changed_by,
      change_reason
    )
    VALUES (
      'incident.lifecycle',
      'legacy',
      1,
      'contract://issue-13/durable-incident-owner',
      event_at,
      'migration:incident_owner_attestation',
      'initial incident lifecycle owner remains legacy'
    );

    INSERT INTO volpred_ops.incident_owner_receipts (
      capability,
      owner,
      generation,
      contract_ref,
      actor_ref,
      reason,
      changed_at
    )
    VALUES (
      'incident.lifecycle',
      'legacy',
      1,
      'contract://issue-13/durable-incident-owner',
      'migration:incident_owner_attestation',
      'initial incident lifecycle owner remains legacy',
      event_at
    );
  END IF;
END;
$$;

DO $$
DECLARE
  matching_rows bigint;
BEGIN
  SELECT count(*)
  INTO matching_rows
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
    AND ownership.owner = 'legacy'
    AND ownership.generation = 1
    AND ownership.contract_ref =
      'contract://issue-13/durable-incident-owner';

  IF matching_rows <> 1
      OR (
        SELECT count(*)
        FROM volpred_ops.incident_owners
        WHERE capability = 'incident.lifecycle'
      ) <> 1 THEN
    RAISE EXCEPTION 'Incident owner attestation drifted';
  END IF;
END;
$$;

ALTER TABLE volpred_ops.incident_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.incident_owners FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.incident_owner_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.incident_owner_receipts
  FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS incident_owners_definer_read
ON volpred_ops.incident_owners;
CREATE POLICY incident_owners_definer_read
ON volpred_ops.incident_owners
FOR SELECT TO volpred_ops_definer USING (true);

DROP POLICY IF EXISTS incident_owner_receipts_definer_read
ON volpred_ops.incident_owner_receipts;
CREATE POLICY incident_owner_receipts_definer_read
ON volpred_ops.incident_owner_receipts
FOR SELECT TO volpred_ops_definer USING (true);

CREATE OR REPLACE FUNCTION public.volpred_read_incident_owner()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  owner_payload jsonb;
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
  )
  INTO STRICT owner_payload
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
    AND ownership.owner = 'legacy'
    AND ownership.generation = 1
    AND ownership.contract_ref =
      'contract://issue-13/durable-incident-owner'
    AND ownership.changed_at <= statement_timestamp();

  RETURN owner_payload;
END;
$$;

REVOKE ALL ON TABLE
  volpred_ops.incident_owners,
  volpred_ops.incident_owner_receipts
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.volpred_read_incident_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_incident_owner()
TO service_role;

COMMENT ON TABLE volpred_ops.incident_owners IS
  'Formal Incident Lifecycle owner; pre-cutover truth is legacy generation 1.';
COMMENT ON TABLE volpred_ops.incident_owner_receipts IS
  'Immutable evidence bound to the formal Incident Lifecycle owner row.';
COMMENT ON FUNCTION public.volpred_read_incident_owner() IS
  'Service-role-only read-only Incident Lifecycle owner attestation.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
