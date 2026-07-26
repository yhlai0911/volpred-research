-- Extend the owned-email recovery actuator to consume provider retries whose
-- backoff is due.  The original actuator only repaired begin-without-settle
-- crashes; retry_scheduled attempts could remain pending forever when no
-- identical alert command was replayed.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

ALTER TABLE volpred_ops.owned_notification_recovery_receipts
  DROP CONSTRAINT
    owned_notification_recovery_receipts_reason_code_check;
ALTER TABLE volpred_ops.owned_notification_recovery_receipts
  ADD CONSTRAINT
    owned_notification_recovery_receipts_reason_code_check
  CHECK (
    reason_code IN (
      'worker_interrupted_after_begin',
      'retry_due_without_actuator'
    )
  );

CREATE OR REPLACE FUNCTION
public.volpred_recover_expired_owned_email_notification(
  p_owner_generation bigint,
  p_worker_id text,
  p_lease_seconds integer,
  p_work_lease_token text,
  p_outbox_claim_token text,
  p_primary_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  candidate_attempt volpred_ops.owned_notification_attempts;
  recovered_attempt jsonb;
  recovered_at timestamptz;
  recovery_evidence_ref text;
  recovery_evidence_sha256 text;
  recovery_attempt_count integer;
  recovery_reason_code text;
BEGIN
  IF p_owner_generation IS NULL OR p_owner_generation <= 0
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_lease_seconds IS NULL OR p_lease_seconds <= 0
      OR p_work_lease_token IS NULL OR btrim(p_work_lease_token) = ''
      OR p_outbox_claim_token IS NULL
      OR btrim(p_outbox_claim_token) = ''
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = '' THEN
    RAISE EXCEPTION 'owned email recovery fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'email.ops_alert'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'notification ownership lost: expected operations_core/% found %/%',
      p_owner_generation, ownership.owner, ownership.generation;
  END IF;

  SELECT attempt.*
  INTO candidate_attempt
  FROM volpred_ops.owned_notification_attempts AS attempt
  JOIN volpred_ops.owned_notification_requests AS owned_request
    ON owned_request.effect_id = attempt.effect_id
  JOIN volpred_ops.work_items AS work
    ON work.id = attempt.work_id
  JOIN volpred_ops.effect_outbox AS message
    ON message.sequence = attempt.outbox_sequence
  JOIN volpred_ops.effect_requests AS effect
    ON effect.id = attempt.effect_id
  WHERE attempt.owner_generation = ownership.generation
    AND owned_request.owner_generation = ownership.generation
    AND message.attempt_count = attempt.attempt_count
    AND effect.status = 'requested'
    AND (
      (
        attempt.status = 'started'
        AND attempt.lease_expires_at <= clock_timestamp()
        AND work.status IN ('claimed', 'running')
        AND work.claim_expires_at IS NOT NULL
        AND work.claim_expires_at <= clock_timestamp()
        AND message.status = 'claimed'
        AND message.claim_expires_at IS NOT NULL
        AND message.claim_expires_at <= clock_timestamp()
      )
      OR
      (
        attempt.status = 'retry_scheduled'
        AND work.status = 'pending'
        AND message.status = 'pending'
        AND message.available_at <= clock_timestamp()
      )
    )
  ORDER BY
    CASE attempt.status WHEN 'started' THEN 0 ELSE 1 END,
    coalesce(attempt.finished_at, attempt.lease_expires_at),
    attempt.effect_id,
    attempt.attempt_count
  FOR UPDATE OF attempt SKIP LOCKED
  LIMIT 1;

  IF candidate_attempt.effect_id IS NULL THEN
    RETURN jsonb_build_object(
      'schema_version', 'owned-email-recovery.v1',
      'recovered', false
    );
  END IF;

  recovery_reason_code := CASE candidate_attempt.status
    WHEN 'started' THEN 'worker_interrupted_after_begin'
    ELSE 'retry_due_without_actuator'
  END;
  recovery_attempt_count := candidate_attempt.attempt_count + 1;
  recovered_at := clock_timestamp();
  recovery_evidence_ref :=
    'owned-email-recovery:' || candidate_attempt.effect_id
    || ':attempt-' || candidate_attempt.attempt_count::text;
  recovery_evidence_sha256 := encode(
    sha256(
      convert_to(
        jsonb_build_object(
          'schema_version', 'owned-email-recovery-receipt.v1',
          'effect_id', candidate_attempt.effect_id,
          'expired_attempt_count', candidate_attempt.attempt_count,
          'recovery_attempt_count', recovery_attempt_count,
          'owner_generation', candidate_attempt.owner_generation,
          'expired_worker_id', candidate_attempt.worker_id,
          'recovery_worker_id', btrim(p_worker_id),
          'expired_lease_expires_at',
            candidate_attempt.lease_expires_at,
          'reason_code', recovery_reason_code,
          'recovered_at', recovered_at,
          'evidence_ref', recovery_evidence_ref
        )::text,
        'UTF8'
      )
    ),
    'hex'
  );

  IF candidate_attempt.status = 'started' THEN
    UPDATE volpred_ops.owned_notification_attempts
    SET status = 'retry_scheduled',
        reported_outcome = 'worker_interrupted',
        disposition = 'recovered_after_expired_lease',
        evidence_ref = recovery_evidence_ref,
        evidence_sha256 = recovery_evidence_sha256,
        work_status = 'running',
        effect_status = 'requested',
        finished_at = recovered_at
    WHERE effect_id = candidate_attempt.effect_id
      AND attempt_count = candidate_attempt.attempt_count;
  END IF;

  INSERT INTO volpred_ops.owned_notification_recovery_receipts (
    effect_id, expired_attempt_count, recovery_attempt_count,
    owner_generation, expired_worker_id, recovery_worker_id,
    expired_lease_expires_at, reason_code, recovered_at, evidence_ref,
    evidence_sha256
  )
  VALUES (
    candidate_attempt.effect_id, candidate_attempt.attempt_count,
    recovery_attempt_count, candidate_attempt.owner_generation,
    candidate_attempt.worker_id, btrim(p_worker_id),
    candidate_attempt.lease_expires_at, recovery_reason_code,
    recovered_at, recovery_evidence_ref, recovery_evidence_sha256
  );

  recovered_attempt :=
    public.volpred_begin_owned_email_notification(
      ownership.generation,
      candidate_attempt.effect_id,
      btrim(p_worker_id),
      p_lease_seconds,
      p_work_lease_token,
      p_outbox_claim_token,
      p_primary_fencing_token
    );
  IF (recovered_attempt ->> 'attempt_count')::integer
      <> recovery_attempt_count THEN
    RAISE EXCEPTION
      'owned email recovery did not advance attempt count';
  END IF;

  RETURN recovered_attempt || jsonb_build_object(
    'recovered', true,
    'recovery', jsonb_build_object(
      'schema_version', 'owned-email-recovery-receipt.v1',
      'reason_code', recovery_reason_code,
      'expired_attempt_count', candidate_attempt.attempt_count,
      'recovery_attempt_count', recovery_attempt_count,
      'evidence_ref', recovery_evidence_ref,
      'evidence_sha256', recovery_evidence_sha256,
      'recovered_at', recovered_at
    )
  );
END;
$$;

ALTER FUNCTION
  public.volpred_recover_expired_owned_email_notification(
    bigint, text, integer, text, text, text
  )
  OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_recover_expired_owned_email_notification(
    bigint, text, integer, text, text, text
  )
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.volpred_recover_expired_owned_email_notification(
    bigint, text, integer, text, text, text
  )
TO service_role;

COMMENT ON FUNCTION
  public.volpred_recover_expired_owned_email_notification(
    bigint, text, integer, text, text, text
  )
IS
  'Atomically recover one expired started attempt or one due provider retry.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
