-- First-party product analytics privacy boundary.
--
-- This schema is deliberately private. Browser/Data API roles receive no
-- schema access, and RLS is enabled without public policies as defense in
-- depth. Only a trusted backend connection may use the adapter.

CREATE SCHEMA IF NOT EXISTS volpred_analytics;
REVOKE ALL ON SCHEMA volpred_analytics FROM PUBLIC;

DO $create_worker$
BEGIN
  CREATE ROLE volpred_analytics_worker
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$create_worker$;

DO $validate_worker$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'volpred_analytics_worker'
      AND NOT rolcanlogin
      AND NOT rolsuper
      AND NOT rolcreatedb
      AND NOT rolcreaterole
      AND NOT rolreplication
      AND NOT rolbypassrls
      AND NOT rolinherit
  ) THEN
    RAISE EXCEPTION
      'existing volpred_analytics_worker role has unsafe attributes';
  END IF;
END;
$validate_worker$;

CREATE TABLE IF NOT EXISTS volpred_analytics.event_definitions (
  kind text PRIMARY KEY,
  purpose text NOT NULL,
  required_fields text[] NOT NULL,
  optional_fields text[] NOT NULL,
  field_contracts jsonb NOT NULL,
  raw_retention_days integer NOT NULL
    CHECK (raw_retention_days > 0),
  identity_contract text NOT NULL
    CHECK (identity_contract = 'anonymous_or_authenticated'),
  dedupe_contract text NOT NULL
    CHECK (dedupe_contract = 'idempotency_key')
);

CREATE TABLE IF NOT EXISTS volpred_analytics.events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  kind text NOT NULL
    REFERENCES volpred_analytics.event_definitions(kind) ON DELETE RESTRICT,
  occurred_at timestamptz NOT NULL,
  anonymous_id text,
  submitted_user_id text,
  user_id text,
  properties jsonb NOT NULL,
  payload_digest bytea NOT NULL,
  raw_expires_at timestamptz NOT NULL,
  ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (anonymous_id IS NOT NULL OR user_id IS NOT NULL),
  CHECK (jsonb_typeof(properties) = 'object'),
  CHECK (octet_length(payload_digest) = 32),
  CHECK (raw_expires_at = occurred_at + interval '30 days')
);

CREATE INDEX IF NOT EXISTS analytics_events_anonymous_idx
  ON volpred_analytics.events (anonymous_id)
  WHERE anonymous_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_events_user_idx
  ON volpred_analytics.events (user_id)
  WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_events_summary_idx
  ON volpred_analytics.events (occurred_at, kind);
CREATE INDEX IF NOT EXISTS analytics_events_expiry_idx
  ON volpred_analytics.events (raw_expires_at);

