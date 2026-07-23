-- Shadow Operations Core coordination state.
--
-- This schema is intentionally private: no Data API client receives USAGE,
-- and every table has RLS enabled as defense in depth.  The shadow adapter
-- connects from a trusted backend worker and is not wired to any live caller.

CREATE SCHEMA IF NOT EXISTS volpred_ops;
REVOKE ALL ON SCHEMA volpred_ops FROM PUBLIC;

DO $$
BEGIN
  CREATE ROLE volpred_ops_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE ROLE volpred_ops_approver NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
BEGIN
  CREATE ROLE volpred_ops_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$$;

DO $$
DECLARE
  checked_role text;
BEGIN
  FOREACH checked_role IN ARRAY
    ARRAY[
      'volpred_ops_worker',
      'volpred_ops_approver',
      'volpred_ops_definer'
    ]
  LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM pg_roles
      WHERE pg_roles.rolname = checked_role
        AND NOT rolcanlogin
        AND NOT rolsuper
        AND NOT rolcreatedb
        AND NOT rolcreaterole
        AND NOT rolreplication
        AND NOT rolbypassrls
        AND NOT rolinherit
        AND NOT EXISTS (
          SELECT 1
          FROM pg_auth_members AS memberships
          WHERE (
              memberships.member = pg_roles.oid
              OR memberships.roleid = pg_roles.oid
            )
            AND NOT (
              -- PostgreSQL 16+ automatically grants a role created by a
              -- non-superuser CREATEROLE principal back to that creator with
              -- ADMIN TRUE / SET FALSE / INHERIT FALSE. The creator cannot
              -- remove that bootstrap-superuser grant. It conveys no runtime
              -- privilege and is the only membership shape allowed here.
              memberships.roleid = pg_roles.oid
              AND memberships.member = (
                SELECT creator.oid
                FROM pg_roles AS creator
                WHERE creator.rolname = current_user
              )
              AND memberships.admin_option
              AND NOT memberships.set_option
              AND NOT memberships.inherit_option
            )
        )
    ) THEN
      RAISE EXCEPTION 'existing % role has unsafe attributes', checked_role;
    END IF;
  END LOOP;
END;
$$;

CREATE TABLE volpred_ops.work_items (
  id text PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  source text NOT NULL,
  kind text NOT NULL,
  title text NOT NULL,
  priority integer NOT NULL,
  required_capabilities text[] NOT NULL DEFAULT '{}',
  required_attestations text[] NOT NULL DEFAULT '{}',
  risk text NOT NULL
    CHECK (risk IN ('safe', 'sensitive', 'destructive')),
  approval text NOT NULL
    CHECK (approval IN ('auto', 'required', 'approved')),
  payload_ref text NOT NULL,
  parent_id text,
  deadline timestamptz,
  requester_ref text NOT NULL,
  status text NOT NULL
    CHECK (
      status IN (
        'awaiting_approval',
        'pending',
        'claimed',
        'running',
        'succeeded',
        'failed',
        'blocked',
        'cancelled'
      )
    ),
  version integer NOT NULL CHECK (version > 0),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  claimed_by text,
  claim_token text,
  claim_expires_at timestamptz,
  latest_verified_checkpoint_id text,
  blocked_reason text,
  last_release_reason text,
  result_ref text,
  result_summary text,
  finished_at timestamptz,
  CHECK (status <> 'blocked' OR blocked_reason IS NOT NULL)
);

ALTER TABLE volpred_ops.work_items
  ADD CONSTRAINT work_items_parent_fk
  FOREIGN KEY (parent_id)
  REFERENCES volpred_ops.work_items(id)
  ON DELETE RESTRICT;

CREATE INDEX work_items_ready_idx
  ON volpred_ops.work_items (priority, deadline, created_at, id)
  WHERE status = 'pending';

CREATE INDEX work_items_parent_idx
  ON volpred_ops.work_items (parent_id)
  WHERE parent_id IS NOT NULL;

CREATE INDEX work_items_latest_checkpoint_idx
  ON volpred_ops.work_items (latest_verified_checkpoint_id)
  WHERE latest_verified_checkpoint_id IS NOT NULL;

CREATE TABLE volpred_ops.work_events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  work_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  kind text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  created_at timestamptz NOT NULL,
  actor_ref text,
  evidence_ref text
);

