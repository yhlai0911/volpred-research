-- Receipt-backed natural-growth experiment registry.
--
-- The registry is private and service-role-only.  It stores immutable
-- preregistration, lifecycle receipts, and the frozen closeout result.
-- Assignment is deterministic from an HMAC digest and is never persisted, so
-- the experiment layer does not create a second identity-retention surface.

UPDATE volpred_analytics.event_definitions
SET
  optional_fields = ARRAY[
    'referrer_class',
    'experiment_id',
    'variant_id'
  ],
  field_contracts = field_contracts || pg_catalog.jsonb_build_object(
    'experiment_id', 'opaque_identifier',
    'variant_id', 'opaque_identifier'
  )
WHERE kind = 'content_impression';

UPDATE volpred_analytics.event_definitions
SET
  optional_fields = ARRAY[
    'surface',
    'experiment_id',
    'variant_id'
  ],
  field_contracts = field_contracts || pg_catalog.jsonb_build_object(
    'experiment_id', 'opaque_identifier',
    'variant_id', 'opaque_identifier'
  )
WHERE kind IN ('read_depth', 'qualified_action');

CREATE OR REPLACE FUNCTION volpred_analytics.enforce_event_retention()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $retention$
DECLARE
  definition volpred_analytics.event_definitions%ROWTYPE;
  field_name text;
  field_value jsonb;
  field_contract text;
  scalar_value text;
  has_experiment_id boolean;
  has_variant_id boolean;
BEGIN
  IF NEW.occurred_at > pg_catalog.clock_timestamp() + interval '5 minutes' THEN
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
    FROM pg_catalog.unnest(definition.required_fields)
      AS required(field_name)
    WHERE NOT NEW.properties ? required.field_name
  ) THEN
    RAISE EXCEPTION 'analytics event is missing required properties';
  END IF;
  FOR field_name, field_value IN
    SELECT key, value FROM pg_catalog.jsonb_each(NEW.properties)
  LOOP
    field_contract := definition.field_contracts ->> field_name;
    IF field_contract IS NULL THEN
      RAISE EXCEPTION 'analytics event contains undeclared property';
    END IF;
    IF pg_catalog.jsonb_typeof(field_value) <> 'string' THEN
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
           pg_catalog.string_to_array(
             pg_catalog.substr(field_contract, 6),
             '|'
           )
         )
       ) THEN
      RAISE EXCEPTION 'analytics enum value is invalid';
    END IF;
  END LOOP;

  has_experiment_id := NEW.properties ? 'experiment_id';
  has_variant_id := NEW.properties ? 'variant_id';
  IF has_experiment_id <> has_variant_id THEN
    RAISE EXCEPTION
      'analytics experiment_id and variant_id must be paired';
  END IF;
  IF has_experiment_id THEN
    IF NEW.properties ->> 'surface' <> 'article' THEN
      RAISE EXCEPTION 'analytics experiment surface must be article';
    END IF;
    IF NEW.kind = 'qualified_action'
       AND NEW.properties ->> 'action' <> 'share' THEN
      RAISE EXCEPTION
        'analytics experiment qualified action must be share';
    END IF;
  END IF;
  RETURN NEW;
END;
$retention$;

CREATE SCHEMA IF NOT EXISTS volpred_growth;
REVOKE ALL ON SCHEMA volpred_growth FROM PUBLIC;

DO $create_growth_worker$
BEGIN
  CREATE ROLE volpred_growth_worker
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END;
$create_growth_worker$;

DO $validate_growth_worker$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = 'volpred_growth_worker'
      AND NOT rolcanlogin
      AND NOT rolsuper
      AND NOT rolcreatedb
      AND NOT rolcreaterole
      AND NOT rolreplication
      AND NOT rolbypassrls
      AND NOT rolinherit
  ) THEN
    RAISE EXCEPTION
      'existing volpred_growth_worker role has unsafe attributes';
  END IF;
END;
$validate_growth_worker$;

DO $grant_worker_to_migration_role$
BEGIN
  IF CURRENT_USER = 'postgres' THEN
    EXECUTE pg_catalog.format(
      'GRANT volpred_growth_worker TO %I WITH INHERIT FALSE',
      CURRENT_USER
    );
    EXECUTE pg_catalog.format(
      'GRANT volpred_growth_worker TO %I WITH SET TRUE',
      CURRENT_USER
    );
  ELSE
    EXECUTE pg_catalog.format(
      'GRANT volpred_growth_worker TO %I',
      CURRENT_USER
    );
  END IF;
END;
$grant_worker_to_migration_role$;

GRANT CREATE ON SCHEMA public, volpred_growth
  TO volpred_growth_worker;

