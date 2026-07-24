-- Durable authority grants for Change Delivery commit intents.
--
-- One transaction verifies the current running WorkLease and the current
-- Primary Authority lease, then records a token-redacted grant. The Git write
-- remains an external actuation and is not performed by this function.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.commit_authority_grants (
  request_sha256 text PRIMARY KEY
    REFERENCES volpred_ops.primary_authority_grants(request_sha256)
    ON DELETE RESTRICT,
  proposal_sha256 text NOT NULL
    CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
  work_item_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  work_item_version integer NOT NULL CHECK (work_item_version > 0),
  work_holder_ref text NOT NULL,
  commit_worker_ref text NOT NULL,
  repository text NOT NULL,
  expected_head text NOT NULL
    CHECK (expected_head ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  work_lease_ref text NOT NULL,
  primary_authority_ref text NOT NULL,
  granted_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS commit_authority_grants_work_idx
  ON volpred_ops.commit_authority_grants (
    work_item_id, work_item_version, granted_at
  );

CREATE OR REPLACE VIEW volpred_ops.commit_authority_grant_reads AS
SELECT
  request_sha256, proposal_sha256, work_item_id, work_item_version,
  work_holder_ref, commit_worker_ref, repository, expected_head,
  work_lease_ref, primary_authority_ref, granted_at
FROM volpred_ops.commit_authority_grants;

CREATE OR REPLACE FUNCTION volpred_ops.authorize_commit_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_request_sha256 text,
  p_proposal_sha256 text,
  p_work_item_id text,
  p_work_item_version integer,
  p_work_lease_token text,
  p_repository text,
  p_expected_head text,
  p_commit_worker_ref text
)
RETURNS SETOF volpred_ops.commit_authority_grant_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  item volpred_ops.work_items;
  primary_grant volpred_ops.primary_authority_grant_reads;
  existing volpred_ops.commit_authority_grants;
  lease_ref text;
  resource_ref text;
BEGIN
  IF p_request_sha256 IS NULL
      OR p_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_proposal_sha256 IS NULL
      OR p_proposal_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'commit authority hashes must be lowercase SHA-256';
  ELSIF p_work_item_id IS NULL OR btrim(p_work_item_id) = ''
      OR p_work_lease_token IS NULL OR btrim(p_work_lease_token) = ''
      OR p_repository IS NULL OR btrim(p_repository) = ''
      OR p_commit_worker_ref IS NULL
      OR btrim(p_commit_worker_ref) !~ '^commit-worker:' THEN
    RAISE EXCEPTION 'commit authority fields are required';
  ELSIF p_work_item_version IS NULL OR p_work_item_version <= 0 THEN
    RAISE EXCEPTION 'commit authority work version must be positive';
  ELSIF p_expected_head IS NULL
      OR p_expected_head !~ '^([0-9a-f]{40}|[0-9a-f]{64})$' THEN
    RAISE EXCEPTION 'commit authority expected head is invalid';
  END IF;

  SELECT * INTO item
  FROM volpred_ops.work_items
  WHERE id = btrim(p_work_item_id)
  FOR UPDATE;
  IF item.id IS NULL THEN
    RAISE EXCEPTION 'commit authority work item is unknown: %',
      btrim(p_work_item_id);
  ELSIF item.version <> p_work_item_version THEN
    RAISE EXCEPTION
      'commit authority work version is stale: expected %, found %',
      p_work_item_version, item.version;
  ELSIF item.status <> 'running' THEN
    RAISE EXCEPTION 'commit authority work item is not running: %',
      item.status;
  ELSIF item.claimed_by IS NULL OR btrim(item.claimed_by) = ''
      OR item.claim_token IS DISTINCT FROM p_work_lease_token
      OR item.claim_expires_at IS NULL
      OR item.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'commit authority WorkLease is stale';
  END IF;

  lease_ref :=
    'work-lease:' || item.id || ':v' || item.version::text;
  resource_ref :=
    'git:' || btrim(p_repository) || '@' || p_expected_head;
  SELECT * INTO primary_grant
  FROM volpred_ops.authorize_primary_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_request_sha256,
    resource_ref
  );

  INSERT INTO volpred_ops.commit_authority_grants (
    request_sha256, proposal_sha256, work_item_id, work_item_version,
    work_holder_ref, commit_worker_ref, repository, expected_head,
    work_lease_ref, primary_authority_ref, granted_at
  )
  VALUES (
    p_request_sha256, p_proposal_sha256, item.id, item.version,
    item.claimed_by, btrim(p_commit_worker_ref), btrim(p_repository),
    p_expected_head, lease_ref, primary_grant.primary_authority_ref,
    primary_grant.granted_at
  )
  ON CONFLICT (request_sha256) DO NOTHING;

  SELECT * INTO existing
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_request_sha256;
  IF existing.proposal_sha256 <> p_proposal_sha256
      OR existing.work_item_id <> item.id
      OR existing.work_item_version <> item.version
      OR existing.work_holder_ref <> item.claimed_by
      OR existing.commit_worker_ref <> btrim(p_commit_worker_ref)
      OR existing.repository <> btrim(p_repository)
      OR existing.expected_head <> p_expected_head
      OR existing.work_lease_ref <> lease_ref
      OR existing.primary_authority_ref
        <> primary_grant.primary_authority_ref THEN
    RAISE EXCEPTION
      'commit authority grant conflicts with its original intent';
  END IF;

  RETURN QUERY
  SELECT * FROM volpred_ops.commit_authority_grant_reads
  WHERE request_sha256 = p_request_sha256;
END;
$$;

ALTER TABLE volpred_ops.commit_authority_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_authority_grants FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS commit_authority_grants_definer_select
  ON volpred_ops.commit_authority_grants;
CREATE POLICY commit_authority_grants_definer_select
  ON volpred_ops.commit_authority_grants
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS commit_authority_grants_definer_insert
  ON volpred_ops.commit_authority_grants;
CREATE POLICY commit_authority_grants_definer_insert
  ON volpred_ops.commit_authority_grants
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER TABLE volpred_ops.commit_authority_grants
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_authority_grant_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.commit_authority_grants,
  volpred_ops.commit_authority_grant_reads
FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, text, text, text, text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION volpred_ops.authorize_commit_write(
  text, text, bigint, text, text, text, text, integer, text, text, text, text
) TO volpred_ops_worker;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
