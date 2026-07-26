-- Terminalize impossible publisher-delete retries after ownership has moved
-- to a newer generation and the exact destructive approval was revoked.
--
-- This seam never calls a provider and preserves the original immutable
-- retry attempt receipt.  A separate receipt proves why the parent
-- WorkItem/EffectRequest/outbox were dead-lettered.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE
  volpred_ops.owned_publisher_delete_reconciliation_receipts (
    effect_id text NOT NULL
      REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
    attempt_count integer NOT NULL CHECK (attempt_count > 0),
    stale_owner_generation bigint NOT NULL
      CHECK (stale_owner_generation > 0),
    current_owner_generation bigint NOT NULL
      CHECK (current_owner_generation > stale_owner_generation),
    approval_ref text NOT NULL,
    approval_revoked_at timestamptz NOT NULL,
    original_attempt_evidence_sha256 text NOT NULL
      CHECK (
        original_attempt_evidence_sha256 ~ '^[0-9a-f]{64}$'
      ),
    reason_code text NOT NULL
      CHECK (reason_code = 'stale_generation_revoked_approval'),
    actor_ref text NOT NULL,
    evidence_ref text NOT NULL UNIQUE,
    evidence_sha256 text NOT NULL
      CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (effect_id, attempt_count)
  );

CREATE INDEX owned_publisher_delete_reconciliation_recorded_idx
  ON volpred_ops.owned_publisher_delete_reconciliation_receipts (
    recorded_at, effect_id, attempt_count
  );

ALTER TABLE
  volpred_ops.owned_publisher_delete_reconciliation_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE
  volpred_ops.owned_publisher_delete_reconciliation_receipts
  FORCE ROW LEVEL SECURITY;

CREATE POLICY owned_publisher_delete_reconciliation_definer_select
  ON volpred_ops.owned_publisher_delete_reconciliation_receipts
  FOR SELECT TO volpred_ops_definer USING (true);
