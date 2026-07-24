-- Route durable outbox claims by provider capability.
--
-- The original three-argument claim function selected the oldest ready effect
-- across every family. A worker bound to one narrow provider could therefore
-- claim another family's effect and terminally reject it. Replace that escape
-- hatch with a required effect-kind filter inside the same SKIP LOCKED
-- transaction. The worker also checks the returned EffectRequest in process,
-- so database or adapter drift fails closed before any external provider call.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

SET ROLE volpred_ops_definer;

DROP FUNCTION IF EXISTS volpred_ops.claim_effect_outbox(
  text, integer, text
);

CREATE OR REPLACE FUNCTION volpred_ops.claim_effect_outbox(
  p_worker_id text,
  p_lease_seconds integer,
  p_token text,
  p_effect_kinds text[]
)
RETURNS SETOF volpred_ops.effect_outbox_reads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  message volpred_ops.effect_outbox;
  normalized_effect_kinds text[];
BEGIN
  IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
      OR p_token IS NULL OR btrim(p_token) = '' THEN
    RAISE EXCEPTION 'effect outbox worker and token are required';
  ELSIF p_lease_seconds IS NULL OR p_lease_seconds <= 0 THEN
    RAISE EXCEPTION 'effect outbox lease_seconds must be positive';
  ELSIF p_effect_kinds IS NULL
      OR cardinality(p_effect_kinds) = 0
      OR EXISTS (
        SELECT 1
        FROM unnest(p_effect_kinds) AS requested(effect_kind)
        WHERE effect_kind IS NULL OR btrim(effect_kind) = ''
      ) THEN
    RAISE EXCEPTION 'effect outbox effect kinds are required';
  END IF;

  SELECT array_agg(DISTINCT btrim(effect_kind) ORDER BY btrim(effect_kind))
  INTO normalized_effect_kinds
  FROM unnest(p_effect_kinds) AS requested(effect_kind);

  SELECT outbox_row.* INTO message
  FROM volpred_ops.effect_outbox AS outbox_row
  JOIN volpred_ops.effect_requests AS effect
    ON effect.id = outbox_row.effect_id
  WHERE effect.effect_kind = ANY(normalized_effect_kinds)
    AND outbox_row.available_at <= clock_timestamp()
    AND (
      outbox_row.status = 'pending'
      OR (
        outbox_row.status = 'claimed'
        AND outbox_row.claim_expires_at IS NOT NULL
        AND outbox_row.claim_expires_at <= clock_timestamp()
      )
    )
  ORDER BY outbox_row.available_at, outbox_row.sequence
  FOR UPDATE OF outbox_row SKIP LOCKED
  LIMIT 1;

  IF message.sequence IS NULL THEN
    RETURN;
  END IF;

  UPDATE volpred_ops.effect_outbox
  SET status = 'claimed',
      attempt_count = attempt_count + 1,
      claimed_by = btrim(p_worker_id),
      claim_token = p_token,
      claim_expires_at =
        clock_timestamp() + make_interval(secs => p_lease_seconds)
  WHERE sequence = message.sequence
  RETURNING * INTO message;

  RETURN QUERY
  SELECT * FROM volpred_ops.effect_outbox_reads
  WHERE sequence = message.sequence;
END;
$$;

CREATE INDEX IF NOT EXISTS effect_requests_kind_id_idx
  ON volpred_ops.effect_requests (effect_kind, id);

REVOKE ALL ON FUNCTION volpred_ops.claim_effect_outbox(
  text, integer, text, text[]
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION volpred_ops.claim_effect_outbox(
  text, integer, text, text[]
) TO volpred_ops_worker;

RESET ROLE;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
