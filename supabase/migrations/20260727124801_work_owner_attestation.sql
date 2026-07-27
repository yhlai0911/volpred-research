-- Service-role-only, read-only attestation for the durable Work Coordinator
-- owner. This exposes no transfer/staging capability and does not read the
-- legacy filesystem queue.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE OR REPLACE FUNCTION public.volpred_read_work_owner()
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
      'schema_version', 'work-owner-attestation.v1',
      'attested_at', statement_timestamp(),
      'ownership_receipt_sequence', receipt.sequence,
      'ownership_receipt_capability', receipt.capability,
      'ownership_receipt_owner', receipt.owner,
      'ownership_receipt_generation', receipt.generation,
      'ownership_receipt_manifest_sha256',
        receipt.cutover_manifest_sha256,
      'ownership_receipt_changed_at', receipt.changed_at,
      'ownership_receipt_actor_ref', receipt.actor_ref,
      'ownership_receipt_reason', receipt.reason,
      'ownership_receipt_rollback_of_generation',
        receipt.rollback_of_generation,
      'cutover_gate_manifest_sha256', gate.manifest_sha256,
      'cutover_gate_status', gate.status,
      'cutover_gate_consumed_generation', gate.consumed_generation,
      'cutover_gate_consumed_at', gate.consumed_at,
      'cutover_gate_rolled_back_at', gate.rolled_back_at
    )
  INTO STRICT owner_payload
  FROM volpred_ops.read_work_owner() AS owner_row
  JOIN volpred_ops.work_owner_receipts AS receipt
    ON receipt.capability = owner_row.capability
   AND receipt.owner = owner_row.owner
   AND receipt.generation = owner_row.generation
   AND receipt.cutover_manifest_sha256
     IS NOT DISTINCT FROM owner_row.cutover_manifest_sha256
   AND receipt.changed_at = owner_row.changed_at
   AND receipt.actor_ref = owner_row.changed_by
   AND receipt.reason = owner_row.change_reason
  LEFT JOIN volpred_ops.work_cutover_gates AS gate
    ON gate.manifest_sha256 = owner_row.cutover_manifest_sha256
  WHERE owner_row.changed_at <= statement_timestamp()
    AND (
      (
        owner_row.owner = 'legacy'
        AND owner_row.generation = 1
        AND owner_row.cutover_manifest_sha256 IS NULL
        AND receipt.previous_owner IS NULL
        AND receipt.rollback_of_generation IS NULL
        AND gate.manifest_sha256 IS NULL
      )
      OR
      (
        owner_row.owner = 'operations_core'
        AND owner_row.cutover_manifest_sha256 IS NOT NULL
        AND receipt.previous_owner = 'legacy'
        AND receipt.rollback_of_generation IS NULL
        AND gate.status = 'consumed'
        AND gate.consumed_generation = owner_row.generation
        AND gate.consumed_at >= owner_row.changed_at
        AND gate.consumed_at <= statement_timestamp()
        AND gate.rolled_back_at IS NULL
      )
      OR
      (
        owner_row.owner = 'legacy'
        AND owner_row.cutover_manifest_sha256 IS NOT NULL
        AND receipt.previous_owner = 'operations_core'
        AND gate.status = 'rolled_back'
        AND gate.consumed_generation = receipt.rollback_of_generation
        AND owner_row.generation = gate.consumed_generation + 1
        AND gate.consumed_at <= owner_row.changed_at
        AND gate.rolled_back_at >= owner_row.changed_at
        AND gate.rolled_back_at <= statement_timestamp()
      )
    );
  RETURN owner_payload;
END;
$$;

REVOKE ALL ON FUNCTION public.volpred_read_work_owner()
FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_work_owner()
TO service_role;

COMMENT ON FUNCTION public.volpred_read_work_owner() IS
  'Service-role-only typed live Work Coordinator owner attestation; cannot stage or transfer ownership.';

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