CREATE TABLE IF NOT EXISTS volpred_analytics.identity_links (
  anonymous_id text PRIMARY KEY,
  user_id text NOT NULL,
  merged_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS analytics_identity_links_user_idx
  ON volpred_analytics.identity_links (user_id);

CREATE TABLE IF NOT EXISTS volpred_analytics.identity_merge_receipts (
  idempotency_key text PRIMARY KEY,
  anonymous_id text NOT NULL,
  user_id text NOT NULL,
  merged_at timestamptz NOT NULL,
  merged_events integer NOT NULL CHECK (merged_events >= 0)
);

CREATE TABLE IF NOT EXISTS volpred_analytics.privacy_preferences (
  subject_kind text NOT NULL
    CHECK (subject_kind IN ('anonymous', 'user')),
  subject_id text NOT NULL,
  opted_out boolean NOT NULL CHECK (opted_out),
  idempotency_key text NOT NULL UNIQUE,
  acted_at timestamptz NOT NULL,
  PRIMARY KEY (subject_kind, subject_id)
);

CREATE TABLE IF NOT EXISTS volpred_analytics.privacy_action_receipts (
  idempotency_key text PRIMARY KEY,
  action text NOT NULL CHECK (action IN ('opt_out', 'clear', 'delete')),
  subject_digest bytea NOT NULL,
  acted_at timestamptz NOT NULL,
  removed_raw_events integer NOT NULL
    CHECK (removed_raw_events >= 0),
  removed_identity_links integer NOT NULL
    CHECK (removed_identity_links >= 0),
  CHECK (octet_length(subject_digest) = 32)
);

CREATE TABLE IF NOT EXISTS volpred_analytics.privacy_tombstones (
  subject_digest bytea PRIMARY KEY,
  deleted_at timestamptz NOT NULL,
  CHECK (octet_length(subject_digest) = 32)
);

CREATE TABLE IF NOT EXISTS volpred_analytics.event_dedupe_tombstones (
  idempotency_digest bytea PRIMARY KEY,
  event_payload_digest bytea NOT NULL,
  suppression_reason text NOT NULL
    CHECK (suppression_reason IN ('expired', 'cleared')),
  suppressed_at timestamptz NOT NULL,
  CHECK (octet_length(idempotency_digest) = 32),
  CHECK (octet_length(event_payload_digest) = 32)
);

CREATE TABLE IF NOT EXISTS volpred_analytics.digest_key_identity (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  key_id text NOT NULL CHECK (length(key_id) > 0),
  verifier bytea NOT NULL CHECK (octet_length(verifier) = 32),
  established_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO volpred_analytics.event_definitions (
  kind,
  purpose,
  required_fields,
  optional_fields,
  field_contracts,
  raw_retention_days,
  identity_contract,
  dedupe_contract
) VALUES
  (
    'content_impression',
    'measure first-party content reach',
    ARRAY['content_id', 'surface'],
    ARRAY['referrer_class'],
    jsonb_build_object(
      'content_id', 'opaque_identifier',
      'surface', 'enum:home|article|search|feed|email',
      'referrer_class', 'enum:direct|internal|search|social|email|other'
    ),
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'content_click',
    'measure first-party content engagement',
    ARRAY['content_id', 'surface'],
    ARRAY['target_class'],
    jsonb_build_object(
      'content_id', 'opaque_identifier',
      'surface', 'enum:home|article|search|feed|email',
      'target_class', 'enum:article|navigation|cta|external'
    ),
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'read_depth',
    'measure aggregate content reading depth',
    ARRAY['content_id', 'depth_bucket'],
    ARRAY['surface'],
    jsonb_build_object(
      'content_id', 'opaque_identifier',
      'depth_bucket', 'enum:25|50|75|100',
      'surface', 'enum:home|article|search|feed|email'
    ),
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'qualified_action',
    'measure aggregate completion of a declared product action',
    ARRAY['content_id', 'action'],
    ARRAY['surface'],
    jsonb_build_object(
      'content_id', 'opaque_identifier',
      'action', 'enum:subscribe|share|save|open_paper|open_experiment',
      'surface', 'enum:home|article|search|feed|email'
    ),
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'return_visit',
    'measure aggregate first-party audience retention',
    ARRAY['surface', 'return_window'],
    ARRAY[]::text[],
    jsonb_build_object(
      'surface', 'enum:home|article|search|feed|email',
      'return_window', 'enum:day_1|day_7|day_30'
    ),
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  )
ON CONFLICT (kind) DO UPDATE SET
  purpose = EXCLUDED.purpose,
  required_fields = EXCLUDED.required_fields,
  optional_fields = EXCLUDED.optional_fields,
  field_contracts = EXCLUDED.field_contracts,
  raw_retention_days = EXCLUDED.raw_retention_days,
  identity_contract = EXCLUDED.identity_contract,
  dedupe_contract = EXCLUDED.dedupe_contract;

CREATE OR REPLACE FUNCTION volpred_analytics.enforce_event_retention()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, volpred_analytics
AS $retention$
DECLARE
  definition volpred_analytics.event_definitions%ROWTYPE;
  field_name text;
  field_value jsonb;
  field_contract text;
  scalar_value text;
BEGIN
  IF NEW.occurred_at > clock_timestamp() + interval '5 minutes' THEN
    RAISE EXCEPTION 'analytics occurred_at is too far in the future';
  END IF;
  IF NEW.raw_expires_at <> NEW.occurred_at + interval '30 days' THEN
    RAISE EXCEPTION 'analytics raw retention must be exactly 30 days';
  END IF;
  SELECT *
  INTO STRICT definition
  FROM volpred_analytics.event_definitions
  WHERE kind = NEW.kind;
  IF EXISTS (
    SELECT 1
    FROM unnest(definition.required_fields) AS required(field_name)
    WHERE NOT NEW.properties ? required.field_name
  ) THEN
    RAISE EXCEPTION 'analytics event is missing required properties';
  END IF;
  FOR field_name, field_value IN
    SELECT key, value FROM jsonb_each(NEW.properties)
  LOOP
    field_contract := definition.field_contracts ->> field_name;
    IF field_contract IS NULL THEN
      RAISE EXCEPTION 'analytics event contains undeclared property';
    END IF;
    IF jsonb_typeof(field_value) <> 'string' THEN
      RAISE EXCEPTION 'analytics event properties must be strings';
    END IF;
    scalar_value := field_value #>> '{}';
    IF field_contract = 'opaque_identifier'
       AND scalar_value !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
      RAISE EXCEPTION 'analytics opaque identifier is invalid';
    END IF;
    IF field_contract LIKE 'enum:%'
       AND NOT (
         scalar_value = ANY(
           string_to_array(substring(field_contract FROM 6), '|')
         )
       ) THEN
      RAISE EXCEPTION 'analytics enum value is invalid';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$retention$;

DROP TRIGGER IF EXISTS enforce_event_retention
  ON volpred_analytics.events;
CREATE TRIGGER enforce_event_retention
BEFORE INSERT OR UPDATE
ON volpred_analytics.events
FOR EACH ROW
EXECUTE FUNCTION volpred_analytics.enforce_event_retention();

ALTER TABLE volpred_analytics.event_definitions
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.event_definitions
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.events FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_links FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_merge_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_merge_receipts
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_preferences
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_preferences
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_action_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_action_receipts
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_tombstones
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_tombstones
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.event_dedupe_tombstones
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.event_dedupe_tombstones
  FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.digest_key_identity
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.digest_key_identity
  FORCE ROW LEVEL SECURITY;

GRANT USAGE ON SCHEMA volpred_analytics TO volpred_analytics_worker;
REVOKE ALL ON ALL TABLES IN SCHEMA volpred_analytics
  FROM volpred_analytics_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_analytics
  FROM volpred_analytics_worker;
GRANT SELECT ON volpred_analytics.event_definitions
  TO volpred_analytics_worker;
GRANT SELECT, INSERT, DELETE ON volpred_analytics.events
  TO volpred_analytics_worker;
GRANT UPDATE (user_id) ON volpred_analytics.events
  TO volpred_analytics_worker;
GRANT SELECT, INSERT, DELETE
  ON volpred_analytics.identity_links,
     volpred_analytics.identity_merge_receipts,
     volpred_analytics.privacy_action_receipts
  TO volpred_analytics_worker;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON volpred_analytics.privacy_preferences
  TO volpred_analytics_worker;
GRANT SELECT, INSERT, UPDATE
  ON volpred_analytics.privacy_tombstones,
     volpred_analytics.event_dedupe_tombstones
  TO volpred_analytics_worker;
GRANT SELECT, INSERT ON volpred_analytics.digest_key_identity
  TO volpred_analytics_worker;
GRANT USAGE, SELECT
  ON ALL SEQUENCES IN SCHEMA volpred_analytics
  TO volpred_analytics_worker;
REVOKE ALL ON FUNCTION volpred_analytics.enforce_event_retention()
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION volpred_analytics.enforce_event_retention()
  TO volpred_analytics_worker;

DO $worker_policies$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'event_definitions',
    'events',
    'identity_links',
    'identity_merge_receipts',
    'privacy_preferences',
    'privacy_action_receipts',
    'privacy_tombstones',
    'event_dedupe_tombstones',
    'digest_key_identity'
  ]
  LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS analytics_worker_access ON volpred_analytics.%I',
      table_name
    );
    EXECUTE format(
      'DROP POLICY IF EXISTS analytics_worker_select ON volpred_analytics.%I',
      table_name
    );
    EXECUTE format(
      'DROP POLICY IF EXISTS analytics_worker_insert ON volpred_analytics.%I',
      table_name
    );
    EXECUTE format(
      'DROP POLICY IF EXISTS analytics_worker_update ON volpred_analytics.%I',
      table_name
    );
    EXECUTE format(
      'DROP POLICY IF EXISTS analytics_worker_delete ON volpred_analytics.%I',
      table_name
    );
    EXECUTE format(
      'CREATE POLICY analytics_worker_select ON volpred_analytics.%I '
      'FOR SELECT TO volpred_analytics_worker USING (true)',
      table_name
    );
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY[
    'events',
    'identity_links',
    'identity_merge_receipts',
    'privacy_preferences',
    'privacy_action_receipts',
    'privacy_tombstones',
    'event_dedupe_tombstones',
    'digest_key_identity'
  ]
  LOOP
    EXECUTE format(
      'CREATE POLICY analytics_worker_insert ON volpred_analytics.%I '
      'FOR INSERT TO volpred_analytics_worker WITH CHECK (true)',
      table_name
    );
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY[
    'events',
    'privacy_preferences',
    'privacy_tombstones',
    'event_dedupe_tombstones'
  ]
  LOOP
    EXECUTE format(
      'CREATE POLICY analytics_worker_update ON volpred_analytics.%I '
      'FOR UPDATE TO volpred_analytics_worker USING (true) WITH CHECK (true)',
      table_name
    );
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY[
    'events',
    'identity_links',
    'identity_merge_receipts',
    'privacy_preferences',
    'privacy_action_receipts'
  ]
  LOOP
    EXECUTE format(
      'CREATE POLICY analytics_worker_delete ON volpred_analytics.%I '
      'FOR DELETE TO volpred_analytics_worker USING (true)',
      table_name
    );
  END LOOP;
END;
$worker_policies$;

REVOKE ALL ON ALL TABLES IN SCHEMA volpred_analytics FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_analytics FROM PUBLIC;

DO $revoke_data_api_roles$
DECLARE
  role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
  LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
      EXECUTE format(
        'REVOKE ALL ON SCHEMA volpred_analytics FROM %I',
        role_name
      );
      EXECUTE format(
        'REVOKE ALL ON ALL TABLES IN SCHEMA volpred_analytics FROM %I',
        role_name
      );
      EXECUTE format(
        'REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_analytics FROM %I',
        role_name
      );
    END IF;
  END LOOP;
END;
$revoke_data_api_roles$;
