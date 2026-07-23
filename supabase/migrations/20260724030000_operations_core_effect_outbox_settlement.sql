-- Durable settlement, retry, and dead-letter lifecycle for Effect Delivery.
--
-- The worker reports typed evidence for one fenced claim. This module owns
-- bounded exponential backoff (30s base, one hour cap, five attempts), token
-- fencing, immutable attempt receipts, and terminal request/outbox state.
-- No provider is invoked by this migration.

ALTER TABLE volpred_ops.effect_requests
  DROP CONSTRAINT effect_requests_status_check;
ALTER TABLE volpred_ops.effect_requests
  ADD CONSTRAINT effect_requests_status_check
  CHECK (status IN ('requested', 'delivered', 'dead_lettered'));

ALTER TABLE volpred_ops.effect_outbox
  DROP CONSTRAINT effect_outbox_status_check;
ALTER TABLE volpred_ops.effect_outbox
  DROP CONSTRAINT effect_outbox_check;
ALTER TABLE volpred_ops.effect_outbox
  ADD CONSTRAINT effect_outbox_status_check
  CHECK (status IN ('pending', 'claimed', 'delivered', 'dead_lettered'));
ALTER TABLE volpred_ops.effect_outbox
  ADD CONSTRAINT effect_outbox_state_check
  CHECK (
    (status = 'pending'
      AND claimed_by IS NULL
      AND claim_token IS NULL
      AND claim_expires_at IS NULL)
    OR
    (status = 'claimed'
      AND claimed_by IS NOT NULL
      AND claim_token IS NOT NULL
      AND claim_expires_at IS NOT NULL)
    OR
    (status IN ('delivered', 'dead_lettered')
      AND claimed_by IS NULL
      AND claim_token IS NULL
      AND claim_expires_at IS NULL)
  );

CREATE TABLE volpred_ops.effect_attempt_receipts (
  effect_id text NOT NULL
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  outbox_sequence bigint NOT NULL
    REFERENCES volpred_ops.effect_outbox(sequence) ON DELETE RESTRICT,
  attempt_count integer NOT NULL CHECK (attempt_count > 0),
  worker_id text NOT NULL,
  claim_token_sha256 text NOT NULL
    CHECK (claim_token_sha256 ~ '^[0-9a-f]{64}$'),
  reported_outcome text NOT NULL
    CHECK (
      reported_outcome IN (
        'acknowledged', 'retryable_failure', 'terminal_failure'
      )
    ),
  disposition text NOT NULL
    CHECK (
      disposition IN ('delivered', 'retry_scheduled', 'dead_lettered')
    ),
  acknowledgement_kind text,
  acknowledgement_target_ref text,
  reason_code text,
  evidence_ref text NOT NULL,
  evidence_sha256 text NOT NULL
    CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  retry_at timestamptz,
  recorded_at timestamptz NOT NULL,
  PRIMARY KEY (effect_id, attempt_count),
  CHECK (
    (reported_outcome = 'acknowledged'
      AND disposition = 'delivered'
      AND acknowledgement_kind IS NOT NULL
      AND acknowledgement_target_ref IS NOT NULL
      AND reason_code IS NULL
      AND retry_at IS NULL)
    OR
    (reported_outcome = 'retryable_failure'
      AND disposition = 'retry_scheduled'
      AND acknowledgement_kind IS NULL
      AND acknowledgement_target_ref IS NULL
      AND reason_code IS NOT NULL
      AND retry_at IS NOT NULL)
    OR
    (reported_outcome IN ('retryable_failure', 'terminal_failure')
      AND disposition = 'dead_lettered'
      AND acknowledgement_kind IS NULL
      AND acknowledgement_target_ref IS NULL
      AND reason_code IS NOT NULL
      AND retry_at IS NULL)
  )
);

CREATE VIEW volpred_ops.effect_attempt_receipt_reads AS
SELECT
  effect_id, outbox_sequence, attempt_count, worker_id, reported_outcome,
  disposition, acknowledgement_kind, acknowledgement_target_ref, reason_code,
  evidence_ref, evidence_sha256, retry_at, recorded_at
FROM volpred_ops.effect_attempt_receipts;

ALTER TABLE volpred_ops.effect_attempt_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_attempt_receipts FORCE ROW LEVEL SECURITY;

