-- Bind every new effect settlement to a verified outbox claim and Primary
-- Authority grant. Existing shadow receipts remain readable with NULL
-- authority fields; the old unfenced settlement function is removed so all
-- new attempts must provide token-redacted authority evidence.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

ALTER TABLE volpred_ops.effect_attempt_receipts
  ADD COLUMN authority_request_sha256 text,
  ADD COLUMN outbox_claim_ref text,
  ADD COLUMN primary_authority_ref text;

ALTER TABLE volpred_ops.effect_attempt_receipts
  ADD CONSTRAINT effect_attempt_receipts_authority_check
  CHECK (
    (
      authority_request_sha256 IS NULL
      AND outbox_claim_ref IS NULL
      AND primary_authority_ref IS NULL
    )
    OR
    (
      authority_request_sha256 ~ '^[0-9a-f]{64}$'
      AND btrim(outbox_claim_ref) <> ''
      AND btrim(primary_authority_ref) <> ''
    )
  ) NOT VALID;

ALTER TABLE volpred_ops.effect_attempt_receipts
  VALIDATE CONSTRAINT effect_attempt_receipts_authority_check;

CREATE OR REPLACE VIEW volpred_ops.effect_attempt_receipt_reads AS
SELECT
  effect_id, outbox_sequence, attempt_count, worker_id, reported_outcome,
  disposition, acknowledgement_kind, acknowledgement_target_ref, reason_code,
  evidence_ref, evidence_sha256, retry_at, recorded_at,
  authority_request_sha256, outbox_claim_ref, primary_authority_ref
FROM volpred_ops.effect_attempt_receipts;

CREATE FUNCTION volpred_ops.settle_effect_outbox(
  p_outbox_sequence bigint,
  p_effect_id text,
  p_attempt_count integer,
  p_worker_id text,
  p_token text,
  p_authority_request_sha256 text,
  p_outbox_claim_ref text,
  p_primary_authority_ref text,
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
  ELSIF p_authority_request_sha256 IS NULL
      OR p_authority_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_outbox_claim_ref IS NULL
      OR btrim(p_outbox_claim_ref) = ''
      OR p_primary_authority_ref IS NULL
      OR btrim(p_primary_authority_ref) = '' THEN
    RAISE EXCEPTION 'effect outbox settlement authority is required';
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
        OR existing.authority_request_sha256
          IS DISTINCT FROM p_authority_request_sha256
        OR existing.outbox_claim_ref
          IS DISTINCT FROM btrim(p_outbox_claim_ref)
        OR existing.primary_authority_ref
          IS DISTINCT FROM btrim(p_primary_authority_ref)
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
    claim_token_sha256, authority_request_sha256, outbox_claim_ref,
    primary_authority_ref, reported_outcome, disposition,
    acknowledgement_kind, acknowledgement_target_ref, reason_code,
    evidence_ref, evidence_sha256, retry_at, recorded_at
  )
  VALUES (
    message.effect_id, message.sequence, message.attempt_count,
    btrim(p_worker_id), token_sha256, p_authority_request_sha256,
    btrim(p_outbox_claim_ref), btrim(p_primary_authority_ref),
    p_outcome, disposition, btrim(p_acknowledgement_kind),
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

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text,
  text, text, text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text,
  text, text, text, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text,
  text, text, text, text, text, text
) TO volpred_ops_worker;

REVOKE ALL ON FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text, text, text, text
) FROM PUBLIC;
DROP FUNCTION volpred_ops.settle_effect_outbox(
  bigint, text, integer, text, text, text, text, text, text, text, text
);

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
