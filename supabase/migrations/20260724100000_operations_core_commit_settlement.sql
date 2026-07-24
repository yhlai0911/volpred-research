-- Durable post-commit settlement for Change Delivery.
--
-- Git remains an external actuator.  A commit is considered landed only when
-- this transaction revalidates the exact running WorkLease and Primary
-- Authority generation that authorized the write, then stores an immutable
-- token-redacted receipt.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.commit_delivery_receipts (
  authority_request_sha256 text PRIMARY KEY
    REFERENCES volpred_ops.commit_authority_grants(request_sha256)
    ON DELETE RESTRICT,
  settlement_sha256 text NOT NULL UNIQUE
    CHECK (settlement_sha256 ~ '^[0-9a-f]{64}$'),
  change_set_id text NOT NULL,
  repository text NOT NULL,
  commit_sha text NOT NULL
    CHECK (commit_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  parent_sha text NOT NULL
    CHECK (parent_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  exact_paths jsonb NOT NULL,
  commit_worker_ref text NOT NULL,
  actuation_observed_at timestamptz NOT NULL,
  settled_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS commit_delivery_receipts_change_set_idx
  ON volpred_ops.commit_delivery_receipts (change_set_id, settled_at);

CREATE OR REPLACE VIEW volpred_ops.commit_delivery_receipt_reads AS
SELECT
  'change-delivery-receipt.v1'::text AS schema_version,
  receipt.change_set_id,
  authority_grant.proposal_sha256,
  authority_grant.work_item_id,
  authority_grant.work_item_version,
  receipt.authority_request_sha256,
  authority_grant.work_lease_ref,
  authority_grant.primary_authority_ref,
  receipt.repository,
  receipt.commit_sha,
  receipt.parent_sha,
  receipt.exact_paths,
  receipt.commit_worker_ref,
  'landed'::text AS status,
  receipt.actuation_observed_at,
  receipt.settled_at,
  (
    'change-delivery:' || receipt.change_set_id || ':' || receipt.commit_sha
  )::text AS settlement_ref,
  receipt.settlement_sha256
FROM volpred_ops.commit_delivery_receipts AS receipt
JOIN volpred_ops.commit_authority_grants AS authority_grant
  ON authority_grant.request_sha256 = receipt.authority_request_sha256;

CREATE OR REPLACE FUNCTION volpred_ops.settle_commit_write(
  p_authority_key text,
  p_authority_holder_ref text,
  p_authority_epoch bigint,
  p_primary_fencing_token text,
  p_authority_request_sha256 text,
  p_settlement_sha256 text,
  p_change_set_id text,
  p_work_lease_token text,
  p_work_lease_ref text,
  p_primary_authority_ref text,
  p_repository text,
  p_commit_sha text,
  p_parent_sha text,
  p_exact_paths jsonb,
  p_commit_worker_ref text,
  p_actuation_observed_at timestamptz,
  p_actuation_status text
)
RETURNS SETOF volpred_ops.commit_delivery_receipt_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  grant_row volpred_ops.commit_authority_grants;
  work volpred_ops.work_items;
  primary_grant volpred_ops.primary_authority_grant_reads;
  existing volpred_ops.commit_delivery_receipts;
  resource_ref text;
BEGIN
  IF p_authority_request_sha256 IS NULL
      OR p_authority_request_sha256 !~ '^[0-9a-f]{64}$'
      OR p_settlement_sha256 IS NULL
      OR p_settlement_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION
      'commit settlement hashes must be lowercase SHA-256';
  ELSIF p_change_set_id IS NULL OR btrim(p_change_set_id) = ''
      OR p_work_lease_token IS NULL OR btrim(p_work_lease_token) = ''
      OR p_work_lease_ref IS NULL OR btrim(p_work_lease_ref) = ''
      OR p_primary_authority_ref IS NULL
      OR btrim(p_primary_authority_ref) = ''
      OR p_repository IS NULL OR btrim(p_repository) = ''
      OR p_commit_worker_ref IS NULL
      OR btrim(p_commit_worker_ref) !~ '^commit-worker:' THEN
    RAISE EXCEPTION 'commit settlement fields are required';
  ELSIF p_commit_sha IS NULL
      OR p_commit_sha !~ '^([0-9a-f]{40}|[0-9a-f]{64})$'
      OR p_parent_sha IS NULL
      OR p_parent_sha !~ '^([0-9a-f]{40}|[0-9a-f]{64})$'
      OR p_commit_sha = p_parent_sha THEN
    RAISE EXCEPTION 'commit settlement Git identity is invalid';
  ELSIF p_exact_paths IS NULL
      OR jsonb_typeof(p_exact_paths) <> 'array'
      OR jsonb_array_length(p_exact_paths) = 0
      OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_exact_paths) AS value
        WHERE jsonb_typeof(value) <> 'string'
          OR btrim(value #>> '{}') = ''
      )
      OR (
        SELECT count(*) <> count(DISTINCT value #>> '{}')
        FROM jsonb_array_elements(p_exact_paths) AS value
      ) THEN
    RAISE EXCEPTION 'commit settlement exact paths are invalid';
  ELSIF p_actuation_observed_at IS NULL
      OR p_actuation_status IS DISTINCT FROM 'committed' THEN
    RAISE EXCEPTION 'commit settlement actuation receipt is invalid';
  END IF;

  SELECT * INTO grant_row
  FROM volpred_ops.commit_authority_grants
  WHERE request_sha256 = p_authority_request_sha256;
  IF grant_row.request_sha256 IS NULL THEN
    RAISE EXCEPTION 'commit settlement authority grant is unknown';
  ELSIF grant_row.work_lease_ref <> btrim(p_work_lease_ref)
      OR grant_row.primary_authority_ref
        <> btrim(p_primary_authority_ref)
      OR grant_row.repository <> btrim(p_repository)
      OR grant_row.expected_head <> p_parent_sha
      OR grant_row.commit_worker_ref <> btrim(p_commit_worker_ref) THEN
    RAISE EXCEPTION
      'commit settlement authority identity does not match its grant';
  END IF;

  SELECT * INTO existing
  FROM volpred_ops.commit_delivery_receipts
  WHERE authority_request_sha256 = p_authority_request_sha256;
  IF existing.authority_request_sha256 IS NOT NULL THEN
    IF existing.settlement_sha256 <> p_settlement_sha256
        OR existing.change_set_id <> btrim(p_change_set_id)
        OR existing.repository <> btrim(p_repository)
        OR existing.commit_sha <> p_commit_sha
        OR existing.parent_sha <> p_parent_sha
        OR existing.exact_paths <> p_exact_paths
        OR existing.commit_worker_ref <> btrim(p_commit_worker_ref)
        OR existing.actuation_observed_at <> p_actuation_observed_at THEN
      RAISE EXCEPTION
        'commit settlement conflicts with its original receipt';
    END IF;
    RETURN QUERY
    SELECT *
    FROM volpred_ops.commit_delivery_receipt_reads
    WHERE authority_request_sha256 = p_authority_request_sha256;
    RETURN;
  END IF;

  SELECT * INTO work
  FROM volpred_ops.work_items
  WHERE id = grant_row.work_item_id
  FOR UPDATE;
  IF work.id IS NULL
      OR work.version <> grant_row.work_item_version
      OR work.status <> 'running'
      OR work.claimed_by <> grant_row.work_holder_ref
      OR work.claim_token IS DISTINCT FROM p_work_lease_token
      OR work.claim_expires_at IS NULL
      OR work.claim_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION
      'commit settlement WorkLease was lost during external write';
  END IF;

  resource_ref :=
    'git:' || grant_row.repository || '@' || grant_row.expected_head;
  SELECT * INTO primary_grant
  FROM volpred_ops.authorize_primary_write(
    p_authority_key,
    p_authority_holder_ref,
    p_authority_epoch,
    p_primary_fencing_token,
    p_authority_request_sha256,
    resource_ref
  );
  IF primary_grant.primary_authority_ref
      <> grant_row.primary_authority_ref THEN
    RAISE EXCEPTION
      'commit settlement Primary Authority drifted during external write';
  END IF;

  INSERT INTO volpred_ops.commit_delivery_receipts (
    authority_request_sha256,
    settlement_sha256,
    change_set_id,
    repository,
    commit_sha,
    parent_sha,
    exact_paths,
    commit_worker_ref,
    actuation_observed_at,
    settled_at
  )
  VALUES (
    p_authority_request_sha256,
    p_settlement_sha256,
    btrim(p_change_set_id),
    btrim(p_repository),
    p_commit_sha,
    p_parent_sha,
    p_exact_paths,
    btrim(p_commit_worker_ref),
    p_actuation_observed_at,
    clock_timestamp()
  )
  ON CONFLICT (authority_request_sha256) DO NOTHING;

  SELECT * INTO existing
  FROM volpred_ops.commit_delivery_receipts
  WHERE authority_request_sha256 = p_authority_request_sha256;
  IF existing.settlement_sha256 <> p_settlement_sha256
      OR existing.change_set_id <> btrim(p_change_set_id)
      OR existing.repository <> btrim(p_repository)
      OR existing.commit_sha <> p_commit_sha
      OR existing.parent_sha <> p_parent_sha
      OR existing.exact_paths <> p_exact_paths
      OR existing.commit_worker_ref <> btrim(p_commit_worker_ref)
      OR existing.actuation_observed_at <> p_actuation_observed_at THEN
    RAISE EXCEPTION
      'commit settlement conflicts with its original receipt';
  END IF;

  RETURN QUERY
  SELECT *
  FROM volpred_ops.commit_delivery_receipt_reads
  WHERE authority_request_sha256 = p_authority_request_sha256;
END;
$$;

ALTER TABLE volpred_ops.commit_delivery_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.commit_delivery_receipts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS commit_delivery_receipts_definer_select
  ON volpred_ops.commit_delivery_receipts;
CREATE POLICY commit_delivery_receipts_definer_select
  ON volpred_ops.commit_delivery_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS commit_delivery_receipts_definer_insert
  ON volpred_ops.commit_delivery_receipts;
CREATE POLICY commit_delivery_receipts_definer_insert
  ON volpred_ops.commit_delivery_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER TABLE volpred_ops.commit_delivery_receipts
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.commit_delivery_receipt_reads
  OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text, jsonb, text, timestamptz, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.commit_delivery_receipts,
  volpred_ops.commit_delivery_receipt_reads
FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text, jsonb, text, timestamptz, text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION volpred_ops.settle_commit_write(
  text, text, bigint, text, text, text, text, text, text, text, text,
  text, text, jsonb, text, timestamptz, text
) TO volpred_ops_worker;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
