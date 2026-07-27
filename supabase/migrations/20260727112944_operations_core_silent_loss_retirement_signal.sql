-- Durable silent-loss evidence for Issue #46 legacy retirement.
--
-- A formal WorkItem is silently lost when its accepted lifecycle can no
-- longer be reconciled to the mandatory event/terminal-receipt contract, or
-- when executable work crosses its explicit deadline without a terminal
-- outcome. A DB-clock reconciliation RPC appends each occurrence before
-- returning the gap-free interval snapshot to Operations Core.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
GRANT REFERENCES ON TABLE volpred_ops.work_items TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE IF NOT EXISTS volpred_ops.legacy_retirement_silent_loss_head (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  high_watermark bigint NOT NULL CHECK (high_watermark >= 0)
);

INSERT INTO volpred_ops.legacy_retirement_silent_loss_head (
  singleton,
  high_watermark
)
VALUES (true, 0)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS volpred_ops.legacy_retirement_silent_loss_events (
  sequence bigint PRIMARY KEY CHECK (sequence > 0),
  work_id text NOT NULL
    REFERENCES volpred_ops.work_items(id) ON DELETE RESTRICT,
  work_version integer NOT NULL CHECK (work_version > 0),
  violation_kind text NOT NULL
    CHECK (
      violation_kind IN (
        'submitted_event_missing',
        'deadline_missed',
        'terminal_receipt_missing',
        'terminal_receipt_mismatch',
        'receipt_without_terminal_state',
        'active_event_missing',
        'terminal_event_missing'
      )
    ),
  work_status text NOT NULL,
  deadline timestamptz,
  detected_at timestamptz NOT NULL,
  UNIQUE (work_id, violation_kind, work_version)
);

ALTER TABLE volpred_ops.legacy_retirement_silent_loss_events
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_silent_loss_events
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_silent_loss_head
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_silent_loss_head
  FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_retirement_silent_loss_definer_select
  ON volpred_ops.legacy_retirement_silent_loss_events;
CREATE POLICY legacy_retirement_silent_loss_definer_select
  ON volpred_ops.legacy_retirement_silent_loss_events
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS legacy_retirement_silent_loss_definer_insert
  ON volpred_ops.legacy_retirement_silent_loss_events;
CREATE POLICY legacy_retirement_silent_loss_definer_insert
  ON volpred_ops.legacy_retirement_silent_loss_events
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS legacy_retirement_silent_loss_head_definer_select
  ON volpred_ops.legacy_retirement_silent_loss_head;
CREATE POLICY legacy_retirement_silent_loss_head_definer_select
  ON volpred_ops.legacy_retirement_silent_loss_head
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS legacy_retirement_silent_loss_head_definer_insert
  ON volpred_ops.legacy_retirement_silent_loss_head;
CREATE POLICY legacy_retirement_silent_loss_head_definer_insert
  ON volpred_ops.legacy_retirement_silent_loss_head
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS legacy_retirement_silent_loss_head_definer_update
  ON volpred_ops.legacy_retirement_silent_loss_head;
CREATE POLICY legacy_retirement_silent_loss_head_definer_update
  ON volpred_ops.legacy_retirement_silent_loss_head
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION volpred_ops.silent_loss_active_candidates(
  p_snapshot_at timestamptz
)
RETURNS TABLE (
  work_id text,
  work_version integer,
  violation_kind text,
  work_status text,
  deadline timestamptz
)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
  SELECT
    work.id,
    work.version,
    'submitted_event_missing'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE NOT EXISTS (
    SELECT 1
    FROM volpred_ops.work_events AS event
    WHERE event.work_id = work.id
      AND event.kind = 'submitted'
      AND event.version = 1
  )

  UNION ALL

  SELECT
    work.id,
    work.version,
    'deadline_missed'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE work.deadline IS NOT NULL
    AND work.deadline < p_snapshot_at
    AND work.status IN ('pending', 'claimed', 'running')

  UNION ALL

  SELECT
    work.id,
    work.version,
    'terminal_receipt_missing'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE work.status IN ('succeeded', 'failed', 'cancelled')
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.work_receipts AS receipt
      WHERE receipt.work_id = work.id
    )

  UNION ALL

  SELECT
    work.id,
    work.version,
    'terminal_receipt_mismatch'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE work.status IN ('succeeded', 'failed', 'cancelled')
    AND (
      (
        SELECT count(*)
        FROM volpred_ops.work_receipts AS receipt
        WHERE receipt.work_id = work.id
      ) > 1
      OR EXISTS (
        SELECT 1
        FROM volpred_ops.work_receipts AS receipt
        WHERE receipt.work_id = work.id
          AND receipt.outcome <> work.status
      )
    )

  UNION ALL

  SELECT
    work.id,
    work.version,
    'receipt_without_terminal_state'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE work.status NOT IN ('succeeded', 'failed', 'cancelled')
    AND EXISTS (
      SELECT 1
      FROM volpred_ops.work_receipts AS receipt
      WHERE receipt.work_id = work.id
    )

  UNION ALL

  SELECT
    work.id,
    work.version,
    'active_event_missing'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE (
    work.status = 'claimed'
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.work_events AS event
      WHERE event.work_id = work.id
        AND event.kind = 'acquired'
        AND event.version = work.version
    )
  ) OR (
    work.status = 'running'
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.work_events AS event
      WHERE event.work_id = work.id
        AND event.kind IN ('started', 'checkpointed')
        AND event.version = work.version
    )
  )

  UNION ALL

  SELECT
    work.id,
    work.version,
    'terminal_event_missing'::text,
    work.status,
    work.deadline
  FROM volpred_ops.work_items AS work
  WHERE work.status IN ('succeeded', 'failed', 'cancelled')
    AND NOT EXISTS (
      SELECT 1
      FROM volpred_ops.work_events AS event
      WHERE event.work_id = work.id
        AND event.kind = CASE work.status
          WHEN 'succeeded' THEN 'completed'
          ELSE work.status
        END
        AND event.version = work.version
    );
