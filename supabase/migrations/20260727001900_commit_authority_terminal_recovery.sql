-- Terminal lifecycle for Git commit authority grants.
--
-- A grant is created before the external Git writer. If that writer
-- definitively exits without the authorized commit, the grant must become a
-- durable terminal abandonment; otherwise it permanently blocks owner
-- rollback. Recovery may only read an existing active grant and can never
-- create authority after observing a Git commit.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.commit_authority_abandonments (
  request_sha256 text PRIMARY KEY
    REFERENCES volpred_ops.commit_authority_grants(request_sha256)
    ON DELETE RESTRICT,
  reason text NOT NULL,
  abandoned_at timestamptz NOT NULL
);

CREATE OR REPLACE VIEW volpred_ops.commit_authority_abandonment_reads AS
SELECT
  'commit-authority-abandonment.v1'::text AS schema_version,
  request_sha256,
  reason,
  abandoned_at
FROM volpred_ops.commit_authority_abandonments;

ALTER TABLE volpred_ops.commit_authority_abandonments ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_authority_abandonments FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS commit_authority_abandonments_definer_select
  ON volpred_ops.commit_authority_abandonments;
CREATE POLICY commit_authority_abandonments_definer_select
  ON volpred_ops.commit_authority_abandonments
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS commit_authority_abandonments_definer_insert
  ON volpred_ops.commit_authority_abandonments;
CREATE POLICY commit_authority_abandonments_definer_insert
  ON volpred_ops.commit_authority_abandonments
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE OR REPLACE FUNCTION volpred_ops.read_active_commit_authority_grant(
  p_request_sha256 text
)
RETURNS SETOF volpred_ops.commit_authority_grant_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  grant_row volpred_ops.commit_authority_grants;
BEGIN
  IF p_request_sha256 IS NULL
      OR p_request_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'commit authority request hash is invalid';
  END IF;
  SELECT * INTO grant_row
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF grant_row.request_sha256 IS NULL THEN
    RETURN;
  ELSIF EXISTS (
    SELECT 1
    FROM volpred_ops.commit_authority_abandonments
    WHERE request_sha256 = p_request_sha256
  ) THEN
    RAISE EXCEPTION 'commit authority grant is terminally abandoned';
  END IF;
  RETURN QUERY
  SELECT *
  FROM volpred_ops.commit_authority_grant_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.abandon_commit_write(
  p_request_sha256 text,
  p_commit_owner_generation bigint,
  p_commit_owner_ref text,
  p_reason text
)
RETURNS SETOF volpred_ops.commit_authority_abandonment_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  grant_row volpred_ops.commit_authority_grants;
  existing volpred_ops.commit_authority_abandonments;
BEGIN
  IF p_request_sha256 IS NULL
      OR p_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_commit_owner_generation IS NULL
      OR p_commit_owner_generation <= 0
      OR p_commit_owner_ref IS NULL
      OR btrim(p_commit_owner_ref) = ''
      OR p_reason IS NULL
      OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'commit authority abandonment fields are invalid';
  END IF;

  PERFORM pg_advisory_xact_lock(
    hashtextextended('commit-authority:' || p_request_sha256, 0)
  );
  SELECT * INTO grant_row
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_request_sha256
  FOR UPDATE;
  IF grant_row.request_sha256 IS NULL THEN
    RAISE EXCEPTION 'commit authority grant is unknown';
  ELSIF grant_row.commit_owner_generation
      <> p_commit_owner_generation
      OR grant_row.commit_owner_ref <> btrim(p_commit_owner_ref) THEN
    RAISE EXCEPTION
      'commit authority abandonment owner identity drifted';
  ELSIF EXISTS (
    SELECT 1
    FROM volpred_ops.commit_delivery_receipts
    WHERE authority_request_sha256 = p_request_sha256
  ) THEN
    RAISE EXCEPTION
      'commit authority delivered grant cannot be abandoned';
  END IF;

  INSERT INTO volpred_ops.commit_authority_abandonments (
    request_sha256,
    reason,
    abandoned_at
  )
  VALUES (
    p_request_sha256,
    btrim(p_reason),
    clock_timestamp()
  )
  ON CONFLICT (request_sha256) DO NOTHING;

  SELECT * INTO STRICT existing
  FROM volpred_ops.commit_authority_abandonments
  WHERE request_sha256 = p_request_sha256;
  IF existing.reason <> btrim(p_reason) THEN
    RAISE EXCEPTION
      'commit authority abandonment conflicts with its terminal receipt';
  END IF;

  RETURN QUERY
  SELECT *
  FROM volpred_ops.commit_authority_abandonment_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.reject_abandoned_commit_settlement()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
