-- Durable effect payloads plus DB-clock Primary Authority leases.
--
-- Payload bytes remain in the private volpred_ops schema and are reachable
-- only through named functions. Primary fencing tokens are stored only as
-- SHA-256 digests. Effect grants atomically verify both the current primary
-- lease and the exact outbox claim, then settlement is guarded by a trigger
-- that requires the matching durable grant.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.effect_payloads (
  payload_ref text PRIMARY KEY,
  payload_bytes bytea NOT NULL,
  payload_sha256 text NOT NULL
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  writer_ref text NOT NULL,
  created_at timestamptz NOT NULL,
  CHECK (byte_size = octet_length(payload_bytes)),
  CHECK (
    payload_sha256 = encode(sha256(payload_bytes), 'hex')
  )
);

CREATE OR REPLACE VIEW volpred_ops.effect_payload_reads AS
SELECT payload_ref, payload_sha256, byte_size, writer_ref, created_at
FROM volpred_ops.effect_payloads;

CREATE TABLE IF NOT EXISTS volpred_ops.primary_authority_leases (
  authority_key text PRIMARY KEY,
  epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
  holder_ref text,
  fencing_token_sha256 text,
  acquired_at timestamptz,
  lease_expires_at timestamptz,
  updated_at timestamptz NOT NULL,
  CHECK (
    (
      holder_ref IS NULL
      AND fencing_token_sha256 IS NULL
      AND acquired_at IS NULL
      AND lease_expires_at IS NULL
    )
    OR
    (
      btrim(holder_ref) <> ''
      AND fencing_token_sha256 ~ '^[0-9a-f]{64}$'
      AND acquired_at IS NOT NULL
      AND lease_expires_at > acquired_at
      AND epoch > 0
    )
  )
);

CREATE OR REPLACE VIEW volpred_ops.primary_authority_lease_reads AS
SELECT
  authority_key, epoch, holder_ref, acquired_at, lease_expires_at, updated_at
FROM volpred_ops.primary_authority_leases;

CREATE TABLE IF NOT EXISTS volpred_ops.primary_authority_grants (
  request_sha256 text PRIMARY KEY
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  authority_key text NOT NULL,
  epoch bigint NOT NULL CHECK (epoch > 0),
  holder_ref text NOT NULL,
  resource_ref text NOT NULL,
  primary_authority_ref text NOT NULL,
  granted_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS primary_authority_grants_authority_epoch_idx
  ON volpred_ops.primary_authority_grants (
    authority_key, epoch, granted_at, request_sha256
  );

CREATE OR REPLACE VIEW volpred_ops.primary_authority_grant_reads AS
SELECT
  request_sha256, authority_key, epoch, holder_ref, resource_ref,
  primary_authority_ref, granted_at
FROM volpred_ops.primary_authority_grants;

CREATE TABLE IF NOT EXISTS volpred_ops.primary_authority_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  authority_key text NOT NULL,
  epoch bigint NOT NULL CHECK (epoch > 0),
  holder_ref text NOT NULL,
  fencing_token_sha256 text NOT NULL
    CHECK (fencing_token_sha256 ~ '^[0-9a-f]{64}$'),
  primary_authority_ref text NOT NULL,
  released_at timestamptz NOT NULL,
  UNIQUE (authority_key, epoch)
);

CREATE OR REPLACE VIEW volpred_ops.primary_authority_receipt_reads AS
SELECT
  authority_key, epoch, holder_ref, primary_authority_ref, released_at
FROM volpred_ops.primary_authority_receipts;

CREATE TABLE IF NOT EXISTS volpred_ops.effect_authority_grants (
  request_sha256 text PRIMARY KEY
    REFERENCES volpred_ops.primary_authority_grants(request_sha256)
    ON DELETE RESTRICT,
  effect_id text NOT NULL
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  effect_request_sha256 text NOT NULL
    CHECK (effect_request_sha256 ~ '^[0-9a-f]{64}$'),
  outbox_sequence bigint NOT NULL
    REFERENCES volpred_ops.effect_outbox(sequence) ON DELETE RESTRICT,
  attempt_count integer NOT NULL CHECK (attempt_count > 0),
  worker_id text NOT NULL,
  outbox_claim_ref text NOT NULL,
  primary_authority_ref text NOT NULL,
  granted_at timestamptz NOT NULL,
  UNIQUE (outbox_sequence, attempt_count)
);

