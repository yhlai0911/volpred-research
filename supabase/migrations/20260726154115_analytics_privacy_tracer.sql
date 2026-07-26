-- First-party product analytics privacy boundary.
--
-- This schema is deliberately private. Browser/Data API roles receive no
-- schema access, and RLS is enabled without public policies as defense in
-- depth. Only a trusted backend connection may use the adapter.

CREATE SCHEMA IF NOT EXISTS volpred_analytics;
REVOKE ALL ON SCHEMA volpred_analytics FROM PUBLIC;

CREATE TABLE volpred_analytics.event_definitions (
  kind text PRIMARY KEY,
  purpose text NOT NULL,
  required_fields text[] NOT NULL,
  optional_fields text[] NOT NULL,
  raw_retention_days integer NOT NULL
    CHECK (raw_retention_days > 0),
  identity_contract text NOT NULL
    CHECK (identity_contract = 'anonymous_or_authenticated'),
  dedupe_contract text NOT NULL
    CHECK (dedupe_contract = 'idempotency_key')
);

CREATE TABLE volpred_analytics.events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  idempotency_key text NOT NULL UNIQUE,
  kind text NOT NULL
    REFERENCES volpred_analytics.event_definitions(kind) ON DELETE RESTRICT,
  occurred_at timestamptz NOT NULL,
  anonymous_id text,
  user_id text,
  properties jsonb NOT NULL,
  raw_expires_at timestamptz NOT NULL,
  CHECK (anonymous_id IS NOT NULL OR user_id IS NOT NULL),
  CHECK (jsonb_typeof(properties) = 'object')
);

CREATE INDEX analytics_events_anonymous_idx
  ON volpred_analytics.events (anonymous_id)
  WHERE anonymous_id IS NOT NULL;
CREATE INDEX analytics_events_user_idx
  ON volpred_analytics.events (user_id)
  WHERE user_id IS NOT NULL;
CREATE INDEX analytics_events_summary_idx
  ON volpred_analytics.events (occurred_at, kind);
CREATE INDEX analytics_events_expiry_idx
  ON volpred_analytics.events (raw_expires_at);

CREATE TABLE volpred_analytics.identity_links (
  anonymous_id text PRIMARY KEY,
  user_id text NOT NULL,
  merged_at timestamptz NOT NULL
);

CREATE INDEX analytics_identity_links_user_idx
  ON volpred_analytics.identity_links (user_id);

CREATE TABLE volpred_analytics.identity_merge_receipts (
  idempotency_key text PRIMARY KEY,
  anonymous_id text NOT NULL,
  user_id text NOT NULL,
  merged_at timestamptz NOT NULL,
  merged_events integer NOT NULL CHECK (merged_events >= 0)
);

CREATE TABLE volpred_analytics.privacy_preferences (
  subject_kind text NOT NULL
    CHECK (subject_kind IN ('anonymous', 'user')),
  subject_id text NOT NULL,
  opted_out boolean NOT NULL CHECK (opted_out),
  idempotency_key text NOT NULL UNIQUE,
  acted_at timestamptz NOT NULL,
  PRIMARY KEY (subject_kind, subject_id)
);

CREATE TABLE volpred_analytics.privacy_action_receipts (
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

CREATE TABLE volpred_analytics.privacy_tombstones (
  subject_digest bytea PRIMARY KEY,
  deleted_at timestamptz NOT NULL,
  CHECK (octet_length(subject_digest) = 32)
);

CREATE TABLE volpred_analytics.event_dedupe_tombstones (
  idempotency_digest bytea PRIMARY KEY,
  expired_at timestamptz NOT NULL,
  CHECK (octet_length(idempotency_digest) = 32)
);

INSERT INTO volpred_analytics.event_definitions (
  kind,
  purpose,
  required_fields,
  optional_fields,
  raw_retention_days,
  identity_contract,
  dedupe_contract
) VALUES
  (
    'content_impression',
    'measure first-party content reach',
    ARRAY['content_id', 'surface'],
    ARRAY['referrer_class'],
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'content_click',
    'measure first-party content engagement',
    ARRAY['content_id', 'surface'],
    ARRAY['target_class'],
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'read_depth',
    'measure aggregate content reading depth',
    ARRAY['content_id', 'depth_bucket'],
    ARRAY['surface'],
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'qualified_action',
    'measure aggregate completion of a declared product action',
    ARRAY['content_id', 'action'],
    ARRAY['surface'],
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  ),
  (
    'return_visit',
    'measure aggregate first-party audience retention',
    ARRAY['surface', 'return_window'],
    ARRAY[]::text[],
    30,
    'anonymous_or_authenticated',
    'idempotency_key'
  );

ALTER TABLE volpred_analytics.event_definitions
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.identity_merge_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_preferences
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_action_receipts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.privacy_tombstones
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_analytics.event_dedupe_tombstones
  ENABLE ROW LEVEL SECURITY;

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