BEGIN
  -- Settlement and abandonment are the two mutually exclusive terminal
  -- outcomes for one authority request. They must serialize on the same key;
  -- a trigger-only visibility check without this lock admits write skew.
  PERFORM pg_advisory_xact_lock(
    hashtextextended(
      'commit-authority:' || NEW.authority_request_sha256,
      0
    )
  );
  IF EXISTS (
    SELECT 1
    FROM volpred_ops.commit_authority_abandonments
    WHERE request_sha256 = NEW.authority_request_sha256
  ) THEN
    RAISE EXCEPTION
      'commit authority grant is terminally abandoned';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS commit_delivery_receipts_reject_abandoned
  ON volpred_ops.commit_delivery_receipts;
CREATE TRIGGER commit_delivery_receipts_reject_abandoned
BEFORE INSERT ON volpred_ops.commit_delivery_receipts
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.reject_abandoned_commit_settlement();

CREATE OR REPLACE FUNCTION volpred_ops.transfer_commit_owner(
  p_expected_owner text,
  p_expected_generation bigint,
  p_target_owner text,
  p_actor_ref text,
  p_reason text,
  p_rollback_of_generation bigint DEFAULT NULL
)
RETURNS SETOF volpred_ops.commit_owner_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  ownership volpred_ops.commit_owners;
  replay volpred_ops.commit_owner_receipts;
  event_at timestamptz;
  owner_ref text;
  has_unsettled_change_sets boolean := false;