REVOKE ALL ON volpred_ops.effect_attempt_receipts FROM PUBLIC;
REVOKE ALL ON volpred_ops.effect_attempt_receipt_reads FROM PUBLIC;
GRANT SELECT ON volpred_ops.effect_attempt_receipt_reads TO volpred_ops_worker;
GRANT SELECT, INSERT ON volpred_ops.effect_attempt_receipts
  TO volpred_ops_definer;
GRANT UPDATE ON volpred_ops.effect_requests TO volpred_ops_definer;

CREATE POLICY effect_attempt_receipts_worker_select
  ON volpred_ops.effect_attempt_receipts
  FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY effect_attempt_receipts_definer_select
  ON volpred_ops.effect_attempt_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY effect_attempt_receipts_definer_insert
  ON volpred_ops.effect_attempt_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
CREATE POLICY effect_requests_definer_update
  ON volpred_ops.effect_requests
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

CREATE FUNCTION volpred_ops.settle_effect_outbox(
  p_outbox_sequence bigint,
  p_effect_id text,
  p_attempt_count integer,
  p_worker_id text,
  p_token text,
  p_outcome text,
  p_acknowledgement_kind text,
  p_acknowledgement_target_ref text,
  p_reason_code text,
  p_evidence_ref text,
  p_evidence_sha256 text
)
RETURNS SETOF volpred_ops.effect_attempt_receipt_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  message volpred_ops.effect_outbox;
  effect volpred_ops.effect_requests;
  existing volpred_ops.effect_attempt_receipts;
  receipt volpred_ops.effect_attempt_receipts;
  event_at timestamptz;
  retry_at timestamptz;
  disposition text;
  token_sha256 text;
