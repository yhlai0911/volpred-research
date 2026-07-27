-- Forward-only hardening for the canonical 20260727130815 read-only
-- attestation. Clean replay and production must both expose only the exact
-- legacy generation-1 owner until Issue #13 adds a separately gated transfer
-- contract. The rejected concurrent 20260727131500 migration is not part of
-- the canonical chain and must never be replayed.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

ALTER TABLE volpred_ops.incident_owners
  DROP CONSTRAINT IF EXISTS
    incident_owners_changed_by_normalized_v2;
ALTER TABLE volpred_ops.incident_owners
  ADD CONSTRAINT incident_owners_changed_by_normalized_v2
  CHECK (
    changed_by = btrim(changed_by)
    AND changed_by <> ''
  );

ALTER TABLE volpred_ops.incident_owners
  DROP CONSTRAINT IF EXISTS
    incident_owners_change_reason_normalized_v2;
ALTER TABLE volpred_ops.incident_owners
  ADD CONSTRAINT incident_owners_change_reason_normalized_v2
  CHECK (
    change_reason = btrim(change_reason)
    AND change_reason <> ''
  );

ALTER TABLE volpred_ops.incident_owner_receipts
  DROP CONSTRAINT IF EXISTS
    incident_owner_receipts_actor_normalized_v2;
ALTER TABLE volpred_ops.incident_owner_receipts
  ADD CONSTRAINT incident_owner_receipts_actor_normalized_v2
  CHECK (
    actor_ref = btrim(actor_ref)
    AND actor_ref <> ''
  );

ALTER TABLE volpred_ops.incident_owner_receipts
  DROP CONSTRAINT IF EXISTS
    incident_owner_receipts_reason_normalized_v2;
ALTER TABLE volpred_ops.incident_owner_receipts
  ADD CONSTRAINT incident_owner_receipts_reason_normalized_v2
  CHECK (
    reason = btrim(reason)
    AND reason <> ''
  );

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_constraint
    WHERE conrelid =
      'volpred_ops.incident_owner_receipts'::regclass
      AND conname =
        'incident_owner_receipts_capability_fkey_v2'
  ) THEN
    ALTER TABLE volpred_ops.incident_owner_receipts
      ADD CONSTRAINT incident_owner_receipts_capability_fkey_v2
      FOREIGN KEY (capability)
      REFERENCES volpred_ops.incident_owners(capability)
      ON DELETE RESTRICT;
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
      ) <> 1
      OR (
        SELECT count(*)
        FROM volpred_ops.incident_owner_receipts
        WHERE capability = 'incident.lifecycle'
      ) <> 1 THEN
    RAISE EXCEPTION 'Incident owner attestation drifted';
  END IF;
END;
$$;

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
    AND ownership.changed_at <= statement_timestamp()
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.incident_owner_receipts AS unexpected
      WHERE unexpected.capability = ownership.capability
        AND unexpected.sequence <> receipt.sequence
    );

  RETURN owner_payload;
END;
$$;

REVOKE ALL ON TABLE
  volpred_ops.incident_owners,
  volpred_ops.incident_owner_receipts
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE
  volpred_ops.incident_owner_receipts_sequence_seq
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.volpred_read_incident_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_incident_owner()
TO service_role;

COMMENT ON FUNCTION public.volpred_read_incident_owner() IS
  'Service-role-only pre-cutover Incident Lifecycle owner attestation; exact legacy generation 1 only.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
