-- Shadow Operations Core EffectRequest and transactional outbox state.
--
-- This migration depends on the private volpred_ops schema and roles created
-- by 20260723062144_operations_core_work_coordinator.sql.  It remains shadow
-- infrastructure: no Data API role receives schema access and no provider is
-- called by these functions.

CREATE TABLE volpred_ops.effect_requests (
  id text PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  work_item_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  work_item_version integer NOT NULL CHECK (work_item_version > 0),
  effect_kind text NOT NULL,
  target_ref text NOT NULL,
  payload_ref text NOT NULL,
  payload_sha256 text NOT NULL
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  risk text NOT NULL
    CHECK (risk IN ('safe', 'sensitive', 'destructive')),
  acknowledgement_kind text NOT NULL,
  acknowledgement_target_ref text NOT NULL,
  requester_ref text NOT NULL,
  request_sha256 text NOT NULL
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'requested'
    CHECK (status IN ('requested')),
  created_at timestamptz NOT NULL
);

CREATE INDEX effect_requests_work_created_idx
  ON volpred_ops.effect_requests (work_item_id, created_at, id);

CREATE TABLE volpred_ops.effect_outbox (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  effect_id text NOT NULL UNIQUE
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'claimed')),
  available_at timestamptz NOT NULL,
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  claimed_by text,
  claim_token text,
  claim_expires_at timestamptz,
  created_at timestamptz NOT NULL,
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
  )
);

CREATE INDEX effect_outbox_ready_idx
  ON volpred_ops.effect_outbox (available_at, sequence)
  WHERE status = 'pending';

CREATE INDEX effect_outbox_claim_expiry_idx
  ON volpred_ops.effect_outbox (claim_expires_at, sequence)
  WHERE status = 'claimed';

CREATE VIEW volpred_ops.effect_request_reads AS
SELECT
  id, idempotency_key, work_item_id, work_item_version, effect_kind,
  target_ref, payload_ref, payload_sha256, risk, acknowledgement_kind,
  acknowledgement_target_ref, requester_ref, request_sha256, status,
  created_at
FROM volpred_ops.effect_requests;

CREATE VIEW volpred_ops.effect_outbox_reads AS
SELECT
  sequence, effect_id, status, available_at, attempt_count, claimed_by,
  claim_expires_at, created_at
FROM volpred_ops.effect_outbox;

ALTER TABLE volpred_ops.effect_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_outbox FORCE ROW LEVEL SECURITY;

REVOKE ALL ON volpred_ops.effect_requests, volpred_ops.effect_outbox
  FROM PUBLIC;
REVOKE ALL ON volpred_ops.effect_request_reads,
  volpred_ops.effect_outbox_reads FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_ops FROM PUBLIC;

GRANT SELECT ON volpred_ops.effect_request_reads,
  volpred_ops.effect_outbox_reads TO volpred_ops_worker;
GRANT SELECT, INSERT ON volpred_ops.effect_requests,
  volpred_ops.effect_outbox TO volpred_ops_definer;
GRANT UPDATE ON volpred_ops.effect_outbox TO volpred_ops_definer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA volpred_ops
  TO volpred_ops_definer;

CREATE POLICY effect_requests_worker_select
  ON volpred_ops.effect_requests FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY effect_outbox_worker_select
  ON volpred_ops.effect_outbox FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY effect_requests_definer_select
  ON volpred_ops.effect_requests FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY effect_requests_definer_insert
  ON volpred_ops.effect_requests FOR INSERT TO volpred_ops_definer
  WITH CHECK (true);
CREATE POLICY effect_outbox_definer_select
  ON volpred_ops.effect_outbox FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY effect_outbox_definer_insert
  ON volpred_ops.effect_outbox FOR INSERT TO volpred_ops_definer
  WITH CHECK (true);
CREATE POLICY effect_outbox_definer_update
  ON volpred_ops.effect_outbox FOR UPDATE TO volpred_ops_definer
  USING (true) WITH CHECK (true);

CREATE FUNCTION volpred_ops.request_effect(
  p_id text,
  p_idempotency_key text,
  p_work_item_id text,
  p_work_item_version integer,
  p_effect_kind text,
  p_target_ref text,
  p_payload_ref text,
  p_payload_sha256 text,
  p_risk text,
  p_acknowledgement_kind text,
  p_acknowledgement_target_ref text,
  p_requester_ref text,
  p_request_sha256 text
)
RETURNS SETOF volpred_ops.effect_request_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  effect volpred_ops.effect_requests;
  work_version integer;
  event_at timestamptz;
