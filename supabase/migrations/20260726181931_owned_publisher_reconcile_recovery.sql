-- Recover immutable publisher reconcile batches from the original durable
-- payload.  A later feed diff is not a substitute: partial success can shrink
-- the next batch or make the diff clean while the original outbox remains due.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE volpred_ops.owned_publisher_reconcile_recovery_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  effect_id text NOT NULL
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  candidate_attempt_count integer NOT NULL
    CHECK (candidate_attempt_count > 0),
  recovery_attempt_count integer NOT NULL
    CHECK (recovery_attempt_count > candidate_attempt_count),
  owner_generation bigint NOT NULL CHECK (owner_generation > 0),
  candidate_status text NOT NULL
    CHECK (candidate_status IN ('started', 'retry_scheduled')),
  candidate_worker_id text NOT NULL,
  recovery_worker_id text NOT NULL,
  candidate_lease_expires_at timestamptz NOT NULL,
  reason_code text NOT NULL
    CHECK (
      (candidate_status = 'started'
        AND reason_code = 'worker_interrupted_after_begin')
      OR
      (candidate_status = 'retry_scheduled'
        AND reason_code = 'retry_due_without_actuator')
    ),
  recovered_at timestamptz NOT NULL,
  evidence_ref text NOT NULL UNIQUE,
  evidence_sha256 text NOT NULL
    CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  UNIQUE (effect_id, candidate_attempt_count)
);

CREATE INDEX owned_publisher_reconcile_recovery_effect_idx
  ON volpred_ops.owned_publisher_reconcile_recovery_receipts (
    effect_id, recovery_attempt_count, recovered_at
  );

ALTER TABLE volpred_ops.owned_publisher_reconcile_recovery_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.owned_publisher_reconcile_recovery_receipts
  FORCE ROW LEVEL SECURITY;

REVOKE ALL ON
  volpred_ops.owned_publisher_reconcile_recovery_receipts
FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT, INSERT ON
  volpred_ops.owned_publisher_reconcile_recovery_receipts
TO volpred_ops_definer;
GRANT USAGE, SELECT ON SEQUENCE
  volpred_ops.owned_publisher_reconcile_recovery_receipts_sequence_seq
TO volpred_ops_definer;

CREATE POLICY owned_publisher_reconcile_recovery_definer_select
  ON volpred_ops.owned_publisher_reconcile_recovery_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY owned_publisher_reconcile_recovery_definer_insert
  ON volpred_ops.owned_publisher_reconcile_recovery_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE OR REPLACE FUNCTION
