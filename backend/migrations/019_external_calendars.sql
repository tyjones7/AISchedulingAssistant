-- Migration 019: External calendar iCal feeds (Google Calendar, etc.)
CREATE TABLE IF NOT EXISTS external_calendars (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  url         TEXT NOT NULL,
  label       TEXT NOT NULL DEFAULT 'My Calendar',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE external_calendars ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own external calendars"
  ON external_calendars FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