BEGIN
  IF p_id IS NULL OR btrim(p_id) = ''
      OR p_idempotency_key IS NULL OR btrim(p_idempotency_key) = ''
      OR p_effect_kind IS NULL OR btrim(p_effect_kind) = ''
      OR p_target_ref IS NULL OR btrim(p_target_ref) = ''
      OR p_payload_ref IS NULL OR btrim(p_payload_ref) = ''
      OR p_acknowledgement_kind IS NULL
      OR btrim(p_acknowledgement_kind) = ''
      OR p_acknowledgement_target_ref IS NULL
      OR btrim(p_acknowledgement_target_ref) = ''
      OR p_requester_ref IS NULL OR btrim(p_requester_ref) = '' THEN
    RAISE EXCEPTION 'effect request fields are required';
  ELSIF p_work_item_version IS NULL OR p_work_item_version <= 0 THEN
    RAISE EXCEPTION 'effect work item version must be positive';
  ELSIF p_payload_sha256 !~ '^[0-9a-f]{64}$'
      OR p_request_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'effect request hashes must be lowercase SHA-256';
  ELSIF p_risk NOT IN ('safe', 'sensitive', 'destructive') THEN
    RAISE EXCEPTION 'unsupported effect risk: %', p_risk;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_idempotency_key, 0));
  SELECT * INTO effect
  FROM volpred_ops.effect_requests
  WHERE idempotency_key = p_idempotency_key;
  IF effect.id IS NOT NULL THEN
    IF effect.request_sha256 <> p_request_sha256 THEN
      RAISE EXCEPTION
        'effect request idempotency key conflicts with its original payload';
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.effect_request_reads WHERE id = effect.id;
    RETURN;
  END IF;

  SELECT version INTO work_version
  FROM volpred_ops.work_items
  WHERE id = p_work_item_id
  FOR KEY SHARE;
  IF work_version IS NULL THEN
    RAISE EXCEPTION 'unknown effect work item: %', p_work_item_id;
  ELSIF work_version <> p_work_item_version THEN
    RAISE EXCEPTION 'stale effect work item version: expected %, found %',
      p_work_item_version, work_version;
  END IF;

  event_at := clock_timestamp();
  INSERT INTO volpred_ops.effect_requests (
    id, idempotency_key, work_item_id, work_item_version, effect_kind,
    target_ref, payload_ref, payload_sha256, risk, acknowledgement_kind,
    acknowledgement_target_ref, requester_ref, request_sha256, created_at
  )
  VALUES (
    p_id, p_idempotency_key, p_work_item_id, p_work_item_version, p_effect_kind,
    p_target_ref, p_payload_ref, p_payload_sha256, p_risk,
    p_acknowledgement_kind, p_acknowledgement_target_ref, p_requester_ref,
    p_request_sha256, event_at
  )
  RETURNING * INTO effect;

  INSERT INTO volpred_ops.effect_outbox (
    effect_id, available_at, created_at
  )
  VALUES (effect.id, event_at, event_at);

  RETURN QUERY
  SELECT * FROM volpred_ops.effect_request_reads WHERE id = effect.id;
END;
$$;

CREATE FUNCTION volpred_ops.claim_effect_outbox(
  p_worker_id text,
  p_lease_seconds integer,
  p_token text
)
RETURNS SETOF volpred_ops.effect_outbox_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  message volpred_ops.effect_outbox;
BEGIN
  IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_token IS NULL OR btrim(p_token) = '' THEN
    RAISE EXCEPTION 'effect outbox worker and token are required';
  ELSIF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
    RAISE EXCEPTION 'effect outbox lease_seconds must be positive';
  END IF;

  SELECT * INTO message
  FROM volpred_ops.effect_outbox
  WHERE available_at <= clock_timestamp()
    AND (
      status = 'pending'
      OR (
        status = 'claimed'
        AND claim_expires_at IS NOT NULL
        AND claim_expires_at <= clock_timestamp()
      )
    )
  ORDER BY available_at, sequence
  FOR UPDATE SKIP LOCKED
  LIMIT 1;

  IF message.sequence IS NULL THEN
    RETURN;
  END IF;

  UPDATE volpred_ops.effect_outbox
  SET status = 'claimed',
      attempt_count = attempt_count + 1,
      claimed_by = p_worker_id,
      claim_token = p_token,
      claim_expires_at =
        clock_timestamp() + make_interval(secs => p_lease_seconds)
  WHERE sequence = message.sequence
  RETURNING * INTO message;

  RETURN QUERY
  SELECT * FROM volpred_ops.effect_outbox_reads
  WHERE sequence = message.sequence;
END;
$$;

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

ALTER TABLE volpred_ops.effect_requests OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.effect_outbox OWNER TO volpred_ops_definer;
ALTER SEQUENCE volpred_ops.effect_outbox_sequence_seq
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.effect_request_reads OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.effect_outbox_reads OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.request_effect(
  text, text, text, integer, text, text, text, text, text, text, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.claim_effect_outbox(text, integer, text)
  OWNER TO volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;

REVOKE ALL ON FUNCTION volpred_ops.request_effect(
  text, text, text, integer, text, text, text, text, text, text, text, text, text
), volpred_ops.claim_effect_outbox(text, integer, text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION volpred_ops.request_effect(
  text, text, text, integer, text, text, text, text, text, text, text, text, text
), volpred_ops.claim_effect_outbox(text, integer, text)
TO volpred_ops_worker;
