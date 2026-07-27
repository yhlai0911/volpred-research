-- Primary Authority append-only lifecycle audit.
--
-- Lease rows are a current-state projection: renew overwrites expiry, expiry
-- is inferred, and a rejected function call normally rolls its transaction
-- back.  That shape cannot satisfy the Issue #18 receipt contract.  This
-- forward-only migration adds an append-only event ledger, transition trigger,
-- and typed try-functions whose exception subtransaction can roll back while
-- the outer function persists a token-redacted rejection receipt.

DO $$
BEGIN
  EXECUTE format('GRANT volpred_ops_definer TO %I', current_user);
END;
$$;

GRANT CREATE ON SCHEMA volpred_ops TO volpred_ops_definer;

-- The owned-effect RPCs predate the umbrella authority contract and locate
-- their keepalive lease using one capability-specific key per effect family.
-- Replacing only the Python builders would therefore leave the actual SQL
-- mutation boundary on the legacy split-brain contract.  Rewrite every live
-- function definition that still embeds one of those authority keys before
-- enforcing the formal-grant trigger below.  Effect-family identifiers use
-- dots rather than colons and are intentionally unchanged.
DO $migration$
DECLARE
  legacy_key text;
  function_row record;
  original_definition text;
  rewritten_definition text;
BEGIN
  FOREACH legacy_key IN ARRAY ARRAY[
    'notification:email.ops_alert',
    'publisher:article.supabase.sync',
    'publisher:article.supabase.reconcile',
    'publisher:article.supabase.delete'
  ]
  LOOP
    FOR function_row IN
      SELECT
        procedure.oid,
        pg_catalog.pg_get_functiondef(procedure.oid) AS definition
      FROM pg_catalog.pg_proc AS procedure
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = procedure.pronamespace
      WHERE namespace.nspname IN ('public', 'volpred_ops')
        AND procedure.prokind = 'f'
        AND pg_catalog.strpos(
          pg_catalog.pg_get_functiondef(procedure.oid),
          legacy_key
        ) > 0
    LOOP
      original_definition := function_row.definition;
      rewritten_definition := pg_catalog.replace(
        original_definition,
        legacy_key,
        'operations-core-primary'
      );
      IF rewritten_definition = original_definition THEN
        RAISE EXCEPTION
          'Primary Authority SQL boundary rewrite did not change function %',
          function_row.oid::regprocedure;
      END IF;
      EXECUTE rewritten_definition;
    END LOOP;
    -- A focused migration test (or an idempotent replay) may not contain a
    -- given owned-effect family.  Zero is safe because the query searched the
    -- complete live function catalog; any matching boundary is rewritten.
  END LOOP;
END;
$migration$;

