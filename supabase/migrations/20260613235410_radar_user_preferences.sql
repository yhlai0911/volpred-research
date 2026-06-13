-- VolPred Radar — member profile preferences persistence (P0).
-- Stores the per-user Radar 風險型態 (profile_key) + notification preference.
-- Owner can read/write only their own row; service_role bypasses RLS for API upsert.

CREATE TABLE IF NOT EXISTS public.radar_user_preferences (
  user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  profile_key text NOT NULL,
  notification_enabled boolean NOT NULL DEFAULT false,
  notification_channel text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT radar_user_preferences_profile_key_check
    CHECK (profile_key IN ('long_etf', 'tw_etf', 'us_etf', 'leveraged', 'retiree')),
  CONSTRAINT radar_user_preferences_notification_channel_check
    CHECK (
      notification_channel IS NULL
      OR notification_channel IN ('email', 'line', 'telegram')
    )
);

CREATE OR REPLACE FUNCTION public._radar_user_preferences_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_radar_user_preferences_touch_updated_at ON public.radar_user_preferences;
CREATE TRIGGER trg_radar_user_preferences_touch_updated_at
BEFORE UPDATE ON public.radar_user_preferences
FOR EACH ROW
EXECUTE FUNCTION public._radar_user_preferences_touch_updated_at();

ALTER TABLE public.radar_user_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS radar_user_preferences_owner_select ON public.radar_user_preferences;
DROP POLICY IF EXISTS radar_user_preferences_owner_insert ON public.radar_user_preferences;
DROP POLICY IF EXISTS radar_user_preferences_owner_update ON public.radar_user_preferences;
DROP POLICY IF EXISTS radar_user_preferences_owner_delete ON public.radar_user_preferences;
DROP POLICY IF EXISTS radar_user_preferences_service_all ON public.radar_user_preferences;

-- Owner can read/write only their own row.
CREATE POLICY radar_user_preferences_owner_select ON public.radar_user_preferences
  FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY radar_user_preferences_owner_insert ON public.radar_user_preferences
  FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY radar_user_preferences_owner_update ON public.radar_user_preferences
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
CREATE POLICY radar_user_preferences_owner_delete ON public.radar_user_preferences
  FOR DELETE USING (auth.uid() = user_id);

-- service_role bypasses RLS for server-side API upsert.
CREATE POLICY radar_user_preferences_service_all ON public.radar_user_preferences
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