CREATE INDEX IF NOT EXISTS effect_authority_grants_effect_idx
  ON volpred_ops.effect_authority_grants (
    effect_id, attempt_count, request_sha256
  );

CREATE OR REPLACE VIEW volpred_ops.effect_authority_grant_reads AS
SELECT
  request_sha256, effect_id, effect_request_sha256, outbox_sequence,
  attempt_count, worker_id, outbox_claim_ref, primary_authority_ref, granted_at
FROM volpred_ops.effect_authority_grants;

ALTER TABLE volpred_ops.effect_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_authority_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_payloads FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_leases FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.effect_authority_grants FORCE ROW LEVEL SECURITY;

REVOKE ALL ON
  volpred_ops.effect_payloads,
  volpred_ops.primary_authority_leases,
  volpred_ops.primary_authority_grants,
  volpred_ops.primary_authority_receipts,
  volpred_ops.effect_authority_grants
FROM PUBLIC;
REVOKE ALL ON
  volpred_ops.effect_payload_reads,
  volpred_ops.primary_authority_lease_reads,
  volpred_ops.primary_authority_grant_reads,
  volpred_ops.primary_authority_receipt_reads,
  volpred_ops.effect_authority_grant_reads
FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_ops FROM PUBLIC;

GRANT SELECT, INSERT ON
  volpred_ops.effect_payloads,
  volpred_ops.primary_authority_grants,
  volpred_ops.primary_authority_receipts,
  volpred_ops.effect_authority_grants
TO volpred_ops_definer;
GRANT SELECT, INSERT, UPDATE ON volpred_ops.primary_authority_leases
  TO volpred_ops_definer;
GRANT SELECT ON
  volpred_ops.primary_authority_lease_reads,
  volpred_ops.primary_authority_grant_reads,
  volpred_ops.primary_authority_receipt_reads,
  volpred_ops.effect_authority_grant_reads
TO volpred_ops_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA volpred_ops
  TO volpred_ops_definer;

DROP POLICY IF EXISTS effect_payloads_definer_select
  ON volpred_ops.effect_payloads;
CREATE POLICY effect_payloads_definer_select
  ON volpred_ops.effect_payloads FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS effect_payloads_definer_insert
  ON volpred_ops.effect_payloads;
CREATE POLICY effect_payloads_definer_insert
  ON volpred_ops.effect_payloads FOR INSERT TO volpred_ops_definer
  WITH CHECK (true);
DROP POLICY IF EXISTS primary_authority_leases_definer_select
  ON volpred_ops.primary_authority_leases;
CREATE POLICY primary_authority_leases_definer_select
  ON volpred_ops.primary_authority_leases
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS primary_authority_leases_definer_insert
  ON volpred_ops.primary_authority_leases;
CREATE POLICY primary_authority_leases_definer_insert
  ON volpred_ops.primary_authority_leases
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS primary_authority_leases_definer_update
  ON volpred_ops.primary_authority_leases;
CREATE POLICY primary_authority_leases_definer_update
  ON volpred_ops.primary_authority_leases
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS primary_authority_grants_definer_select
  ON volpred_ops.primary_authority_grants;
CREATE POLICY primary_authority_grants_definer_select
  ON volpred_ops.primary_authority_grants
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS primary_authority_grants_definer_insert
  ON volpred_ops.primary_authority_grants;
CREATE POLICY primary_authority_grants_definer_insert
  ON volpred_ops.primary_authority_grants
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS primary_authority_receipts_definer_select
  ON volpred_ops.primary_authority_receipts;
CREATE POLICY primary_authority_receipts_definer_select
  ON volpred_ops.primary_authority_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS primary_authority_receipts_definer_insert
  ON volpred_ops.primary_authority_receipts;
CREATE POLICY primary_authority_receipts_definer_insert
  ON volpred_ops.primary_authority_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS effect_authority_grants_definer_select
  ON volpred_ops.effect_authority_grants;