CREATE TABLE IF NOT EXISTS volpred_ops.primary_authority_events (
  sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  authority_key text NOT NULL CHECK (btrim(authority_key) <> ''),
  event_type text NOT NULL CHECK (
    event_type IN ('acquired', 'renewed', 'expired', 'demoted', 'rejected')
  ),
  operation text NOT NULL CHECK (
    operation IN ('acquire', 'renew', 'authorize', 'release', 'reconcile')
  ),
  epoch bigint CHECK (epoch IS NULL OR epoch > 0),
  holder_ref text,
  reason_code text,
  reason text,
  lease_expires_at timestamptz,
  occurred_at timestamptz NOT NULL,
  CHECK (
    (event_type = 'rejected' AND reason_code IS NOT NULL AND reason IS NOT NULL)
    OR
    (event_type <> 'rejected' AND reason_code IS NULL AND reason IS NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS
  primary_authority_events_single_terminal_idx
ON volpred_ops.primary_authority_events (authority_key, epoch, event_type)
WHERE event_type IN ('expired', 'demoted');

CREATE INDEX IF NOT EXISTS primary_authority_events_read_idx
ON volpred_ops.primary_authority_events (
  authority_key, sequence, occurred_at
);

CREATE OR REPLACE VIEW volpred_ops.primary_authority_event_reads AS
SELECT
  'primary-authority-event:' || sequence::text AS event_ref,
  authority_key,
  event_type,
  operation,
  epoch,
  holder_ref,
  reason_code,
  reason,
  lease_expires_at,
  occurred_at
FROM volpred_ops.primary_authority_events;

ALTER TABLE volpred_ops.primary_authority_events
  OWNER TO volpred_ops_definer;
ALTER VIEW volpred_ops.primary_authority_event_reads
  OWNER TO volpred_ops_definer;
ALTER SEQUENCE volpred_ops.primary_authority_events_sequence_seq
  OWNER TO volpred_ops_definer;

ALTER TABLE volpred_ops.primary_authority_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_ops.primary_authority_events FORCE ROW LEVEL SECURITY;
REVOKE ALL ON volpred_ops.primary_authority_events FROM PUBLIC;
REVOKE ALL ON volpred_ops.primary_authority_event_reads FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_ops FROM PUBLIC;
GRANT SELECT, INSERT ON volpred_ops.primary_authority_events
  TO volpred_ops_definer;
GRANT SELECT ON volpred_ops.primary_authority_event_reads
  TO volpred_ops_definer, volpred_ops_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA volpred_ops
  TO volpred_ops_definer;

DROP POLICY IF EXISTS primary_authority_events_definer_select
  ON volpred_ops.primary_authority_events;
CREATE POLICY primary_authority_events_definer_select
  ON volpred_ops.primary_authority_events
  FOR SELECT TO volpred_ops_definer USING (true);
DROP POLICY IF EXISTS primary_authority_events_definer_insert
  ON volpred_ops.primary_authority_events;
CREATE POLICY primary_authority_events_definer_insert
  ON volpred_ops.primary_authority_events
  FOR INSERT TO volpred_ops_definer WITH CHECK (true);

CREATE OR REPLACE FUNCTION volpred_ops.audit_primary_authority_transition()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  event_at timestamptz;
BEGIN
  event_at := COALESCE(NEW.updated_at, clock_timestamp());
  IF TG_OP = 'INSERT' AND NEW.holder_ref IS NOT NULL THEN
    INSERT INTO volpred_ops.primary_authority_events (
      authority_key, event_type, operation, epoch, holder_ref,
      lease_expires_at, occurred_at
    )
    VALUES (
      NEW.authority_key, 'acquired', 'acquire', NEW.epoch, NEW.holder_ref,
      NEW.lease_expires_at, event_at
    );
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.holder_ref IS NOT NULL
        AND NEW.epoch > OLD.epoch
        AND OLD.lease_expires_at IS NOT NULL
        AND OLD.lease_expires_at <= event_at THEN
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        OLD.authority_key, 'expired', 'acquire', OLD.epoch, OLD.holder_ref,
        OLD.lease_expires_at, event_at
      )
      ON CONFLICT (authority_key, epoch, event_type)
        WHERE event_type IN ('expired', 'demoted')
      DO NOTHING;
    END IF;

    IF NEW.epoch > OLD.epoch AND NEW.holder_ref IS NOT NULL THEN
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        NEW.authority_key, 'acquired', 'acquire', NEW.epoch, NEW.holder_ref,
        NEW.lease_expires_at, event_at
      );
    ELSIF OLD.holder_ref IS NOT NULL AND NEW.holder_ref IS NULL THEN
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        OLD.authority_key, 'demoted', 'release', OLD.epoch, OLD.holder_ref,
        OLD.lease_expires_at, event_at
      )
      ON CONFLICT (authority_key, epoch, event_type)
        WHERE event_type IN ('expired', 'demoted')
      DO NOTHING;
    ELSIF NEW.epoch = OLD.epoch
        AND NEW.holder_ref IS NOT DISTINCT FROM OLD.holder_ref
        AND NEW.lease_expires_at > OLD.lease_expires_at THEN
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        NEW.authority_key, 'renewed', 'renew', NEW.epoch, NEW.holder_ref,
        NEW.lease_expires_at, event_at
      );
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

ALTER FUNCTION volpred_ops.audit_primary_authority_transition()
  OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION volpred_ops.audit_primary_authority_transition()
  FROM PUBLIC, anon, authenticated, service_role;

