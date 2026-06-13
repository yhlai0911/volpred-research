-- VolPred Radar — daily notification event log (P0 notification productization skeleton).
-- Records, per user + day + channel, whether a daily risk notification WOULD fire
-- and (eventually) its delivery status. This期 only writes 'previewed' (and is wired
-- for 'queued'); no real email/LINE/telegram delivery is implemented yet.
-- The unique (user_id, event_date, channel) constraint is the dedup guard that
-- prevents re-sending the same daily notification twice.
-- Owner can read only their own events; only service_role inserts (server-side API).

CREATE TABLE IF NOT EXISTS public.radar_notification_events (
  id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  event_date date NOT NULL,
  risk_light text NOT NULL,
  channel text,
  status text NOT NULL DEFAULT 'previewed',
  payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT radar_notification_events_risk_light_check
    CHECK (risk_light IN ('green', 'yellow', 'red', 'insufficient')),
  CONSTRAINT radar_notification_events_channel_check
    CHECK (
      channel IS NULL
      OR channel IN ('email', 'line', 'telegram')
    ),
  CONSTRAINT radar_notification_events_status_check
    CHECK (status IN ('previewed', 'queued', 'sent', 'skipped', 'cancelled'))
);

-- Dedup guard: one row per user per day per channel.
-- NULL channel is treated as distinct per Postgres NULL semantics; the API always
-- supplies a concrete channel so the dedup is effective in practice.
CREATE UNIQUE INDEX IF NOT EXISTS radar_notification_events_user_date_channel_uidx
  ON public.radar_notification_events (user_id, event_date, channel);

-- Helper index for "recent N events for this user" lookups.
CREATE INDEX IF NOT EXISTS radar_notification_events_user_created_idx
  ON public.radar_notification_events (user_id, created_at DESC);

ALTER TABLE public.radar_notification_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS radar_notification_events_owner_select ON public.radar_notification_events;
DROP POLICY IF EXISTS radar_notification_events_service_all ON public.radar_notification_events;

-- Owner can read only their own events.
CREATE POLICY radar_notification_events_owner_select ON public.radar_notification_events
  FOR SELECT USING (auth.uid() = user_id);

-- service_role bypasses RLS for server-side API insert/update.
CREATE POLICY radar_notification_events_service_all ON public.radar_notification_events
  FOR ALL USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

NOTIFY pgrst, 'reload schema';
