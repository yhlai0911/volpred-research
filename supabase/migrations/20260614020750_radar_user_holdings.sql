-- VolPred Radar Phase A — 持倉風險體檢 MVP：使用者持倉持久化。
-- 每位使用者一筆 holdings（jsonb 陣列 [{ticker, weight_pct}]），供持倉風險體檢 API 讀取。
-- Owner-only RLS：使用者只能讀寫自己那筆；service_role 供 server-side API upsert。
--
-- holdings schema：jsonb array，每個元素 { "ticker": "<TICKER>", "weight_pct": <number> }
--   e.g. [{"ticker":"SPY","weight_pct":60},{"ticker":"TLT","weight_pct":40}]
--   weight_pct 是百分比（0-100）。cash 為隱含（sum < 100 的部分視為現金），不是一個 key。
-- 風險數字本身不存這張表 — 由 /api/radar/holdings/risk 用真實歷史價格即時計算（研究誠實：不快照臆造數字）。

CREATE TABLE IF NOT EXISTS public.radar_user_holdings (
  user_id    uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  holdings   jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT radar_user_holdings_is_array
    CHECK (jsonb_typeof(holdings) = 'array')
);

CREATE OR REPLACE FUNCTION public._radar_user_holdings_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_radar_user_holdings_touch_updated_at ON public.radar_user_holdings;
CREATE TRIGGER trg_radar_user_holdings_touch_updated_at
BEFORE UPDATE ON public.radar_user_holdings
FOR EACH ROW
EXECUTE FUNCTION public._radar_user_holdings_touch_updated_at();

ALTER TABLE public.radar_user_holdings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS radar_user_holdings_owner_select ON public.radar_user_holdings;
DROP POLICY IF EXISTS radar_user_holdings_owner_insert ON public.radar_user_holdings;
DROP POLICY IF EXISTS radar_user_holdings_owner_update ON public.radar_user_holdings;
DROP POLICY IF EXISTS radar_user_holdings_owner_delete ON public.radar_user_holdings;
DROP POLICY IF EXISTS radar_user_holdings_service_all ON public.radar_user_holdings;

-- Owner can read/write only their own row.
CREATE POLICY radar_user_holdings_owner_select ON public.radar_user_holdings
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY radar_user_holdings_owner_insert ON public.radar_user_holdings
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY radar_user_holdings_owner_update ON public.radar_user_holdings
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
CREATE POLICY radar_user_holdings_owner_delete ON public.radar_user_holdings
  FOR DELETE USING (auth.uid() = user_id);

-- service_role bypasses RLS for server-side API upsert.
CREATE POLICY radar_user_holdings_service_all ON public.radar_user_holdings
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
