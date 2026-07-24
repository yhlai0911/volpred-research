-- Durable ChangeSet proposal and crash-recovery checkpoints.
--
-- This state closes the process-local gap between immutable proposal,
-- token-redacted Git actuation, and post-commit settlement. Raw WorkLease and
-- Primary Authority tokens are deliberately absent.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

CREATE TABLE IF NOT EXISTS volpred_ops.change_sets (
  id text PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  work_item_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  work_item_version integer NOT NULL CHECK (work_item_version > 0),
  base_commit text NOT NULL
    CHECK (base_commit ~ '^([0-9a-f]{40}|[0-9a-f]{64})$'),
  workspace_ref text NOT NULL,
  exact_paths jsonb NOT NULL,
  content_hashes jsonb NOT NULL,
  required_checks jsonb NOT NULL,
  author_ref text NOT NULL,
  author_evidence_ref text NOT NULL,
  proposal_sha256 text NOT NULL
    CHECK (proposal_sha256 ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version = 'changeset.v1'),
  status text NOT NULL
    CHECK (status IN ('proposed', 'commit_unsettled', 'landed')),
  land_command_sha256 text
    CHECK (
      land_command_sha256 IS NULL
      OR land_command_sha256 ~ '^[0-9a-f]{64}$'
    ),
  actuation_receipt jsonb,
  delivery_authority_request_sha256 text
    REFERENCES volpred_ops.commit_delivery_receipts(authority_request_sha256)
    ON DELETE RESTRICT,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CHECK (
    (status = 'proposed'
      AND land_command_sha256 IS NULL
      AND actuation_receipt IS NULL
      AND delivery_authority_request_sha256 IS NULL)
    OR
    (status = 'commit_unsettled'
      AND land_command_sha256 IS NOT NULL
      AND actuation_receipt IS NOT NULL
      AND delivery_authority_request_sha256 IS NULL)
    OR
    (status = 'landed'
      AND land_command_sha256 IS NOT NULL
      AND actuation_receipt IS NOT NULL
      AND delivery_authority_request_sha256 IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS change_sets_work_created_idx
  ON volpred_ops.change_sets (work_item_id, work_item_version, created_at, id);
CREATE INDEX IF NOT EXISTS change_sets_unsettled_idx
  ON volpred_ops.change_sets (updated_at, id)
  WHERE status = 'commit_unsettled';

CREATE OR REPLACE VIEW volpred_ops.change_set_reads AS
SELECT
  change_set.schema_version,
  change_set.id,
  change_set.idempotency_key,
  change_set.work_item_id,
  change_set.work_item_version,
  change_set.base_commit,
  change_set.workspace_ref,
  change_set.exact_paths,
  change_set.content_hashes,
  change_set.required_checks,
  change_set.author_ref,
  change_set.author_evidence_ref,
  change_set.proposal_sha256,
  change_set.status,
  change_set.land_command_sha256,
  change_set.actuation_receipt,
  change_set.created_at,
  change_set.updated_at,
  receipt.schema_version AS delivery_schema_version,
  receipt.authority_request_sha256
    AS delivery_authority_request_sha256,
  receipt.work_lease_ref AS delivery_work_lease_ref,
  receipt.primary_authority_ref AS delivery_primary_authority_ref,
  receipt.repository AS delivery_repository,
  receipt.commit_sha AS delivery_commit_sha,
  receipt.parent_sha AS delivery_parent_sha,
  receipt.exact_paths AS delivery_exact_paths,
  receipt.commit_worker_ref AS delivery_commit_worker_ref,
  receipt.status AS delivery_status,
  receipt.actuation_observed_at AS delivery_actuation_observed_at,
  receipt.settled_at AS delivery_settled_at,
  receipt.settlement_ref AS delivery_settlement_ref,
  receipt.settlement_sha256 AS delivery_settlement_sha256
FROM volpred_ops.change_sets AS change_set
LEFT JOIN volpred_ops.commit_delivery_receipt_reads AS receipt
  ON receipt.authority_request_sha256 =
    change_set.delivery_authority_request_sha256;

CREATE OR REPLACE FUNCTION volpred_ops.create_change_set(
  p_id text,
  p_idempotency_key text,
  p_work_item_id text,
  p_work_item_version integer,
  p_base_commit text,
  p_workspace_ref text,
  p_exact_paths jsonb,
  p_content_hashes jsonb,
  p_required_checks jsonb,
  p_author_ref text,
  p_author_evidence_ref text,
  p_proposal_sha256 text,
  p_schema_version text,
  p_created_at timestamptz
)
RETURNS SETOF volpred_ops.change_set_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  existing volpred_ops.change_sets;
  work_version integer;
BEGIN
  IF p_id IS NULL OR btrim(p_id) = ''
      OR p_idempotency_key IS NULL OR btrim(p_idempotency_key) = ''
      OR p_work_item_id IS NULL OR btrim(p_work_item_id) = ''
      OR p_workspace_ref IS NULL OR btrim(p_workspace_ref) = ''
      OR p_author_ref IS NULL OR btrim(p_author_ref) = ''
      OR p_author_evidence_ref IS NULL
      OR btrim(p_author_evidence_ref) = ''
      OR p_created_at IS NULL
      OR p_schema_version IS DISTINCT FROM 'changeset.v1' THEN
    RAISE EXCEPTION 'ChangeSet fields are required';
  ELSIF p_work_item_version IS NULL OR p_work_item_version <= 0 THEN
    RAISE EXCEPTION 'ChangeSet fields are required';
  ELSIF p_base_commit IS NULL
      OR p_base_commit !~ '^([0-9a-f]{40}|[0-9a-f]{64})$'
      OR p_proposal_sha256 IS NULL
      OR p_proposal_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'ChangeSet hashes must be lowercase SHA-256 or Git ids';
  ELSIF jsonb_typeof(p_exact_paths) IS DISTINCT FROM 'array'
      OR jsonb_array_length(p_exact_paths) = 0
      OR jsonb_typeof(p_content_hashes) IS DISTINCT FROM 'array'
      OR jsonb_array_length(p_content_hashes) = 0
      OR jsonb_typeof(p_required_checks) IS DISTINCT FROM 'array'
      OR jsonb_array_length(p_required_checks) = 0 THEN
    RAISE EXCEPTION 'ChangeSet JSON evidence is invalid';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_idempotency_key, 0));
  SELECT * INTO existing
  FROM volpred_ops.change_sets
  WHERE idempotency_key = btrim(p_idempotency_key);
  IF existing.id IS NOT NULL THEN
    IF existing.proposal_sha256 <> p_proposal_sha256 THEN
      RAISE EXCEPTION
        'ChangeSet idempotency key conflicts with its original payload';
    END IF;
    RETURN QUERY
    SELECT * FROM volpred_ops.change_set_reads WHERE id = existing.id;
    RETURN;
  END IF;

  IF EXISTS (SELECT 1 FROM volpred_ops.change_sets WHERE id = btrim(p_id)) THEN
    RAISE EXCEPTION 'duplicate ChangeSet id: %', btrim(p_id);
  END IF;

  SELECT version INTO work_version
  FROM volpred_ops.work_items
  WHERE id = btrim(p_work_item_id)
  FOR KEY SHARE;
  IF work_version IS NULL THEN
    RAISE EXCEPTION 'ChangeSet work item is unknown: %', btrim(p_work_item_id);
  ELSIF work_version <> p_work_item_version THEN
    RAISE EXCEPTION
      'ChangeSet work item version is stale: expected %, found %',
      p_work_item_version, work_version;
  END IF;

  INSERT INTO volpred_ops.change_sets (
    id, idempotency_key, work_item_id, work_item_version, base_commit,
    workspace_ref, exact_paths, content_hashes, required_checks, author_ref,
    author_evidence_ref, proposal_sha256, schema_version, status,
    created_at, updated_at
  )
  VALUES (
    btrim(p_id), btrim(p_idempotency_key), btrim(p_work_item_id),
    p_work_item_version, p_base_commit, btrim(p_workspace_ref),
    p_exact_paths, p_content_hashes, p_required_checks, btrim(p_author_ref),
    btrim(p_author_evidence_ref), p_proposal_sha256, p_schema_version,
    'proposed', p_created_at, clock_timestamp()
  );

  RETURN QUERY
  SELECT * FROM volpred_ops.change_set_reads WHERE id = btrim(p_id);
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.checkpoint_change_set_actuation(
  p_change_set_id text,
  p_proposal_sha256 text,
  p_land_command_sha256 text,
  p_actuation_receipt jsonb
)
RETURNS SETOF volpred_ops.change_set_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  current_change volpred_ops.change_sets;
BEGIN
  IF p_change_set_id IS NULL OR btrim(p_change_set_id) = ''
      OR p_proposal_sha256 IS NULL
      OR p_proposal_sha256 !~ '^[0-9a-f]{64}$'
      OR p_land_command_sha256 IS NULL
      OR p_land_command_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'ChangeSet hashes must be lowercase SHA-256';
  ELSIF jsonb_typeof(p_actuation_receipt) IS DISTINCT FROM 'object'
      OR p_actuation_receipt - ARRAY[
        'schema_version',
        'proposal_sha256',
        'work_item_id',
        'work_item_version',
        'authority_request_sha256',
        'work_lease_ref',
        'primary_authority_ref',
        'commit_sha',
        'parent_sha',
        'exact_paths',
        'actor',
        'status',
        'observed_at'
      ] <> '{}'::jsonb
      OR p_actuation_receipt->>'schema_version'
        IS DISTINCT FROM 'commit-actuation.v1'
      OR p_actuation_receipt->>'proposal_sha256'
        IS DISTINCT FROM p_proposal_sha256
      OR p_actuation_receipt->>'authority_request_sha256' IS NULL
      OR p_actuation_receipt->>'authority_request_sha256'
        !~ '^[0-9a-f]{64}$'
      OR p_actuation_receipt->>'commit_sha' IS NULL
      OR p_actuation_receipt->>'commit_sha'
        !~ '^([0-9a-f]{40}|[0-9a-f]{64})$'
      OR p_actuation_receipt->>'actor' IS NULL
      OR p_actuation_receipt->>'actor' !~ '^commit-worker:'
      OR p_actuation_receipt->>'status' IS DISTINCT FROM 'committed'
      OR p_actuation_receipt->>'observed_at' IS NULL
      OR p_actuation_receipt->>'observed_at'
        !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR jsonb_typeof(p_actuation_receipt->'exact_paths')
        IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'ChangeSet actuation receipt is invalid';
  END IF;

  SELECT * INTO current_change
  FROM volpred_ops.change_sets
  WHERE id = btrim(p_change_set_id)
  FOR UPDATE;
  IF current_change.id IS NULL THEN
    RAISE EXCEPTION 'unknown ChangeSet: %', btrim(p_change_set_id);
  ELSIF current_change.proposal_sha256 <> p_proposal_sha256 THEN
    RAISE EXCEPTION
      'ChangeSet proposal conflicts with its durable identity';
  ELSIF current_change.land_command_sha256 IS NOT NULL
      AND current_change.land_command_sha256 <> p_land_command_sha256 THEN
    RAISE EXCEPTION
      'ChangeSet landing command conflicts with its original payload';
  ELSIF current_change.actuation_receipt IS NOT NULL
      AND current_change.actuation_receipt <> p_actuation_receipt THEN
    RAISE EXCEPTION
      'ChangeSet actuation conflicts with its durable checkpoint';
  ELSIF current_change.status = 'landed' THEN
    RETURN QUERY
    SELECT * FROM volpred_ops.change_set_reads
    WHERE id = current_change.id;
    RETURN;
  ELSIF current_change.status NOT IN ('proposed', 'commit_unsettled') THEN
    RAISE EXCEPTION 'ChangeSet status cannot checkpoint actuation: %',
      current_change.status;
  END IF;

  IF p_actuation_receipt->>'work_item_id'
      IS DISTINCT FROM current_change.work_item_id
      OR (p_actuation_receipt->>'work_item_version')::integer
        IS DISTINCT FROM current_change.work_item_version
      OR p_actuation_receipt->>'parent_sha'
        IS DISTINCT FROM current_change.base_commit
      OR p_actuation_receipt->'exact_paths'
        IS DISTINCT FROM current_change.exact_paths
      OR coalesce(btrim(p_actuation_receipt->>'work_lease_ref'), '') = ''
      OR coalesce(
        btrim(p_actuation_receipt->>'primary_authority_ref'),
        ''
      ) = '' THEN
    RAISE EXCEPTION
      'ChangeSet actuation receipt is invalid';
  END IF;

  UPDATE volpred_ops.change_sets
  SET status = 'commit_unsettled',
      land_command_sha256 = p_land_command_sha256,
      actuation_receipt = p_actuation_receipt,
      updated_at = clock_timestamp()
  WHERE id = current_change.id
    AND status = 'proposed';

  RETURN QUERY
  SELECT * FROM volpred_ops.change_set_reads WHERE id = current_change.id;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.mark_change_set_landed(
  p_change_set_id text,
  p_proposal_sha256 text,
  p_land_command_sha256 text,
  p_delivery_authority_request_sha256 text
)
RETURNS SETOF volpred_ops.change_set_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  current_change volpred_ops.change_sets;
  receipt volpred_ops.commit_delivery_receipt_reads;
BEGIN
  IF p_change_set_id IS NULL OR btrim(p_change_set_id) = ''
      OR p_proposal_sha256 IS NULL
      OR p_proposal_sha256 !~ '^[0-9a-f]{64}$'
      OR p_land_command_sha256 IS NULL
      OR p_land_command_sha256 !~ '^[0-9a-f]{64}$'
      OR p_delivery_authority_request_sha256 IS NULL
      OR p_delivery_authority_request_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'ChangeSet hashes must be lowercase SHA-256';
  END IF;

  SELECT * INTO current_change
  FROM volpred_ops.change_sets
  WHERE id = btrim(p_change_set_id)
  FOR UPDATE;
  IF current_change.id IS NULL THEN
    RAISE EXCEPTION 'unknown ChangeSet: %', btrim(p_change_set_id);
  ELSIF current_change.proposal_sha256 <> p_proposal_sha256 THEN
    RAISE EXCEPTION
      'ChangeSet proposal conflicts with its durable identity';
  ELSIF current_change.land_command_sha256
      IS DISTINCT FROM p_land_command_sha256 THEN
    RAISE EXCEPTION
      'ChangeSet landing command conflicts with its original payload';
  ELSIF current_change.delivery_authority_request_sha256 IS NOT NULL
      AND current_change.delivery_authority_request_sha256
        <> p_delivery_authority_request_sha256 THEN
    RAISE EXCEPTION
      'ChangeSet delivery conflicts with its durable receipt';
  END IF;

  SELECT * INTO receipt
  FROM volpred_ops.commit_delivery_receipt_reads
  WHERE authority_request_sha256 =
    p_delivery_authority_request_sha256;
  IF receipt.authority_request_sha256 IS NULL THEN
    RAISE EXCEPTION 'ChangeSet delivery receipt is unknown';
  ELSIF receipt.change_set_id <> current_change.id
      OR receipt.proposal_sha256 <> current_change.proposal_sha256
      OR receipt.work_item_id <> current_change.work_item_id
      OR receipt.work_item_version <> current_change.work_item_version
      OR receipt.commit_sha
        IS DISTINCT FROM current_change.actuation_receipt->>'commit_sha'
      OR receipt.parent_sha
        IS DISTINCT FROM current_change.actuation_receipt->>'parent_sha'
      OR receipt.exact_paths
        IS DISTINCT FROM current_change.actuation_receipt->'exact_paths'
      OR receipt.commit_worker_ref
        IS DISTINCT FROM current_change.actuation_receipt->>'actor'
      OR receipt.actuation_observed_at
        <> (current_change.actuation_receipt->>'observed_at')::timestamptz THEN
    RAISE EXCEPTION
      'ChangeSet delivery receipt does not match its actuation checkpoint';
  ELSIF current_change.status = 'proposed' THEN
    RAISE EXCEPTION 'ChangeSet status cannot land from proposed';
  END IF;

  UPDATE volpred_ops.change_sets
  SET status = 'landed',
      delivery_authority_request_sha256 =
        p_delivery_authority_request_sha256,
      updated_at = clock_timestamp()
  WHERE id = current_change.id
    AND status = 'commit_unsettled';

  RETURN QUERY
  SELECT * FROM volpred_ops.change_set_reads WHERE id = current_change.id;
END;
$$;

ALTER TABLE volpred_ops.change_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.change_sets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS change_sets_definer_select ON volpred_ops.change_sets;
CREATE POLICY change_sets_definer_select
  ON volpred_ops.change_sets
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS change_sets_definer_insert ON volpred_ops.change_sets;
CREATE POLICY change_sets_definer_insert
  ON volpred_ops.change_sets
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS change_sets_definer_update ON volpred_ops.change_sets;
CREATE POLICY change_sets_definer_update
  ON volpred_ops.change_sets
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

ALTER TABLE volpred_ops.change_sets OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.change_set_reads OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.create_change_set(
  text, text, text, integer, text, text, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.checkpoint_change_set_actuation(
  text, text, text, jsonb
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.mark_change_set_landed(
  text, text, text, text
) OWNER TO volpred_ops_definer;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON TABLE volpred_ops.change_sets FROM PUBLIC;
REVOKE ALL ON TABLE volpred_ops.change_set_reads FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_ops.create_change_set(
  text, text, text, integer, text, text, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_ops.checkpoint_change_set_actuation(
  text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_ops.mark_change_set_landed(
  text, text, text, text
) FROM PUBLIC;

GRANT SELECT ON volpred_ops.change_set_reads TO volpred_ops_worker;
GRANT EXECUTE ON FUNCTION volpred_ops.create_change_set(
  text, text, text, integer, text, text, jsonb, jsonb, jsonb,
  text, text, text, text, timestamptz
) TO volpred_ops_worker;
GRANT EXECUTE ON FUNCTION volpred_ops.checkpoint_change_set_actuation(
  text, text, text, jsonb
) TO volpred_ops_worker;
GRANT EXECUTE ON FUNCTION volpred_ops.mark_change_set_landed(
  text, text, text, text
) TO volpred_ops_worker;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
