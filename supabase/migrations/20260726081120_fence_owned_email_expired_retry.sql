-- Make the recovery actuator the only path that may supersede an expired
-- owned-email attempt.  Ordinary begin previously reclaimed the WorkItem and
-- outbox but left its predecessor in status=started forever.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

DO $migration$
DECLARE
  function_definition text;
  rewritten_definition text;
BEGIN
  SELECT pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'public.volpred_begin_owned_email_notification(bigint,text,text,integer,text,text,text)'
    )
  )
  INTO STRICT function_definition;

  rewritten_definition := pg_catalog.replace(
    function_definition,
    $old_begin$
  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;

  event_at := clock_timestamp();
$old_begin$,
    $new_begin$
  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.owned_notification_attempts AS predecessor
    WHERE predecessor.effect_id = owned_request.effect_id
      AND predecessor.status = 'started'
  ) THEN
    RAISE EXCEPTION
      'owned email expired attempt requires recovery actuator';
  END IF;

  event_at := clock_timestamp();
$new_begin$
  );
  IF rewritten_definition = function_definition THEN
    IF pg_catalog.strpos(
      function_definition,
      'owned email expired attempt requires recovery actuator'
    ) = 0 THEN
      RAISE EXCEPTION
        'owned email begin predecessor gate pre-image did not match';
    END IF;
  ELSE
    EXECUTE rewritten_definition;
  END IF;
END;
$migration$;

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
  expired_attempt volpred_ops.owned_notification_attempts;
  recovered_attempt jsonb;
  recovered_at timestamptz;
  recovery_evidence_ref text;
  recovery_evidence_sha256 text;
  recovery_attempt_count integer;
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
  INTO expired_attempt
  FROM volpred_ops.owned_notification_attempts AS attempt
  JOIN volpred_ops.owned_notification_requests AS owned_request
    ON owned_request.effect_id = attempt.effect_id
  JOIN volpred_ops.work_items AS work
    ON work.id = attempt.work_id
  JOIN volpred_ops.effect_outbox AS message
    ON message.sequence = attempt.outbox_sequence
  JOIN volpred_ops.effect_requests AS effect
    ON effect.id = attempt.effect_id
  WHERE attempt.status = 'started'
    AND attempt.lease_expires_at <= clock_timestamp()
    AND attempt.owner_generation = ownership.generation
    AND owned_request.owner_generation = ownership.generation
    AND work.status IN ('claimed', 'running')
    AND work.claim_expires_at IS NOT NULL
    AND work.claim_expires_at <= clock_timestamp()
    AND message.status = 'claimed'
    AND message.claim_expires_at IS NOT NULL
    AND message.claim_expires_at <= clock_timestamp()
    AND message.attempt_count = attempt.attempt_count
    AND effect.status = 'requested'
  ORDER BY
    attempt.lease_expires_at,
    attempt.effect_id,
    attempt.attempt_count
  FOR UPDATE OF attempt SKIP LOCKED
  LIMIT 1;

  IF expired_attempt.effect_id IS NULL THEN
    RETURN jsonb_build_object(
      'schema_version', 'owned-email-recovery.v1',
      'recovered', false
    );
  END IF;

  recovery_attempt_count := expired_attempt.attempt_count + 1;
  recovered_at := clock_timestamp();
  recovery_evidence_ref :=
    'owned-email-recovery:' || expired_attempt.effect_id
    || ':attempt-' || expired_attempt.attempt_count::text;
  recovery_evidence_sha256 := encode(
    sha256(
      convert_to(
        jsonb_build_object(
          'schema_version', 'owned-email-recovery-receipt.v1',
          'effect_id', expired_attempt.effect_id,
          'expired_attempt_count', expired_attempt.attempt_count,
          'recovery_attempt_count', recovery_attempt_count,
          'owner_generation', expired_attempt.owner_generation,
          'expired_worker_id', expired_attempt.worker_id,
          'recovery_worker_id', btrim(p_worker_id),
          'expired_lease_expires_at',
            expired_attempt.lease_expires_at,
          'reason_code', 'worker_interrupted_after_begin',
          'recovered_at', recovered_at,
          'evidence_ref', recovery_evidence_ref
        )::text,
        'UTF8'
      )
    ),
    'hex'
  );

  UPDATE volpred_ops.owned_notification_attempts
  SET status = 'retry_scheduled',
      reported_outcome = 'worker_interrupted',
      disposition = 'recovered_after_expired_lease',
      evidence_ref = recovery_evidence_ref,
      evidence_sha256 = recovery_evidence_sha256,
      work_status = 'running',
      effect_status = 'requested',
      finished_at = recovered_at
  WHERE effect_id = expired_attempt.effect_id
    AND attempt_count = expired_attempt.attempt_count;

  INSERT INTO volpred_ops.owned_notification_recovery_receipts (
    effect_id, expired_attempt_count, recovery_attempt_count,
    owner_generation, expired_worker_id, recovery_worker_id,
    expired_lease_expires_at, reason_code, recovered_at, evidence_ref,
    evidence_sha256
  )
  VALUES (
    expired_attempt.effect_id, expired_attempt.attempt_count,
    recovery_attempt_count, expired_attempt.owner_generation,
    expired_attempt.worker_id, btrim(p_worker_id),
    expired_attempt.lease_expires_at,
    'worker_interrupted_after_begin', recovered_at,
    recovery_evidence_ref, recovery_evidence_sha256
  );

  recovered_attempt :=
    public.volpred_begin_owned_email_notification(
      ownership.generation,
      expired_attempt.effect_id,
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
      'expired_attempt_count', expired_attempt.attempt_count,
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
  'Atomically close one expired predecessor before its fenced replacement begins.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
