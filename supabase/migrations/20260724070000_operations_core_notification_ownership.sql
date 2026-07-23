-- Production ownership transaction for the safe ops-alert email family.
--
-- State stays in the private volpred_ops schema with FORCE RLS. Four narrow
-- RPC functions live in the exposed public schema solely because the runtime
-- has a Supabase service-role key but no direct Postgres DSN. PUBLIC, anon,
-- and authenticated are explicitly denied; only service_role may execute.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.notification_owners (
  effect_family text PRIMARY KEY,
  owner text NOT NULL CHECK (owner IN ('legacy', 'operations_core')),
  generation bigint NOT NULL CHECK (generation > 0),
  changed_at timestamptz NOT NULL,
  changed_by text NOT NULL,
  change_reason text NOT NULL
);

CREATE TABLE IF NOT EXISTS volpred_ops.notification_owner_receipts (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  effect_family text NOT NULL
    REFERENCES volpred_ops.notification_owners(effect_family)
    ON DELETE RESTRICT,
  generation bigint NOT NULL CHECK (generation > 0),
  previous_owner text
    CHECK (previous_owner IS NULL OR previous_owner IN (
      'legacy', 'operations_core'
    )),
  owner text NOT NULL CHECK (owner IN ('legacy', 'operations_core')),
  actor_ref text NOT NULL,
  reason text NOT NULL,
  rollback_of_generation bigint,
  changed_at timestamptz NOT NULL,
  UNIQUE (effect_family, generation),
  CHECK (
    rollback_of_generation IS NULL OR rollback_of_generation > 0
  )
);

CREATE INDEX IF NOT EXISTS notification_owner_receipts_family_changed_idx
  ON volpred_ops.notification_owner_receipts (
    effect_family, changed_at, generation
  );