public.volpred_recover_due_owned_publisher_article_reconcile(
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
  recovery_attempt_count integer;
  recovery_reason_code text;
  recovery_evidence_ref text;
  recovery_evidence_sha256 text;
BEGIN
  IF p_owner_generation IS NULL OR p_owner_generation <= 0
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_lease_seconds IS NULL OR p_lease_seconds <= 0
      OR p_work_lease_token IS NULL
      OR btrim(p_work_lease_token) = ''
      OR p_outbox_claim_token IS NULL
      OR btrim(p_outbox_claim_token) = ''
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = '' THEN
    RAISE EXCEPTION 'owned publisher reconcile recovery fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.reconcile'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'publisher reconcile ownership lost: '
      'expected operations_core/% found %/%',
      p_owner_generation,
      ownership.owner,
      ownership.generation;
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
    AND owned_request.effect_family = ownership.effect_family
    AND owned_request.owner_generation = ownership.generation
    AND effect.effect_kind = ownership.effect_family
    AND effect.status = 'requested'
    AND message.attempt_count = attempt.attempt_count
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.owned_publisher_reconcile_recovery_receipts
        AS recovery_receipt
      WHERE recovery_receipt.effect_id = attempt.effect_id
        AND recovery_receipt.candidate_attempt_count =
          attempt.attempt_count
    )
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
    CASE
      WHEN attempt.status = 'started'
      THEN attempt.lease_expires_at
      ELSE message.available_at
    END,
    attempt.effect_id,
    attempt.attempt_count
  FOR UPDATE OF attempt SKIP LOCKED
  LIMIT 1;

  IF candidate_attempt.effect_id IS NULL THEN
    RETURN jsonb_build_object(
      'schema_version', 'owned-publisher-reconcile-recovery.v1',
      'recovered', false
    );
  END IF;

  recovery_attempt_count := candidate_attempt.attempt_count + 1;
  recovery_reason_code := CASE candidate_attempt.status
    WHEN 'started' THEN 'worker_interrupted_after_begin'
    ELSE 'retry_due_without_actuator'
  END;
  recovered_at := clock_timestamp();
  recovery_evidence_ref :=
    'owned-publisher-reconcile-recovery:' || candidate_attempt.effect_id
    || ':attempt-' || candidate_attempt.attempt_count::text;
  recovery_evidence_sha256 := encode(
    sha256(
      convert_to(
        jsonb_build_object(
          'schema_version',
            'owned-publisher-reconcile-recovery-receipt.v1',
          'effect_id', candidate_attempt.effect_id,
          'candidate_attempt_count', candidate_attempt.attempt_count,
          'recovery_attempt_count', recovery_attempt_count,
          'owner_generation', candidate_attempt.owner_generation,
          'candidate_status', candidate_attempt.status,
          'candidate_worker_id', candidate_attempt.worker_id,
          'recovery_worker_id', btrim(p_worker_id),
          'candidate_lease_expires_at',
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

  INSERT INTO volpred_ops.owned_publisher_reconcile_recovery_receipts (
    effect_id, candidate_attempt_count, recovery_attempt_count,
    owner_generation, candidate_status, candidate_worker_id,
    recovery_worker_id, candidate_lease_expires_at, reason_code,
    recovered_at, evidence_ref, evidence_sha256
  )
  VALUES (
    candidate_attempt.effect_id,
    candidate_attempt.attempt_count,
    recovery_attempt_count,
    candidate_attempt.owner_generation,
    candidate_attempt.status,
    candidate_attempt.worker_id,
    btrim(p_worker_id),
    candidate_attempt.lease_expires_at,
    recovery_reason_code,
    recovered_at,
    recovery_evidence_ref,
    recovery_evidence_sha256
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

  recovered_attempt :=
    public.volpred_begin_owned_publisher_article_reconcile(
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
      'owned publisher reconcile recovery did not advance attempt count';
  END IF;

  RETURN recovered_attempt || jsonb_build_object(
    'recovered', true,
    'recovery', jsonb_build_object(
      'schema_version',
        'owned-publisher-reconcile-recovery-receipt.v1',
      'reason_code', recovery_reason_code,
      'candidate_attempt_count', candidate_attempt.attempt_count,
      'recovery_attempt_count', recovery_attempt_count,
      'evidence_ref', recovery_evidence_ref,
      'evidence_sha256', recovery_evidence_sha256,
      'recovered_at', recovered_at
    )
  );
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER TABLE volpred_ops.owned_publisher_reconcile_recovery_receipts
  OWNER TO volpred_ops_definer;
ALTER SEQUENCE
  volpred_ops.owned_publisher_reconcile_recovery_receipts_sequence_seq
  OWNER TO volpred_ops_definer;
ALTER FUNCTION
  public.volpred_recover_due_owned_publisher_article_reconcile(
    bigint, text, integer, text, text, text
  )
  OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_recover_due_owned_publisher_article_reconcile(
    bigint, text, integer, text, text, text
  )
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.volpred_recover_due_owned_publisher_article_reconcile(
    bigint, text, integer, text, text, text
  )
TO service_role;

COMMENT ON FUNCTION
  public.volpred_recover_due_owned_publisher_article_reconcile(
    bigint, text, integer, text, text, text
  )
IS
  'Recover one immutable publisher reconcile crash or due retry from its durable payload.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