CREATE POLICY owned_publisher_delete_reconciliation_definer_insert
  ON volpred_ops.owned_publisher_delete_reconciliation_receipts
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE OR REPLACE FUNCTION
public.volpred_reconcile_stale_owned_publisher_article_delete(
  p_limit integer,
  p_actor_ref text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  ownership volpred_ops.notification_owners;
  candidate record;
  event_at timestamptz;
  receipt_evidence_ref text;
  receipt_evidence_sha256 text;
  receipts jsonb := '[]'::jsonb;
  reconciled_count integer := 0;
BEGIN
  IF p_limit IS NULL OR p_limit <= 0 OR p_limit > 100
      OR p_actor_ref IS NULL OR btrim(p_actor_ref) = '' THEN
    RAISE EXCEPTION
      'publisher delete reconciliation fields are invalid';
  END IF;

  SELECT * INTO STRICT ownership
  FROM volpred_ops.notification_owners
  WHERE effect_family = 'publisher.article.supabase.delete'
  FOR SHARE;

  FOR candidate IN
    SELECT
      attempt.effect_id,
      attempt.attempt_count,
      attempt.work_id,
      attempt.owner_generation AS stale_owner_generation,
      approval.approval_ref,
      approval.revoked_at AS approval_revoked_at,
      attempt_receipt.evidence_sha256
        AS original_attempt_evidence_sha256
    FROM volpred_ops.owned_notification_attempts AS attempt
    JOIN volpred_ops.owned_notification_requests AS owned_request
      ON owned_request.effect_id = attempt.effect_id
    JOIN volpred_ops.work_items AS work
      ON work.id = attempt.work_id
    JOIN volpred_ops.effect_requests AS effect
      ON effect.id = attempt.effect_id
    JOIN volpred_ops.effect_outbox AS message
      ON message.sequence = attempt.outbox_sequence
    JOIN volpred_ops.effect_attempt_receipts AS attempt_receipt
      ON attempt_receipt.effect_id = attempt.effect_id
     AND attempt_receipt.attempt_count = attempt.attempt_count
    JOIN volpred_ops.publisher_article_delete_approvals AS approval
      ON approval.approval_ref = (
        convert_from(
          volpred_ops.read_effect_payload(effect.payload_ref),
          'UTF8'
        )::jsonb -> 'authorization' ->> 'approval_ref'
      )
    WHERE owned_request.effect_family = ownership.effect_family
      AND owned_request.owner_generation = attempt.owner_generation
      AND effect.effect_kind = ownership.effect_family
      AND attempt.owner_generation < ownership.generation
      AND attempt.status = 'retry_scheduled'
      AND attempt.reported_outcome = 'retryable_failure'
      AND attempt.disposition = 'retry_scheduled'
      AND attempt_receipt.reported_outcome = 'retryable_failure'
      AND attempt_receipt.disposition = 'retry_scheduled'
      AND work.status = 'pending'
      AND effect.status = 'requested'
      AND message.status = 'pending'
      AND message.attempt_count = attempt.attempt_count
      AND approval.active = false
      AND approval.revoked_at IS NOT NULL
      AND NOT EXISTS (
        SELECT 1
        FROM
          volpred_ops.owned_publisher_delete_reconciliation_receipts
            AS prior_receipt
        WHERE prior_receipt.effect_id = attempt.effect_id
          AND prior_receipt.attempt_count = attempt.attempt_count
      )
    ORDER BY
      attempt.owner_generation,
      attempt.effect_id,
      attempt.attempt_count
    FOR UPDATE OF attempt SKIP LOCKED
    LIMIT p_limit
  LOOP
    event_at := clock_timestamp();
    receipt_evidence_ref :=
      'owned-publisher-delete-reconciliation:'
      || candidate.effect_id
      || ':attempt-' || candidate.attempt_count::text
      || ':current-generation-' || ownership.generation::text;
    receipt_evidence_sha256 := encode(
      sha256(
        convert_to(
          jsonb_build_object(
            'schema_version',
              'owned-publisher-delete-reconciliation-evidence.v1',
            'effect_id', candidate.effect_id,
            'attempt_count', candidate.attempt_count,
            'stale_owner_generation',
              candidate.stale_owner_generation,
            'current_owner_generation', ownership.generation,
            'approval_ref', candidate.approval_ref,
            'approval_revoked_at', candidate.approval_revoked_at,
            'original_attempt_evidence_sha256',
              candidate.original_attempt_evidence_sha256,
            'reason_code', 'stale_generation_revoked_approval',
            'actor_ref', btrim(p_actor_ref),
            'recorded_at', event_at
          )::text,
          'UTF8'
        )
      ),
      'hex'
    );

    INSERT INTO
      volpred_ops.owned_publisher_delete_reconciliation_receipts (
        effect_id,
        attempt_count,
        stale_owner_generation,
        current_owner_generation,
        approval_ref,
        approval_revoked_at,
        original_attempt_evidence_sha256,
        reason_code,
        actor_ref,
        evidence_ref,
        evidence_sha256,
        recorded_at
      )
    VALUES (
      candidate.effect_id,
      candidate.attempt_count,
      candidate.stale_owner_generation,
      ownership.generation,
      candidate.approval_ref,
      candidate.approval_revoked_at,
      candidate.original_attempt_evidence_sha256,
      'stale_generation_revoked_approval',
      btrim(p_actor_ref),
      receipt_evidence_ref,
      receipt_evidence_sha256,
      event_at
    );

    UPDATE volpred_ops.work_items
    SET status = 'failed',
        version = version + 1,
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL,
        result_ref = receipt_evidence_ref,
        result_summary = (
          'publisher delete retry terminalized: '
          'stale generation and revoked approval'
        ),
        finished_at = event_at,
        updated_at = event_at
    WHERE id = candidate.work_id
      AND status = 'pending';
    IF NOT FOUND THEN
      RAISE EXCEPTION
        'publisher delete reconciliation lost WorkItem state';
    END IF;

    INSERT INTO volpred_ops.work_receipts (
      id, work_id, outcome, result_ref, summary, created_at
    )
    VALUES (
      'owned-publisher-delete-reconciliation:'
        || candidate.effect_id
        || ':attempt-' || candidate.attempt_count::text,
      candidate.work_id,
      'failed',
      receipt_evidence_ref,
      'publisher delete retry terminalized without provider mutation',
      event_at
    );

    INSERT INTO volpred_ops.work_events (
      work_id, kind, version, created_at, actor_ref, evidence_ref
    )
    SELECT
      work.id,
      'failed',
      work.version,
      event_at,
      btrim(p_actor_ref),
      receipt_evidence_ref
    FROM volpred_ops.work_items AS work
    WHERE work.id = candidate.work_id;

    UPDATE volpred_ops.effect_requests
    SET status = 'dead_lettered'
    WHERE id = candidate.effect_id
      AND status = 'requested';
    IF NOT FOUND THEN
      RAISE EXCEPTION
        'publisher delete reconciliation lost EffectRequest state';
    END IF;

    UPDATE volpred_ops.effect_outbox
    SET status = 'dead_lettered',
        claimed_by = NULL,
        claim_token = NULL,
        claim_expires_at = NULL
    WHERE effect_id = candidate.effect_id
      AND status = 'pending';
    IF NOT FOUND THEN
      RAISE EXCEPTION
        'publisher delete reconciliation lost outbox state';
    END IF;

    receipts := receipts || jsonb_build_array(
      jsonb_build_object(
        'schema_version',
          'owned-publisher-delete-reconciliation-receipt.v1',
        'effect_id', candidate.effect_id,
        'attempt_count', candidate.attempt_count,
        'stale_owner_generation',
          candidate.stale_owner_generation,
        'current_owner_generation', ownership.generation,
        'approval_ref', candidate.approval_ref,
        'reason_code', 'stale_generation_revoked_approval',
        'evidence_ref', receipt_evidence_ref,
        'evidence_sha256', receipt_evidence_sha256,
        'recorded_at', event_at
      )
    );
    reconciled_count := reconciled_count + 1;
  END LOOP;

  RETURN jsonb_build_object(
    'schema_version',
      'owned-publisher-delete-reconciliation-summary.v1',
    'reconciled_count', reconciled_count,
    'receipts', receipts
  );
END;
$$;

RESET ROLE;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

REVOKE ALL ON
  volpred_ops.owned_publisher_delete_reconciliation_receipts
FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION
  public.volpred_reconcile_stale_owned_publisher_article_delete(
    integer, text
  )
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.volpred_reconcile_stale_owned_publisher_article_delete(
    integer, text
  )
TO service_role;

COMMENT ON FUNCTION
  public.volpred_reconcile_stale_owned_publisher_article_delete(
    integer, text
  )
IS
  'Terminalize stale revoked publisher-delete retries without any provider call.';

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