DROP TRIGGER IF EXISTS audit_primary_authority_transition
  ON volpred_ops.primary_authority_leases;
CREATE TRIGGER audit_primary_authority_transition
AFTER INSERT OR UPDATE ON volpred_ops.primary_authority_leases
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.audit_primary_authority_transition();

-- Preserve the identity of a lease that was already active when this
-- forward-only migration was applied.
INSERT INTO volpred_ops.primary_authority_events (
  authority_key, event_type, operation, epoch, holder_ref,
  lease_expires_at, occurred_at
)
SELECT
  lease.authority_key,
  'acquired',
  'acquire',
  lease.epoch,
  lease.holder_ref,
  lease.lease_expires_at,
  lease.acquired_at
FROM volpred_ops.primary_authority_leases AS lease
WHERE lease.holder_ref IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM volpred_ops.primary_authority_events AS event
    WHERE event.authority_key = lease.authority_key
      AND event.epoch = lease.epoch
      AND event.event_type = 'acquired'
  );

CREATE OR REPLACE FUNCTION
  volpred_ops.materialize_primary_authority_expiry(
    p_authority_key text
  )
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  event_at timestamptz;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = '' THEN
    RAISE EXCEPTION 'Primary Authority key is required';
  END IF;
  event_at := clock_timestamp();
  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;
  IF authority.authority_key IS NULL
      OR authority.holder_ref IS NULL
      OR authority.lease_expires_at > event_at THEN
    RETURN false;
  END IF;

  INSERT INTO volpred_ops.primary_authority_events (
    authority_key, event_type, operation, epoch, holder_ref,
    lease_expires_at, occurred_at
  )
  VALUES (
    authority.authority_key, 'expired', 'reconcile', authority.epoch,
    authority.holder_ref, authority.lease_expires_at, event_at
  )
  ON CONFLICT (authority_key, epoch, event_type)
    WHERE event_type IN ('expired', 'demoted')
  DO NOTHING;
  INSERT INTO volpred_ops.primary_authority_events (
    authority_key, event_type, operation, epoch, holder_ref,
    lease_expires_at, occurred_at
  )
  VALUES (
    authority.authority_key, 'demoted', 'reconcile', authority.epoch,
    authority.holder_ref, authority.lease_expires_at, event_at
  )
  ON CONFLICT (authority_key, epoch, event_type)
    WHERE event_type IN ('expired', 'demoted')
  DO NOTHING;
  UPDATE volpred_ops.primary_authority_leases
  SET holder_ref = NULL,
      fencing_token_sha256 = NULL,
      acquired_at = NULL,
      lease_expires_at = NULL,
      updated_at = event_at
  WHERE authority_key = authority.authority_key
    AND epoch = authority.epoch;
  RETURN true;
END;
$$;