CREATE TABLE IF NOT EXISTS volpred_growth.experiments (
  experiment_id text PRIMARY KEY
    CHECK (
      experiment_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
  definition jsonb NOT NULL
    CHECK (pg_catalog.jsonb_typeof(definition) = 'object'),
  definition_digest bytea NOT NULL
    CHECK (pg_catalog.octet_length(definition_digest) = 32),
  status text NOT NULL
    CHECK (
      status IN ('preregistered', 'active', 'observing', 'closed')
    ),
  preregistered_at timestamptz NOT NULL,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  activated_at timestamptz,
  exposure_stopped_at timestamptz,
  observation_ends_at timestamptz,
  stop_reason text
    CHECK (
      stop_reason IS NULL
      OR stop_reason IN (
        'window_ended',
        'stop_rule_reached',
        'manual_safety_stop'
      )
    ),
  closed_at timestamptz,
  closure_reason text
    CHECK (
      closure_reason IS NULL
      OR closure_reason IN (
        'window_ended',
        'stop_rule_reached',
        'manual_safety_stop'
      )
    ),
  result jsonb,
  created_at timestamptz NOT NULL
    DEFAULT pg_catalog.clock_timestamp(),
  CHECK (preregistered_at < starts_at),
  CHECK (starts_at < ends_at),
  CHECK (
    (status = 'preregistered'
      AND activated_at IS NULL
      AND exposure_stopped_at IS NULL
      AND observation_ends_at IS NULL
      AND stop_reason IS NULL
      AND closed_at IS NULL
      AND result IS NULL)
    OR
    (status = 'active'
      AND activated_at IS NOT NULL
      AND exposure_stopped_at IS NULL
      AND observation_ends_at IS NULL
      AND stop_reason IS NULL
      AND closed_at IS NULL
      AND result IS NULL)
    OR
    (status = 'observing'
      AND activated_at IS NOT NULL
      AND exposure_stopped_at IS NOT NULL
      AND observation_ends_at IS NOT NULL
      AND stop_reason IS NOT NULL
      AND closed_at IS NULL
      AND result IS NULL)
    OR
    (status = 'closed'
      AND activated_at IS NOT NULL
      AND exposure_stopped_at IS NOT NULL
      AND observation_ends_at IS NOT NULL
      AND stop_reason IS NOT NULL
      AND closed_at IS NOT NULL
      AND closure_reason IS NOT NULL
      AND pg_catalog.jsonb_typeof(result) = 'object')
  )
);

CREATE TABLE IF NOT EXISTS volpred_growth.command_receipts (
  command_id text PRIMARY KEY
    CHECK (
      command_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'
    ),
  action text NOT NULL
    CHECK (action IN ('preregister', 'activate', 'stop', 'close')),
  experiment_id text NOT NULL
    REFERENCES volpred_growth.experiments(experiment_id)
    ON DELETE RESTRICT,
  request_digest bytea NOT NULL
    CHECK (pg_catalog.octet_length(request_digest) = 32),
  request_payload jsonb NOT NULL
    CHECK (pg_catalog.jsonb_typeof(request_payload) = 'object'),
  result jsonb NOT NULL
    CHECK (pg_catalog.jsonb_typeof(result) = 'object'),
  applied_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS volpred_growth.audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  experiment_id text NOT NULL
    REFERENCES volpred_growth.experiments(experiment_id)
    ON DELETE RESTRICT,
  command_id text NOT NULL
    REFERENCES volpred_growth.command_receipts(command_id)
    ON DELETE RESTRICT,
  action text NOT NULL
    CHECK (action IN ('preregister', 'activate', 'stop', 'close')),
  from_status text,
  to_status text NOT NULL
    CHECK (
      to_status IN ('preregistered', 'active', 'observing', 'closed')
    ),
  request_payload jsonb NOT NULL
    CHECK (pg_catalog.jsonb_typeof(request_payload) = 'object'),
  recorded_at timestamptz NOT NULL
);

ALTER TABLE volpred_growth.experiments
  ADD COLUMN IF NOT EXISTS closure_reason text;
ALTER TABLE volpred_growth.experiments
  ADD COLUMN IF NOT EXISTS exposure_stopped_at timestamptz,
  ADD COLUMN IF NOT EXISTS observation_ends_at timestamptz,
  ADD COLUMN IF NOT EXISTS stop_reason text;
ALTER TABLE volpred_growth.command_receipts
  ADD COLUMN IF NOT EXISTS request_payload jsonb;
ALTER TABLE volpred_growth.audit_log
  ADD COLUMN IF NOT EXISTS request_payload jsonb;

ALTER TABLE volpred_growth.experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_growth.experiments FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_growth.command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_growth.command_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE volpred_growth.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE volpred_growth.audit_log FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA volpred_growth FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_growth FROM PUBLIC;

GRANT USAGE ON SCHEMA volpred_growth, volpred_analytics
  TO volpred_growth_worker;
GRANT SELECT, INSERT, UPDATE
  ON volpred_growth.experiments
  TO volpred_growth_worker;
GRANT SELECT, INSERT
  ON volpred_growth.command_receipts,
     volpred_growth.audit_log
  TO volpred_growth_worker;
GRANT USAGE, SELECT
  ON ALL SEQUENCES IN SCHEMA volpred_growth
  TO volpred_growth_worker;
GRANT SELECT ON volpred_analytics.events
  TO volpred_growth_worker;
GRANT EXECUTE ON FUNCTION public.record_volpred_analytics_event(
  text, text, timestamptz, text, text, jsonb, bytea, bytea,
  text, bytea, bytea, bytea
) TO volpred_growth_worker;

DO $growth_worker_policies$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'experiments',
    'command_receipts',
    'audit_log'
  ]
  LOOP
    EXECUTE pg_catalog.format(
      'DROP POLICY IF EXISTS growth_worker_select ON volpred_growth.%I',
      table_name
    );
    EXECUTE pg_catalog.format(
      'CREATE POLICY growth_worker_select ON volpred_growth.%I '
      'FOR SELECT TO volpred_growth_worker USING (true)',
      table_name
    );
    EXECUTE pg_catalog.format(
      'DROP POLICY IF EXISTS growth_worker_insert ON volpred_growth.%I',
      table_name
    );
    EXECUTE pg_catalog.format(
      'CREATE POLICY growth_worker_insert ON volpred_growth.%I '
      'FOR INSERT TO volpred_growth_worker WITH CHECK (true)',
      table_name
    );
  END LOOP;
  EXECUTE
    'DROP POLICY IF EXISTS growth_worker_update '
    'ON volpred_growth.experiments';
  EXECUTE
    'CREATE POLICY growth_worker_update '
    'ON volpred_growth.experiments '
    'FOR UPDATE TO volpred_growth_worker '
    'USING (true) WITH CHECK (true)';

  EXECUTE
    'DROP POLICY IF EXISTS growth_worker_analytics_select '
    'ON volpred_analytics.events';
  EXECUTE
    'CREATE POLICY growth_worker_analytics_select '
    'ON volpred_analytics.events '
    'FOR SELECT TO volpred_growth_worker USING (true)';
END;
$growth_worker_policies$;

DO $revoke_data_api_roles$
DECLARE
  role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY[
    'anon',
    'authenticated',
    'service_role'
  ]
  LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_catalog.pg_roles
      WHERE rolname = role_name
    ) THEN
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON SCHEMA volpred_growth FROM %I',
        role_name
      );
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL TABLES IN SCHEMA volpred_growth FROM %I',
        role_name
      );
      EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL SEQUENCES IN SCHEMA volpred_growth FROM %I',
        role_name
      );
    END IF;
  END LOOP;
END;
$revoke_data_api_roles$;

SET LOCAL ROLE volpred_growth_worker;

CREATE OR REPLACE FUNCTION volpred_growth.validate_spec(p_spec jsonb)
RETURNS void
LANGUAGE plpgsql
SET search_path = ''
AS $validate_spec$
DECLARE
  starts_at timestamptz;
  ends_at timestamptz;
  preregistered_at timestamptz;
  attribution_window_hours integer;
  delivery_grace_minutes integer;
  maximum_exposure_hours integer;
  maximum_lifecycle_hours integer;
  minimum_exposures integer;
  maximum_exposures integer;
  variant jsonb;
  variant_ids text[] := ARRAY[]::text[];
  total_weight integer := 0;
