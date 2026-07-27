-- Durable, read-only owner attestation for the formal incident lifecycle.
-- This migration records current reality (legacy owner); it intentionally
-- exposes no transfer or mutation RPC and does not bypass Issue #9/#13.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE IF NOT EXISTS volpred_ops.incident_owners (
  capability text PRIMARY KEY
    CHECK (capability = 'incident.lifecycle'),
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  contract_ref text NOT NULL
    CHECK (
      contract_ref =
        'contract://issue-13/durable-incident-owner'
    ),
  changed_at timestamptz NOT NULL,
  changed_by text NOT NULL CHECK (btrim(changed_by) <> ''),
  change_reason text NOT NULL CHECK (btrim(change_reason) <> '')
);

CREATE TABLE IF NOT EXISTS volpred_ops.incident_owner_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capability text NOT NULL
    CHECK (capability = 'incident.lifecycle'),
  owner text NOT NULL
    CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  contract_ref text NOT NULL
    CHECK (
      contract_ref =
        'contract://issue-13/durable-incident-owner'
    ),
  changed_at timestamptz NOT NULL,
  actor_ref text NOT NULL CHECK (btrim(actor_ref) <> ''),
  reason text NOT NULL CHECK (btrim(reason) <> ''),
  UNIQUE (capability, generation)
);

-- Supabase migration replay tests execute each migration twice. The table
-- owner may only seed the exact bootstrap row while FORCE is temporarily off;
-- FORCE is restored before the service-role RPC exists.
ALTER TABLE volpred_ops.incident_owners NO FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.incident_owner_receipts
  NO FORCE ROW LEVEL SECURITY;

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
  statement_timestamp(),
  'migration:incident_owner_attestation',
  'initial incident lifecycle owner remains legacy'
)
ON CONFLICT (capability) DO NOTHING;

INSERT INTO volpred_ops.incident_owner_receipts (
  capability,
  owner,
  generation,
  contract_ref,
  changed_at,
  actor_ref,
  reason
)
SELECT
  capability,
  owner,
  generation,
  contract_ref,
  changed_at,
  changed_by,
  change_reason
FROM volpred_ops.incident_owners
ON CONFLICT (capability, generation) DO NOTHING;

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
FOR SELECT
TO volpred_ops_definer
USING (true);

DROP POLICY IF EXISTS incident_owner_receipts_definer_read
ON volpred_ops.incident_owner_receipts;
CREATE POLICY incident_owner_receipts_definer_read
ON volpred_ops.incident_owner_receipts
FOR SELECT
TO volpred_ops_definer
USING (true);

REVOKE ALL ON TABLE
  volpred_ops.incident_owners,
  volpred_ops.incident_owner_receipts
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE
  volpred_ops.incident_owner_receipts_sequence_seq
FROM PUBLIC, anon, authenticated, service_role;

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
  SELECT
    to_jsonb(owner_row)
    || jsonb_build_object(
      'schema_version', 'incident-owner-attestation.v1',
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
  FROM volpred_ops.incident_owners AS owner_row
  JOIN volpred_ops.incident_owner_receipts AS receipt
    ON receipt.capability = owner_row.capability
   AND receipt.owner = owner_row.owner
   AND receipt.generation = owner_row.generation
   AND receipt.contract_ref = owner_row.contract_ref
   AND receipt.changed_at = owner_row.changed_at
   AND receipt.actor_ref = owner_row.changed_by
   AND receipt.reason = owner_row.change_reason
  WHERE owner_row.changed_at <= statement_timestamp();
  RETURN owner_payload;
END;
$$;

REVOKE ALL ON FUNCTION public.volpred_read_incident_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_incident_owner()
TO service_role;

COMMENT ON FUNCTION public.volpred_read_incident_owner() IS
  'Service-role-only typed live incident-lifecycle owner attestation; cannot transfer ownership.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