CREATE TABLE IF NOT EXISTS volpred_ops.owned_notification_requests (
  idempotency_key text PRIMARY KEY,
  effect_family text NOT NULL,
  owner_generation bigint NOT NULL CHECK (owner_generation > 0),
  work_id text NOT NULL UNIQUE
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  effect_id text NOT NULL UNIQUE
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  request_sha256 text NOT NULL
    CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
  actor_ref text NOT NULL,
  created_at timestamptz NOT NULL,
  FOREIGN KEY (effect_family, owner_generation)
    REFERENCES volpred_ops.notification_owner_receipts(
      effect_family, generation
    )
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS volpred_ops.owned_notification_attempts (
  effect_id text NOT NULL
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  attempt_count integer NOT NULL CHECK (attempt_count > 0),
  work_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  outbox_sequence bigint NOT NULL
    REFERENCES volpred_ops.effect_outbox(sequence) ON DELETE RESTRICT,
  owner_generation bigint NOT NULL CHECK (owner_generation > 0),
  worker_id text NOT NULL,
  lease_expires_at timestamptz NOT NULL,
  authority_request_sha256 text NOT NULL
    CHECK (authority_request_sha256 ~ '^[0-9a-f]{64}$'),
  outbox_claim_ref text NOT NULL,
  primary_authority_ref text NOT NULL,
  status text NOT NULL
    CHECK (
      status IN (
        'started', 'delivered', 'retry_scheduled', 'dead_lettered'
      )
    ),
  reported_outcome text,
  disposition text,
  evidence_ref text,
  evidence_sha256 text
    CHECK (
      evidence_sha256 IS NULL
      OR evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
  work_status text,
  effect_status text,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  PRIMARY KEY (effect_id, attempt_count)
);

CREATE INDEX IF NOT EXISTS owned_notification_requests_owner_generation_idx
  ON volpred_ops.owned_notification_requests (
    effect_family, owner_generation
  );

CREATE INDEX IF NOT EXISTS owned_notification_attempts_work_idx
  ON volpred_ops.owned_notification_attempts (
    work_id, attempt_count, effect_id
  );

CREATE INDEX IF NOT EXISTS owned_notification_attempts_outbox_idx
  ON volpred_ops.owned_notification_attempts (
    outbox_sequence, attempt_count
  );

CREATE INDEX IF NOT EXISTS owned_notification_attempts_active_idx
  ON volpred_ops.owned_notification_attempts (
    lease_expires_at, effect_id, attempt_count
  )
  WHERE status = 'started';

CREATE OR REPLACE VIEW volpred_ops.notification_owner_reads AS
SELECT
  effect_family, owner, generation, changed_at, changed_by, change_reason
FROM volpred_ops.notification_owners;

CREATE OR REPLACE VIEW volpred_ops.notification_owner_receipt_reads AS
SELECT
  sequence, effect_family, generation, previous_owner, owner, actor_ref,
  reason, rollback_of_generation, changed_at
FROM volpred_ops.notification_owner_receipts;

CREATE OR REPLACE VIEW volpred_ops.owned_notification_request_reads AS
SELECT
  idempotency_key, effect_family, owner_generation, work_id, effect_id,
  request_sha256, actor_ref, created_at
FROM volpred_ops.owned_notification_requests;

CREATE OR REPLACE VIEW volpred_ops.owned_notification_attempt_reads AS
SELECT
  effect_id, attempt_count, work_id, outbox_sequence, owner_generation,
  worker_id, lease_expires_at, authority_request_sha256, outbox_claim_ref,
  primary_authority_ref, status, reported_outcome, disposition, evidence_ref,
  evidence_sha256, work_status, effect_status, started_at, finished_at
FROM volpred_ops.owned_notification_attempts;

ALTER TABLE volpred_ops.notification_owners ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.notification_owner_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.owned_notification_requests
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.owned_notification_attempts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.notification_owners FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.notification_owner_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.owned_notification_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.owned_notification_attempts FORCE ROW LEVEL SECURITY;

REVOKE ALL ON
  volpred_ops.notification_owners,
  volpred_ops.notification_owner_receipts,
  volpred_ops.owned_notification_requests,
  volpred_ops.owned_notification_attempts
FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON
  volpred_ops.notification_owner_reads,
  volpred_ops.notification_owner_receipt_reads,
  volpred_ops.owned_notification_request_reads,
  volpred_ops.owned_notification_attempt_reads
FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT, INSERT, UPDATE ON
  volpred_ops.notification_owners,
  volpred_ops.owned_notification_attempts
TO volpred_ops_definer;
GRANT SELECT, INSERT ON
  volpred_ops.notification_owner_receipts,
  volpred_ops.owned_notification_requests
TO volpred_ops_definer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA volpred_ops
  TO volpred_ops_definer;

DROP POLICY IF EXISTS notification_owners_definer_all
  ON volpred_ops.notification_owners;
CREATE POLICY notification_owners_definer_all
  ON volpred_ops.notification_owners
  FOR ALL TO volpred_ops_definer USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS notification_owner_receipts_definer_select
  ON volpred_ops.notification_owner_receipts;
CREATE POLICY notification_owner_receipts_definer_select
  ON volpred_ops.notification_owner_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS notification_owner_receipts_definer_insert
  ON volpred_ops.notification_owner_receipts;
CREATE POLICY notification_owner_receipts_definer_insert
  ON volpred_ops.notification_owner_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS owned_notification_requests_definer_select
  ON volpred_ops.owned_notification_requests;
CREATE POLICY owned_notification_requests_definer_select
  ON volpred_ops.owned_notification_requests
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS owned_notification_requests_definer_insert
  ON volpred_ops.owned_notification_requests;
CREATE POLICY owned_notification_requests_definer_insert
  ON volpred_ops.owned_notification_requests
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS owned_notification_attempts_definer_all
  ON volpred_ops.owned_notification_attempts;
CREATE POLICY owned_notification_attempts_definer_all
  ON volpred_ops.owned_notification_attempts
  FOR ALL TO volpred_ops_definer USING (true) WITH CHECK (true);

INSERT INTO volpred_ops.notification_owners (
  effect_family, owner, generation, changed_at, changed_by, change_reason
)
VALUES (
  'email.ops_alert',
  'legacy',
  1,
  clock_timestamp(),
  'migration:operations_core_notification_ownership',
  'initial owner remains legacy until explicit CAS cutover'
)
ON CONFLICT (effect_family) DO NOTHING;

INSERT INTO volpred_ops.notification_owner_receipts (
  effect_family, generation, previous_owner, owner, actor_ref, reason,
  rollback_of_generation, changed_at
)
SELECT
  effect_family, generation, NULL, owner, changed_by, change_reason,
  NULL, changed_at
FROM volpred_ops.notification_owners
WHERE effect_family = 'email.ops_alert'
ON CONFLICT (effect_family, generation) DO NOTHING;

CREATE OR REPLACE FUNCTION public.volpred_read_notification_owner()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
BEGIN
  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'email.ops_alert';
  RETURN jsonb_build_object(
    'schema_version', 'notification-owner.v1',
    'effect_family', ownership.effect_family,
    'owner', ownership.owner,
    'generation', ownership.generation,
    'changed_at', ownership.changed_at,
    'changed_by', ownership.changed_by,
    'change_reason', ownership.change_reason
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_transfer_notification_owner(
  p_expected_owner text,
  p_expected_generation bigint,
  p_target_owner text,
  p_actor_ref text,
  p_reason text,
  p_rollback_of_generation bigint DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  replay volpred_ops.notification_owner_receipts;
  event_at timestamptz;
BEGIN
  IF p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'notification ownership transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation IS DISTINCT FROM p_expected_generation THEN
    RAISE EXCEPTION
      'notification ownership rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'notification ownership cutover cannot carry rollback generation';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'email.ops_alert'
  FOR UPDATE;

  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    SELECT * INTO replay
    FROM volpred_ops.notification_owner_receipts
    WHERE effect_family = ownership.effect_family
      AND generation = p_expected_generation + 1;
    IF replay.effect_family IS NULL
        OR ownership.generation <> replay.generation
        OR ownership.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'notification ownership compare-and-set failed: expected %/% found %/%',
        p_expected_owner, p_expected_generation,
        ownership.owner, ownership.generation;
    END IF;
    RETURN public.volpred_read_notification_owner();
  END IF;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.owned_notification_attempts
    WHERE status = 'started'
      AND lease_expires_at > clock_timestamp()
  ) THEN
    RAISE EXCEPTION
      'notification ownership transfer requires zero active attempts';
  END IF;

  event_at := clock_timestamp();
  UPDATE volpred_ops.notification_owners
  SET owner = p_target_owner,
      generation = generation + 1,
      changed_at = event_at,
      changed_by = btrim(p_actor_ref),
      change_reason = btrim(p_reason)
  WHERE effect_family = ownership.effect_family
  RETURNING * INTO ownership;

  INSERT INTO volpred_ops.notification_owner_receipts (
    effect_family, generation, previous_owner, owner, actor_ref, reason,
    rollback_of_generation, changed_at
  )
  VALUES (
    ownership.effect_family, ownership.generation, p_expected_owner,
    ownership.owner, ownership.changed_by, ownership.change_reason,
    p_rollback_of_generation, ownership.changed_at
  );
  RETURN public.volpred_read_notification_owner();
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_request_owned_email_notification(
  p_owner_generation bigint,
  p_idempotency_key text,
  p_level text,
  p_title text,
  p_recipient text,
  p_payload jsonb,
  p_actor_ref text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  existing volpred_ops.owned_notification_requests;
  work volpred_ops.work_item_reads;
  effect volpred_ops.effect_request_reads;
  payload_view volpred_ops.effect_payload_reads;
  payload_bytes bytea;
  payload_sha256 text;
  payload_ref text;
  work_id text;
  effect_id text;
  request_identity jsonb;
  request_sha256 text;
  event_at timestamptz;
  priority integer;
BEGIN
  IF p_owner_generation IS NULL OR p_owner_generation <= 0
      OR p_idempotency_key IS NULL OR btrim(p_idempotency_key) = ''
      OR p_level NOT IN ('info', 'warn', 'critical')
      OR p_title IS NULL OR btrim(p_title) = ''
      OR p_recipient IS NULL OR btrim(p_recipient) = ''
      OR p_recipient !~ '^[^[:space:]@,;]+@[^[:space:]@,;]+$'
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = ''
      OR jsonb_typeof(p_payload) <> 'object'
      OR (
        SELECT count(*) FROM pg_catalog.jsonb_object_keys(p_payload)
      ) <> 4
      OR NOT p_payload ?& ARRAY[
        'schema_version', 'subject', 'text_body', 'html_body'
      ]
      OR p_payload ->> 'schema_version' <> 'email-notification.v1'
      OR p_payload ->> 'subject' <> p_title
      OR coalesce(btrim(p_payload ->> 'text_body'), '') = ''
      OR (
        p_payload -> 'html_body' <> 'null'::jsonb
        AND jsonb_typeof(p_payload -> 'html_body') <> 'string'
      ) THEN
    RAISE EXCEPTION 'owned email notification request fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'email.ops_alert'
  FOR SHARE;
  IF ownership.owner <> 'operations_core'
      OR ownership.generation <> p_owner_generation THEN
    RAISE EXCEPTION
      'operations core does not own email.ops_alert generation %',
      p_owner_generation;
  END IF;

  request_identity := jsonb_build_object(
    'schema_version', 'owned-email-request.v1',
    'effect_family', ownership.effect_family,
    'owner_generation', ownership.generation,
    'idempotency_key', btrim(p_idempotency_key),
    'level', p_level,
    'title', p_title,
    'recipient', lower(btrim(p_recipient)),
    'payload', p_payload,
    'actor_ref', btrim(p_actor_ref)
  );
  request_sha256 := encode(
    sha256(convert_to(request_identity::text, 'UTF8')),
    'hex'
  );
  PERFORM pg_advisory_xact_lock(
    hashtextextended('owned-email:' || btrim(p_idempotency_key), 0)
  );
  SELECT * INTO existing
  FROM volpred_ops.owned_notification_requests
  WHERE idempotency_key = btrim(p_idempotency_key);
  IF existing.idempotency_key IS NOT NULL THEN
    IF existing.request_sha256 <> request_sha256
        OR existing.owner_generation <> ownership.generation THEN
      RAISE EXCEPTION
        'owned email idempotency key conflicts with original request';
    END IF;
    RETURN jsonb_build_object(
      'schema_version', 'owned-email-request.v1',
      'owner_generation', existing.owner_generation,
      'work_id', existing.work_id,
      'effect_id', existing.effect_id,
      'request_sha256', existing.request_sha256
    );
  END IF;

  work_id := 'work_owned_email_' || substr(request_sha256, 1, 32);
  effect_id := 'effect_owned_email_' || substr(request_sha256, 1, 32);
  payload_ref := 'effect-payload:' || effect_id || ':email';
  payload_bytes := convert_to(p_payload::text, 'UTF8');
  payload_sha256 := encode(sha256(payload_bytes), 'hex');
  event_at := clock_timestamp();
  priority := CASE p_level
    WHEN 'critical' THEN 1
    WHEN 'warn' THEN 2
    ELSE 3
  END;

  SELECT * INTO STRICT payload_view
  FROM volpred_ops.put_effect_payload(
    payload_ref,
    payload_bytes,
    payload_sha256,
    btrim(p_actor_ref)
  );
  SELECT * INTO STRICT work
  FROM volpred_ops.submit_work(
    work_id,
    'owned-email-work:' || btrim(p_idempotency_key),
    'ops.alerts.send_alert',
    'ops.alert.email',
    p_title,
    priority,
    ARRAY['email-effect'],
    ARRAY['sent-mail-readback'],
    'safe',
    'auto',
    payload_ref,
    NULL,
    NULL,
    btrim(p_actor_ref),
    'pending',
    1,
    event_at,
    event_at
  );
  SELECT * INTO STRICT effect
  FROM volpred_ops.request_effect(
    effect_id,
    'owned-email-effect:' || btrim(p_idempotency_key),
    work.id,
    work.version,
    'email.notification.send',
    'email:' || lower(btrim(p_recipient)),
    payload_ref,
    payload_sha256,
    'safe',
    'email.sent-mail.readback',
    'email:' || lower(btrim(p_recipient)),
    btrim(p_actor_ref),
    request_sha256
  );
  INSERT INTO volpred_ops.owned_notification_requests (
    idempotency_key, effect_family, owner_generation, work_id, effect_id,
    request_sha256, actor_ref, created_at
  )
  VALUES (
    btrim(p_idempotency_key), ownership.effect_family,
    ownership.generation, work.id, effect.id, request_sha256,
    btrim(p_actor_ref), event_at
  );
  RETURN jsonb_build_object(
    'schema_version', 'owned-email-request.v1',
    'owner_generation', ownership.generation,
    'work_id', work.id,
    'effect_id', effect.id,
    'request_sha256', request_sha256
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_begin_owned_email_notification(
  p_owner_generation bigint,
  p_effect_id text,
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
  owned_request volpred_ops.owned_notification_requests;
  work volpred_ops.work_items;
  effect volpred_ops.effect_requests;
  message volpred_ops.effect_outbox;
  primary_lease volpred_ops.primary_authority_lease_reads;
  authority_grant volpred_ops.effect_authority_grant_reads;
  event_at timestamptz;
  lease_expires_at timestamptz;
  authority_request_sha256 text;
  payload_bytes bytea;
BEGIN
  IF p_owner_generation IS NULL OR p_owner_generation <= 0
      OR p_effect_id IS NULL OR btrim(p_effect_id) = ''
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_lease_seconds IS NULL OR p_lease_seconds <= 0
      OR p_work_lease_token IS NULL OR btrim(p_work_lease_token) = ''
      OR p_outbox_claim_token IS NULL OR btrim(p_outbox_claim_token) = ''
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = '' THEN
    RAISE EXCEPTION 'owned email begin fields are invalid';
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
  SELECT * INTO STRICT owned_request
  FROM volpred_ops.owned_notification_requests
  WHERE effect_id = btrim(p_effect_id)
    AND effect_family = ownership.effect_family
    AND owner_generation = ownership.generation;

  event_at := clock_timestamp();
  lease_expires_at :=
    event_at + make_interval(secs => p_lease_seconds);
  SELECT * INTO STRICT work
  FROM volpred_ops.work_items
  WHERE id = owned_request.work_id
  FOR UPDATE;
  IF NOT (
    work.status = 'pending'
    OR (
      work.status IN ('claimed', 'running')
      AND work.claim_expires_at IS NOT NULL
      AND work.claim_expires_at <= event_at
    )
  ) THEN
    RAISE EXCEPTION 'owned email work is not available: %', work.status;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'claimed',
      version = version + 1,
      claimed_by = btrim(p_worker_id),
      claim_token = p_work_lease_token,
      claim_expires_at = lease_expires_at,
      updated_at = event_at
  WHERE id = work.id
  RETURNING * INTO work;
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref
  )
  VALUES (
    work.id, 'acquired', work.version, event_at, btrim(p_worker_id)
  );
  UPDATE volpred_ops.work_items
  SET status = 'running',
      version = version + 1,
      updated_at = event_at
  WHERE id = work.id
  RETURNING * INTO work;
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref
  )
  VALUES (
    work.id, 'started', work.version, event_at, btrim(p_worker_id)
  );

  SELECT * INTO STRICT message
  FROM volpred_ops.effect_outbox
  WHERE effect_id = owned_request.effect_id
  FOR UPDATE;
  IF message.available_at > event_at
      OR NOT (
        message.status = 'pending'
        OR (
          message.status = 'claimed'
          AND message.claim_expires_at IS NOT NULL
          AND message.claim_expires_at <= event_at
        )
      ) THEN
    RAISE EXCEPTION 'owned email effect is not available: %', message.status;
  END IF;
  UPDATE volpred_ops.effect_outbox
  SET status = 'claimed',
      attempt_count = attempt_count + 1,
      claimed_by = btrim(p_worker_id),
      claim_token = p_outbox_claim_token,
      claim_expires_at = lease_expires_at
  WHERE sequence = message.sequence
  RETURNING * INTO message;
  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_requests
  WHERE id = message.effect_id
  FOR KEY SHARE;

  SELECT * INTO STRICT primary_lease
  FROM volpred_ops.acquire_primary_authority(
    'notification:email.ops_alert',
    btrim(p_worker_id),
    p_lease_seconds,
    p_primary_fencing_token
  );
  authority_request_sha256 := encode(
    sha256(
      convert_to(
        jsonb_build_object(
          'schema_version', 'owned-email-authority.v1',
          'owner_generation', ownership.generation,
          'work_id', work.id,
          'work_version', work.version,
          'effect_id', effect.id,
          'effect_request_sha256', effect.request_sha256,
          'outbox_sequence', message.sequence,
          'attempt_count', message.attempt_count,
          'worker_id', message.claimed_by,
          'lease_expires_at', message.claim_expires_at,
          'primary_authority_key', primary_lease.authority_key,
          'primary_authority_epoch', primary_lease.epoch
        )::text,
        'UTF8'
      )
    ),
    'hex'
  );
  SELECT * INTO STRICT authority_grant
  FROM volpred_ops.authorize_effect_write(
    primary_lease.authority_key,
    primary_lease.holder_ref,
    primary_lease.epoch,
    p_primary_fencing_token,
    authority_request_sha256,
    effect.id,
    effect.request_sha256,
    effect.work_item_id,
    effect.work_item_version,
    message.sequence,
    message.attempt_count,
    p_outbox_claim_token,
    message.claim_expires_at,
    message.claimed_by,
    effect.effect_kind,
    effect.target_ref,
    effect.payload_ref,
    effect.payload_sha256,
    effect.acknowledgement_kind,
    effect.acknowledgement_target_ref
  );
  payload_bytes := volpred_ops.read_effect_payload(effect.payload_ref);
  IF encode(sha256(payload_bytes), 'hex') <> effect.payload_sha256 THEN
    RAISE EXCEPTION 'owned email durable payload hash mismatch';
  END IF;

  INSERT INTO volpred_ops.owned_notification_attempts (
    effect_id, attempt_count, work_id, outbox_sequence, owner_generation,
    worker_id, lease_expires_at, authority_request_sha256, outbox_claim_ref,
    primary_authority_ref, status, started_at
  )
  VALUES (
    effect.id, message.attempt_count, work.id, message.sequence,
    ownership.generation, message.claimed_by, lease_expires_at,
    authority_grant.request_sha256, authority_grant.outbox_claim_ref,
    authority_grant.primary_authority_ref, 'started', event_at
  );

  RETURN jsonb_build_object(
    'schema_version', 'owned-email-attempt.v1',
    'owner_generation', ownership.generation,
    'work_id', work.id,
    'work_version', work.version,
    'effect', jsonb_build_object(
      'schema_version', 'effect-request.v1',
      'id', effect.id,
      'idempotency_key', effect.idempotency_key,
      'work_item_id', effect.work_item_id,
      'work_item_version', effect.work_item_version,
      'effect_kind', effect.effect_kind,
      'target_ref', effect.target_ref,
      'payload_ref', effect.payload_ref,
      'payload_sha256', effect.payload_sha256,
      'risk', effect.risk,
      'acknowledgement', jsonb_build_object(
        'kind', effect.acknowledgement_kind,
        'target_ref', effect.acknowledgement_target_ref
      ),
      'requester_ref', effect.requester_ref,
      'request_sha256', effect.request_sha256,
      'status', effect.status,
      'created_at', effect.created_at
    ),
    'payload_base64',
      replace(encode(payload_bytes, 'base64'), E'\n', ''),
    'outbox_sequence', message.sequence,
    'attempt_count', message.attempt_count,
    'worker_id', message.claimed_by,
    'primary_authority_key', primary_lease.authority_key,
    'primary_authority_holder_ref', primary_lease.holder_ref,
    'primary_authority_epoch', primary_lease.epoch,
    'authority_request_sha256', authority_grant.request_sha256,
    'outbox_claim_ref', authority_grant.outbox_claim_ref,
    'primary_authority_ref', authority_grant.primary_authority_ref,
    'lease_expires_at', lease_expires_at
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_settle_owned_email_notification(
  p_owner_generation bigint,
  p_work_id text,
  p_work_version integer,
  p_work_lease_token text,
  p_effect_id text,
  p_outbox_sequence bigint,
  p_attempt_count integer,
  p_worker_id text,
  p_outbox_claim_token text,
  p_primary_authority_key text,
  p_primary_authority_holder_ref text,
  p_primary_authority_epoch bigint,
  p_primary_fencing_token text,
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
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  owned_attempt volpred_ops.owned_notification_attempts;
  work volpred_ops.work_items;
  effect volpred_ops.effect_requests;
  attempt_receipt volpred_ops.effect_attempt_receipt_reads;
  released_authority volpred_ops.primary_authority_receipt_reads;
  event_at timestamptz;
  terminal_status text;
  work_receipt_id text;
BEGIN
  IF p_owner_generation IS NULL OR p_owner_generation <= 0
      OR p_work_id IS NULL OR btrim(p_work_id) = ''
      OR p_work_version IS NULL OR p_work_version <= 0
      OR p_work_lease_token IS NULL OR btrim(p_work_lease_token) = ''
      OR p_effect_id IS NULL OR btrim(p_effect_id) = ''
      OR p_outbox_sequence IS NULL OR p_outbox_sequence <= 0
      OR p_attempt_count IS NULL OR p_attempt_count <= 0
      OR p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_outbox_claim_token IS NULL OR btrim(p_outbox_claim_token) = ''
      OR p_primary_authority_key IS NULL
      OR btrim(p_primary_authority_key) = ''
      OR p_primary_authority_holder_ref IS NULL
      OR btrim(p_primary_authority_holder_ref) = ''
      OR p_primary_authority_epoch IS NULL
      OR p_primary_authority_epoch <= 0
      OR p_primary_fencing_token IS NULL
      OR btrim(p_primary_fencing_token) = ''
      OR p_authority_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_outbox_claim_ref IS NULL OR btrim(p_outbox_claim_ref) = ''
      OR p_primary_authority_ref IS NULL
      OR btrim(p_primary_authority_ref) = ''
      OR p_outcome NOT IN (
        'acknowledged', 'retryable_failure', 'terminal_failure'
      )
      OR p_evidence_ref IS NULL OR btrim(p_evidence_ref) = ''
      OR p_evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'owned email settlement fields are invalid';
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
  SELECT * INTO STRICT owned_attempt
  FROM volpred_ops.owned_notification_attempts
  WHERE effect_id = btrim(p_effect_id)
    AND attempt_count = p_attempt_count
  FOR UPDATE;
  IF owned_attempt.owner_generation <> ownership.generation
      OR owned_attempt.work_id <> btrim(p_work_id)
      OR owned_attempt.outbox_sequence <> p_outbox_sequence
      OR owned_attempt.worker_id <> btrim(p_worker_id)
      OR owned_attempt.authority_request_sha256
        <> p_authority_request_sha256
      OR owned_attempt.outbox_claim_ref <> btrim(p_outbox_claim_ref)
      OR owned_attempt.primary_authority_ref
        <> btrim(p_primary_authority_ref) THEN
    RAISE EXCEPTION 'owned email attempt identity mismatch';
  END IF;
  IF owned_attempt.status <> 'started' THEN
    IF owned_attempt.reported_outcome <> p_outcome
        OR owned_attempt.evidence_ref <> btrim(p_evidence_ref)
        OR owned_attempt.evidence_sha256 <> p_evidence_sha256 THEN
      RAISE EXCEPTION
        'owned email settlement conflicts with original outcome';
    END IF;
    RETURN jsonb_build_object(
      'schema_version', 'owned-email-receipt.v1',
      'owner_generation', owned_attempt.owner_generation,
      'work_id', owned_attempt.work_id,
      'work_status', owned_attempt.work_status,
      'effect_id', owned_attempt.effect_id,
      'effect_status', owned_attempt.effect_status,
      'attempt_count', owned_attempt.attempt_count,
      'disposition', owned_attempt.disposition,
      'evidence_ref', owned_attempt.evidence_ref,
      'evidence_sha256', owned_attempt.evidence_sha256,
      'primary_authority_ref', owned_attempt.primary_authority_ref,
      'recorded_at', owned_attempt.finished_at
    );
  ELSIF owned_attempt.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'owned email attempt lease expired';
  END IF;

  SELECT * INTO STRICT work
  FROM volpred_ops.work_items
  WHERE id = owned_attempt.work_id
  FOR UPDATE;
  IF work.version <> p_work_version
      OR work.status <> 'running'
      OR work.claimed_by <> btrim(p_worker_id)
      OR work.claim_token <> p_work_lease_token
      OR work.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'notification ownership work lease lost';
  END IF;

  SELECT * INTO STRICT attempt_receipt
  FROM volpred_ops.settle_effect_outbox(
    p_outbox_sequence,
    btrim(p_effect_id),
    p_attempt_count,
    btrim(p_worker_id),
    p_outbox_claim_token,
    p_authority_request_sha256,
    btrim(p_outbox_claim_ref),
    btrim(p_primary_authority_ref),
    p_outcome,
    p_acknowledgement_kind,
    p_acknowledgement_target_ref,
    p_reason_code,
    btrim(p_evidence_ref),
    p_evidence_sha256
  );

  IF attempt_receipt.disposition = 'delivered' THEN
    work_receipt_id :=
      'owned-email-completion:' || p_effect_id
      || ':attempt-' || p_attempt_count::text;
    SELECT * INTO STRICT work
    FROM volpred_ops.complete_work(
      work_receipt_id,
      work.id,
      p_work_lease_token,
      work.version,
      attempt_receipt.evidence_ref,
      'owned email delivered with exact Sent read-back'
    );
  ELSIF attempt_receipt.disposition = 'retry_scheduled' THEN
    SELECT * INTO STRICT work
    FROM volpred_ops.release_work(
      work.id,
      p_work_lease_token,
      work.version,
      'owned email provider requested durable retry'
    );
  ELSE
    event_at := clock_timestamp();
    terminal_status := 'failed';
    work_receipt_id :=
      'owned-email-failure:' || p_effect_id
      || ':attempt-' || p_attempt_count::text;
    UPDATE volpred_ops.work_items
    SET status = terminal_status,
        version = version + 1,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL,
        result_ref = attempt_receipt.evidence_ref,
        result_summary = 'owned email dead-lettered',
        finished_at = event_at,
        updated_at = event_at
    WHERE id = work.id
    RETURNING * INTO work;
    INSERT INTO volpred_ops.work_receipts (
      id, work_id, outcome, result_ref, summary, created_at
    )
    VALUES (
      work_receipt_id, work.id, 'failed',
      attempt_receipt.evidence_ref,
      'owned email dead-lettered',
      event_at
    );
    INSERT INTO volpred_ops.work_events (
      work_id, kind, version, created_at, actor_ref, evidence_ref
    )
    VALUES (
      work.id, 'failed', work.version, event_at,
      btrim(p_worker_id), attempt_receipt.evidence_ref
    );
  END IF;

  SELECT * INTO STRICT released_authority
  FROM volpred_ops.release_primary_authority(
    btrim(p_primary_authority_key),
    btrim(p_primary_authority_holder_ref),
    p_primary_authority_epoch,
    p_primary_fencing_token
  );
  SELECT * INTO STRICT effect
  FROM volpred_ops.effect_requests
  WHERE id = btrim(p_effect_id);
  event_at := attempt_receipt.recorded_at;
  UPDATE volpred_ops.owned_notification_attempts
  SET status = attempt_receipt.disposition,
      reported_outcome = attempt_receipt.reported_outcome,
      disposition = attempt_receipt.disposition,
      evidence_ref = attempt_receipt.evidence_ref,
      evidence_sha256 = attempt_receipt.evidence_sha256,
      work_status = work.status,
      effect_status = effect.status,
      finished_at = event_at
  WHERE effect_id = owned_attempt.effect_id
    AND attempt_count = owned_attempt.attempt_count
  RETURNING * INTO owned_attempt;

  RETURN jsonb_build_object(
    'schema_version', 'owned-email-receipt.v1',
    'owner_generation', owned_attempt.owner_generation,
    'work_id', owned_attempt.work_id,
    'work_status', owned_attempt.work_status,
    'effect_id', owned_attempt.effect_id,
    'effect_status', owned_attempt.effect_status,
    'attempt_count', owned_attempt.attempt_count,
    'disposition', owned_attempt.disposition,
    'evidence_ref', owned_attempt.evidence_ref,
    'evidence_sha256', owned_attempt.evidence_sha256,
    'primary_authority_ref', owned_attempt.primary_authority_ref,
    'recorded_at', owned_attempt.finished_at
  );
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER TABLE volpred_ops.notification_owners
  OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.notification_owner_receipts
  OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.owned_notification_requests
  OWNER TO volpred_ops_definer;
ALTER TABLE volpred_ops.owned_notification_attempts
  OWNER TO volpred_ops_definer;
ALTER SEQUENCE volpred_ops.notification_owner_receipts_sequence_seq
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.notification_owner_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.notification_owner_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.owned_notification_request_reads
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.owned_notification_attempt_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_notification_owner()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_transfer_notification_owner(
  text, bigint, text, text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_request_owned_email_notification(
  bigint, text, text, text, text, jsonb, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_begin_owned_email_notification(
  bigint, text, text, integer, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_settle_owned_email_notification(
  bigint, text, integer, text, text, bigint, integer, text, text,
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  public.volpred_read_notification_owner(),
  public.volpred_transfer_notification_owner(
    text, bigint, text, text, text, bigint
  ),
  public.volpred_request_owned_email_notification(
    bigint, text, text, text, text, jsonb, text
  ),
  public.volpred_begin_owned_email_notification(
    bigint, text, text, integer, text, text, text
  ),
  public.volpred_settle_owned_email_notification(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text, text,
    text, text
  )
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  public.volpred_read_notification_owner(),
  public.volpred_transfer_notification_owner(
    text, bigint, text, text, text, bigint
  ),
  public.volpred_request_owned_email_notification(
    bigint, text, text, text, text, jsonb, text
  ),
  public.volpred_begin_owned_email_notification(
    bigint, text, text, integer, text, text, text
  ),
  public.volpred_settle_owned_email_notification(
    bigint, text, integer, text, text, bigint, integer, text, text,
    text, text, bigint, text, text, text, text, text, text, text, text,
    text, text
  )
TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
