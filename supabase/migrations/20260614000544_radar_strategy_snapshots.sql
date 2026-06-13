-- VolPred Radar — daily strategy allocation snapshots (P1).
-- Stores one row per (snapshot_date, strategy_id) capturing the canonical
-- active strategy weights (from strategy_signals.weights, {asset: weight})
-- plus a metrics blob, so the Radar diff API can compute "今日 vs 前次" 配置變動.
--
-- weights schema mirrors strategy_signals.weights jsonb: { "<asset>": <weight_pct> }
--   e.g. {"SPY": 62}  -> 62% SPY, remaining 38% cash (cash is implicit, not a key).
-- metrics is the strategy_metrics_cache.metrics blob (sharpe/mdd/...) at snapshot time, nullable.
--
-- RLS: public read (this is public strategy configuration, NOT personal data);
--      service_role full write for the server-side daily snapshot job.

CREATE TABLE IF NOT EXISTS public.radar_strategy_snapshots (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date date NOT NULL,
  strategy_id   text NOT NULL,
  weights       jsonb NOT NULL,
  metrics       jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT radar_strategy_snapshots_unique_day_strategy
    UNIQUE (snapshot_date, strategy_id)
);

-- Diff API reads the two most-recent snapshot_dates; index keeps that cheap.
CREATE INDEX IF NOT EXISTS radar_strategy_snapshots_date_idx
  ON public.radar_strategy_snapshots (snapshot_date DESC);

ALTER TABLE public.radar_strategy_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS radar_strategy_snapshots_public_read ON public.radar_strategy_snapshots;
DROP POLICY IF EXISTS radar_strategy_snapshots_service_all ON public.radar_strategy_snapshots;

-- Public read: anon + authenticated may SELECT (public strategy config, non-personal).
CREATE POLICY radar_strategy_snapshots_public_read ON public.radar_strategy_snapshots
  FOR SELECT USING (true);

-- service_role bypasses RLS for server-side daily snapshot upsert.
CREATE POLICY radar_strategy_snapshots_service_all ON public.radar_strategy_snapshots
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
