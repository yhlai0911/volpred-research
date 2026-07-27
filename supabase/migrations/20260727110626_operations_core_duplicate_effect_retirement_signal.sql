-- Append-only duplicate-effect violations for Issue #46 retirement evidence.
--
-- A duplicate is a second acknowledged/delivered settlement for one immutable
-- EffectRequest. The normal outbox state machine makes this unreachable; the
-- trigger is an independent tripwire at the durable settlement boundary.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;
GRANT CREATE ON SCHEMA public TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

CREATE TABLE IF NOT EXISTS volpred_ops.legacy_retirement_duplicate_effect_head (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  high_watermark bigint NOT NULL CHECK (high_watermark >= 0)
);

INSERT INTO volpred_ops.legacy_retirement_duplicate_effect_head (
  singleton,
  high_watermark
)
VALUES (true, 0)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS volpred_ops.legacy_retirement_duplicate_effect_events (
  sequence bigint PRIMARY KEY CHECK (sequence > 0),
  effect_id text NOT NULL
    REFERENCES volpred_ops.effect_requests(id) ON DELETE RESTRICT,
  first_delivered_attempt_count integer NOT NULL
    CHECK (first_delivered_attempt_count > 0),
  offending_attempt_count integer NOT NULL
    CHECK (
      offending_attempt_count > 0
      AND offending_attempt_count <> first_delivered_attempt_count
    ),
  offending_evidence_sha256 text NOT NULL
    CHECK (offending_evidence_sha256 ~ '^[0-9a-f]{64}$'),
  detected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (effect_id, offending_attempt_count)
);

ALTER TABLE volpred_ops.legacy_retirement_duplicate_effect_events
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_duplicate_effect_events
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_duplicate_effect_head
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.legacy_retirement_duplicate_effect_head
  FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_retirement_duplicate_effect_definer_select
  ON volpred_ops.legacy_retirement_duplicate_effect_events;
CREATE POLICY legacy_retirement_duplicate_effect_definer_select
  ON volpred_ops.legacy_retirement_duplicate_effect_events
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS legacy_retirement_duplicate_effect_definer_insert
  ON volpred_ops.legacy_retirement_duplicate_effect_events;
CREATE POLICY legacy_retirement_duplicate_effect_definer_insert
  ON volpred_ops.legacy_retirement_duplicate_effect_events
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS legacy_retirement_duplicate_effect_head_definer_select
  ON volpred_ops.legacy_retirement_duplicate_effect_head;
CREATE POLICY legacy_retirement_duplicate_effect_head_definer_select
  ON volpred_ops.legacy_retirement_duplicate_effect_head
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS legacy_retirement_duplicate_effect_head_definer_insert
  ON volpred_ops.legacy_retirement_duplicate_effect_head;
CREATE POLICY legacy_retirement_duplicate_effect_head_definer_insert
  ON volpred_ops.legacy_retirement_duplicate_effect_head
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);
DROP POLICY IF EXISTS legacy_retirement_duplicate_effect_head_definer_update
  ON volpred_ops.legacy_retirement_duplicate_effect_head;
CREATE POLICY legacy_retirement_duplicate_effect_head_definer_update
  ON volpred_ops.legacy_retirement_duplicate_effect_head
  FOR UPDATE TO volpred_ops_definer USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION volpred_ops.capture_duplicate_effect_delivery()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  first_attempt integer;
  next_sequence bigint;
BEGIN
  IF NEW.disposition <> 'delivered' THEN
    RETURN NEW;
  END IF;

  -- Receipt attempts normally settle in increasing order, but the retirement
  -- tripwire cannot rely on that business invariant.  Serialize every
  -- delivered insert for one immutable EffectRequest, then classify the first
  -- already-committed receipt as the original delivery.
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'duplicate-effect-delivery:' || NEW.effect_id,
      0
    )
  );

  SELECT receipt.attempt_count
  INTO first_attempt
  FROM volpred_ops.effect_attempt_receipts AS receipt
  WHERE receipt.effect_id = NEW.effect_id
    AND receipt.disposition = 'delivered'
    AND receipt.attempt_count <> NEW.attempt_count
  ORDER BY receipt.recorded_at, receipt.attempt_count
  LIMIT 1;

  IF first_attempt IS NOT NULL THEN
    UPDATE volpred_ops.legacy_retirement_duplicate_effect_head
    SET high_watermark = high_watermark + 1
    WHERE singleton
    RETURNING high_watermark INTO next_sequence;
    IF next_sequence IS NULL THEN
      RAISE EXCEPTION 'duplicate-effect durable head is missing';
    END IF;
    INSERT INTO volpred_ops.legacy_retirement_duplicate_effect_events (
      sequence,
      effect_id,
      first_delivered_attempt_count,
      offending_attempt_count,
      offending_evidence_sha256,
      detected_at
    )
    VALUES (
      next_sequence,
      NEW.effect_id,
      first_attempt,
      NEW.attempt_count,
      NEW.evidence_sha256,
      NEW.recorded_at
    );
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS capture_duplicate_effect_delivery
  ON volpred_ops.effect_attempt_receipts;