CREATE POLICY effect_authority_grants_definer_select
  ON volpred_ops.effect_authority_grants
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS effect_authority_grants_definer_insert
  ON volpred_ops.effect_authority_grants;
CREATE POLICY effect_authority_grants_definer_insert
  ON volpred_ops.effect_authority_grants
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE OR REPLACE FUNCTION volpred_ops.put_effect_payload(
  p_payload_ref text,
  p_payload_bytes bytea,
  p_payload_sha256 text,
  p_writer_ref text
)
RETURNS SETOF volpred_ops.effect_payload_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  payload volpred_ops.effect_payloads;
  observed_sha256 text;
BEGIN
  IF p_payload_ref IS NULL OR btrim(p_payload_ref) = ''
      OR p_payload_bytes IS NULL
      OR p_writer_ref IS NULL OR btrim(p_writer_ref) = '' THEN
    RAISE EXCEPTION 'effect payload fields are required';
  ELSIF p_payload_sha256 IS NULL
      OR p_payload_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'effect payload hash must be lowercase SHA-256';
  END IF;

  observed_sha256 := encode(sha256(p_payload_bytes), 'hex');
  IF observed_sha256 <> p_payload_sha256 THEN
    RAISE EXCEPTION 'effect payload hash does not match its bytes';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(btrim(p_payload_ref), 0));
  SELECT * INTO payload
  FROM volpred_ops.effect_payloads
  WHERE payload_ref = btrim(p_payload_ref);
  IF payload.payload_ref IS NOT NULL THEN
    IF payload.payload_sha256 <> p_payload_sha256
        OR payload.payload_bytes <> p_payload_bytes
        OR payload.writer_ref <> btrim(p_writer_ref) THEN
      RAISE EXCEPTION
        'effect payload ref conflicts with its original bytes';
    END IF;
  ELSE
    INSERT INTO volpred_ops.effect_payloads (
      payload_ref, payload_bytes, payload_sha256, byte_size,
      writer_ref, created_at
    )
    VALUES (
      btrim(p_payload_ref), p_payload_bytes, p_payload_sha256,
      octet_length(p_payload_bytes), btrim(p_writer_ref), clock_timestamp()
    )
    RETURNING * INTO payload;
  END IF;

  RETURN QUERY
  SELECT * FROM volpred_ops.effect_payload_reads
  WHERE payload_ref = payload.payload_ref;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.read_effect_payload(p_payload_ref text)
RETURNS bytea
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  payload bytea;
BEGIN
  IF p_payload_ref IS NULL OR btrim(p_payload_ref) = '' THEN
    RAISE EXCEPTION 'effect payload fields are required';
  END IF;
  SELECT payload_bytes INTO payload
  FROM volpred_ops.effect_payloads
  WHERE payload_ref = btrim(p_payload_ref);
  IF payload IS NULL THEN
    RAISE EXCEPTION 'unknown effect payload: %', btrim(p_payload_ref);
  END IF;
  RETURN payload;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.verify_durable_effect_payload()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  payload volpred_ops.effect_payloads;
BEGIN
  IF NEW.payload_ref LIKE 'effect-payload:%' THEN
    SELECT * INTO payload
    FROM volpred_ops.effect_payloads AS stored
    WHERE stored.payload_ref = NEW.payload_ref;
    IF payload.payload_ref IS NULL THEN
      RAISE EXCEPTION 'unknown effect payload: %', NEW.payload_ref;
    ELSIF payload.payload_sha256 <> NEW.payload_sha256 THEN
      RAISE EXCEPTION
        'effect payload hash does not match its durable bytes';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS verify_durable_effect_payload
  ON volpred_ops.effect_requests;
CREATE TRIGGER verify_durable_effect_payload
BEFORE INSERT ON volpred_ops.effect_requests
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.verify_durable_effect_payload();