ALTER FUNCTION volpred_ops.materialize_primary_authority_expiry(text)
  OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION
  volpred_ops.materialize_primary_authority_expiry(text)
  FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
  volpred_ops.materialize_primary_authority_expiry(text)
  TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION
  volpred_ops.reconcile_primary_authority_demotion(
    p_authority_key text,
    p_holder_ref text,
    p_epoch bigint
  )
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  authority volpred_ops.primary_authority_leases;
  acquired_event volpred_ops.primary_authority_events;
  demoted_event volpred_ops.primary_authority_events;
  event_at timestamptz;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = ''
      OR p_holder_ref IS NULL OR btrim(p_holder_ref) = ''
      OR p_epoch IS NULL OR p_epoch <= 0 THEN
    RAISE EXCEPTION 'Primary Authority demotion identity is required';
  END IF;
  PERFORM volpred_ops.materialize_primary_authority_expiry(
    btrim(p_authority_key)
  );
  SELECT * INTO acquired_event
  FROM volpred_ops.primary_authority_events
  WHERE authority_key = btrim(p_authority_key)
    AND epoch = p_epoch
    AND holder_ref = btrim(p_holder_ref)
    AND event_type = 'acquired'
  ORDER BY sequence
  LIMIT 1;
  IF acquired_event.sequence IS NULL THEN
    RAISE EXCEPTION 'Primary Authority demotion identity is unknown';
  END IF;
  SELECT * INTO authority
  FROM volpred_ops.primary_authority_leases
  WHERE authority_key = btrim(p_authority_key)
  FOR UPDATE;
  IF authority.epoch = p_epoch
      AND authority.holder_ref = btrim(p_holder_ref)
      AND authority.lease_expires_at > clock_timestamp() THEN
    RETURN jsonb_build_object(
      'schema_version', 'primary-authority-demotion-reconcile.v1',
      'status', 'pending',
      'authority_key', btrim(p_authority_key),
      'holder_ref', btrim(p_holder_ref),
      'epoch', p_epoch
    );
  END IF;
  event_at := clock_timestamp();
  INSERT INTO volpred_ops.primary_authority_events (
    authority_key, event_type, operation, epoch, holder_ref,
    lease_expires_at, occurred_at
  )
  VALUES (
    btrim(p_authority_key), 'demoted', 'reconcile', p_epoch,
    btrim(p_holder_ref), acquired_event.lease_expires_at, event_at
  )
  ON CONFLICT (authority_key, epoch, event_type)
    WHERE event_type IN ('expired', 'demoted')
  DO NOTHING;
  SELECT * INTO STRICT demoted_event
  FROM volpred_ops.primary_authority_events
  WHERE authority_key = btrim(p_authority_key)
    AND epoch = p_epoch
    AND event_type = 'demoted';
  RETURN jsonb_build_object(
    'schema_version', 'primary-authority-demotion-reconcile.v1',
    'status', 'reconciled',
    'authority_key', demoted_event.authority_key,
    'holder_ref', demoted_event.holder_ref,
    'epoch', demoted_event.epoch,
    'event_ref',
      'primary-authority-event:' || demoted_event.sequence::text,
    'occurred_at', demoted_event.occurred_at
  );
END;
$$;