BEGIN
  IF p_effect_id IS NULL OR btrim(p_effect_id) = ''
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_token IS NULL OR btrim(p_token) = ''
      OR p_evidence_ref IS NULL OR btrim(p_evidence_ref) = '' THEN
    RAISE EXCEPTION 'effect outbox settlement fields are required';
  ELSIF p_outbox_sequence IS NULL OR p_outbox_sequence <= 0 THEN
    RAISE EXCEPTION 'effect outbox sequence must be positive';
  ELSIF p_attempt_count IS NULL OR p_attempt_count <= 0 THEN
    RAISE EXCEPTION 'effect outbox attempt_count must be positive';
  ELSIF p_evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'effect outbox settlement hash must be lowercase SHA-256';
  ELSIF p_outcome NOT IN (
      'acknowledged', 'retryable_failure', 'terminal_failure'
  ) THEN
    RAISE EXCEPTION 'unsupported effect outbox outcome: %', p_outcome;
  END IF;

  IF p_outcome = 'acknowledged' THEN
    IF p_acknowledgement_kind IS NULL
        OR btrim(p_acknowledgement_kind) = ''
        OR p_acknowledgement_target_ref IS NULL
        OR btrim(p_acknowledgement_target_ref) = ''
        OR p_reason_code IS NOT NULL THEN
      RAISE EXCEPTION 'effect outbox acknowledgement fields are required';
    END IF;
  ELSIF p_acknowledgement_kind IS NOT NULL
      OR p_acknowledgement_target_ref IS NOT NULL
      OR p_reason_code IS NULL
      OR btrim(p_reason_code) = '' THEN
    RAISE EXCEPTION 'effect outbox failure reason_code is required';
  END IF;

  token_sha256 :=
    encode(sha256(convert_to(p_token, 'UTF8')), 'hex');

  -- Serialize equivalent client retries before checking the immutable
  -- receipt. Without this identity lock, two transactions can both observe
  -- "no receipt"; the loser then wakes after the outbox is terminal and
  -- incorrectly reports a stale claim instead of replaying success.
  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      btrim(p_effect_id) || ':' || p_attempt_count::text,
      0
    )
  );

  SELECT * INTO existing
  FROM volpred_ops.effect_attempt_receipts
  WHERE effect_id = btrim(p_effect_id)
    AND attempt_count = p_attempt_count;
  IF existing.effect_id IS NOT NULL THEN
    IF existing.outbox_sequence <> p_outbox_sequence
        OR existing.worker_id <> btrim(p_worker_id)
        OR existing.claim_token_sha256 <> token_sha256
        OR existing.reported_outcome <> p_outcome
        OR existing.acknowledgement_kind
          IS DISTINCT FROM btrim(p_acknowledgement_kind)
        OR existing.acknowledgement_target_ref
          IS DISTINCT FROM btrim(p_acknowledgement_target_ref)
        OR existing.reason_code IS DISTINCT FROM btrim(p_reason_code)
        OR existing.evidence_ref <> btrim(p_evidence_ref)
        OR existing.evidence_sha256 <> p_evidence_sha256 THEN
      RAISE EXCEPTION
        'effect outbox settlement conflicts with its original outcome';
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.effect_attempt_receipt_reads
    WHERE effect_id = existing.effect_id
      AND attempt_count = existing.attempt_count;
    RETURN;
  END IF;

  SELECT * INTO message
  FROM volpred_ops.effect_outbox
  WHERE sequence = p_outbox_sequence
    AND effect_id = btrim(p_effect_id)
  FOR UPDATE;
  IF message.sequence IS NULL THEN
    RAISE EXCEPTION 'unknown effect outbox attempt: %/%',
      p_effect_id, p_attempt_count;
  ELSIF message.status <> 'claimed' THEN
    RAISE EXCEPTION 'effect outbox attempt is not actively claimed: %/%',
      p_effect_id, p_attempt_count;
  ELSIF message.claimed_by <> btrim(p_worker_id) THEN
    RAISE EXCEPTION 'effect outbox attempt worker mismatch: %/%',
      p_effect_id, p_attempt_count;
  ELSIF message.claim_token <> p_token THEN
    RAISE EXCEPTION 'effect outbox attempt token mismatch: %/%',
      p_effect_id, p_attempt_count;
  ELSIF message.attempt_count <> p_attempt_count THEN
    RAISE EXCEPTION 'effect outbox attempt count mismatch: expected %, found %',
      p_attempt_count, message.attempt_count;
  ELSIF message.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'effect outbox attempt lease expired: %/%',
      p_effect_id, p_attempt_count;
  END IF;

  SELECT * INTO effect
  FROM volpred_ops.effect_requests
  WHERE id = message.effect_id
  FOR UPDATE;
  IF effect.id IS NULL THEN
    RAISE EXCEPTION 'unknown EffectRequest: %', message.effect_id;
  END IF;
  IF p_outcome = 'acknowledged'
      AND (
        effect.acknowledgement_kind <> btrim(p_acknowledgement_kind)
        OR effect.acknowledgement_target_ref
          <> btrim(p_acknowledgement_target_ref)
      ) THEN
    RAISE EXCEPTION 'effect outbox acknowledgement mismatch: %',
      message.effect_id;
  END IF;

  event_at := clock_timestamp();
  IF p_outcome = 'acknowledged' THEN
    disposition := 'delivered';
  ELSIF p_outcome = 'retryable_failure'
      AND message.attempt_count < 5 THEN
    disposition := 'retry_scheduled';
    retry_at := event_at + make_interval(
      secs => least(
        3600,
        (30 * power(2, message.attempt_count - 1))::integer
      )
    );
  ELSE
    disposition := 'dead_lettered';
  END IF;

  INSERT INTO volpred_ops.effect_attempt_receipts (
    effect_id, outbox_sequence, attempt_count, worker_id,
    claim_token_sha256, reported_outcome, disposition,
    acknowledgement_kind, acknowledgement_target_ref, reason_code,
    evidence_ref, evidence_sha256, retry_at, recorded_at
  )
  VALUES (
    message.effect_id, message.sequence, message.attempt_count,
    btrim(p_worker_id), token_sha256, p_outcome, disposition,
    btrim(p_acknowledgement_kind),
    btrim(p_acknowledgement_target_ref), btrim(p_reason_code),
    btrim(p_evidence_ref), p_evidence_sha256, retry_at, event_at
  )
  RETURNING * INTO receipt;

  IF disposition = 'retry_scheduled' THEN
    UPDATE volpred_ops.effect_outbox
    SET status = 'pending',
        available_at = retry_at,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL
    WHERE sequence = message.sequence;
  ELSE
    UPDATE volpred_ops.effect_outbox
    SET status = disposition,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL
    WHERE sequence = message.sequence;
    UPDATE volpred_ops.effect_requests
    SET status = disposition
    WHERE id = message.effect_id;
  END IF;

  RETURN QUERY
  SELECT * FROM volpred_ops.effect_attempt_receipt_reads
  WHERE effect_id = receipt.effect_id
    AND attempt_count = receipt.attempt_count;
END;
$$;

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

ALTER TABLE volpred_ops.effect_attempt_receipts
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.effect_attempt_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text, text, text, text
) OWNER TO volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;

REVOKE ALL ON FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text, text, text, text
) TO volpred_ops_worker;