$$;

RESET ROLE;

CREATE OR REPLACE FUNCTION public.volpred_reconcile_silent_loss_retirement_events(
  p_after_sequence bigint DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  snapshot_at timestamptz;
  high_watermark bigint;
  next_sequence bigint;
  candidate record;
  events jsonb;
  active_violations jsonb;
BEGIN
  IF p_after_sequence IS NULL OR p_after_sequence < 0 THEN
    RAISE EXCEPTION 'silent-loss cursor must be non-negative';
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'legacy-retirement:silent-loss-reconcile',
      0
    )
  );
  snapshot_at := pg_catalog.clock_timestamp();

  SELECT head.high_watermark
  INTO high_watermark
  FROM volpred_ops.legacy_retirement_silent_loss_head AS head
  WHERE head.singleton;
  IF high_watermark IS NULL THEN
    RAISE EXCEPTION 'silent-loss durable head is missing';
  ELSIF p_after_sequence > high_watermark THEN
    RAISE EXCEPTION 'silent-loss cursor exceeds durable high watermark';
  END IF;

  FOR candidate IN
    SELECT candidates.*
    FROM volpred_ops.silent_loss_active_candidates(snapshot_at) AS candidates
    WHERE NOT EXISTS (
      SELECT 1
      FROM volpred_ops.legacy_retirement_silent_loss_events AS event
      WHERE event.work_id = candidates.work_id
        AND event.violation_kind = candidates.violation_kind
        AND event.work_version = candidates.work_version
    )
    ORDER BY
      candidates.work_id,
      candidates.work_version,
      candidates.violation_kind
  LOOP
    UPDATE volpred_ops.legacy_retirement_silent_loss_head AS head
    SET high_watermark = head.high_watermark + 1
    WHERE head.singleton
    RETURNING head.high_watermark INTO next_sequence;
    IF next_sequence IS NULL THEN
      RAISE EXCEPTION 'silent-loss durable head is missing';
    END IF;
    INSERT INTO volpred_ops.legacy_retirement_silent_loss_events (
      sequence,
      work_id,
      work_version,
      violation_kind,
      work_status,
      deadline,
      detected_at
    )
    VALUES (
      next_sequence,
      candidate.work_id,
      candidate.work_version,
      candidate.violation_kind,
      candidate.work_status,
      candidate.deadline,
      snapshot_at
    );
  END LOOP;

  SELECT head.high_watermark
  INTO high_watermark
  FROM volpred_ops.legacy_retirement_silent_loss_head AS head
  WHERE head.singleton;

  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'sequence', event.sequence,
        'work_id', event.work_id,
        'work_version', event.work_version,
        'violation_kind', event.violation_kind,
        'work_status', event.work_status,
        'deadline', event.deadline,
        'detected_at', event.detected_at
      )
      ORDER BY event.sequence
    ),
    '[]'::jsonb
  )
  INTO events
  FROM volpred_ops.legacy_retirement_silent_loss_events AS event
  WHERE event.sequence > p_after_sequence
    AND event.sequence <= high_watermark;

  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'sequence', event.sequence,
        'work_id', event.work_id,
        'work_version', event.work_version,
        'violation_kind', event.violation_kind,
        'work_status', event.work_status,
        'deadline', event.deadline,
        'detected_at', event.detected_at
      )
      ORDER BY event.sequence
    ),
    '[]'::jsonb
  )
  INTO active_violations
  FROM volpred_ops.silent_loss_active_candidates(snapshot_at)
    AS active_candidate
  JOIN volpred_ops.legacy_retirement_silent_loss_events AS event
    ON event.work_id = active_candidate.work_id
   AND event.work_version = active_candidate.work_version
   AND event.violation_kind = active_candidate.violation_kind;

  RETURN jsonb_build_object(
    'schema_version', 'silent-loss-retirement-events.v1',
    'observed_at', snapshot_at,
    'after_sequence', p_after_sequence,
    'high_watermark', high_watermark,
    'events', events,
    'active_violations', active_violations
  );
END;
$$;

ALTER FUNCTION public.volpred_reconcile_silent_loss_retirement_events(bigint)
  OWNER TO volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.legacy_retirement_silent_loss_events
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE
  volpred_ops.legacy_retirement_silent_loss_head
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  volpred_ops.silent_loss_active_candidates(timestamptz)
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  public.volpred_reconcile_silent_loss_retirement_events(bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.volpred_reconcile_silent_loss_retirement_events(bigint)
  TO service_role;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;
REVOKE REFERENCES ON TABLE volpred_ops.work_items FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