ALTER FUNCTION volpred_ops.reconcile_primary_authority_demotion(
  text, text, bigint
) OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION volpred_ops.reconcile_primary_authority_demotion(
  text, text, bigint
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION volpred_ops.reconcile_primary_authority_demotion(
  text, text, bigint
) TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION volpred_ops.enforce_formal_primary_grant()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
  IF NEW.authority_key <> 'operations-core-primary' THEN
    RAISE EXCEPTION
      'Primary Authority formal grant requires operations-core-primary';
  END IF;
  RETURN NEW;
END;
$$;

ALTER FUNCTION volpred_ops.enforce_formal_primary_grant()
  OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION volpred_ops.enforce_formal_primary_grant()
  FROM PUBLIC, anon, authenticated, service_role;

DROP TRIGGER IF EXISTS enforce_formal_primary_grant
  ON volpred_ops.primary_authority_grants;
CREATE TRIGGER enforce_formal_primary_grant
BEFORE INSERT ON volpred_ops.primary_authority_grants
FOR EACH ROW
EXECUTE FUNCTION volpred_ops.enforce_formal_primary_grant();

CREATE OR REPLACE FUNCTION volpred_ops.primary_authority_reason_code(
  p_reason text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
  SELECT CASE
    WHEN p_reason LIKE 'Primary Authority is already held:%'
      THEN 'already_held'
    WHEN p_reason LIKE 'Primary Authority lease lost:%'
      THEN 'lease_lost'
    WHEN p_reason LIKE 'Primary Authority epoch mismatch:%'
      THEN 'stale_epoch'
    WHEN p_reason LIKE 'Primary Authority lease expired:%'
      THEN 'lease_expired'
    WHEN p_reason = 'Primary Authority fields are required'
      THEN 'invalid_fields'
    WHEN p_reason = 'Primary Authority lease_seconds must be positive'
      THEN 'invalid_lease_window'
    WHEN p_reason =
      'Primary Authority request hash must be lowercase SHA-256'
      THEN 'invalid_request_hash'
    WHEN p_reason =
      'Primary Authority grant conflicts with its original intent'
      THEN 'grant_conflict'
    WHEN p_reason =
      'Primary Authority formal grant requires operations-core-primary'
      THEN 'formal_primary_required'
    ELSE 'authority_rejected'
  END
$$;

ALTER FUNCTION volpred_ops.primary_authority_reason_code(text)
  OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION volpred_ops.primary_authority_reason_code(text)
  FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION volpred_ops.primary_authority_reason_code(text)
  TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION volpred_ops.record_primary_authority_rejection(
  p_operation text,
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_reason text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, volpred_ops
AS $$
DECLARE
  stored volpred_ops.primary_authority_event_reads;
  normalized_key text;
  event_at timestamptz;
BEGIN
  IF p_operation NOT IN ('acquire', 'renew', 'authorize', 'release') THEN
    RAISE EXCEPTION 'unsupported Primary Authority operation';
  END IF;
  IF p_reason IS NULL OR p_reason NOT LIKE 'Primary Authority%' THEN
    RAISE EXCEPTION 'unsupported Primary Authority rejection';
  END IF;
  normalized_key := COALESCE(NULLIF(btrim(p_authority_key), ''), '<invalid>');
  event_at := clock_timestamp();
  INSERT INTO volpred_ops.primary_authority_events (
    authority_key, event_type, operation, epoch, holder_ref,
    reason_code, reason, occurred_at
  )
  VALUES (
    normalized_key,
    'rejected',
    p_operation,
    CASE WHEN p_epoch > 0 THEN p_epoch ELSE NULL END,
    NULLIF(btrim(p_holder_ref), ''),
    volpred_ops.primary_authority_reason_code(p_reason),
    p_reason,
    event_at
  )
  RETURNING
    'primary-authority-event:' || sequence::text,
    authority_key,
    event_type,
    operation,
    epoch,
    holder_ref,
    reason_code,
    reason,
    lease_expires_at,
    occurred_at
  INTO stored;
  RETURN jsonb_build_object(
    'schema_version', 'primary-authority-rejection.v1',
    'status', 'rejected',
    'operation', stored.operation,
    'authority_key', stored.authority_key,
    'event_ref', stored.event_ref,
    'reason_code', stored.reason_code,
    'reason', stored.reason,
    'occurred_at', stored.occurred_at
  );
END;
$$;

ALTER FUNCTION volpred_ops.record_primary_authority_rejection(
  text, text, text, bigint, text
) OWNER TO volpred_ops_definer;
REVOKE ALL ON FUNCTION volpred_ops.record_primary_authority_rejection(
  text, text, text, bigint, text
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION volpred_ops.record_primary_authority_rejection(
  text, text, text, bigint, text
) TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION volpred_ops.try_acquire_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  BEGIN
    SELECT to_jsonb(lease_row)
    INTO STRICT payload
    FROM volpred_ops.acquire_primary_authority(
      p_authority_key, p_holder_ref, p_lease_seconds, p_fencing_token
    ) AS lease_row;
    RETURN payload;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE 'Primary Authority%' THEN
      RAISE;
    END IF;
    RETURN volpred_ops.record_primary_authority_rejection(
      'acquire', p_authority_key, p_holder_ref, NULL, SQLERRM
    );
  END;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.try_renew_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
  expired_at timestamptz;
BEGIN
  BEGIN
    SELECT to_jsonb(lease_row)
    INTO STRICT payload
    FROM volpred_ops.renew_primary_authority(
      p_authority_key, p_holder_ref, p_epoch, p_lease_seconds,
      p_fencing_token
    ) AS lease_row;
    RETURN payload;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE 'Primary Authority%' THEN
      RAISE;
    END IF;
    IF SQLERRM LIKE 'Primary Authority lease expired:%' THEN
      SELECT lease_expires_at INTO expired_at
      FROM volpred_ops.primary_authority_leases
      WHERE authority_key = btrim(p_authority_key);
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        btrim(p_authority_key), 'expired', 'renew', p_epoch,
        NULLIF(btrim(p_holder_ref), ''), expired_at, clock_timestamp()
      )
      ON CONFLICT (authority_key, epoch, event_type)
        WHERE event_type IN ('expired', 'demoted')
      DO NOTHING;
    END IF;
    RETURN volpred_ops.record_primary_authority_rejection(
      'renew', p_authority_key, p_holder_ref, p_epoch, SQLERRM
    );
  END;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.try_authorize_primary_write(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text,
  p_request_sha256 text,
  p_resource_ref text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
  expired_at timestamptz;
BEGIN
  BEGIN
    SELECT to_jsonb(grant_row)
    INTO STRICT payload
    FROM volpred_ops.authorize_primary_write(
      p_authority_key, p_holder_ref, p_epoch, p_fencing_token,
      p_request_sha256, p_resource_ref
    ) AS grant_row;
    RETURN payload;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE 'Primary Authority%' THEN
      RAISE;
    END IF;
    IF SQLERRM LIKE 'Primary Authority lease expired:%' THEN
      SELECT lease_expires_at INTO expired_at
      FROM volpred_ops.primary_authority_leases
      WHERE authority_key = btrim(p_authority_key);
      INSERT INTO volpred_ops.primary_authority_events (
        authority_key, event_type, operation, epoch, holder_ref,
        lease_expires_at, occurred_at
      )
      VALUES (
        btrim(p_authority_key), 'expired', 'authorize', p_epoch,
        NULLIF(btrim(p_holder_ref), ''), expired_at, clock_timestamp()
      )
      ON CONFLICT (authority_key, epoch, event_type)
        WHERE event_type IN ('expired', 'demoted')
      DO NOTHING;
    END IF;
    RETURN volpred_ops.record_primary_authority_rejection(
      'authorize', p_authority_key, p_holder_ref, p_epoch, SQLERRM
    );
  END;
END;
$$;

CREATE OR REPLACE FUNCTION volpred_ops.try_release_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  BEGIN
    SELECT to_jsonb(receipt_row)
    INTO STRICT payload
    FROM volpred_ops.release_primary_authority(
      p_authority_key, p_holder_ref, p_epoch, p_fencing_token
    ) AS receipt_row;
    RETURN payload;
  EXCEPTION WHEN OTHERS THEN
    IF SQLERRM NOT LIKE 'Primary Authority%' THEN
      RAISE;
    END IF;
    RETURN volpred_ops.record_primary_authority_rejection(
      'release', p_authority_key, p_holder_ref, p_epoch, SQLERRM
    );
  END;
END;
$$;

ALTER FUNCTION volpred_ops.try_acquire_primary_authority(
  text, text, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.try_renew_primary_authority(
  text, text, bigint, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.try_authorize_primary_write(
  text, text, bigint, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION volpred_ops.try_release_primary_authority(
  text, text, bigint, text
) OWNER TO volpred_ops_definer;

REVOKE ALL ON FUNCTION volpred_ops.try_acquire_primary_authority(
  text, text, integer, text
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION volpred_ops.try_renew_primary_authority(
  text, text, bigint, integer, text
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION volpred_ops.try_authorize_primary_write(
  text, text, bigint, text, text, text
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION volpred_ops.try_release_primary_authority(
  text, text, bigint, text
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION volpred_ops.try_acquire_primary_authority(
  text, text, integer, text
) TO volpred_ops_definer;
GRANT EXECUTE ON FUNCTION volpred_ops.try_renew_primary_authority(
  text, text, bigint, integer, text
) TO volpred_ops_definer;
GRANT EXECUTE ON FUNCTION volpred_ops.try_authorize_primary_write(
  text, text, bigint, text, text, text
) TO volpred_ops_definer;
GRANT EXECUTE ON FUNCTION volpred_ops.try_release_primary_authority(
  text, text, bigint, text
) TO volpred_ops_definer;

CREATE OR REPLACE FUNCTION public.volpred_acquire_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT volpred_ops.try_acquire_primary_authority(
    p_authority_key, p_holder_ref, p_lease_seconds, p_fencing_token
  )
$$;

CREATE OR REPLACE FUNCTION public.volpred_renew_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_lease_seconds integer,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT volpred_ops.try_renew_primary_authority(
    p_authority_key, p_holder_ref, p_epoch, p_lease_seconds, p_fencing_token
  )
$$;

CREATE OR REPLACE FUNCTION public.volpred_authorize_primary_write(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text,
  p_request_sha256 text,
  p_resource_ref text
)
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT volpred_ops.try_authorize_primary_write(
    p_authority_key, p_holder_ref, p_epoch, p_fencing_token,
    p_request_sha256, p_resource_ref
  )
$$;

CREATE OR REPLACE FUNCTION public.volpred_release_primary_authority(
  p_authority_key text,
  p_holder_ref text,
  p_epoch bigint,
  p_fencing_token text
)
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT volpred_ops.try_release_primary_authority(
    p_authority_key, p_holder_ref, p_epoch, p_fencing_token
  )
$$;

CREATE OR REPLACE FUNCTION
  public.volpred_reconcile_primary_authority_demotion(
    p_authority_key text,
    p_holder_ref text,
    p_epoch bigint
  )
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT volpred_ops.reconcile_primary_authority_demotion(
    p_authority_key, p_holder_ref, p_epoch
  )
$$;

CREATE OR REPLACE FUNCTION public.volpred_read_primary_authority_events(
  p_authority_key text,
  p_limit integer DEFAULT 100
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  payload jsonb;
BEGIN
  IF p_authority_key IS NULL OR btrim(p_authority_key) = '' THEN
    RAISE EXCEPTION 'Primary Authority key is required';
  END IF;
  IF p_limit IS NULL OR p_limit <= 0 OR p_limit > 500 THEN
    RAISE EXCEPTION 'Primary Authority event limit must be between 1 and 500';
  END IF;
  PERFORM volpred_ops.materialize_primary_authority_expiry(
    btrim(p_authority_key)
  );
  SELECT COALESCE(
    jsonb_agg(
      jsonb_build_object(
        'schema_version', 'primary-authority-event.v1',
        'event_ref', event_ref,
        'authority_key', authority_key,
        'event_type', event_type,
        'operation', operation,
        'epoch', epoch,
        'holder_ref', holder_ref,
        'reason_code', reason_code,
        'reason', reason,
        'lease_expires_at', lease_expires_at,
        'occurred_at', occurred_at
      )
      ORDER BY sequence
    ),
    '[]'::jsonb
  )
  INTO payload
  FROM (
    SELECT
      event_ref, authority_key, event_type, operation, epoch, holder_ref,
      reason_code, reason, lease_expires_at, occurred_at, sequence
    FROM (
      SELECT
        'primary-authority-event:' || event.sequence::text AS event_ref,
        event.authority_key,
        event.event_type,
        event.operation,
        event.epoch,
        event.holder_ref,
        event.reason_code,
        event.reason,
        event.lease_expires_at,
        event.occurred_at,
        event.sequence
      FROM volpred_ops.primary_authority_events AS event
      WHERE event.authority_key = btrim(p_authority_key)
      ORDER BY event.sequence DESC
      LIMIT p_limit
    ) AS recent
    ORDER BY sequence
  ) AS ordered_events;
  RETURN payload;
END;
$$;

GRANT CREATE ON SCHEMA public TO volpred_ops_definer;
ALTER FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_reconcile_primary_authority_demotion(
  text, text, bigint
) OWNER TO volpred_ops_definer;
ALTER FUNCTION public.volpred_read_primary_authority_events(
  text, integer
) OWNER TO volpred_ops_definer;
REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer;

REVOKE ALL ON FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_reconcile_primary_authority_demotion(
  text, text, bigint
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.volpred_read_primary_authority_events(
  text, integer
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.volpred_acquire_primary_authority(
  text, text, integer, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_renew_primary_authority(
  text, text, bigint, integer, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_authorize_primary_write(
  text, text, bigint, text, text, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_release_primary_authority(
  text, text, bigint, text
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_reconcile_primary_authority_demotion(
  text, text, bigint
) TO service_role;
GRANT EXECUTE ON FUNCTION public.volpred_read_primary_authority_events(
  text, integer
) TO service_role;

REVOKE CREATE ON SCHEMA volpred_ops FROM volpred_ops_definer;

DO $$
BEGIN
  EXECUTE format('REVOKE volpred_ops_definer FROM %I', current_user);
END;
$$;
