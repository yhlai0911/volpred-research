-- Indicator Arena Phase 1c.
-- Local storage/indicator_arena/* is canonical. Supabase is a projection.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'indicator_league') THEN
    CREATE TYPE public.indicator_league AS ENUM ('direction', 'calibration');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'indicator_status') THEN
    CREATE TYPE public.indicator_status AS ENUM ('active', 'observation', 'delisted');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.indicator_registry (
  indicator_id text PRIMARY KEY,
  name_zh text NOT NULL,
  league public.indicator_league NOT NULL,
  signal_rule text NOT NULL,
  target text NOT NULL,
  horizon_days integer NOT NULL CHECK (horizon_days >= 1),
  data_sources jsonb NOT NULL DEFAULT '{}'::jsonb,
  k_refs text[] NOT NULL DEFAULT '{}'::text[],
  oos_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  caveats text NOT NULL,
  status public.indicator_status NOT NULL,
  status_since timestamptz NOT NULL,
  listed_at timestamptz NOT NULL,
  delisted_at timestamptz,
  status_history jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.daily_signals (
  signal_id text PRIMARY KEY,
  indicator_id text NOT NULL REFERENCES public.indicator_registry(indicator_id),
  published_at timestamptz NOT NULL,
  target_date date,
  resolve_after timestamptz,
  indicator_value numeric,
  prediction jsonb NOT NULL DEFAULT '{}'::jsonb,
  inputs_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  code_version text,
  as_of_ts timestamptz,
  emitted_at timestamptz,
  expires_at timestamptz,
  data_hash text,
  late boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.outcome_reviews (
  review_id text PRIMARY KEY,
  signal_id text NOT NULL REFERENCES public.daily_signals(signal_id),
  indicator_id text REFERENCES public.indicator_registry(indicator_id),
  reviewed_at timestamptz NOT NULL,
  realized jsonb NOT NULL DEFAULT '{}'::jsonb,
  hit boolean,
  econ_value_bps numeric,
  data_source_asof timestamptz,
  correction_of text,
  league public.indicator_league,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_indicator_registry_status
  ON public.indicator_registry(status);
CREATE INDEX IF NOT EXISTS idx_daily_signals_indicator_target_date
  ON public.daily_signals(indicator_id, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_signals_resolve_after
  ON public.daily_signals(resolve_after);
CREATE INDEX IF NOT EXISTS idx_outcome_reviews_signal_id
  ON public.outcome_reviews(signal_id);

CREATE OR REPLACE FUNCTION public._indicator_arena_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_indicator_registry_touch_updated_at ON public.indicator_registry;
CREATE TRIGGER trg_indicator_registry_touch_updated_at
BEFORE UPDATE ON public.indicator_registry
FOR EACH ROW
EXECUTE FUNCTION public._indicator_arena_touch_updated_at();

CREATE OR REPLACE FUNCTION public._indicator_arena_reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'append-only table: % on % is forbidden', TG_OP, TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS trg_daily_signals_no_update ON public.daily_signals;
CREATE TRIGGER trg_daily_signals_no_update
BEFORE UPDATE OR DELETE ON public.daily_signals
FOR EACH ROW
EXECUTE FUNCTION public._indicator_arena_reject_mutation();

DROP TRIGGER IF EXISTS trg_outcome_reviews_no_update ON public.outcome_reviews;
CREATE TRIGGER trg_outcome_reviews_no_update
BEFORE UPDATE OR DELETE ON public.outcome_reviews
FOR EACH ROW
EXECUTE FUNCTION public._indicator_arena_reject_mutation();

ALTER TABLE public.indicator_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcome_reviews ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS indicator_registry_public_read ON public.indicator_registry;
DROP POLICY IF EXISTS indicator_registry_service_write ON public.indicator_registry;
DROP POLICY IF EXISTS daily_signals_public_read ON public.daily_signals;
DROP POLICY IF EXISTS daily_signals_service_insert ON public.daily_signals;
DROP POLICY IF EXISTS outcome_reviews_public_read ON public.outcome_reviews;
DROP POLICY IF EXISTS outcome_reviews_service_insert ON public.outcome_reviews;

CREATE POLICY indicator_registry_public_read ON public.indicator_registry
  FOR SELECT USING (true);
CREATE POLICY indicator_registry_service_write ON public.indicator_registry
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY daily_signals_public_read ON public.daily_signals
  FOR SELECT USING (true);
CREATE POLICY daily_signals_service_insert ON public.daily_signals
  FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY outcome_reviews_public_read ON public.outcome_reviews
  FOR SELECT USING (true);
CREATE POLICY outcome_reviews_service_insert ON public.outcome_reviews
  FOR INSERT WITH CHECK (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