BEGIN
  IF p_spec IS NULL
     OR pg_catalog.jsonb_typeof(p_spec) <> 'object' THEN
    RAISE EXCEPTION 'growth spec must be an object';
  END IF;
  IF p_spec ->> 'schema_version'
       IS DISTINCT FROM 'growth-experiment.v1'
     OR p_spec ->> 'status' IS DISTINCT FROM 'preregistered'
     OR p_spec ->> 'channel' IS DISTINCT FROM 'organic_first_party'
     OR p_spec ->> 'surface' IS DISTINCT FROM 'article_share_cta'
     OR p_spec ->> 'experiment_id' IS NULL
     OR p_spec ->> 'experiment_id'
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR pg_catalog.length(p_spec ->> 'hypothesis') NOT BETWEEN 1 AND 512
     OR p_spec ->> 'assignment_salt' IS NULL
     OR p_spec ->> 'assignment_salt'
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
    RAISE EXCEPTION 'growth preregistration identity is invalid';
  END IF;
  IF p_spec #>> '{primary_metric,name}'
        IS DISTINCT FROM 'qualified_action_rate'
     OR p_spec #>> '{primary_metric,action}' IS DISTINCT FROM 'share'
     OR p_spec #>> '{attribution,event_kind}'
        IS DISTINCT FROM 'qualified_action'
     OR p_spec #>> '{attribution,action}' IS DISTINCT FROM 'share'
     OR COALESCE(
          (p_spec #>> '{attribution,window_hours}')::integer
            NOT BETWEEN 1 AND 168,
          true
        )
     OR COALESCE(
          (p_spec #>> '{attribution,delivery_grace_minutes}')::integer
            NOT BETWEEN 0 AND 1440,
          true
        ) THEN
    RAISE EXCEPTION
      'growth metric must be a qualified conversion or return';
  END IF;
  IF p_spec #>> '{guardrail,name}'
       IS DISTINCT FROM 'read_depth_75_rate'
     OR COALESCE(
          (p_spec
            #>> '{guardrail,minimum_ratio_to_control}')::numeric
            NOT BETWEEN 0.000001 AND 1,
          true
        ) THEN
    RAISE EXCEPTION 'growth guardrail is invalid';
  END IF;
  IF p_spec #>> '{decision_rule,method}'
       IS DISTINCT FROM 'non_overlapping_wilson_95'
     OR (p_spec #>> '{decision_rule,confidence_level}')::numeric
       IS DISTINCT FROM 0.95
     OR COALESCE(
          (p_spec
            #>> '{decision_rule,minimum_absolute_uplift}')::numeric
            NOT BETWEEN 0 AND 1,
          true
        ) THEN
    RAISE EXCEPTION 'growth decision rule is invalid';
  END IF;
  IF p_spec #>> '{policy,paid_ads}' IS DISTINCT FROM 'false'
     OR p_spec #>> '{policy,dark_patterns}' IS DISTINCT FROM 'false'
     OR p_spec #>> '{policy,research_fact_changes}'
       IS DISTINCT FROM 'false'
     OR p_spec #>> '{policy,retain_null_result}'
       IS DISTINCT FROM 'true' THEN
    RAISE EXCEPTION 'forbidden growth policy';
  END IF;

  preregistered_at :=
    (p_spec ->> 'preregistered_at')::timestamptz;
  starts_at := (p_spec #>> '{window,starts_at}')::timestamptz;
  ends_at := (p_spec #>> '{window,ends_at}')::timestamptz;
  attribution_window_hours :=
    (p_spec #>> '{attribution,window_hours}')::integer;
  delivery_grace_minutes :=
    (p_spec #>> '{attribution,delivery_grace_minutes}')::integer;
  maximum_exposure_hours :=
    (p_spec #>> '{stop_rule,maximum_exposure_hours}')::integer;
  maximum_lifecycle_hours :=
    (p_spec #>> '{stop_rule,maximum_lifecycle_hours}')::integer;
  minimum_exposures :=
    (p_spec #>> '{stop_rule,minimum_exposures_per_variant}')::integer;
  maximum_exposures :=
    (p_spec #>> '{stop_rule,maximum_exposures_total}')::integer;
  IF preregistered_at IS NULL
     OR starts_at IS NULL
     OR ends_at IS NULL
     OR preregistered_at >= starts_at
     OR starts_at >= ends_at
     OR maximum_exposure_hours IS NULL
     OR maximum_exposure_hours NOT BETWEEN 1 AND 720
     OR maximum_lifecycle_hours IS NULL
     OR maximum_lifecycle_hours NOT BETWEEN 1 AND 720
     OR ends_at - starts_at
        > pg_catalog.make_interval(hours => maximum_exposure_hours)
     OR ends_at
          + pg_catalog.make_interval(hours => attribution_window_hours)
          + pg_catalog.make_interval(mins => delivery_grace_minutes)
          - starts_at
        > pg_catalog.make_interval(hours => maximum_lifecycle_hours)
     OR minimum_exposures NOT BETWEEN 1 AND 100000
     OR maximum_exposures < minimum_exposures * 2
     OR maximum_exposures > 1000000 THEN
    RAISE EXCEPTION 'growth window or stop rule is invalid';
  END IF;

  IF pg_catalog.jsonb_typeof(p_spec -> 'variants') <> 'array'
     OR pg_catalog.jsonb_array_length(p_spec -> 'variants') <> 2 THEN
    RAISE EXCEPTION 'growth experiment requires two variants';
  END IF;
  FOR variant IN
    SELECT value
    FROM pg_catalog.jsonb_array_elements(p_spec -> 'variants')
  LOOP
    IF variant ->> 'variant_id' IS NULL
       OR variant ->> 'variant_id'
          NOT IN ('control', 'treatment')
       OR (variant ->> 'weight_bps')::integer
          NOT BETWEEN 1 AND 9999
       OR variant ->> 'reversible' <> 'true'
       OR pg_catalog.jsonb_typeof(variant -> 'payload') <> 'object'
       OR (variant -> 'payload') - 'share_label'::text <> '{}'::jsonb
       OR variant #>> '{payload,share_label}'
          NOT IN ('分享', '分享這篇研究') THEN
      RAISE EXCEPTION 'growth variant is invalid or not reversible';
    END IF;
    IF variant ->> 'variant_id' = ANY(variant_ids) THEN
      RAISE EXCEPTION 'growth variant_id must be unique';
    END IF;
    variant_ids := pg_catalog.array_append(
      variant_ids,
      variant ->> 'variant_id'
    );
    total_weight := total_weight + (variant ->> 'weight_bps')::integer;
  END LOOP;
  IF total_weight <> 10000
     OR NOT (variant_ids @> ARRAY['control', 'treatment']::text[]) THEN
    RAISE EXCEPTION 'growth variant weights or identities are invalid';
  END IF;
EXCEPTION
  WHEN invalid_text_representation OR datetime_field_overflow THEN
    RAISE EXCEPTION 'growth numeric or timestamp field is invalid';
END;
$validate_spec$;

CREATE OR REPLACE FUNCTION volpred_growth.fnv1a_bucket(p_value text)
RETURNS integer
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = ''
AS $fnv1a$
DECLARE
  raw bytea := pg_catalog.convert_to(p_value, 'UTF8');
  hash_value bigint := 2166136261;
  index integer;
BEGIN
  IF pg_catalog.octet_length(raw) > 512 THEN
    RAISE EXCEPTION 'growth assignment input is too long';
  END IF;
  FOR index IN 0..pg_catalog.octet_length(raw) - 1
  LOOP
    hash_value := hash_value # pg_catalog.get_byte(raw, index);
    hash_value := (hash_value * 16777619) % 4294967296;
  END LOOP;
  RETURN (hash_value % 10000)::integer;
END;
$fnv1a$;

CREATE OR REPLACE FUNCTION volpred_growth.assigned_variant(
  p_experiment_id text,
  p_privacy_digest text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
STRICT
SET search_path = ''
AS $assigned_variant$
DECLARE
  experiment record;
  bucket integer;
  boundary integer := 0;
  variant jsonb;
BEGIN
  IF p_experiment_id
       !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR p_privacy_digest !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'growth assignment input is invalid';
  END IF;
  SELECT definition
  INTO STRICT experiment
  FROM volpred_growth.experiments
  WHERE experiment_id = p_experiment_id;
  bucket := volpred_growth.fnv1a_bucket(
    p_experiment_id
    || ':'
    || (experiment.definition ->> 'assignment_salt')
    || ':'
    || p_privacy_digest
  );
  FOR variant IN
    SELECT value
    FROM pg_catalog.jsonb_array_elements(
      experiment.definition -> 'variants'
    )
  LOOP
    boundary := boundary + (variant ->> 'weight_bps')::integer;
    IF bucket < boundary THEN
      RETURN variant;
    END IF;
  END LOOP;
  RAISE EXCEPTION 'growth assignment weights are invalid';
END;
$assigned_variant$;

CREATE OR REPLACE FUNCTION volpred_growth.measure_experiment(
  p_experiment_id text
)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = ''
AS $measure$
  WITH experiment AS (
    SELECT
      starts_at,
      ends_at,
      (
        definition #>> '{attribution,window_hours}'
      )::integer AS attribution_window_hours
    FROM volpred_growth.experiments
    WHERE experiment_id = p_experiment_id
  ),
  variants(variant_id) AS (
    VALUES ('control'::text), ('treatment'::text)
  ),
  content_exposure_cohort AS (
    SELECT
      event.anonymous_id,
      event.properties ->> 'content_id' AS content_id,
      event.properties ->> 'variant_id' AS variant_id,
      pg_catalog.min(event.occurred_at) AS exposed_at
    FROM volpred_analytics.events AS event
    CROSS JOIN experiment
    WHERE event.kind = 'content_impression'
      AND event.anonymous_id IS NOT NULL
      AND event.properties ->> 'experiment_id' = p_experiment_id
      AND event.occurred_at >= experiment.starts_at
      AND event.occurred_at < experiment.ends_at
    GROUP BY
      event.anonymous_id,
      event.properties ->> 'content_id',
      event.properties ->> 'variant_id'
  ),
  content_outcomes AS (
    SELECT
      cohort.anonymous_id,
      cohort.variant_id,
      pg_catalog.bool_or(
        outcome.kind = 'qualified_action'
        AND outcome.properties ->> 'action' = 'share'
      ) AS qualified_action,
      pg_catalog.bool_or(
        outcome.kind = 'read_depth'
        AND outcome.properties ->> 'depth_bucket' = '75'
      ) AS read_depth_75
    FROM content_exposure_cohort AS cohort
    CROSS JOIN experiment
    LEFT JOIN volpred_analytics.events AS outcome
      ON outcome.anonymous_id = cohort.anonymous_id
     AND outcome.properties ->> 'content_id' = cohort.content_id
     AND outcome.properties ->> 'experiment_id' = p_experiment_id
     AND outcome.properties ->> 'variant_id' = cohort.variant_id
     AND outcome.occurred_at >= cohort.exposed_at
     AND outcome.occurred_at
       <= cohort.exposed_at
          + pg_catalog.make_interval(
              hours => experiment.attribution_window_hours
            )
     AND outcome.kind IN ('qualified_action', 'read_depth')
    GROUP BY
      cohort.anonymous_id,
      cohort.content_id,
      cohort.variant_id
  ),
  subject_outcomes AS (
    SELECT
      outcome.anonymous_id,
      outcome.variant_id,
      pg_catalog.bool_or(outcome.qualified_action)
        AS qualified_action,
      pg_catalog.bool_or(outcome.read_depth_75)
        AS read_depth_75
    FROM content_outcomes AS outcome
    GROUP BY outcome.anonymous_id, outcome.variant_id
  ),
  measured AS (
    SELECT
      variant.variant_id,
      pg_catalog.count(outcome.variant_id) AS exposures,
      pg_catalog.count(outcome.variant_id)
        FILTER (WHERE outcome.qualified_action) AS qualified_actions,
      pg_catalog.count(outcome.variant_id)
        FILTER (WHERE outcome.read_depth_75) AS read_depth_75
    FROM variants AS variant
    LEFT JOIN subject_outcomes AS outcome
      ON outcome.variant_id = variant.variant_id
    GROUP BY variant.variant_id
  )
  SELECT pg_catalog.jsonb_object_agg(
    variant_id,
    pg_catalog.jsonb_build_object(
      'exposures', exposures,
      'qualified_actions', qualified_actions,
      'read_depth_75', read_depth_75,
      'qualified_action_rate',
        CASE WHEN exposures = 0 THEN NULL
        ELSE pg_catalog.round(
          qualified_actions::numeric / exposures,
          6
        ) END,
      'read_depth_75_rate',
        CASE WHEN exposures = 0 THEN NULL
        ELSE pg_catalog.round(
          read_depth_75::numeric / exposures,
          6
        ) END
    )
  )
  FROM measured;
$measure$;

CREATE OR REPLACE FUNCTION volpred_growth.wilson_bound(
  p_successes bigint,
  p_total bigint,
  p_lower boolean
)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = ''
AS $wilson$
DECLARE
  z numeric := 1.959963984540054;
  proportion numeric;
  center numeric;
  margin numeric;
BEGIN
  IF p_total <= 0
     OR p_successes < 0
     OR p_successes > p_total THEN
    RETURN NULL;
  END IF;
  proportion := p_successes::numeric / p_total;
  center := (
    proportion + z * z / (2 * p_total)
  ) / (1 + z * z / p_total);
  margin := z * pg_catalog.sqrt(
    proportion * (1 - proportion) / p_total
    + z * z / (4 * p_total * p_total)
  ) / (1 + z * z / p_total);
  RETURN pg_catalog.round(
    CASE WHEN p_lower THEN center - margin ELSE center + margin END,
    6
  );
END;
$wilson$;

CREATE OR REPLACE FUNCTION public.command_volpred_growth_experiment(
  p_command_id text,
  p_action text,
  p_payload jsonb,
  p_request_digest bytea,
  p_now timestamptz
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $command$
DECLARE
  resolved_experiment_id text;
  existing_receipt record;
  experiment record;
  command_result jsonb;
  measurement jsonb;
  control_exposures bigint;
  treatment_exposures bigint;
  total_exposures bigint;
  control_actions bigint;
  treatment_actions bigint;
  control_action_rate numeric;
  treatment_action_rate numeric;
  control_depth_rate numeric;
  treatment_depth_rate numeric;
  minimum_exposures integer;
  maximum_exposures integer;
  minimum_uplift numeric;
  guardrail_ratio numeric;
  control_upper numeric;
  treatment_lower numeric;
  outcome text;
  reason text;
  from_status text;
  last_exposure_at timestamptz;
  maturation_deadline timestamptz;
  attribution_window_hours integer;
  delivery_grace_minutes integer;
  maximum_lifecycle_hours integer;
  command_now timestamptz := pg_catalog.clock_timestamp();
BEGIN
  IF p_command_id IS NULL
     OR p_command_id
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'
     OR p_action NOT IN ('preregister', 'activate', 'stop', 'close')
     OR p_payload IS NULL
     OR pg_catalog.jsonb_typeof(p_payload) <> 'object'
     OR p_request_digest IS NULL
     OR pg_catalog.octet_length(p_request_digest) <> 32
     OR p_now IS NULL THEN
    RAISE EXCEPTION 'growth command is invalid';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-growth:command:' || p_command_id,
      0
    )
  );
  SELECT
    receipt.action,
    receipt.request_digest,
    receipt.result
  INTO existing_receipt
  FROM volpred_growth.command_receipts AS receipt
  WHERE receipt.command_id = p_command_id;
  IF FOUND THEN
    IF existing_receipt.action <> p_action
       OR existing_receipt.request_digest <> p_request_digest THEN
      RAISE EXCEPTION 'growth command_id was reused';
    END IF;
    RETURN existing_receipt.result
      || pg_catalog.jsonb_build_object('duplicate', true);
  END IF;
  IF pg_catalog.abs(
       pg_catalog.date_part('epoch', p_now - command_now)
     ) > 60 THEN
    RAISE EXCEPTION 'growth command is invalid';
  END IF;

  IF p_action = 'preregister' THEN
    PERFORM volpred_growth.validate_spec(p_payload);
    resolved_experiment_id := p_payload ->> 'experiment_id';
  ELSE
    resolved_experiment_id := p_payload ->> 'experiment_id';
    IF resolved_experiment_id IS NULL
       OR resolved_experiment_id
          !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' THEN
      RAISE EXCEPTION 'growth experiment_id is invalid';
    END IF;
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-growth:experiment:' || resolved_experiment_id,
      0
    )
  );

  IF p_action = 'preregister' THEN
    IF EXISTS (
      SELECT 1
      FROM volpred_growth.experiments
      WHERE experiments.experiment_id = resolved_experiment_id
    ) THEN
      RAISE EXCEPTION 'growth experiment already exists';
    END IF;
    IF p_now
         <> (p_payload ->> 'preregistered_at')::timestamptz
       OR command_now
         >= (p_payload #>> '{window,starts_at}')::timestamptz THEN
      RAISE EXCEPTION
        'growth preregistration timestamp must match its receipt '
        'and precede exposure';
    END IF;
    INSERT INTO volpred_growth.experiments (
      experiment_id,
      definition,
      definition_digest,
      status,
      preregistered_at,
      starts_at,
      ends_at
    )
    VALUES (
      resolved_experiment_id,
      p_payload - 'status',
      p_request_digest,
      'preregistered',
      (p_payload ->> 'preregistered_at')::timestamptz,
      (p_payload #>> '{window,starts_at}')::timestamptz,
      (p_payload #>> '{window,ends_at}')::timestamptz
    );
    from_status := NULL;
    command_result := pg_catalog.jsonb_build_object(
      'contract', 'growth-command-receipt.v1',
      'command_id', p_command_id,
      'experiment_id', resolved_experiment_id,
      'action', p_action,
      'status', 'preregistered',
      'duplicate', false
    );
  ELSE
    SELECT *
    INTO STRICT experiment
    FROM volpred_growth.experiments
    WHERE experiments.experiment_id = resolved_experiment_id
    FOR UPDATE;
    from_status := experiment.status;
    IF p_action = 'activate' THEN
      IF experiment.status <> 'preregistered'
         OR command_now < experiment.starts_at
         OR command_now >= experiment.ends_at THEN
        RAISE EXCEPTION 'growth experiment cannot be activated';
      END IF;
      UPDATE volpred_growth.experiments
      SET status = 'active', activated_at = command_now
      WHERE experiments.experiment_id = resolved_experiment_id;
      command_result := pg_catalog.jsonb_build_object(
        'contract', 'growth-command-receipt.v1',
        'command_id', p_command_id,
        'experiment_id', resolved_experiment_id,
        'action', p_action,
        'status', 'active',
        'duplicate', false
      );
    ELSIF p_action = 'stop' THEN
      IF experiment.status <> 'active'
         OR p_payload ->> 'reason' IS NULL
         OR p_payload ->> 'reason'
              NOT IN (
                'window_ended',
                'stop_rule_reached',
                'manual_safety_stop'
              ) THEN
        RAISE EXCEPTION 'growth experiment cannot stop exposure';
      END IF;
      measurement :=
        volpred_growth.measure_experiment(resolved_experiment_id);
      control_exposures :=
        (measurement #>> '{control,exposures}')::bigint;
      treatment_exposures :=
        (measurement #>> '{treatment,exposures}')::bigint;
      total_exposures := control_exposures + treatment_exposures;
      maximum_exposures :=
        (experiment.definition
          #>> '{stop_rule,maximum_exposures_total}')::integer;
      IF (
        p_payload ->> 'reason' = 'window_ended'
        AND command_now < experiment.ends_at
      ) OR (
        p_payload ->> 'reason' = 'stop_rule_reached'
        AND total_exposures < maximum_exposures
      ) THEN
        RAISE EXCEPTION
          'growth stop reason does not match the stop condition';
      END IF;
      attribution_window_hours :=
        (experiment.definition
          #>> '{attribution,window_hours}')::integer;
      delivery_grace_minutes :=
        (experiment.definition
          #>> '{attribution,delivery_grace_minutes}')::integer;
      SELECT pg_catalog.max(event.occurred_at)
      INTO last_exposure_at
      FROM volpred_analytics.events AS event
      WHERE event.kind = 'content_impression'
        AND event.properties ->> 'experiment_id'
          = resolved_experiment_id;
      IF p_payload ->> 'reason' = 'window_ended' THEN
        maturation_deadline := experiment.ends_at;
      ELSE
        maturation_deadline :=
          COALESCE(last_exposure_at, command_now);
      END IF;
      maturation_deadline := maturation_deadline
        + pg_catalog.make_interval(hours => attribution_window_hours)
        + pg_catalog.make_interval(mins => delivery_grace_minutes);
      maximum_lifecycle_hours :=
        (experiment.definition
          #>> '{stop_rule,maximum_lifecycle_hours}')::integer;
      IF maturation_deadline
           > experiment.starts_at
             + pg_catalog.make_interval(
                 hours => maximum_lifecycle_hours
               ) THEN
        RAISE EXCEPTION
          'growth observation exceeds preregistered lifecycle';
      END IF;
      UPDATE volpred_growth.experiments
      SET
        status = 'observing',
        exposure_stopped_at = command_now,
        observation_ends_at = maturation_deadline,
        stop_reason = p_payload ->> 'reason'
      WHERE experiments.experiment_id = resolved_experiment_id;
      command_result := pg_catalog.jsonb_build_object(
        'contract', 'growth-command-receipt.v1',
        'command_id', p_command_id,
        'experiment_id', resolved_experiment_id,
        'action', p_action,
        'status', 'observing',
        'stop_reason', p_payload ->> 'reason',
        'observation_ends_at', maturation_deadline,
        'duplicate', false
      );
    ELSE
      IF experiment.status <> 'observing'
         OR p_payload ->> 'reason'
              IS DISTINCT FROM experiment.stop_reason
         OR command_now < experiment.observation_ends_at THEN
        RAISE EXCEPTION
          'growth attribution cohort has not matured';
      END IF;
      measurement :=
        volpred_growth.measure_experiment(resolved_experiment_id);
      control_exposures :=
        (measurement #>> '{control,exposures}')::bigint;
      treatment_exposures :=
        (measurement #>> '{treatment,exposures}')::bigint;

      control_actions :=
        (measurement #>> '{control,qualified_actions}')::bigint;
      treatment_actions :=
        (measurement #>> '{treatment,qualified_actions}')::bigint;
      control_action_rate :=
        (measurement #>> '{control,qualified_action_rate}')::numeric;
      treatment_action_rate :=
        (measurement #>> '{treatment,qualified_action_rate}')::numeric;
      control_depth_rate :=
        (measurement #>> '{control,read_depth_75_rate}')::numeric;
      treatment_depth_rate :=
        (measurement #>> '{treatment,read_depth_75_rate}')::numeric;
      minimum_exposures :=
        (experiment.definition
          #>> '{stop_rule,minimum_exposures_per_variant}')::integer;
      minimum_uplift :=
        (experiment.definition
          #>> '{decision_rule,minimum_absolute_uplift}')::numeric;
      guardrail_ratio :=
        (experiment.definition
          #>> '{guardrail,minimum_ratio_to_control}')::numeric;
      control_upper := volpred_growth.wilson_bound(
        control_actions,
        control_exposures,
        false
      );
      treatment_lower := volpred_growth.wilson_bound(
        treatment_actions,
        treatment_exposures,
        true
      );

      IF control_exposures < minimum_exposures
         OR treatment_exposures < minimum_exposures THEN
        outcome := 'insufficient_data';
        reason := 'minimum_exposures_not_met';
      ELSIF control_depth_rate IS NULL
         OR treatment_depth_rate IS NULL
         OR treatment_depth_rate
            < control_depth_rate * guardrail_ratio THEN
        outcome := 'guardrail_failed';
        reason := 'read_depth_guardrail_failed';
      ELSIF treatment_action_rate - control_action_rate
            >= minimum_uplift
         AND treatment_lower > control_upper THEN
        outcome := 'positive';
        reason := 'preregistered_decision_rule_met';
      ELSE
        outcome := 'null';
        reason := 'preregistered_decision_rule_not_met';
      END IF;

      command_result := pg_catalog.jsonb_build_object(
        'contract', 'growth-command-receipt.v1',
        'command_id', p_command_id,
        'experiment_id', resolved_experiment_id,
        'action', p_action,
        'status', 'closed',
        'duplicate', false,
        'result', pg_catalog.jsonb_build_object(
          'contract', 'growth-experiment-result.v1',
          'experiment_id', resolved_experiment_id,
          'outcome', outcome,
          'decision_reason', reason,
          'closure_reason', experiment.stop_reason,
          'closed_at', command_now,
          'measurement', measurement,
          'decision', pg_catalog.jsonb_build_object(
            'method', 'non_overlapping_wilson_95',
            'minimum_absolute_uplift', minimum_uplift,
            'control_upper_95', control_upper,
            'treatment_lower_95', treatment_lower,
            'guardrail_ratio', guardrail_ratio
          ),
          'null_result_retained',
            outcome IN ('null', 'insufficient_data')
        )
      ) || pg_catalog.jsonb_build_object(
        'closure_reason', experiment.stop_reason
      );
      UPDATE volpred_growth.experiments
      SET
        status = 'closed',
        closed_at = command_now,
        closure_reason = experiment.stop_reason,
        result = command_result -> 'result'
      WHERE experiments.experiment_id = resolved_experiment_id;
    END IF;
  END IF;

  command_result := command_result
    || pg_catalog.jsonb_build_object('applied_at', command_now);
  INSERT INTO volpred_growth.command_receipts (
    command_id,
    action,
    experiment_id,
    request_digest,
    request_payload,
    result,
    applied_at
  )
  VALUES (
    p_command_id,
    p_action,
    resolved_experiment_id,
    p_request_digest,
    p_payload,
    command_result,
    command_now
  );
  INSERT INTO volpred_growth.audit_log (
    experiment_id,
    command_id,
    action,
    from_status,
    to_status,
    request_payload,
    recorded_at
  )
  VALUES (
    resolved_experiment_id,
    p_command_id,
    p_action,
    from_status,
    command_result ->> 'status',
    p_payload,
    command_now
  );
  RETURN command_result;
END;
$command$;

CREATE OR REPLACE FUNCTION public.resolve_volpred_growth_assignment(
  p_experiment_id text,
  p_privacy_digest text,
  p_observed_at timestamptz
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $resolve$
DECLARE
  experiment record;
  variant jsonb;
  measurement jsonb;
  total_exposures bigint;
  maximum_exposures integer;
  lease_ttl_seconds integer;
BEGIN
  IF p_experiment_id IS NULL
     OR p_experiment_id
        !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
     OR p_privacy_digest IS NULL
     OR p_privacy_digest !~ '^[a-f0-9]{64}$'
     OR p_observed_at IS NULL THEN
    RAISE EXCEPTION 'growth assignment input is invalid';
  END IF;
  SELECT *
  INTO experiment
  FROM volpred_growth.experiments
  WHERE experiment_id = p_experiment_id;
  IF NOT FOUND
     OR experiment.status <> 'active'
     OR p_observed_at < experiment.starts_at
     OR p_observed_at >= experiment.ends_at THEN
    RETURN NULL;
  END IF;
  measurement := volpred_growth.measure_experiment(p_experiment_id);
  total_exposures :=
    (measurement #>> '{control,exposures}')::bigint
    + (measurement #>> '{treatment,exposures}')::bigint;
  maximum_exposures :=
    (experiment.definition
      #>> '{stop_rule,maximum_exposures_total}')::integer;
  IF total_exposures >= maximum_exposures THEN
    RETURN NULL;
  END IF;
  variant := volpred_growth.assigned_variant(
    p_experiment_id,
    p_privacy_digest
  );
  lease_ttl_seconds := GREATEST(
    1,
    LEAST(
      60,
      pg_catalog.ceil(
        pg_catalog.date_part(
          'epoch',
          experiment.ends_at - p_observed_at
        )
      )::integer
    )
  );
  RETURN pg_catalog.jsonb_build_object(
    'experiment_id', p_experiment_id,
    'variant_id', variant ->> 'variant_id',
    'payload', variant -> 'payload',
    'lease_expires_at',
      LEAST(
        experiment.ends_at,
        pg_catalog.statement_timestamp()
          + pg_catalog.make_interval(secs => lease_ttl_seconds)
      ),
    'lease_ttl_seconds', lease_ttl_seconds
  );
END;
$resolve$;

CREATE OR REPLACE FUNCTION public.record_volpred_growth_analytics_event(
  p_idempotency_key text,
  p_kind text,
  p_occurred_at timestamptz,
  p_anonymous_id text,
  p_submitted_user_id text,
  p_properties jsonb,
  p_payload_digest bytea,
  p_idempotency_digest bytea,
  p_digest_key_id text,
  p_digest_key_verifier bytea,
  p_anonymous_subject_digest bytea DEFAULT NULL,
  p_user_subject_digest bytea DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $growth_ingress$
DECLARE
  assignment jsonb;
  experiment record;
  expected_variant jsonb;
  exposed_at timestamptz;
  attribution_window_hours integer;
  delivery_grace_minutes integer;
  delivery_deadline timestamptz;
BEGIN
  IF p_anonymous_subject_digest IS NULL
     OR p_properties ->> 'experiment_id' IS NULL
     OR p_properties ->> 'variant_id' IS NULL THEN
    RAISE EXCEPTION 'growth analytics attribution is required';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'volpred-growth:experiment:'
      || (p_properties ->> 'experiment_id'),
      0
    )
  );
  IF p_kind = 'content_impression' THEN
    assignment := public.resolve_volpred_growth_assignment(
      p_properties ->> 'experiment_id',
      pg_catalog.encode(p_anonymous_subject_digest, 'hex'),
      p_occurred_at
    );
    IF assignment IS NULL
       OR assignment ->> 'variant_id'
          <> p_properties ->> 'variant_id' THEN
      RAISE EXCEPTION 'growth analytics assignment mismatch';
    END IF;
  ELSIF p_kind IN ('qualified_action', 'read_depth') THEN
    SELECT *
    INTO STRICT experiment
    FROM volpred_growth.experiments
    WHERE experiments.experiment_id
      = (p_properties ->> 'experiment_id');
    IF experiment.status NOT IN ('active', 'observing') THEN
      RAISE EXCEPTION 'growth analytics assignment mismatch';
    END IF;
    expected_variant := volpred_growth.assigned_variant(
      p_properties ->> 'experiment_id',
      pg_catalog.encode(p_anonymous_subject_digest, 'hex')
    );
    IF expected_variant ->> 'variant_id'
         <> p_properties ->> 'variant_id' THEN
      RAISE EXCEPTION 'growth analytics assignment mismatch';
    END IF;
    attribution_window_hours :=
      (experiment.definition
        #>> '{attribution,window_hours}')::integer;
    delivery_grace_minutes :=
      (experiment.definition
        #>> '{attribution,delivery_grace_minutes}')::integer;
    SELECT pg_catalog.min(event.occurred_at)
    INTO exposed_at
    FROM volpred_analytics.events AS event
    WHERE event.kind = 'content_impression'
      AND event.anonymous_id = p_anonymous_id
      AND event.properties ->> 'content_id'
        = p_properties ->> 'content_id'
      AND event.properties ->> 'experiment_id'
        = p_properties ->> 'experiment_id'
      AND event.properties ->> 'variant_id'
        = p_properties ->> 'variant_id';
    IF exposed_at IS NULL
       OR p_occurred_at < exposed_at
       OR p_occurred_at > exposed_at
          + pg_catalog.make_interval(
              hours => attribution_window_hours
            ) THEN
      RAISE EXCEPTION 'growth analytics attribution window mismatch';
    END IF;
    delivery_deadline := CASE
      WHEN experiment.status = 'observing'
        THEN experiment.observation_ends_at
      ELSE experiment.ends_at
        + pg_catalog.make_interval(
            hours => attribution_window_hours
          )
        + pg_catalog.make_interval(
            mins => delivery_grace_minutes
          )
    END;
    IF pg_catalog.clock_timestamp() > delivery_deadline THEN
      RAISE EXCEPTION 'growth analytics delivery grace expired';
    END IF;
  ELSE
    RAISE EXCEPTION 'growth analytics event kind is invalid';
  END IF;
  RETURN public.record_volpred_analytics_event(
    p_idempotency_key,
    p_kind,
    p_occurred_at,
    p_anonymous_id,
    p_submitted_user_id,
    p_properties,
    p_payload_digest,
    p_idempotency_digest,
    p_digest_key_id,
    p_digest_key_verifier,
    p_anonymous_subject_digest,
    p_user_subject_digest
  );
END;
$growth_ingress$;

CREATE OR REPLACE FUNCTION public.read_volpred_growth_experiment(
  p_experiment_id text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $read$
DECLARE
  experiment record;
BEGIN
  SELECT *
  INTO STRICT experiment
  FROM volpred_growth.experiments
  WHERE experiment_id = p_experiment_id;
  RETURN pg_catalog.jsonb_build_object(
    'contract', 'growth-experiment-read.v1',
    'experiment_id', experiment.experiment_id,
    'status', experiment.status,
    'spec',
      experiment.definition
      || pg_catalog.jsonb_build_object(
        'status',
        experiment.status
      ),
    'measurement',
      CASE WHEN experiment.status = 'closed'
        THEN experiment.result -> 'measurement'
        ELSE volpred_growth.measure_experiment(experiment.experiment_id)
      END,
    'result', experiment.result,
    'preregistered_at', experiment.preregistered_at,
    'activated_at', experiment.activated_at,
    'exposure_stopped_at', experiment.exposure_stopped_at,
    'observation_ends_at', experiment.observation_ends_at,
    'stop_reason', experiment.stop_reason,
    'closed_at', experiment.closed_at,
    'closure_reason', experiment.closure_reason
  );
END;
$read$;

CREATE OR REPLACE FUNCTION public.read_volpred_growth_command_receipt(
  p_command_id text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $read_receipt$
DECLARE
  receipt record;
BEGIN
  IF p_command_id IS NULL
     OR p_command_id
       !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$' THEN
    RAISE EXCEPTION 'growth command_id is invalid';
  END IF;
  SELECT *
  INTO receipt
  FROM volpred_growth.command_receipts
  WHERE command_id = p_command_id;
  IF NOT FOUND THEN
    RETURN NULL;
  END IF;
  RETURN pg_catalog.jsonb_build_object(
    'contract', 'growth-command-receipt-read.v1',
    'command_id', receipt.command_id,
    'action', receipt.action,
    'request_payload', receipt.request_payload,
    'receipt', receipt.result
  );
END;
$read_receipt$;

REVOKE ALL ON FUNCTION volpred_growth.validate_spec(jsonb)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_growth.fnv1a_bucket(text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_growth.assigned_variant(text, text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_growth.measure_experiment(text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION volpred_growth.wilson_bound(
  bigint, bigint, boolean
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.command_volpred_growth_experiment(
  text, text, jsonb, bytea, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.resolve_volpred_growth_assignment(
  text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_volpred_growth_analytics_event(
  text, text, timestamptz, text, text, jsonb, bytea, bytea,
  text, bytea, bytea, bytea
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.read_volpred_growth_experiment(text)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION public.read_volpred_growth_command_receipt(text)
  FROM PUBLIC;

DO $grant_service_role$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_roles
    WHERE rolname = 'service_role'
  ) THEN
    RAISE EXCEPTION
      'service_role is required for growth experiment registry';
  END IF;
  REVOKE ALL ON FUNCTION public.command_volpred_growth_experiment(
    text, text, jsonb, bytea, timestamptz
  ) FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.resolve_volpred_growth_assignment(
    text, text, timestamptz
  ) FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.record_volpred_growth_analytics_event(
    text, text, timestamptz, text, text, jsonb, bytea, bytea,
    text, bytea, bytea, bytea
  ) FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.read_volpred_growth_experiment(text)
    FROM anon, authenticated;
  REVOKE ALL ON FUNCTION public.read_volpred_growth_command_receipt(text)
    FROM anon, authenticated;
  GRANT EXECUTE ON FUNCTION public.command_volpred_growth_experiment(
    text, text, jsonb, bytea, timestamptz
  ) TO service_role;
  GRANT EXECUTE ON FUNCTION public.resolve_volpred_growth_assignment(
    text, text, timestamptz
  ) TO service_role;
  GRANT EXECUTE ON FUNCTION public.record_volpred_growth_analytics_event(
    text, text, timestamptz, text, text, jsonb, bytea, bytea,
    text, bytea, bytea, bytea
  ) TO service_role;
  GRANT EXECUTE ON FUNCTION public.read_volpred_growth_experiment(text)
    TO service_role;
  GRANT EXECUTE ON FUNCTION public.read_volpred_growth_command_receipt(text)
    TO service_role;
END;
$grant_service_role$;

RESET ROLE;

REVOKE CREATE ON SCHEMA public, volpred_growth
  FROM volpred_growth_worker;
DO $revoke_worker_from_migration_role$
BEGIN
  IF CURRENT_USER = 'postgres' THEN
    EXECUTE pg_catalog.format(
      'REVOKE volpred_growth_worker FROM %I '
      'GRANTED BY CURRENT_USER',
      CURRENT_USER
    );
  ELSE
    EXECUTE pg_catalog.format(
      'REVOKE volpred_growth_worker FROM %I',
      CURRENT_USER
    );
  END IF;
END;
$revoke_worker_from_migration_role$;