CREATE OR REPLACE FUNCTION volpred_ops.acquire_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS SETOF volpred_ops.primary_authority_lease_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  event_at timestamptz;
  token_sha256 text;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = ''
      OR p_holder_ref IS NULL OR btrim(p_holder_ref) = ''
      OR p_fencing_token IS NULL OR btrim(p_fencing_token) = '' THEN
    RAISE EXCEPTION 'Primary Authority fields are required';
  ELSIF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
    RAISE EXCEPTION 'Primary Authority lease_seconds must be positive';
  END IF;
  event_at := clock_timestamp();
  token_sha256 :=
    encode(sha256(convert_to(p_fencing_token, 'UTF8')), 'hex');
  PERFORM pg_advisory_xact_lock(
    hashtextextended('primary:' || btrim(p_authority_key), 0)
  );
  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;

  IF authority.authority_key IS NULL THEN
    INSERT INTO volpred_ops.primary_authority_leases (
      authority_key, epoch, holder_ref, fencing_token_sha256,
      acquired_at, lease_expires_at, updated_at
    )
    VALUES (
      btrim(p_authority_key), 1, btrim(p_holder_ref), token_sha256,
      event_at, event_at + make_interval(secs => p_lease_seconds), event_at
    )
    RETURNING * INTO authority;
  ELSIF authority.holder_ref IS NOT NULL
      AND authority.lease_expires_at > event_at THEN
    IF authority.holder_ref <> btrim(p_holder_ref)
        OR authority.fencing_token_sha256 <> token_sha256 THEN
      RAISE EXCEPTION 'Primary Authority is already held: %',
        btrim(p_authority_key);
    END IF;
  ELSE
    UPDATE volpred_ops.primary_authority_leases
    SET epoch = epoch + 1,
        holder_ref = btrim(p_holder_ref),
        fencing_token_sha256 = token_sha256,
        acquired_at = event_at,
        lease_expires_at =
          event_at + make_interval(secs => p_lease_seconds),
        updated_at = event_at
    WHERE authority_key = authority.authority_key
    RETURNING * INTO authority;
  END IF;

  RETURN QUERY
  SELECT * FROM volpred_ops.primary_authority_lease_reads
  WHERE authority_key = authority.authority_key;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.renew_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS SETOF volpred_ops.primary_authority_lease_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  event_at timestamptz;
  token_sha256 text;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = ''
      OR p_holder_ref IS NULL OR btrim(p_holder_ref) = ''
      OR p_fencing_token IS NULL OR btrim(p_fencing_token) = '' THEN
    RAISE EXCEPTION 'Primary Authority fields are required';
  ELSIF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
    RAISE EXCEPTION 'Primary Authority lease_seconds must be positive';
  END IF;
  event_at := clock_timestamp();
  token_sha256 :=
    encode(sha256(convert_to(p_fencing_token, 'UTF8')), 'hex');
  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;
  IF authority.authority_key IS NULL
      OR authority.holder_ref IS DISTINCT FROM btrim(p_holder_ref)
      OR authority.fencing_token_sha256 IS DISTINCT FROM token_sha256 THEN
    RAISE EXCEPTION 'Primary Authority lease lost: %',
      btrim(p_authority_key);
  ELSIF authority.epoch <> p_epoch THEN
    RAISE EXCEPTION 'Primary Authority epoch mismatch: expected %, found %',
      p_epoch, authority.epoch;
  ELSIF authority.lease_expires_at <= event_at THEN
    RAISE EXCEPTION 'Primary Authority lease expired: %',
      btrim(p_authority_key);
  END IF;
  UPDATE volpred_ops.primary_authority_leases
  SET lease_expires_at =
        event_at + make_interval(secs => p_lease_seconds),
      updated_at = event_at
  WHERE authority_key = authority.authority_key
  RETURNING * INTO authority;
  RETURN QUERY
  SELECT * FROM volpred_ops.primary_authority_lease_reads
  WHERE authority_key = authority.authority_key;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.authorize_primary_write(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text,
  p_request_sha256 text,
  p_resource_ref text
)
RETURNS SETOF volpred_ops.primary_authority_grant_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  existing volpred_ops.primary_authority_grants;
  token_sha256 text;
  authority_ref text;
  event_at timestamptz;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = ''
      OR p_holder_ref IS NULL OR btrim(p_holder_ref) = ''
      OR p_fencing_token IS NULL OR btrim(p_fencing_token) = ''
      OR p_resource_ref IS NULL OR btrim(p_resource_ref) = '' THEN
    RAISE EXCEPTION 'Primary Authority fields are required';
  ELSIF p_request_sha256 IS NULL
      OR p_request_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'Primary Authority request hash must be lowercase SHA-256';
  END IF;
  event_at := clock_timestamp();
  token_sha256 :=
    encode(sha256(convert_to(p_fencing_token, 'UTF8')), 'hex');
  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;
  IF authority.authority_key IS NULL
      OR authority.holder_ref IS DISTINCT FROM btrim(p_holder_ref)
      OR authority.fencing_token_sha256 IS DISTINCT FROM token_sha256 THEN
    RAISE EXCEPTION 'Primary Authority lease lost: %',
      btrim(p_authority_key);
  ELSIF authority.epoch <> p_epoch THEN
    RAISE EXCEPTION 'Primary Authority epoch mismatch: expected %, found %',
      p_epoch, authority.epoch;
  ELSIF authority.lease_expires_at <= event_at THEN
    RAISE EXCEPTION 'Primary Authority lease expired: %',
      btrim(p_authority_key);
  END IF;

  authority_ref :=
    'primary-authority:' || authority.authority_key
    || ':epoch-' || authority.epoch::text;
  INSERT INTO volpred_ops.primary_authority_grants (
    request_sha256, authority_key, epoch, holder_ref, resource_ref,
    primary_authority_ref, granted_at
  )
  VALUES (
    p_request_sha256, authority.authority_key, authority.epoch,
    authority.holder_ref, btrim(p_resource_ref), authority_ref, event_at
  )
  ON CONFLICT (request_sha256) DO NOTHING;

  SELECT * INTO existing
  FROM volpred_ops.primary_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF existing.authority_key <> authority.authority_key
      OR existing.epoch <> authority.epoch
      OR existing.holder_ref <> authority.holder_ref
      OR existing.resource_ref <> btrim(p_resource_ref)
      OR existing.primary_authority_ref <> authority_ref THEN
    RAISE EXCEPTION
      'Primary Authority grant conflicts with its original intent';
  END IF;
  RETURN QUERY
  SELECT * FROM volpred_ops.primary_authority_grant_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.release_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text
)
RETURNS SETOF volpred_ops.primary_authority_receipt_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  existing volpred_ops.primary_authority_receipts;
  token_sha256 text;
  authority_ref text;
  event_at timestamptz;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = ''
      OR p_holder_ref IS NULL OR btrim(p_holder_ref) = ''
      OR p_fencing_token IS NULL OR btrim(p_fencing_token) = '' THEN
    RAISE EXCEPTION 'Primary Authority fields are required';
  END IF;
  token_sha256 :=
    encode(sha256(convert_to(p_fencing_token, 'UTF8')), 'hex');
  SELECT * INTO existing
  FROM volpred_ops.primary_authority_receipts
  WHERE authority_key = btrim(p_authority_key)
    AND epoch = p_epoch;
  IF existing.authority_key IS NOT NULL THEN
    IF existing.holder_ref <> btrim(p_holder_ref)
        OR existing.fencing_token_sha256 <> token_sha256 THEN
      RAISE EXCEPTION 'Primary Authority lease lost: %',
        btrim(p_authority_key);
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.primary_authority_receipt_reads
    WHERE authority_key = existing.authority_key
      AND epoch = existing.epoch;
    RETURN;
  END IF;

  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;
  IF authority.authority_key IS NULL
      OR authority.holder_ref IS DISTINCT FROM btrim(p_holder_ref)
      OR authority.fencing_token_sha256 IS DISTINCT FROM token_sha256 THEN
    RAISE EXCEPTION 'Primary Authority lease lost: %',
      btrim(p_authority_key);
  ELSIF authority.epoch <> p_epoch THEN
    RAISE EXCEPTION 'Primary Authority epoch mismatch: expected %, found %',
      p_epoch, authority.epoch;
  END IF;
  event_at := clock_timestamp();
  authority_ref :=
    'primary-authority:' || authority.authority_key
    || ':epoch-' || authority.epoch::text;
  INSERT INTO volpred_ops.primary_authority_receipts (
    authority_key, epoch, holder_ref, fencing_token_sha256,
    primary_authority_ref, released_at
  )
  VALUES (
    authority.authority_key, authority.epoch, authority.holder_ref,
    authority.fencing_token_sha256, authority_ref, event_at
  )
  RETURNING * INTO existing;
  UPDATE volpred_ops.primary_authority_leases
  SET holder_ref = NULL,
      fencing_token_sha256 = NULL,
      acquired_at = NULL,
      lease_expires_at = NULL,
      updated_at = event_at
  WHERE authority_key = authority.authority_key;
  RETURN QUERY
  SELECT * FROM volpred_ops.primary_authority_receipt_reads
  WHERE authority_key = existing.authority_key
    AND epoch = existing.epoch;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.authorize_effect_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_request_sha256 text,
  p_effect_id text,
  p_effect_request_sha256 text,
  p_work_item_id text,
  p_work_item_version integer,
  p_outbox_sequence bigint,
  p_attempt_count integer,
  p_outbox_claim_token text,
  p_outbox_claim_expires_at timestamptz,
  p_worker_id text,
  p_effect_kind text,
  p_target_ref text,
  p_payload_ref text,
  p_payload_sha256 text,
  p_acknowledgement_kind text,
  p_acknowledgement_target_ref text
)
RETURNS SETOF volpred_ops.effect_authority_grant_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  message volpred_ops.effect_outbox;
  effect volpred_ops.effect_requests;
  primary_grant volpred_ops.primary_authority_grant_reads;
  existing volpred_ops.effect_authority_grants;
  claim_ref text;
