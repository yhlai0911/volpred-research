-- Final forward-only convergence after concurrent hardening applies.
-- Refuse to install over ambiguous evidence, then make the read RPC reject
-- any receipt other than the exact legacy generation-1 bootstrap receipt.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

DO $$
DECLARE
  matching_rows bigint;
  owner_rows bigint;
  receipt_rows bigint;
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

  SELECT count(*)
  INTO owner_rows
  FROM volpred_ops.incident_owners
  WHERE capability = 'incident.lifecycle';

  SELECT count(*)
  INTO receipt_rows
  FROM volpred_ops.incident_owner_receipts
  WHERE capability = 'incident.lifecycle';

  IF matching_rows <> 1
      OR owner_rows <> 1
      OR receipt_rows <> 1 THEN
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
