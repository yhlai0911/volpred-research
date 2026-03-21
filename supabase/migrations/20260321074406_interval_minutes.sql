-- 007: Change interval_hours (integer) to interval_minutes (integer)
-- This allows sub-hour intervals (e.g., 15 minutes) without float precision issues

ALTER TABLE content_release_settings 
  ADD COLUMN interval_minutes integer DEFAULT 1440;

UPDATE content_release_settings 
  SET interval_minutes = interval_hours * 60;

ALTER TABLE content_release_settings 
  DROP COLUMN interval_hours;

-- Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