CREATE TRIGGER capture_duplicate_effect_delivery
AFTER INSERT ON volpred_ops.effect_attempt_receipts
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.capture_duplicate_effect_delivery();

-- Preserve any violation that predates this forward ratchet with a dense,
-- deterministic transactional sequence.  Unlike an IDENTITY sequence, this
-- head cannot advance when its inserting transaction rolls back.
DO $$
DECLARE
  duplicate record;
  next_sequence bigint;
BEGIN
  FOR duplicate IN
    WITH ranked AS (
      SELECT
        receipt.effect_id,
        receipt.attempt_count,
        receipt.evidence_sha256,
        receipt.recorded_at,
        first_value(receipt.attempt_count) OVER (
          PARTITION BY receipt.effect_id
          ORDER BY receipt.recorded_at, receipt.attempt_count
        ) AS first_attempt_count,
        row_number() OVER (
          PARTITION BY receipt.effect_id
          ORDER BY receipt.recorded_at, receipt.attempt_count
        ) AS delivered_ordinal
      FROM volpred_ops.effect_attempt_receipts AS receipt
      WHERE receipt.disposition = 'delivered'
    )
    SELECT
      ranked.effect_id,
      ranked.first_attempt_count,
      ranked.attempt_count,
      ranked.evidence_sha256,
      ranked.recorded_at
    FROM ranked
    WHERE ranked.delivered_ordinal > 1
      AND NOT EXISTS (
        SELECT 1
        FROM volpred_ops.legacy_retirement_duplicate_effect_events AS event
        WHERE event.effect_id = ranked.effect_id
      )
    ORDER BY ranked.recorded_at, ranked.effect_id, ranked.attempt_count
  LOOP
    UPDATE volpred_ops.legacy_retirement_duplicate_effect_head
    SET high_watermark = high_watermark + 1
    WHERE singleton
    RETURNING high_watermark INTO next_sequence;
    INSERT INTO volpred_ops.legacy_retirement_duplicate_effect_events (
      sequence,
      effect_id,
      first_delivered_attempt_count,
      offending_attempt_count,
      offending_evidence_sha256,
      detected_at
    )
    VALUES (
      next_sequence,
      duplicate.effect_id,
      duplicate.first_attempt_count,
      duplicate.attempt_count,
      duplicate.evidence_sha256,
      duplicate.recorded_at
    );
  END LOOP;
END;
$$;

RESET ROLE;

CREATE OR REPLACE FUNCTION public.volpred_read_duplicate_effect_retirement_events(
  p_after_sequence bigint DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  snapshot_at timestamptz;
  high_watermark bigint;
  events jsonb;
BEGIN
  IF p_after_sequence IS NULL OR p_after_sequence < 0 THEN
    RAISE EXCEPTION 'duplicate-effect cursor must be non-negative';
  END IF;
  snapshot_at := statement_timestamp();

  SELECT head.high_watermark
  INTO high_watermark
  FROM volpred_ops.legacy_retirement_duplicate_effect_head AS head
  WHERE head.singleton;
  IF high_watermark IS NULL THEN
    RAISE EXCEPTION 'duplicate-effect durable head is missing';
  END IF;

  IF p_after_sequence > high_watermark THEN
    RAISE EXCEPTION
      'duplicate-effect cursor exceeds durable high watermark';
  END IF;

  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'sequence', event.sequence,
        'effect_id', event.effect_id,
        'first_delivered_attempt_count',
          event.first_delivered_attempt_count,
        'offending_attempt_count', event.offending_attempt_count,
        'offending_evidence_sha256', event.offending_evidence_sha256,
        'detected_at', event.detected_at
      )
      ORDER BY event.sequence
    ),
    '[]'::jsonb
  )
  INTO events
  FROM volpred_ops.legacy_retirement_duplicate_effect_events AS event
  WHERE event.sequence > p_after_sequence
    AND event.sequence <= high_watermark;

  RETURN jsonb_build_object(
    'schema_version', 'duplicate-effect-retirement-events.v1',
    'observed_at', snapshot_at,
    'after_sequence', p_after_sequence,
    'high_watermark', high_watermark,
    'events', events
  );
END;
$$;

ALTER FUNCTION public.volpred_read_duplicate_effect_retirement_events(bigint)
  OWNER TO volpred_ops_definer;

REVOKE ALL ON TABLE
  volpred_ops.legacy_retirement_duplicate_effect_events
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE
  volpred_ops.legacy_retirement_duplicate_effect_head
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  volpred_ops.capture_duplicate_effect_delivery()
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
  public.volpred_read_duplicate_effect_retirement_events(bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.volpred_read_duplicate_effect_retirement_events(bigint)
  TO service_role;

REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;
REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
