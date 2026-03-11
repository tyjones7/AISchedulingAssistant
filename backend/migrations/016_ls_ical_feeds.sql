-- Migration 016: Learning Suite iCal feed support
--
-- Adds:
--   1. ls_ical_feeds table — stores per-user iCal feed URLs
--   2. ls_ical_uid column on assignments — stable UID from iCal events for deduplication

-- Table to store saved iCal feed URLs per user
CREATE TABLE IF NOT EXISTS ls_ical_feeds (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES auth.users(id) NOT NULL,
    url          TEXT NOT NULL,
    course_name  TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE ls_ical_feeds ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own_ls_ical_feeds" ON ls_ical_feeds
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Stable UID from iCal VEVENT for deduplication (equivalent to canvas_id for Canvas)
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS ls_ical_uid TEXT;

-- Index for fast uid lookups scoped to a user
CREATE INDEX IF NOT EXISTS assignments_ls_ical_uid
    ON assignments (user_id, ls_ical_uid)
    WHERE ls_ical_uid IS NOT NULL;