BEGIN
  IF p_expected_owner NOT IN ('legacy', 'operations_core')
      OR p_target_owner NOT IN ('legacy', 'operations_core')
      OR p_expected_owner = p_target_owner
      OR p_expected_generation IS NULL
      OR p_expected_generation <= 0
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = ''
      OR p_reason IS NULL OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'commit ownership transfer fields are invalid';
  ELSIF p_target_owner = 'legacy'
      AND p_rollback_of_generation IS DISTINCT FROM p_expected_generation THEN
    RAISE EXCEPTION
      'commit ownership rollback must identify current generation';
  ELSIF p_target_owner = 'operations_core'
      AND p_rollback_of_generation IS NOT NULL THEN
    RAISE EXCEPTION
      'commit ownership cutover cannot carry rollback generation';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.commit_owners
  WHERE capability = 'git.commit'
  FOR UPDATE;

  IF ownership.owner <> p_expected_owner
      OR ownership.generation <> p_expected_generation THEN
    SELECT * INTO replay
    FROM volpred_ops.commit_owner_receipts
    WHERE capability = ownership.capability
      AND generation = p_expected_generation + 1;
    IF replay.capability IS NULL
        OR ownership.generation <> replay.generation
        OR ownership.owner <> replay.owner
        OR replay.previous_owner <> p_expected_owner
        OR replay.owner <> p_target_owner
        OR replay.actor_ref <> btrim(p_actor_ref)
        OR replay.reason <> btrim(p_reason)
        OR replay.rollback_of_generation
          IS DISTINCT FROM p_rollback_of_generation THEN
      RAISE EXCEPTION
        'commit ownership compare-and-set failed: expected %/% found %/%',
        p_expected_owner, p_expected_generation,
        ownership.owner, ownership.generation;
    END IF;
    RETURN QUERY SELECT * FROM volpred_ops.read_commit_owner();
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM volpred_ops.commit_authority_grants AS authority_grant
    LEFT JOIN volpred_ops.commit_delivery_receipts AS receipt
      ON receipt.authority_request_sha256 =
        authority_grant.request_sha256
    LEFT JOIN volpred_ops.commit_authority_abandonments AS abandonment
      ON abandonment.request_sha256 = authority_grant.request_sha256
    WHERE authority_grant.commit_owner_generation = ownership.generation
      AND receipt.authority_request_sha256 IS NULL
      AND abandonment.request_sha256 IS NULL
  ) THEN
    RAISE EXCEPTION
      'commit ownership transfer requires zero unsettled grants';
  END IF;

  owner_ref :=
    'commit-owner:git.commit:generation-' || ownership.generation::text;
  IF to_regclass('volpred_ops.change_sets') IS NOT NULL THEN
    EXECUTE
      'SELECT EXISTS ('
      'SELECT 1 FROM volpred_ops.change_sets '
      'WHERE status = ''commit_unsettled'' '
      'AND actuation_receipt->>''commit_owner_ref'' = $1'
      ')'
    INTO has_unsettled_change_sets
    USING owner_ref;
  END IF;
  IF has_unsettled_change_sets THEN
    RAISE EXCEPTION
      'commit ownership transfer requires zero unsettled ChangeSets';
  END IF;

  event_at := clock_timestamp();
  UPDATE volpred_ops.commit_owners
  SET owner = p_target_owner,
      generation = generation + 1,
      changed_at = event_at,
      changed_by = btrim(p_actor_ref),
      change_reason = btrim(p_reason)
  WHERE capability = ownership.capability
  RETURNING * INTO ownership;

  INSERT INTO volpred_ops.commit_owner_receipts (
    capability, generation, previous_owner, owner, actor_ref, reason,
    rollback_of_generation, changed_at
  )
  VALUES (
    ownership.capability, ownership.generation, p_expected_owner,
    ownership.owner, ownership.changed_by, ownership.change_reason,
    p_rollback_of_generation, ownership.changed_at
  );
  RETURN QUERY SELECT * FROM volpred_ops.read_commit_owner();
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_commit_authority_grant(
  p_request_sha256 text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  SELECT to_jsonb(grant_row)
  INTO payload
  FROM volpred_ops.read_active_commit_authority_grant(
    p_request_sha256
  ) AS grant_row;
  RETURN payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_abandon_commit_write(
  p_request_sha256 text,
  p_commit_owner_generation bigint,
  p_commit_owner_ref text,
  p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  SELECT to_jsonb(abandonment)
  INTO STRICT payload
  FROM volpred_ops.abandon_commit_write(
    p_request_sha256,
    p_commit_owner_generation,
    p_commit_owner_ref,
    p_reason
  ) AS abandonment;
  RETURN payload;
END;
$$;

CREATE OR REPLACE FUNCTION public.volpred_authorize_commit_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_request_sha256 text,
  p_proposal_sha256 text,
  p_work_item_id text,
  p_work_item_version integer,
  p_commit_owner_generation bigint,
  p_work_lease_token text,
  p_repository text,
  p_expected_head text,
  p_commit_worker_ref text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  PERFORM *
  FROM volpred_ops.authorize_commit_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_request_sha256,
    p_proposal_sha256,
    p_work_item_id,
    p_work_item_version,
    p_commit_owner_generation,
    p_work_lease_token,
    p_repository,
    p_expected_head,
    p_commit_worker_ref
  );
  SELECT to_jsonb(grant_row)
  INTO STRICT payload
  FROM volpred_ops.read_active_commit_authority_grant(
    p_request_sha256
  ) AS grant_row;
  RETURN payload;
END;
$$;

GRANT SELECT, INSERT ON volpred_ops.commit_authority_abandonments
  TO volpred_ops_definer;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

ALTER TABLE volpred_ops.commit_authority_abandonments
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_authority_abandonment_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.read_active_commit_authority_grant(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.abandon_commit_write(
  text, bigint, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.reject_abandoned_commit_settlement()
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.transfer_commit_owner(
  text, bigint, text, text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_commit_authority_grant(text)
  OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_abandon_commit_write(
  text, bigint, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, bigint,
  text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.commit_authority_abandonments,
  volpred_ops.commit_authority_abandonment_reads
FROM PUBLIC;
REVOKE ALL ON FUNCTION
  volpred_ops.read_active_commit_authority_grant(text),
  volpred_ops.abandon_commit_write(text, bigint, text, text),
  volpred_ops.reject_abandoned_commit_settlement(),
  public.volpred_read_commit_authority_grant(text),
  public.volpred_abandon_commit_write(text, bigint, text, text)
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
  volpred_ops.read_active_commit_authority_grant(text),
  volpred_ops.abandon_commit_write(text, bigint, text, text)
TO volpred_ops_worker;
GRANT EXECUTE ON FUNCTION
  public.volpred_read_commit_authority_grant(text),
  public.volpred_abandon_commit_write(text, bigint, text, text)
TO service_role;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