BEGIN
  IF p_effect_id IS NULL OR btrim(p_effect_id) = ''
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_outbox_claim_token IS NULL
      OR btrim(p_outbox_claim_token) = '' THEN
    RAISE EXCEPTION 'effect authority fields are required';
  ELSIF p_outbox_sequence IS NULL OR p_outbox_sequence <= 0
      OR p_attempt_count IS NULL OR p_attempt_count <= 0 THEN
    RAISE EXCEPTION 'effect authority attempt identity is invalid';
  ELSIF p_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_effect_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_payload_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'effect authority hashes must be lowercase SHA-256';
  END IF;

  SELECT * INTO message
  FROM volpred_ops.effect_outbox
  WHERE sequence = p_outbox_sequence
    AND effect_id = btrim(p_effect_id)
  FOR UPDATE;
  IF message.sequence IS NULL THEN
    RAISE EXCEPTION 'effect authority outbox claim is unknown';
  ELSIF message.status <> 'claimed'
      OR message.claimed_by <> btrim(p_worker_id)
      OR message.claim_token <> p_outbox_claim_token
      OR message.attempt_count <> p_attempt_count
      OR message.claim_expires_at IS DISTINCT FROM p_outbox_claim_expires_at
      OR message.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'effect authority outbox claim is stale';
  END IF;

  SELECT * INTO effect
  FROM volpred_ops.effect_requests
  WHERE id = message.effect_id
  FOR KEY SHARE;
  IF effect.id IS NULL
      OR effect.request_sha256 <> p_effect_request_sha256
      OR effect.work_item_id <> btrim(p_work_item_id)
      OR effect.work_item_version <> p_work_item_version
      OR effect.effect_kind <> btrim(p_effect_kind)
      OR effect.target_ref <> btrim(p_target_ref)
      OR effect.payload_ref <> btrim(p_payload_ref)
      OR effect.payload_sha256 <> p_payload_sha256
      OR effect.acknowledgement_kind <> btrim(p_acknowledgement_kind)
      OR effect.acknowledgement_target_ref
        <> btrim(p_acknowledgement_target_ref) THEN
    RAISE EXCEPTION 'effect authority request does not match durable intent';
  END IF;

  claim_ref :=
    'effect-outbox:' || message.sequence::text
    || ':attempt-' || message.attempt_count::text;
  SELECT * INTO primary_grant
  FROM volpred_ops.authorize_primary_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_request_sha256,
    claim_ref
  );

  INSERT INTO volpred_ops.effect_authority_grants (
    request_sha256, effect_id, effect_request_sha256, outbox_sequence,
    attempt_count, worker_id, outbox_claim_ref, primary_authority_ref,
    granted_at
  )
  VALUES (
    p_request_sha256, effect.id, effect.request_sha256, message.sequence,
    message.attempt_count, message.claimed_by, claim_ref,
    primary_grant.primary_authority_ref, primary_grant.granted_at
  )
  ON CONFLICT (request_sha256) DO NOTHING;
  SELECT * INTO existing
  FROM volpred_ops.effect_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF existing.effect_id <> effect.id
      OR existing.effect_request_sha256 <> effect.request_sha256
      OR existing.outbox_sequence <> message.sequence
      OR existing.attempt_count <> message.attempt_count
      OR existing.worker_id <> message.claimed_by
      OR existing.outbox_claim_ref <> claim_ref
      OR existing.primary_authority_ref
        <> primary_grant.primary_authority_ref THEN
    RAISE EXCEPTION
      'effect authority grant conflicts with its original intent';
  END IF;
  RETURN QUERY
  SELECT * FROM volpred_ops.effect_authority_grant_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.require_effect_authority_grant()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.effect_authority_grants;