CREATE INDEX work_events_work_sequence_idx
  ON volpred_ops.work_events (work_id, sequence);

CREATE TABLE volpred_ops.work_checkpoints (
  id text PRIMARY KEY,
  work_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  artifact_ref text NOT NULL,
  artifact_sha256 text NOT NULL
    CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
  verification_ref text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE INDEX work_checkpoints_work_created_idx
  ON volpred_ops.work_checkpoints (work_id, created_at, id);

ALTER TABLE volpred_ops.work_items
  ADD CONSTRAINT work_items_latest_checkpoint_fk
  FOREIGN KEY (latest_verified_checkpoint_id)
  REFERENCES volpred_ops.work_checkpoints(id)
  ON DELETE RESTRICT;

CREATE TABLE volpred_ops.work_receipts (
  id text PRIMARY KEY,
  work_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  outcome text NOT NULL
    CHECK (outcome IN ('succeeded', 'failed', 'cancelled')),
  result_ref text NOT NULL,
  summary text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE INDEX work_receipts_work_created_idx
  ON volpred_ops.work_receipts (work_id, created_at, id);

CREATE VIEW volpred_ops.work_item_reads AS
SELECT
  id, idempotency_key, source, kind, title, priority,
  required_capabilities, required_attestations, risk, approval, payload_ref,
  parent_id, deadline, requester_ref, status, version, created_at, updated_at,
  claimed_by, claim_expires_at, latest_verified_checkpoint_id, blocked_reason,
  last_release_reason, result_ref, result_summary, finished_at
FROM volpred_ops.work_items;

ALTER TABLE volpred_ops.work_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_items FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_events FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.work_receipts FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA volpred_ops FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_ops FROM PUBLIC;

GRANT USAGE ON SCHEMA volpred_ops TO volpred_ops_worker;
GRANT USAGE ON SCHEMA volpred_ops TO volpred_ops_approver;
GRANT USAGE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT SELECT ON volpred_ops.work_item_reads, volpred_ops.work_events,
  volpred_ops.work_checkpoints, volpred_ops.work_receipts
  TO volpred_ops_worker;
GRANT SELECT ON volpred_ops.work_item_reads, volpred_ops.work_events,
  volpred_ops.work_checkpoints, volpred_ops.work_receipts
  TO volpred_ops_approver;
GRANT SELECT, INSERT, UPDATE ON volpred_ops.work_items
  TO volpred_ops_definer;
GRANT SELECT, INSERT ON
  volpred_ops.work_events,
  volpred_ops.work_checkpoints,
  volpred_ops.work_receipts
TO volpred_ops_definer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA volpred_ops
  TO volpred_ops_definer;

CREATE POLICY work_items_worker_select
  ON volpred_ops.work_items FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY work_events_worker_select
  ON volpred_ops.work_events FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY work_checkpoints_worker_select
  ON volpred_ops.work_checkpoints FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY work_receipts_worker_select
  ON volpred_ops.work_receipts FOR SELECT TO volpred_ops_worker USING (true);
CREATE POLICY work_items_approver_select
  ON volpred_ops.work_items FOR SELECT TO volpred_ops_approver USING (true);
CREATE POLICY work_events_approver_select
  ON volpred_ops.work_events FOR SELECT TO volpred_ops_approver USING (true);
CREATE POLICY work_checkpoints_approver_select
  ON volpred_ops.work_checkpoints FOR SELECT TO volpred_ops_approver USING (true);
CREATE POLICY work_receipts_approver_select
  ON volpred_ops.work_receipts FOR SELECT TO volpred_ops_approver USING (true);

CREATE POLICY work_items_definer_select
  ON volpred_ops.work_items FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_items_definer_insert
  ON volpred_ops.work_items FOR INSERT TO volpred_ops_definer WITH CHECK (true);
CREATE POLICY work_items_definer_update
  ON volpred_ops.work_items FOR UPDATE TO volpred_ops_definer
  USING (true) WITH CHECK (true);
CREATE POLICY work_events_definer_select
  ON volpred_ops.work_events FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_events_definer_insert
  ON volpred_ops.work_events FOR INSERT TO volpred_ops_definer WITH CHECK (true);
CREATE POLICY work_checkpoints_definer_select
  ON volpred_ops.work_checkpoints FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_checkpoints_definer_insert
  ON volpred_ops.work_checkpoints FOR INSERT TO volpred_ops_definer
  WITH CHECK (true);
CREATE POLICY work_receipts_definer_select
  ON volpred_ops.work_receipts FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY work_receipts_definer_insert
  ON volpred_ops.work_receipts FOR INSERT TO volpred_ops_definer
  WITH CHECK (true);

CREATE FUNCTION volpred_ops.submit_work(
  p_id text,
  p_idempotency_key text,
  p_source text,
  p_kind text,
  p_title text,
  p_priority integer,
  p_required_capabilities text[],
  p_required_attestations text[],
  p_risk text,
  p_approval text,
  p_payload_ref text,
  p_parent_id text,
  p_deadline timestamptz,
  p_requester_ref text,
  p_status text,
  p_version integer,
  p_created_at timestamptz,
  p_updated_at timestamptz
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
  expected_status text;
BEGIN
  expected_status := CASE
    WHEN p_risk = 'safe' AND p_approval = 'auto' THEN 'pending'
    ELSE 'awaiting_approval'
  END;
  IF p_approval NOT IN ('auto', 'required')
      OR p_version <> 1
      OR p_status <> expected_status THEN
    RAISE EXCEPTION 'invalid submitted work policy or initial state';
  END IF;
  INSERT INTO volpred_ops.work_items (
    id, idempotency_key, source, kind, title, priority,
    required_capabilities, required_attestations, risk, approval,
    payload_ref, parent_id, deadline, requester_ref, status, version,
    created_at, updated_at
  )
  VALUES (
    p_id, p_idempotency_key, p_source, p_kind, p_title, p_priority,
    p_required_capabilities, p_required_attestations, p_risk, p_approval,
    p_payload_ref, p_parent_id, p_deadline, p_requester_ref, p_status, p_version,
    p_created_at, p_updated_at
  )
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING * INTO item;

  IF item.id IS NOT NULL THEN
    INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
    VALUES (item.id, 'submitted', item.version, item.created_at);
  ELSE
    SELECT * INTO STRICT item
    FROM volpred_ops.work_items
    WHERE idempotency_key = p_idempotency_key;
  END IF;
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.acquire_work(
  p_worker_id text,
  p_capabilities text[],
  p_attestations text[],
  p_lease_seconds integer,
  p_token text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
BEGIN
  IF p_token IS NULL OR btrim(p_token) = '' THEN
    RAISE EXCEPTION 'claim token is required';
  ELSIF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
    RAISE EXCEPTION 'lease_seconds must be positive';
  END IF;
  SELECT * INTO item
  FROM volpred_ops.work_items
  WHERE (
    status = 'pending'
    OR (
      status IN ('claimed', 'running')
      AND claim_expires_at IS NOT NULL
      AND claim_expires_at <= clock_timestamp()
    )
  )
    AND required_capabilities <@ p_capabilities
    AND required_attestations <@ p_attestations
    AND (
      parent_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM volpred_ops.work_items AS parent
        WHERE parent.id = work_items.parent_id
          AND parent.status = 'succeeded'
      )
    )
  ORDER BY priority, deadline NULLS LAST, created_at, id
  FOR UPDATE SKIP LOCKED
  LIMIT 1;

  IF item.id IS NULL THEN
    RETURN;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'claimed',
      version = version + 1,
      claimed_by = p_worker_id,
      claim_token = p_token,
      claim_expires_at =
        clock_timestamp() + make_interval(secs => p_lease_seconds),
      updated_at = clock_timestamp()
  WHERE id = item.id
  RETURNING * INTO item;
  INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
  VALUES (item.id, 'acquired', item.version, item.updated_at);
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.approve_work(
  p_work_id text,
  p_expected_version integer,
  p_approved_by text,
  p_evidence_ref text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
BEGIN
  SELECT * INTO item FROM volpred_ops.work_items
  WHERE id = p_work_id FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'unknown work item: %', p_work_id;
  ELSIF item.version <> p_expected_version THEN
    RAISE EXCEPTION 'stale work item version: expected %, found %',
      p_expected_version, item.version;
  ELSIF item.status <> 'awaiting_approval' THEN
    RAISE EXCEPTION 'cannot approve work item % from %',
      p_work_id, item.status;
  ELSIF p_approved_by IS NULL OR btrim(p_approved_by) = ''
      OR p_evidence_ref IS NULL OR btrim(p_evidence_ref) = '' THEN
    RAISE EXCEPTION 'approval requires actor and evidence references';
  END IF;
  UPDATE volpred_ops.work_items
  SET approval = 'approved', status = 'pending',
      version = version + 1, updated_at = clock_timestamp()
  WHERE id = p_work_id RETURNING * INTO item;
  INSERT INTO volpred_ops.work_events (
    work_id, kind, version, created_at, actor_ref, evidence_ref
  )
  VALUES (
    item.id, 'approval_granted', item.version, item.updated_at,
    p_approved_by, p_evidence_ref
  );
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.start_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
BEGIN
  SELECT * INTO item FROM volpred_ops.work_items
  WHERE id = p_work_id FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'unknown work item: %', p_work_id;
  ELSIF item.claim_token IS DISTINCT FROM p_lease_token
      OR item.claim_expires_at IS NULL
      OR item.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'claim lost: %', p_work_id;
  ELSIF item.version <> p_expected_version THEN
    RAISE EXCEPTION 'stale work item version: expected %, found %',
      p_expected_version, item.version;
  ELSIF item.status <> 'claimed' THEN
    RAISE EXCEPTION 'cannot mutate work item % from %', p_work_id, item.status;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'running', version = version + 1,
      updated_at = clock_timestamp()
  WHERE id = p_work_id RETURNING * INTO item;
  INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
  VALUES (item.id, 'started', item.version, item.updated_at);
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.checkpoint_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_checkpoint_id text,
  p_artifact_ref text,
  p_artifact_sha256 text,
  p_verification_ref text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
  replay volpred_ops.work_checkpoints;
  event_at timestamptz;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_checkpoint_id, 0));
  SELECT * INTO item FROM volpred_ops.work_items
  WHERE id = p_work_id FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'unknown work item: %', p_work_id;
  END IF;
  SELECT * INTO replay
  FROM volpred_ops.work_checkpoints
  WHERE id = p_checkpoint_id;
  IF replay.id IS NOT NULL THEN
    IF replay.work_id <> p_work_id
        OR replay.artifact_ref <> p_artifact_ref
        OR replay.artifact_sha256 <> p_artifact_sha256
        OR replay.verification_ref <> p_verification_ref THEN
      RAISE EXCEPTION 'checkpoint report % conflicts with its original payload',
        p_checkpoint_id;
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
    RETURN;
  ELSIF item.claim_token IS DISTINCT FROM p_lease_token
      OR item.claim_expires_at IS NULL
      OR item.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'claim lost: %', p_work_id;
  ELSIF item.version <> p_expected_version THEN
    RAISE EXCEPTION 'stale work item version: expected %, found %',
      p_expected_version, item.version;
  ELSIF item.status <> 'running' THEN
    RAISE EXCEPTION 'cannot mutate work item % from %', p_work_id, item.status;
  END IF;
  event_at := clock_timestamp();
  INSERT INTO volpred_ops.work_checkpoints (
    id, work_id, artifact_ref, artifact_sha256, verification_ref, created_at
  )
  VALUES (
    p_checkpoint_id, p_work_id, p_artifact_ref, p_artifact_sha256,
    p_verification_ref, event_at
  );
  UPDATE volpred_ops.work_items
  SET version = version + 1,
      latest_verified_checkpoint_id = p_checkpoint_id,
      updated_at = event_at
  WHERE id = p_work_id RETURNING * INTO item;
  INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
  VALUES (item.id, 'checkpointed', item.version, event_at);
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.release_work(
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_reason text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
BEGIN
  SELECT * INTO item FROM volpred_ops.work_items
  WHERE id = p_work_id FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'unknown work item: %', p_work_id;
  ELSIF item.claim_token IS DISTINCT FROM p_lease_token
      OR item.claim_expires_at IS NULL
      OR item.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'claim lost: %', p_work_id;
  ELSIF item.version <> p_expected_version THEN
    RAISE EXCEPTION 'stale work item version: expected %, found %',
      p_expected_version, item.version;
  ELSIF item.status NOT IN ('claimed', 'running') THEN
    RAISE EXCEPTION 'cannot mutate work item % from %', p_work_id, item.status;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'pending', version = version + 1,
      claimed_by = NULL, claim_token = NULL, claim_expires_at = NULL,
      last_release_reason = p_reason, updated_at = clock_timestamp()
  WHERE id = p_work_id RETURNING * INTO item;
  INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
  VALUES (item.id, 'released', item.version, item.updated_at);
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

CREATE FUNCTION volpred_ops.complete_work(
  p_report_id text,
  p_work_id text,
  p_lease_token text,
  p_expected_version integer,
  p_result_ref text,
  p_summary text
)
RETURNS SETOF volpred_ops.work_item_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
  receipt_work_id text;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_report_id, 0));
  SELECT * INTO item FROM volpred_ops.work_items
  WHERE id = p_work_id FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'unknown work item: %', p_work_id;
  END IF;
  SELECT work_id INTO receipt_work_id
  FROM volpred_ops.work_receipts WHERE id = p_report_id;
  IF receipt_work_id IS NOT NULL THEN
    IF receipt_work_id <> p_work_id THEN
      RAISE EXCEPTION 'completion report % belongs to %',
        p_report_id, receipt_work_id;
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
    RETURN;
  END IF;
  IF item.claim_token IS DISTINCT FROM p_lease_token
      OR item.claim_expires_at IS NULL
      OR item.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'claim lost: %', p_work_id;
  ELSIF item.version <> p_expected_version THEN
    RAISE EXCEPTION 'stale work item version: expected %, found %',
      p_expected_version, item.version;
  ELSIF item.status <> 'running' THEN
    RAISE EXCEPTION 'cannot mutate work item % from %', p_work_id, item.status;
  END IF;
  UPDATE volpred_ops.work_items
  SET status = 'succeeded', version = version + 1,
      claimed_by = NULL, claim_token = NULL, claim_expires_at = NULL,
      result_ref = p_result_ref, result_summary = p_summary,
      finished_at = clock_timestamp(), updated_at = clock_timestamp()
  WHERE id = p_work_id RETURNING * INTO item;
  INSERT INTO volpred_ops.work_receipts (
    id, work_id, outcome, result_ref, summary, created_at
  )
  VALUES (
    p_report_id, p_work_id, 'succeeded', p_result_ref, p_summary, item.updated_at
  );
  INSERT INTO volpred_ops.work_events (work_id, kind, version, created_at)
  VALUES (item.id, 'completed', item.version, item.updated_at);
  RETURN QUERY
  SELECT * FROM volpred_ops.work_item_reads WHERE id = item.id;
END;
$$;

DO $$
BEGIN
  EXECUTE format(
    'GRANT volpred_ops_definer TO %I',
    current_user
  );
END;
$$;

-- A non-superuser migration executor may transfer object ownership only when
-- the target owner has CREATE on the containing schema. Keep that privilege
-- strictly inside this ownership-transfer window.
GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER FUNCTION volpred_ops.submit_work(
  text, text, text, text, text, integer, text[], text[], text, text,
  text, text, timestamptz, text, text, integer, timestamptz, timestamptz
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.acquire_work(
  text, text[], text[], integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.approve_work(
  text, integer, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.start_work(
  text, text, integer
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.checkpoint_work(
  text, text, integer, text, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.release_work(
  text, text, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.complete_work(
  text, text, text, integer, text, text
) OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.work_item_reads OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz
  ),
  volpred_ops.acquire_work(text, text[], text[], integer, text),
  volpred_ops.approve_work(text, integer, text, text),
  volpred_ops.start_work(text, text, integer),
  volpred_ops.checkpoint_work(text, text, integer, text, text, text, text),
  volpred_ops.release_work(text, text, integer, text),
  volpred_ops.complete_work(text, text, text, integer, text, text)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION
  volpred_ops.submit_work(
    text, text, text, text, text, integer, text[], text[], text, text,
    text, text, timestamptz, text, text, integer, timestamptz, timestamptz
  ),
  volpred_ops.acquire_work(text, text[], text[], integer, text),
  volpred_ops.start_work(text, text, integer),
  volpred_ops.checkpoint_work(text, text, integer, text, text, text, text),
  volpred_ops.release_work(text, text, integer, text),
  volpred_ops.complete_work(text, text, text, integer, text, text)
TO volpred_ops_worker;

GRANT EXECUTE ON FUNCTION
  volpred_ops.approve_work(text, integer, text, text)
TO volpred_ops_approver;

DO $$
BEGIN
  EXECUTE format(
    'REVOKE volpred_ops_definer FROM %I',
    current_user
  );
END;
$$;