BEGIN
  SELECT * INTO authority
  FROM volpred_ops.effect_authority_grants
  WHERE request_sha256 = NEW.authority_request_sha256;
  IF authority.request_sha256 IS NULL
      OR authority.effect_id <> NEW.effect_id
      OR authority.outbox_sequence <> NEW.outbox_sequence
      OR authority.attempt_count <> NEW.attempt_count
      OR authority.worker_id <> NEW.worker_id
      OR authority.outbox_claim_ref <> NEW.outbox_claim_ref
      OR authority.primary_authority_ref <> NEW.primary_authority_ref THEN
    RAISE EXCEPTION
      'effect authority grant is missing or does not match settlement';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS require_effect_authority_grant
  ON volpred_ops.effect_attempt_receipts;
CREATE TRIGGER require_effect_authority_grant
BEFORE INSERT ON volpred_ops.effect_attempt_receipts
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.require_effect_authority_grant();

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER TABLE volpred_ops.effect_payloads OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.primary_authority_leases OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.primary_authority_grants OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.primary_authority_receipts OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.effect_authority_grants OWNER TO volpred_ops_definer;
ALTER SEQUENCE volpred_ops.primary_authority_receipts_sequence_seq
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.effect_payload_reads OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.primary_authority_lease_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.primary_authority_grant_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.primary_authority_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.effect_authority_grant_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.put_effect_payload(text, bytea, text, text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.read_effect_payload(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.verify_durable_effect_payload()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.acquire_primary_authority(text, text, integer, text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.renew_primary_authority(
  text, text, bigint, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.authorize_primary_write(
  text, text, bigint, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.release_primary_authority(
  text, text, bigint, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.authorize_effect_write(
  text, text, bigint, text, text, text, text, text, integer,
  bigint, integer, text, timestamptz, text, text, text, text, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.require_effect_authority_grant()
  OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  volpred_ops.put_effect_payload(text, bytea, text, text),
  volpred_ops.read_effect_payload(text),
  volpred_ops.verify_durable_effect_payload(),
  volpred_ops.acquire_primary_authority(text, text, integer, text),
  volpred_ops.renew_primary_authority(text, text, bigint, integer, text),
  volpred_ops.authorize_primary_write(text, text, bigint, text, text, text),
  volpred_ops.release_primary_authority(text, text, bigint, text),
  volpred_ops.authorize_effect_write(
    text, text, bigint, text, text, text, text, text, integer,
    bigint, integer, text, timestamptz, text, text, text, text, text, text, text
  ),
  volpred_ops.require_effect_authority_grant()
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  volpred_ops.put_effect_payload(text, bytea, text, text),
  volpred_ops.read_effect_payload(text),
  volpred_ops.acquire_primary_authority(text, text, integer, text),
  volpred_ops.renew_primary_authority(text, text, bigint, integer, text),
  volpred_ops.authorize_primary_write(text, text, bigint, text, text, text),
  volpred_ops.release_primary_authority(text, text, bigint, text),
  volpred_ops.authorize_effect_write(
    text, text, bigint, text, text, text, text, text, integer,
    bigint, integer, text, timestamptz, text, text, text, text, text, text, text
  )
TO volpred_ops_worker;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
